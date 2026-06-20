"""Ontology-metadata operations — the base URI, its domain (host), and its prefix.

Renaming the base URI propagates to every *local* entity (those sharing the base);
external namespaces are left untouched. Part of the domain layer
(docs/architecture/module-layout.md): reached through ``ster.operations``, never
imported directly by a front-end.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..model import OntologyAnnotation, Taxonomy

# ── shared helpers ────────────────────────────────────────────────────────────


def _all_owl_uris(taxonomy: Taxonomy) -> list[str]:
    """Every OWL entity URI — classes, individuals, and properties."""
    return (
        list(taxonomy.owl_classes) + list(taxonomy.owl_individuals) + list(taxonomy.owl_properties)
    )


def _ontology_separator(taxonomy: Taxonomy) -> str:
    """Detect the separator ('#' or '/') used between the base URI and locals."""
    root = (taxonomy.ontology_uri or "").rstrip("#/")
    for u in _all_owl_uris(taxonomy):
        if len(u) > len(root) and u.startswith(root) and u[len(root)] in ("#", "/"):
            return u[len(root)]
    return "#"


def collect_ontology_entities(taxonomy: Taxonomy) -> list[str]:
    """Return all entity URIs that belong to the current ontology base.

    An entity is "local" if its URI starts with ``ontology_uri + "#"`` or
    ``ontology_uri + "/"``. Returns an empty list when no ontology URI is set.
    """
    if not taxonomy.ontology_uri:
        return []
    root = taxonomy.ontology_uri.rstrip("#/")
    return [
        u
        for u in _all_owl_uris(taxonomy)
        if len(u) > len(root) and u.startswith(root) and u[len(root)] in ("#", "/")
    ]


# ── base URI rename ─────────────────────────────────────────────────────────


def _build_rename_map(taxonomy: Taxonomy, old_base: str, new_base: str) -> dict[str, str]:
    """Map every local entity URI under *old_base* to its *new_base* equivalent."""
    return {
        u: new_base + u[len(old_base) :] for u in _all_owl_uris(taxonomy) if u.startswith(old_base)
    }


def _relocate_entities(taxonomy: Taxonomy, old_to_new: dict[str, str]) -> None:
    """Re-key each renamed class / individual / property to its new URI."""
    # Heterogeneous stores sharing only the structural `.uri`; Any keeps the
    # single generic loop (vs three near-identical typed loops).
    stores: tuple[dict[str, Any], ...] = (
        taxonomy.owl_classes,
        taxonomy.owl_individuals,
        taxonomy.owl_properties,
    )
    for store in stores:
        for old, new in list(old_to_new.items()):
            if old in store:
                entity = store.pop(old)
                entity.uri = new
                store[new] = entity


def _remap_cross_references(taxonomy: Taxonomy, old_to_new: dict[str, str]) -> None:
    """Update every cross-reference list/tuple to point at the renamed URIs."""

    def remap(lst: list[str]) -> None:
        for i, v in enumerate(lst):
            if v in old_to_new:
                lst[i] = old_to_new[v]

    for cls in taxonomy.owl_classes.values():
        remap(cls.sub_class_of)
        remap(cls.equivalent_class)
        remap(cls.disjoint_with)
    for ind in taxonomy.owl_individuals.values():
        remap(ind.types)
        ind.property_values = [
            (old_to_new.get(p, p), old_to_new.get(v, v)) for p, v in ind.property_values
        ]
        ind.literal_values = [(old_to_new.get(p, p), v, ld) for p, v, ld in ind.literal_values]
    for prop in taxonomy.owl_properties.values():
        remap(prop.domains)
        remap(prop.ranges)
        remap(prop.sub_property_of)
        remap(prop.inverse_of)


def rename_ontology_uri(taxonomy: Taxonomy, new_uri: str, new_sep: str) -> None:
    """Rename the global ontology URI and propagate the change to all local entities.

    *new_uri* is the bare ontology URI without a trailing separator; *new_sep* is
    ``"#"`` or ``"/"``. Only entity URIs sharing the current ontology base are
    renamed (external namespaces untouched); cross-reference lists (subClassOf,
    types, domains, ranges, property_values) are updated to match.
    """
    old_base = (taxonomy.ontology_uri or "").rstrip("#/") + _ontology_separator(taxonomy)
    new_uri = new_uri.rstrip("#/")
    new_base = new_uri + new_sep
    old_to_new = _build_rename_map(taxonomy, old_base, new_base)
    _relocate_entities(taxonomy, old_to_new)
    _remap_cross_references(taxonomy, old_to_new)
    taxonomy.ontology_uri = new_uri


def count_ontology_rename_changes(
    taxonomy: Taxonomy, new_uri: str, new_sep: str
) -> tuple[str, str, int]:
    """Return (old_base, new_base, count) for a prospective ontology base URI rename.

    *old_base* is the current base URI with its detected separator appended;
    *new_base* is *new_uri* + *new_sep*; *count* is the number of local entities
    whose URI would change (0 when unchanged).
    """
    old_base = (taxonomy.ontology_uri or "").rstrip("#/") + _ontology_separator(taxonomy)
    new_base = new_uri.rstrip("#/") + new_sep
    if old_base == new_base:
        return old_base, new_base, 0
    return old_base, new_base, len(collect_ontology_entities(taxonomy))


# ── ontology domain (host of the base URI) ────────────────────────────────────


def ontology_domain(taxonomy: Taxonomy) -> str:
    """Return the host of the ontology URI (e.g. 'www.adeo.com'), or '' if none/non-http."""
    uri = taxonomy.ontology_uri or ""
    if not uri.startswith(("http://", "https://")):
        return ""
    return urlsplit(uri).netloc


def _ontology_uri_with_domain(taxonomy: Taxonomy, new_domain: str) -> str:
    """The ontology URI with its host swapped for *new_domain* (scheme/path kept)."""
    parts = urlsplit(taxonomy.ontology_uri or "")
    return urlunsplit((parts.scheme, new_domain, parts.path, parts.query, parts.fragment))


def count_domain_rename_changes(taxonomy: Taxonomy, new_domain: str) -> tuple[str, str, int]:
    """(old_base, new_base, count) for swapping only the ontology URI's host."""
    new_uri = _ontology_uri_with_domain(taxonomy, new_domain)
    return count_ontology_rename_changes(taxonomy, new_uri, _ontology_separator(taxonomy))


