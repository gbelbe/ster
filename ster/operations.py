"""Business logic — all mutations to a Taxonomy live here."""

from __future__ import annotations

from .exceptions import (
    CircularHierarchyError,
    ClassNotFoundError,
    ConceptAlreadyExistsError,
    ConceptNotFoundError,
    HandleNotFoundError,
    HasChildrenError,
    RelatedHierarchyConflictError,
    URIAlreadyExistsError,
)
from .handles import assign_handles, handle_for_uri
from .model import (
    Concept,
    ConceptScheme,
    Definition,
    Label,
    LabelType,
    OWLProperty,
    RDFClass,
    Taxonomy,
)

# ──────────────────────────── resolve & expand ───────────────────────────────


def resolve(taxonomy: Taxonomy, handle_or_name: str) -> str:
    """Resolve a handle, local name, or full URI to a URI.

    Resolution order:
      1. Full URI (contains "://") — verified against known concepts/schemes.
      2. Handle (case-insensitive lookup in handle_index).
      3. Local name (matched against concept.local_name).

    Raises HandleNotFoundError if nothing matches.
    """
    uri = taxonomy.resolve(handle_or_name)
    if uri is None:
        raise HandleNotFoundError(handle_or_name)
    return uri


def expand_uri(taxonomy: Taxonomy, name_or_uri: str) -> str:
    """Return a full URI for a local name, expanding with the taxonomy's base URI.

    If name_or_uri already contains "://" it is returned as-is.
    Otherwise, the taxonomy's base URI is prepended.
    """
    if "://" in name_or_uri:
        return name_or_uri
    base = taxonomy.base_uri()
    if not base:
        raise HandleNotFoundError(
            f"Cannot expand {name_or_uri!r}: no base URI configured. "
            "Use a full URI or run 'ster init' to set one."
        )
    return base + name_or_uri


# ──────────────────────────── add ────────────────────────────────────────────


def add_concept(
    taxonomy: Taxonomy,
    uri: str,
    pref_labels: dict[str, str],
    parent_handle: str | None = None,
    definitions: dict[str, str] | None = None,
) -> Concept:
    """Add a new concept. parent_handle may be a concept or scheme handle/URI."""
    if uri in taxonomy.concepts:
        raise ConceptAlreadyExistsError(uri)

    labels = [Label(lang=lang, value=val) for lang, val in pref_labels.items()]
    defns = [Definition(lang=lang, value=val) for lang, val in (definitions or {}).items()]
    concept = Concept(uri=uri, labels=labels, definitions=defns)

    if parent_handle:
        parent_uri = taxonomy.resolve(parent_handle)
        if parent_uri is None:
            raise HandleNotFoundError(parent_handle)

        if parent_uri in taxonomy.schemes:
            # Adding as a top concept of a scheme
            scheme = taxonomy.schemes[parent_uri]
            if uri not in scheme.top_concepts:
                scheme.top_concepts.append(uri)
            concept.top_concept_of = parent_uri
        else:
            # Adding as narrower of a concept
            parent = taxonomy.concepts[parent_uri]
            if uri not in parent.narrower:
                parent.narrower.append(uri)
            concept.broader.append(parent_uri)
    else:
        # No parent: add as top concept of the primary scheme
        maybe_scheme = taxonomy.primary_scheme()
        if maybe_scheme:
            if uri not in maybe_scheme.top_concepts:
                maybe_scheme.top_concepts.append(uri)
            concept.top_concept_of = maybe_scheme.uri

    taxonomy.concepts[uri] = concept

    # Assign a handle for the new concept
    used = set(taxonomy.handle_index.keys())
    h = handle_for_uri(uri, used)
    taxonomy.handle_index[h] = uri

    return concept


# ──────────────────────────── remove ─────────────────────────────────────────