def rename_ontology_domain(taxonomy: Taxonomy, new_domain: str) -> None:
    """Swap the host of the ontology URI, propagating to all entities (path & separator kept)."""
    new_uri = _ontology_uri_with_domain(taxonomy, new_domain)
    rename_ontology_uri(taxonomy, new_uri, _ontology_separator(taxonomy))


# ── ontology prefix (namespace label) ─────────────────────────────────────────


def validate_domain(domain: str) -> str | None:
    """Return an error message if *domain* is not a bare host, else None."""
    d = domain.strip()
    if not d:
        return "Domain is required."
    if " " in d:
        return "Domain must not contain spaces."
    if "://" in d or "/" in d:
        return "Enter only the host, e.g. www.adeo.com (no scheme or path)."
    return None


def validate_prefix(prefix: str) -> str | None:
    """Return an error message if *prefix* is not a valid namespace prefix, else None."""
    p = prefix.strip()
    if not p:
        return "Prefix is required."
    if not re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", p):
        return "Prefix must start with a letter and use only letters, digits, '-' or '_'."
    return None


def ontology_prefix(taxonomy: Taxonomy) -> str | None:
    """Return the prefix bound to the ontology base namespace, or None."""
    base = taxonomy.base_uri()
    if not base:
        return None
    for prefix, ns in taxonomy.namespace_bindings.items():
        if ns == base:
            return prefix
    return None


def count_prefix_uses(taxonomy: Taxonomy, prefix: str) -> int:
    """Number of local entity URIs under the namespace bound to *prefix*."""
    ns = taxonomy.namespace_bindings.get(prefix)
    if not ns:
        return 0
    root = ns.rstrip("#/")
    return sum(1 for u in _all_owl_uris(taxonomy) if u.startswith(root))


def rename_prefix(taxonomy: Taxonomy, old_prefix: str, new_prefix: str) -> int:
    """Rebind the namespace label from *old_prefix* to *new_prefix* (entity URIs unchanged).

    Returns the number of local entities that will serialize under the new prefix;
    0 when *old_prefix* is not bound.
    """
    if old_prefix not in taxonomy.namespace_bindings:
        return 0
    if new_prefix != old_prefix:
        ns = taxonomy.namespace_bindings.pop(old_prefix)
        taxonomy.namespace_bindings[new_prefix] = ns
    return count_prefix_uses(taxonomy, new_prefix)


# Ontology metadata field → the Taxonomy attribute it sets (None-empties a blank value).
_ONTOLOGY_METADATA_ATTRS = {
    "label": "ontology_label",
    "title": "ontology_title",
    "description": "ontology_description",
}


def set_ontology_prefix(taxonomy: Taxonomy, new_prefix: str) -> None:
    """Set the ontology's namespace prefix.

    Binds *new_prefix* to the base URI when none is bound yet; otherwise renames the
    existing prefix (entity URIs are unchanged)."""
    old = ontology_prefix(taxonomy)
    if old is None:
        base = taxonomy.base_uri()
        if base:
            taxonomy.namespace_bindings[new_prefix] = base
    else:
        rename_prefix(taxonomy, old, new_prefix)


def set_ontology_metadata(taxonomy: Taxonomy, field_name: str, value: str) -> None:
    """Set an ontology metadata field (``label`` / ``title`` / ``description``).

    A blank *value* clears the field (stored as ``None``). Unknown fields are a no-op."""
    attr = _ONTOLOGY_METADATA_ATTRS.get(field_name)
    if attr is not None:
        setattr(taxonomy, attr, value or None)


def add_ontology_annotation(
    taxonomy: Taxonomy,
    predicate: str,
    new_value: str,
    *,
    old_value: str = "",
    is_iri: bool = False,
    lang: str = "",
) -> None:
    """Add or replace one annotation value on the owl:Ontology node.

    When *old_value* is given, replaces the first matching entry (same predicate +
    value) in place so the ordering of other annotations is preserved. When there
    is no matching entry, appends a new one.
    """
    if old_value:
        for i, a in enumerate(taxonomy.ontology_annotations):
            if a.predicate == predicate and a.value == old_value:
                taxonomy.ontology_annotations[i] = OntologyAnnotation(
                    predicate=predicate, value=new_value, is_iri=is_iri, lang=lang
                )
                return
    taxonomy.ontology_annotations.append(
        OntologyAnnotation(predicate=predicate, value=new_value, is_iri=is_iri, lang=lang)
    )


def remove_ontology_annotation(taxonomy: Taxonomy, predicate: str, value: str) -> None:
    """Remove the first annotation with matching *predicate* and *value*."""
    for i, a in enumerate(taxonomy.ontology_annotations):
        if a.predicate == predicate and a.value == value:
            del taxonomy.ontology_annotations[i]
            return