def remove_concept(taxonomy: Taxonomy, uri: str, *, cascade: bool = False) -> set[str]:
    """Remove a concept. Returns set of removed URIs.

    Raises HasChildrenError if concept has children and cascade=False.
    """
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)

    if concept.narrower and not cascade:
        raise HasChildrenError(uri, len(concept.narrower))

    to_remove = _subtree_uris(taxonomy, uri) if cascade else {uri}

    for r_uri in to_remove:
        c = taxonomy.concepts.get(r_uri)
        if c is None:
            continue
        # Detach from parents
        for parent_uri in c.broader:
            parent = taxonomy.concepts.get(parent_uri)
            if parent and r_uri in parent.narrower:
                parent.narrower.remove(r_uri)
        # Detach from schemes
        for scheme in taxonomy.schemes.values():
            if r_uri in scheme.top_concepts:
                scheme.top_concepts.remove(r_uri)
        # Clean up related links
        for other in taxonomy.concepts.values():
            if r_uri in other.related:
                other.related.remove(r_uri)
        del taxonomy.concepts[r_uri]

    # Final defensive pass: strip any remaining dangling refs across ALL concepts
    # (handles inconsistent data or multi-broader scenarios)
    for c in taxonomy.concepts.values():
        c.narrower = [u for u in c.narrower if u not in to_remove]
        c.broader = [u for u in c.broader if u not in to_remove]
    for scheme in taxonomy.schemes.values():
        scheme.top_concepts = [u for u in scheme.top_concepts if u not in to_remove]

    # Rebuild handle index (removed concepts should no longer appear)
    assign_handles(taxonomy)
    return to_remove


# ──────────────────────────── move ───────────────────────────────────────────


def move_concept(taxonomy: Taxonomy, uri: str, new_parent_uri: str | None) -> None:
    """Move a concept to a new parent (or to top level if new_parent_uri is None)."""
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)

    if (
        new_parent_uri
        and new_parent_uri not in taxonomy.concepts
        and new_parent_uri not in taxonomy.schemes
    ):
        raise ConceptNotFoundError(new_parent_uri)

    # Guard against circular hierarchy
    if (
        new_parent_uri
        and new_parent_uri in taxonomy.concepts
        and _is_ancestor(taxonomy, uri, new_parent_uri)
    ):
        raise CircularHierarchyError(uri, new_parent_uri)

    # Detach from current parents
    for old_parent_uri in list(concept.broader):
        parent = taxonomy.concepts.get(old_parent_uri)
        if parent and uri in parent.narrower:
            parent.narrower.remove(uri)
    concept.broader.clear()
    concept.top_concept_of = None
    for scheme in taxonomy.schemes.values():
        if uri in scheme.top_concepts:
            scheme.top_concepts.remove(uri)

    # Attach to new parent
    if new_parent_uri is None:
        maybe_scheme = taxonomy.primary_scheme()
        if maybe_scheme:
            maybe_scheme.top_concepts.append(uri)
            concept.top_concept_of = maybe_scheme.uri
    elif new_parent_uri in taxonomy.schemes:
        scheme = taxonomy.schemes[new_parent_uri]
        scheme.top_concepts.append(uri)
        concept.top_concept_of = new_parent_uri
    else:
        new_parent = taxonomy.concepts[new_parent_uri]
        if uri not in new_parent.narrower:
            new_parent.narrower.append(uri)
        concept.broader.append(new_parent_uri)


# ──────────────────────────── add broader link ───────────────────────────────


def add_broader_link(taxonomy: Taxonomy, uri: str, new_parent_uri: str) -> None:
    """Add an additional skos:broader link without removing existing ones.

    The concept keeps all its current parents; new_parent_uri is added as an
    extra broader.  The concept's narrower subtree moves with it (polyhierarchy).
    """
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)
    if new_parent_uri not in taxonomy.concepts:
        raise ConceptNotFoundError(new_parent_uri)
    if new_parent_uri == uri:
        raise CircularHierarchyError(uri, new_parent_uri)
    if _is_ancestor(taxonomy, uri, new_parent_uri):
        raise CircularHierarchyError(uri, new_parent_uri)
    if new_parent_uri in concept.broader:
        return  # already linked — no-op

    concept.broader.append(new_parent_uri)
    new_parent = taxonomy.concepts[new_parent_uri]
    if uri not in new_parent.narrower:
        new_parent.narrower.append(uri)


# ──────────────────────────── labels ─────────────────────────────────────────


def set_label(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    value: str,
    label_type: LabelType = LabelType.PREF,
) -> None:
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)

    if label_type == LabelType.PREF:
        # Replace existing pref label for this language
        concept.labels = [
            lbl for lbl in concept.labels if not (lbl.type == LabelType.PREF and lbl.lang == lang)
        ]
    concept.labels.append(Label(lang=lang, value=value, type=label_type))


def remove_label(
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    value: str,
    label_type: LabelType = LabelType.ALT,
) -> None:
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)
    concept.labels = [
        lbl
        for lbl in concept.labels
        if not (lbl.type == label_type and lbl.lang == lang and lbl.value == value)
    ]


# ──────────────────────────── definitions ────────────────────────────────────


def set_definition(taxonomy: Taxonomy, uri: str, lang: str, value: str) -> None:
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)
    concept.definitions = [d for d in concept.definitions if d.lang != lang]
    concept.definitions.append(Definition(lang=lang, value=value))


def set_scope_note(taxonomy: Taxonomy, uri: str, lang: str, value: str) -> None:
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)
    concept.scope_notes = [sn for sn in concept.scope_notes if sn.lang != lang]
    concept.scope_notes.append(Definition(lang=lang, value=value))


# ──────────────────────────── relations ──────────────────────────────────────


def add_related(taxonomy: Taxonomy, uri_a: str, uri_b: str) -> None:
    for uri in (uri_a, uri_b):
        if uri not in taxonomy.concepts:
            raise ConceptNotFoundError(uri)
    if _is_ancestor(taxonomy, uri_a, uri_b) or _is_ancestor(taxonomy, uri_b, uri_a):
        raise RelatedHierarchyConflictError(uri_a, uri_b)
    a, b = taxonomy.concepts[uri_a], taxonomy.concepts[uri_b]
    if uri_b not in a.related:
        a.related.append(uri_b)
    if uri_a not in b.related:
        b.related.append(uri_a)


def remove_related(taxonomy: Taxonomy, uri_a: str, uri_b: str) -> None:
    for uri in (uri_a, uri_b):
        if uri not in taxonomy.concepts:
            raise ConceptNotFoundError(uri)
    a, b = taxonomy.concepts[uri_a], taxonomy.concepts[uri_b]
    a.related = [u for u in a.related if u != uri_b]
    b.related = [u for u in b.related if u != uri_a]


# ──────────────────────────── rename URI ─────────────────────────────────────


def rename_uri(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    """Change the URI of a concept, updating all cross-references."""
    if old_uri not in taxonomy.concepts:
        raise ConceptNotFoundError(old_uri)
    if new_uri in taxonomy.concepts:
        raise ConceptAlreadyExistsError(new_uri)

    concept = taxonomy.concepts.pop(old_uri)
    concept.uri = new_uri
    taxonomy.concepts[new_uri] = concept

    # Update scheme top_concepts
    for scheme in taxonomy.schemes.values():
        _replace_in_list(scheme.top_concepts, old_uri, new_uri)

    # Update all cross-references
    for c in taxonomy.concepts.values():
        _replace_in_list(c.narrower, old_uri, new_uri)
        _replace_in_list(c.broader, old_uri, new_uri)
        _replace_in_list(c.related, old_uri, new_uri)
        # SKOS mapping properties may point at the renamed concept too
        _replace_in_list(c.broad_match, old_uri, new_uri)
        _replace_in_list(c.narrow_match, old_uri, new_uri)
        _replace_in_list(c.related_match, old_uri, new_uri)
        _replace_in_list(c.exact_match, old_uri, new_uri)
        _replace_in_list(c.close_match, old_uri, new_uri)
        if c.top_concept_of == old_uri:
            c.top_concept_of = new_uri

    assign_handles(taxonomy)


# ──────────────────────────── create scheme ──────────────────────────────────


def create_scheme(
    taxonomy: Taxonomy,
    uri: str,
    labels: dict[str, str],
    descriptions: dict[str, str] | None = None,
    creator: str = "",
    created: str = "",
    languages: list[str] | None = None,
    base_uri: str = "",
) -> ConceptScheme:
    scheme = ConceptScheme(
        uri=uri,
        labels=[Label(lang=lang, value=val) for lang, val in labels.items()],
        descriptions=[
            Definition(lang=lang, value=val) for lang, val in (descriptions or {}).items()
        ],
        creator=creator,
        created=created,
        languages=languages or list(labels.keys()),
        base_uri=base_uri,
    )
    taxonomy.schemes[uri] = scheme
    assign_handles(taxonomy)
    return scheme


# ──────────────────────────── OWL property operations ───────────────────────


def add_owl_property(
    taxonomy: Taxonomy,
    uri: str,
    prop_type: str,
    label: str,
    lang: str,
    domain_uri: str | None = None,
    range_uri: str | None = None,
) -> OWLProperty:
    """Create a new OWL property and register it in *taxonomy*.

    Raises ValueError if *uri* is already taken.
    """
    if uri in taxonomy.owl_properties:
        raise ValueError(f"Property already exists: {uri}")
    labels = [Label(lang=lang, value=label)] if label else []
    domains = [domain_uri] if domain_uri else []
    ranges = [range_uri] if range_uri else []
    prop = OWLProperty(uri=uri, prop_type=prop_type, labels=labels, domains=domains, ranges=ranges)
    taxonomy.owl_properties[uri] = prop
    return prop


def find_individuals_using_property(taxonomy: Taxonomy, prop_uri: str) -> list[str]:
    """Return URIs of all individuals that have at least one value for *prop_uri*."""
    return [
        ind_uri
        for ind_uri, ind in taxonomy.owl_individuals.items()
        if any(pv_uri == prop_uri for pv_uri, _ in ind.property_values)
    ]


def delete_owl_property(taxonomy: Taxonomy, prop_uri: str) -> list[str]:
    """Remove *prop_uri* from *taxonomy* and return impacted individual URIs.

    Raises KeyError if the property does not exist.
    """
    impacted = find_individuals_using_property(taxonomy, prop_uri)
    del taxonomy.owl_properties[prop_uri]
    return impacted


def clear_property_values(taxonomy: Taxonomy, prop_uri: str) -> None:
    """Remove all property-value tuples for *prop_uri* from every individual."""
    for ind in taxonomy.owl_individuals.values():
        ind.property_values = [(p, v) for p, v in ind.property_values if p != prop_uri]


def _owl_subclass_tree(taxonomy: Taxonomy, root_uri: str) -> set[str]:
    """Return all URIs in the OWL subclass tree rooted at *root_uri* (inclusive)."""
    result: set[str] = set()

    def visit(u: str) -> None:
        if u in result:
            return
        result.add(u)
        for other_uri, cls in taxonomy.owl_classes.items():
            if u in cls.sub_class_of and other_uri not in result:
                visit(other_uri)

    visit(root_uri)
    return result


def delete_owl_class(
    taxonomy: Taxonomy,
    uri: str,
    *,
    mode: str,
) -> None:
    """Delete an OWL class from *taxonomy*.

    *mode* controls how subclasses and typed individuals are handled:

    ``"keep_all"``
        Delete the class only.  Direct subclasses are re-parented to the
        deleted class's own parents (or become roots).  Individuals typed
        as the deleted class are re-typed to those same parents.

    ``"cascade_subclasses"``
        Delete the class and all its subclass descendants (transitive).
        Individuals typed to any deleted class are re-typed to the deleted
        class's parents (or lose all types when there are none).

    ``"delete_all"``
        Delete the class, all subclass descendants, and every individual
        typed to any of the deleted classes.
    """
    if uri not in taxonomy.owl_classes:
        return

    deleted_cls = taxonomy.owl_classes[uri]
    # parents of the class being deleted (only those that are themselves OWL classes)
    surviving_parents = [
        p for p in deleted_cls.sub_class_of if p in taxonomy.owl_classes and p != uri
    ]

    if mode == "keep_all":
        deleted_uris: set[str] = {uri}
    else:
        deleted_uris = _owl_subclass_tree(taxonomy, uri)

    # ── handle individuals ─────────────────────────────────────────────────
    for ind_uri in list(taxonomy.owl_individuals):
        ind = taxonomy.owl_individuals[ind_uri]
        affected_types = [t for t in ind.types if t in deleted_uris]
        if not affected_types:
            continue
        if mode == "delete_all":
            del taxonomy.owl_individuals[ind_uri]
            continue
        # keep_all or cascade_subclasses: re-type to surviving parents
        for t in affected_types:
            ind.types.remove(t)
        for parent in surviving_parents:
            if parent not in ind.types:
                ind.types.append(parent)

    # ── remove deleted classes from other classes' sub_class_of ───────────
    for other_uri, cls in taxonomy.owl_classes.items():
        if other_uri in deleted_uris:
            continue
        for dead in deleted_uris:
            if dead in cls.sub_class_of:
                cls.sub_class_of.remove(dead)
                # re-parent: add surviving parents if not already present
                for parent in surviving_parents:
                    if parent not in cls.sub_class_of and parent != other_uri:
                        cls.sub_class_of.append(parent)

    # ── clean property domain/range references ────────────────────────────
    for prop in taxonomy.owl_properties.values():
        prop.domains = [d for d in prop.domains if d not in deleted_uris]
        prop.ranges = [r for r in prop.ranges if r not in deleted_uris]

    # ── delete the classes ────────────────────────────────────────────────
    for dead in deleted_uris:
        taxonomy.owl_classes.pop(dead, None)


# ──────────────────────────── OWL promotion ──────────────────────────────────


def promote_to_class(taxonomy: Taxonomy, uri: str) -> RDFClass:
    """Add an owl:Class layer to an existing SKOS concept at the same URI.

    Labels are copied from skos:prefLabel → rdfs:label and definitions from
    skos:definition → rdfs:comment.  The skos:broader hierarchy is mirrored
    into sub_class_of only for parents that are already OWL classes, keeping
    the two hierarchies independent by default.
    """
    if uri not in taxonomy.concepts:
        raise ConceptNotFoundError(uri)
    if uri in taxonomy.owl_classes:
        return taxonomy.owl_classes[uri]

    concept = taxonomy.concepts[uri]
    rdf_class = RDFClass(
        uri=uri,
        labels=list(concept.labels),
        comments=list(concept.definitions),
        sub_class_of=[p for p in concept.broader if p in taxonomy.owl_classes],
    )
    taxonomy.owl_classes[uri] = rdf_class
    return rdf_class


def demote_from_class(taxonomy: Taxonomy, uri: str) -> None:
    """Remove the owl:Class layer from a promoted concept, leaving the SKOS concept intact."""
    taxonomy.owl_classes.pop(uri, None)


# ──────────────────────────── OWL subclass hierarchy ─────────────────────────


def add_subclass_of(taxonomy: Taxonomy, child_uri: str, parent_uri: str) -> None:
    """Add an rdfs:subClassOf link from child_uri to parent_uri.

    Idempotent: calling twice with the same arguments has no effect.
    Raises ClassNotFoundError if either URI is absent from owl_classes.
    Raises CircularHierarchyError on self-reference or transitively circular links.
    """
    if child_uri not in taxonomy.owl_classes:
        raise ClassNotFoundError(child_uri)
    if parent_uri not in taxonomy.owl_classes:
        raise ClassNotFoundError(parent_uri)
    if child_uri == parent_uri:
        raise CircularHierarchyError(child_uri, parent_uri)
    if _is_class_ancestor(taxonomy, child_uri, parent_uri):
        raise CircularHierarchyError(parent_uri, child_uri)
    child = taxonomy.owl_classes[child_uri]
    if parent_uri not in child.sub_class_of:
        child.sub_class_of.append(parent_uri)


# ──────────────────────────── internal helpers ───────────────────────────────


def _subtree_uris(taxonomy: Taxonomy, root_uri: str) -> set[str]:
    """Return all URIs in the subtree rooted at root_uri (inclusive)."""
    result: set[str] = set()

    def visit(uri: str) -> None:
        if uri in result:
            return
        result.add(uri)
        concept = taxonomy.concepts.get(uri)
        if concept:
            for child_uri in concept.narrower:
                visit(child_uri)

    visit(root_uri)
    return result


def _is_ancestor(taxonomy: Taxonomy, candidate_uri: str, of_uri: str) -> bool:
    """Return True if candidate_uri is an ancestor of of_uri."""
    visited: set[str] = set()

    def check(uri: str) -> bool:
        if uri in visited:
            return False
        visited.add(uri)
        concept = taxonomy.concepts.get(uri)
        if not concept:
            return False
        for parent_uri in concept.broader:
            if parent_uri == candidate_uri:
                return True
            if check(parent_uri):
                return True
        return False

    return check(of_uri)


def _is_class_ancestor(taxonomy: Taxonomy, candidate_uri: str, of_uri: str) -> bool:
    """Return True if candidate_uri is an ancestor of of_uri in the OWL class hierarchy."""
    visited: set[str] = set()

    def check(uri: str) -> bool:
        if uri in visited:
            return False
        visited.add(uri)
        cls = taxonomy.owl_classes.get(uri)
        if not cls:
            return False
        for parent_uri in cls.sub_class_of:
            if parent_uri == candidate_uri:
                return True
            if check(parent_uri):
                return True
        return False

    return check(of_uri)


def _replace_in_list(lst: list[str], old: str, new: str) -> None:
    for i, v in enumerate(lst):
        if v == old:
            lst[i] = new


# ──────────────────────────── OWL URI rename ─────────────────────────────────


def rename_owl_uri(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    """Rename an OWL class, individual, or property URI, updating all references.

    Raises URIAlreadyExistsError if *new_uri* is already occupied by any entity
    in owl_classes, owl_individuals, or owl_properties.
    """
    all_uris = (
        set(taxonomy.owl_classes) | set(taxonomy.owl_individuals) | set(taxonomy.owl_properties)
    )
    if new_uri in all_uris:
        raise URIAlreadyExistsError(new_uri)

    if old_uri in taxonomy.owl_classes:
        _rename_owl_class(taxonomy, old_uri, new_uri)
    elif old_uri in taxonomy.owl_individuals:
        _rename_owl_individual(taxonomy, old_uri, new_uri)
    elif old_uri in taxonomy.owl_properties:
        _rename_owl_property(taxonomy, old_uri, new_uri)


def _rename_owl_class(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    cls = taxonomy.owl_classes.pop(old_uri)
    cls.uri = new_uri
    taxonomy.owl_classes[new_uri] = cls

    # Update own sub_class_of list (if it somehow self-referenced)
    _replace_in_list(cls.sub_class_of, old_uri, new_uri)

    # Update all other classes
    for other_cls in taxonomy.owl_classes.values():
        _replace_in_list(other_cls.sub_class_of, old_uri, new_uri)
        _replace_in_list(other_cls.equivalent_class, old_uri, new_uri)
        _replace_in_list(other_cls.disjoint_with, old_uri, new_uri)

    # Update individuals' rdf:type lists
    for ind in taxonomy.owl_individuals.values():
        _replace_in_list(ind.types, old_uri, new_uri)

    # Update property domains and ranges
    for prop in taxonomy.owl_properties.values():
        _replace_in_list(prop.domains, old_uri, new_uri)
        _replace_in_list(prop.ranges, old_uri, new_uri)


def _rename_owl_individual(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    ind = taxonomy.owl_individuals.pop(old_uri)
    ind.uri = new_uri
    taxonomy.owl_individuals[new_uri] = ind

    # Update other individuals' property_values where this URI appears as value
    for other_ind in taxonomy.owl_individuals.values():
        other_ind.property_values = [
            (p, new_uri if v == old_uri else v) for p, v in other_ind.property_values
        ]
        other_ind.literal_values = [
            (new_uri if p == old_uri else p, v, ld) for p, v, ld in other_ind.literal_values
        ]


def _rename_owl_property(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    prop = taxonomy.owl_properties.pop(old_uri)
    prop.uri = new_uri
    taxonomy.owl_properties[new_uri] = prop

    # Update all individuals' property_values and literal_values where this URI appears as predicate
    for ind in taxonomy.owl_individuals.values():
        ind.property_values = [(new_uri if p == old_uri else p, v) for p, v in ind.property_values]
        ind.literal_values = [
            (new_uri if p == old_uri else p, v, ld) for p, v, ld in ind.literal_values
        ]

    # Update other properties referencing this one via subPropertyOf / inverseOf
    for other_prop in taxonomy.owl_properties.values():
        _replace_in_list(other_prop.sub_property_of, old_uri, new_uri)
        _replace_in_list(other_prop.inverse_of, old_uri, new_uri)


def collect_ontology_entities(taxonomy: Taxonomy) -> list[str]:
    """Return all entity URIs that belong to the current ontology base.

    An entity is "local" if its URI starts with ``ontology_uri + "#"`` or
    ``ontology_uri + "/"``.  Returns an empty list when no ontology URI is set.
    """
    if not taxonomy.ontology_uri:
        return []
    root = taxonomy.ontology_uri.rstrip("#/")
    result: list[str] = []
    for u in (
        list(taxonomy.owl_classes) + list(taxonomy.owl_individuals) + list(taxonomy.owl_properties)
    ):
        if len(u) > len(root) and u.startswith(root) and u[len(root)] in ("#", "/"):
            result.append(u)
    return result


def rename_ontology_uri(taxonomy: Taxonomy, new_uri: str, new_sep: str) -> None:
    """Rename the global ontology URI and propagate the change to all local entities.

    *new_uri* is the bare ontology URI without a trailing separator.
    *new_sep* is ``"#"`` or ``"/"``.

    Only entity URIs that currently share the ontology base are renamed;
    external URIs (other namespaces) are left untouched.  Cross-reference lists
    (subClassOf, types, domains, ranges, property_values) are updated to match
    the new URIs.
    """
    old_uri = (taxonomy.ontology_uri or "").rstrip("#/")
    new_uri = new_uri.rstrip("#/")

    # Detect old separator from existing entities; default to "#"
    old_sep = "#"
    for u in (
        list(taxonomy.owl_classes) + list(taxonomy.owl_individuals) + list(taxonomy.owl_properties)
    ):
        if len(u) > len(old_uri) and u.startswith(old_uri) and u[len(old_uri)] in ("#", "/"):
            old_sep = u[len(old_uri)]
            break

    old_base = old_uri + old_sep
    new_base = new_uri + new_sep

    # Build mapping old → new for every local entity
    old_to_new: dict[str, str] = {}
    for u in (
        list(taxonomy.owl_classes) + list(taxonomy.owl_individuals) + list(taxonomy.owl_properties)
    ):
        if u.startswith(old_base):
            local = u[len(old_base) :]
            old_to_new[u] = new_base + local

    def _remap(lst: list[str]) -> None:
        for i, v in enumerate(lst):
            if v in old_to_new:
                lst[i] = old_to_new[v]

    # ── rename classes ────────────────────────────────────────────────────
    for old, new in list(old_to_new.items()):
        if old in taxonomy.owl_classes:
            cls = taxonomy.owl_classes.pop(old)
            cls.uri = new
            taxonomy.owl_classes[new] = cls

    # ── rename individuals ────────────────────────────────────────────────
    for old, new in list(old_to_new.items()):
        if old in taxonomy.owl_individuals:
            ind = taxonomy.owl_individuals.pop(old)
            ind.uri = new
            taxonomy.owl_individuals[new] = ind

    # ── rename properties ─────────────────────────────────────────────────
    for old, new in list(old_to_new.items()):
        if old in taxonomy.owl_properties:
            prop = taxonomy.owl_properties.pop(old)
            prop.uri = new
            taxonomy.owl_properties[new] = prop

    # ── update cross-references ───────────────────────────────────────────
    for cls in taxonomy.owl_classes.values():
        _remap(cls.sub_class_of)
        _remap(cls.equivalent_class)
        _remap(cls.disjoint_with)

    for ind in taxonomy.owl_individuals.values():
        _remap(ind.types)
        ind.property_values = [
            (old_to_new.get(p, p), old_to_new.get(v, v)) for p, v in ind.property_values
        ]
        ind.literal_values = [(old_to_new.get(p, p), v, ld) for p, v, ld in ind.literal_values]

    for prop in taxonomy.owl_properties.values():
        _remap(prop.domains)
        _remap(prop.ranges)
        _remap(prop.sub_property_of)
        _remap(prop.inverse_of)

    taxonomy.ontology_uri = new_uri


def count_ontology_rename_changes(
    taxonomy: Taxonomy, new_uri: str, new_sep: str
) -> tuple[str, str, int]:
    """Return (old_base, new_base, count) for a prospective ontology base URI rename.

    *old_base* is the current base URI with its detected separator appended.
    *new_base* is *new_uri* + *new_sep*.
    *count* is the number of local entities whose URI would change (0 when unchanged).
    """
    old_uri = (taxonomy.ontology_uri or "").rstrip("#/")
    new_uri_clean = new_uri.rstrip("#/")

    old_sep = "#"
    for u in (
        list(taxonomy.owl_classes) + list(taxonomy.owl_individuals) + list(taxonomy.owl_properties)
    ):
        if len(u) > len(old_uri) and u.startswith(old_uri) and u[len(old_uri)] in ("#", "/"):
            old_sep = u[len(old_uri)]
            break

    old_base = old_uri + old_sep
    new_base = new_uri_clean + new_sep

    if old_base == new_base:
        return old_base, new_base, 0

    return old_base, new_base, len(collect_ontology_entities(taxonomy))


def count_owl_uri_references(taxonomy: Taxonomy, uri: str) -> int:
    """Count the number of RDF-model positions where *uri* appears.

    Counts both the entity's own triples (subject) and all cross-references
    from other entities (object / predicate).  Used to inform the user how
    many statements will change when a URI is renamed.
    """
    count = 0

    # ── subject: the entity's own triples ─────────────────────────────────
    if uri in taxonomy.owl_classes:
        cls = taxonomy.owl_classes[uri]
        count += 1  # rdf:type owl:Class
        count += len(cls.labels)
        count += len(cls.comments)
        count += len(cls.sub_class_of)
        count += len(cls.equivalent_class)
        count += len(cls.disjoint_with)

    if uri in taxonomy.owl_individuals:
        ind = taxonomy.owl_individuals[uri]
        count += 1  # rdf:type owl:NamedIndividual
        count += len(ind.labels)
        count += len(ind.comments)
        count += len(ind.types)
        count += len(ind.property_values)

    if uri in taxonomy.owl_properties:
        prop = taxonomy.owl_properties[uri]
        count += 1  # rdf:type owl:ObjectProperty / owl:DatatypeProperty
        count += len(prop.labels)
        count += len(prop.comments)
        count += len(prop.domains)
        count += len(prop.ranges)

    # ── object / predicate: references from other entities ────────────────
    for cls_uri, cls in taxonomy.owl_classes.items():
        if cls_uri == uri:
            continue
        count += cls.sub_class_of.count(uri)
        count += cls.equivalent_class.count(uri)
        count += cls.disjoint_with.count(uri)

    for ind_uri, ind in taxonomy.owl_individuals.items():
        if ind_uri == uri:
            continue
        count += ind.types.count(uri)
        count += sum(1 for p, v in ind.property_values if p == uri or v == uri)
        count += sum(1 for p, _v, _ld in ind.literal_values if p == uri)

    for prop_uri, prop in taxonomy.owl_properties.items():
        if prop_uri == uri:
            continue
        count += prop.domains.count(uri)
        count += prop.ranges.count(uri)
        count += prop.sub_property_of.count(uri)
        count += prop.inverse_of.count(uri)

    return count


def count_concept_uri_references(taxonomy: Taxonomy, uri: str) -> int:
    """Count RDF-model positions where *uri* appears in the SKOS layer.

    SKOS-layer counterpart of :func:`count_owl_uri_references`: counts the
    concept's own triples (subject) plus every cross-reference from other
    concepts (broader / narrower / related / *Match) and from scheme
    ``top_concepts`` lists (object).
    """
    count = 0

    # ── subject: the concept's own triples ────────────────────────────────
    if uri in taxonomy.concepts:
        c = taxonomy.concepts[uri]
        count += 1  # rdf:type skos:Concept
        count += len(c.labels)
        count += len(c.definitions)
        count += len(c.scope_notes)
        count += len(c.broader)
        count += len(c.narrower)
        count += len(c.related)
        count += len(c.broad_match)
        count += len(c.narrow_match)
        count += len(c.related_match)
        count += len(c.exact_match)
        count += len(c.close_match)
        if c.top_concept_of:
            count += 1

    # ── object: cross-references from other concepts ──────────────────────
    for c_uri, c in taxonomy.concepts.items():
        if c_uri == uri:
            continue
        count += c.broader.count(uri)
        count += c.narrower.count(uri)
        count += c.related.count(uri)
        count += c.broad_match.count(uri)
        count += c.narrow_match.count(uri)
        count += c.related_match.count(uri)
        count += c.exact_match.count(uri)
        count += c.close_match.count(uri)

    # ── object: scheme hasTopConcept references ───────────────────────────
    for scheme in taxonomy.schemes.values():
        count += scheme.top_concepts.count(uri)

    return count


# ──────────────────────── common rename front ────────────────────────────────
# The generic flow — detect the layer(s) owning a URI, count affected
# statements, and rename — is identical for SKOS and OWL.  These dispatchers
# hide the SKOS-vs-OWL specifics so callers (e.g. the viewer) stay layer-
# agnostic; a node promoted to both layers is handled in both.


def rename_kind(taxonomy: Taxonomy, uri: str) -> str:
    """Return the entity-kind label for *uri*.

    One of ``"concept"``, ``"class"``, ``"individual"``, ``"property"``,
    ``"promoted"`` (concept + class), or ``"unknown"``.
    """
    return taxonomy.node_type(uri)


def _owns_owl(taxonomy: Taxonomy, uri: str) -> bool:
    return (
        uri in taxonomy.owl_classes
        or uri in taxonomy.owl_individuals
        or uri in taxonomy.owl_properties
    )


def count_uri_references(taxonomy: Taxonomy, uri: str) -> int:
    """Total statements affected by renaming *uri*, across every layer it owns.

    Dispatches to :func:`count_concept_uri_references` and/or
    :func:`count_owl_uri_references`; a promoted node sums both.
    """
    total = 0
    if uri in taxonomy.concepts:
        total += count_concept_uri_references(taxonomy, uri)
    if _owns_owl(taxonomy, uri):
        total += count_owl_uri_references(taxonomy, uri)
    return total


def rename_entity_uri(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    """Rename *old_uri* to *new_uri* in every layer that owns it.

    Performs a single unified collision check (raising
    :class:`URIAlreadyExistsError` if *new_uri* is already taken in any layer)
    before delegating to the SKOS-specialized :func:`rename_uri` and/or the
    OWL-specialized :func:`rename_owl_uri`.  Raises
    :class:`ConceptNotFoundError` when *old_uri* exists in no layer.
    """
    in_concepts = old_uri in taxonomy.concepts
    in_owl = _owns_owl(taxonomy, old_uri)
    if not in_concepts and not in_owl:
        raise ConceptNotFoundError(old_uri)

    if new_uri in taxonomy.concepts or _owns_owl(taxonomy, new_uri):
        raise URIAlreadyExistsError(new_uri)

    if in_concepts:
        rename_uri(taxonomy, old_uri, new_uri)
    if in_owl:
        rename_owl_uri(taxonomy, old_uri, new_uri)

    assign_handles(taxonomy)
