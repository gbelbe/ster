"""SKOS concept operations — concepts, labels, definitions, relations, schemes.

Part of the domain layer (docs/architecture/module-layout.md): reached through
``ster.operations``, never imported directly by a front-end.
"""

from __future__ import annotations

from ..exceptions import (
    CircularHierarchyError,
    ConceptAlreadyExistsError,
    ConceptNotFoundError,
    HandleNotFoundError,
    HasChildrenError,
    RelatedHierarchyConflictError,
    SchemeNotFoundError,
    URIAlreadyExistsError,
)
from ..handles import assign_handles, handle_for_uri
from ..model import Concept, ConceptScheme, Definition, Label, LabelType, Taxonomy
from ._shared import _replace_in_list


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
    if taxonomy.uri_taken(uri):  # taken by a scheme / class / individual / property
        raise URIAlreadyExistsError(uri)

    labels = [Label(lang=lang, value=val) for lang, val in pref_labels.items()]
    defns = [Definition(lang=lang, value=val) for lang, val in (definitions or {}).items()]
    concept = Concept(uri=uri, labels=labels, definitions=defns)

    _attach_new_concept(taxonomy, concept, uri, parent_handle)
    taxonomy.concepts[uri] = concept

    # Assign a handle for the new concept
    used = set(taxonomy.handle_index.keys())
    h = handle_for_uri(uri, used)
    taxonomy.handle_index[h] = uri

    return concept


def _attach_as_top_concept(concept: Concept, uri: str, scheme: ConceptScheme | None) -> None:
    """Attach *concept* as a top concept of *scheme* (no-op when *scheme* is None)."""
    if scheme is None:
        return
    if uri not in scheme.top_concepts:
        scheme.top_concepts.append(uri)
    concept.top_concept_of = scheme.uri


def _attach_new_concept(
    taxonomy: Taxonomy, concept: Concept, uri: str, parent_handle: str | None
) -> None:
    """Link a freshly built concept under its parent (scheme top-concept or narrower)."""
    if not parent_handle:
        _attach_as_top_concept(concept, uri, taxonomy.primary_scheme())
        return
    parent_uri = taxonomy.resolve(parent_handle)
    if parent_uri is None:
        raise HandleNotFoundError(parent_handle)
    if parent_uri in taxonomy.schemes:
        _attach_as_top_concept(concept, uri, taxonomy.schemes[parent_uri])
    else:
        parent = taxonomy.concepts[parent_uri]
        if uri not in parent.narrower:
            parent.narrower.append(uri)
        concept.broader.append(parent_uri)


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
        _detach_and_delete_concept(taxonomy, r_uri)
    _strip_dangling_concept_refs(taxonomy, to_remove)
    assign_handles(taxonomy)  # rebuild handle index (removed concepts gone)
    return to_remove


def remove_scheme(taxonomy: Taxonomy, uri: str, *, cascade: bool = False) -> set[str]:
    """Remove a concept scheme. Returns the set of removed URIs (the scheme, plus
    every concept in it when *cascade* is True).

    Without cascade the scheme's concepts survive; any concept that was a top
    concept of this scheme has its ``top_concept_of`` link cleared. With cascade
    every concept reachable from the scheme's top concepts is deleted too.

    Raises ``SchemeNotFoundError`` if the scheme does not exist.
    """
    scheme = taxonomy.schemes.get(uri)
    if scheme is None:
        raise SchemeNotFoundError(uri)

    removed: set[str] = {uri}
    if cascade:
        concept_uris: set[str] = set()
        for top_uri in scheme.top_concepts:
            concept_uris |= _subtree_uris(taxonomy, top_uri)
        for c_uri in concept_uris:
            _detach_and_delete_concept(taxonomy, c_uri)
        _strip_dangling_concept_refs(taxonomy, concept_uris)
        removed |= concept_uris
    else:
        for concept in taxonomy.concepts.values():
            if concept.top_concept_of == uri:
                concept.top_concept_of = None

    del taxonomy.schemes[uri]
    assign_handles(taxonomy)  # rebuild handle index (removed entities gone)
    return removed


def _detach_and_delete_concept(taxonomy: Taxonomy, r_uri: str) -> None:
    """Detach *r_uri* from parents, schemes, and related links, then delete it."""
    c = taxonomy.concepts.get(r_uri)
    if c is None:
        return
    for parent_uri in c.broader:
        parent = taxonomy.concepts.get(parent_uri)
        if parent and r_uri in parent.narrower:
            parent.narrower.remove(r_uri)
    for scheme in taxonomy.schemes.values():
        if r_uri in scheme.top_concepts:
            scheme.top_concepts.remove(r_uri)
    for other in taxonomy.concepts.values():
        if r_uri in other.related:
            other.related.remove(r_uri)
    del taxonomy.concepts[r_uri]


def _strip_dangling_concept_refs(taxonomy: Taxonomy, removed: set[str]) -> None:
    """Defensive pass: drop any remaining refs to *removed* across all concepts/schemes.

    Handles inconsistent data or multi-broader scenarios left after the main pass.
    """
    for c in taxonomy.concepts.values():
        c.narrower = [u for u in c.narrower if u not in removed]
        c.broader = [u for u in c.broader if u not in removed]
    for scheme in taxonomy.schemes.values():
        scheme.top_concepts = [u for u in scheme.top_concepts if u not in removed]


def move_concept(taxonomy: Taxonomy, uri: str, new_parent_uri: str | None) -> None:
    """Move a concept to a new parent (or to top level if new_parent_uri is None)."""
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)

    _validate_move_target(taxonomy, uri, new_parent_uri)
    _detach_concept_from_hierarchy(taxonomy, concept, uri)
    _attach_moved_concept(taxonomy, concept, uri, new_parent_uri)


def _validate_move_target(taxonomy: Taxonomy, uri: str, new_parent_uri: str | None) -> None:
    """Reject an unknown move target, or one that would create a cycle."""
    if (
        new_parent_uri
        and new_parent_uri not in taxonomy.concepts
        and new_parent_uri not in taxonomy.schemes
    ):
        raise ConceptNotFoundError(new_parent_uri)
    if (
        new_parent_uri
        and new_parent_uri in taxonomy.concepts
        and _is_ancestor(taxonomy, uri, new_parent_uri)
    ):
        raise CircularHierarchyError(uri, new_parent_uri)


def _detach_concept_from_hierarchy(taxonomy: Taxonomy, concept: Concept, uri: str) -> None:
    """Remove *concept* from all its current parents and scheme top-concept lists."""
    for old_parent_uri in list(concept.broader):
        parent = taxonomy.concepts.get(old_parent_uri)
        if parent and uri in parent.narrower:
            parent.narrower.remove(uri)
    concept.broader.clear()
    concept.top_concept_of = None
    for scheme in taxonomy.schemes.values():
        if uri in scheme.top_concepts:
            scheme.top_concepts.remove(uri)


def _attach_moved_concept(
    taxonomy: Taxonomy, concept: Concept, uri: str, new_parent_uri: str | None
) -> None:
    """Attach *concept* under its new parent (primary scheme, a named scheme, or a concept)."""
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


def _replace_literal(taxonomy: Taxonomy, uri: str, attr: str, lang: str, value: str) -> None:
    """Replace the *lang* entry of a concept's literal list *attr* (definitions/scope_notes)."""
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)
    items = [it for it in getattr(concept, attr) if it.lang != lang]
    items.append(Definition(lang=lang, value=value))
    setattr(concept, attr, items)


def set_definition(taxonomy: Taxonomy, uri: str, lang: str, value: str) -> None:
    _replace_literal(taxonomy, uri, "definitions", lang, value)


def set_scope_note(taxonomy: Taxonomy, uri: str, lang: str, value: str) -> None:
    _replace_literal(taxonomy, uri, "scope_notes", lang, value)


def remove_definition(taxonomy: Taxonomy, uri: str, lang: str) -> None:
    """Remove the concept's ``skos:definition`` for *lang*."""
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)
    concept.definitions = [d for d in concept.definitions if d.lang != lang]


def remove_scope_note(taxonomy: Taxonomy, uri: str, lang: str, value: str) -> None:
    """Remove the concept's matching ``skos:scopeNote`` (*lang* + *value*)."""
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)
    concept.scope_notes = [
        sn for sn in concept.scope_notes if not (sn.lang == lang and sn.value == value)
    ]


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
    if taxonomy.uri_taken(uri):  # taken by a concept / class / individual / property
        raise URIAlreadyExistsError(uri)
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


def _set_scheme_base_uri(scheme: ConceptScheme, value: str, _lang: str) -> None:
    scheme.base_uri = value or ""


def _set_scheme_title(scheme: ConceptScheme, value: str, lang: str) -> None:
    for lbl in scheme.labels:
        if lbl.type == LabelType.PREF and lbl.lang == lang:
            lbl.value = value
            return
    scheme.labels.append(Label(lang=lang, value=value, type=LabelType.PREF))


def _set_scheme_desc(scheme: ConceptScheme, value: str, lang: str) -> None:
    for desc in scheme.descriptions:
        if desc.lang == lang:
            desc.value = value
            return
    scheme.descriptions.append(Definition(lang=lang, value=value))


def _set_scheme_creator(scheme: ConceptScheme, value: str, _lang: str) -> None:
    scheme.creator = value


def _set_scheme_created(scheme: ConceptScheme, value: str, _lang: str) -> None:
    scheme.created = value


def _set_scheme_languages(scheme: ConceptScheme, value: str, _lang: str) -> None:
    scheme.languages = [lg.strip() for lg in value.split(",") if lg.strip()]


# Dispatch table: scheme field name → setter. Keeps set_scheme_field flat (no
# if/elif ladder) and makes adding a field a one-row change.
_SCHEME_FIELD_SETTERS = {
    "base_uri": _set_scheme_base_uri,
    "title": _set_scheme_title,
    "desc": _set_scheme_desc,
    "creator": _set_scheme_creator,
    "created": _set_scheme_created,
    "languages": _set_scheme_languages,
}


# Concept attributes holding cross-scheme SKOS mapping links.
_MAPPING_ATTRS = {"broad_match", "narrow_match", "related_match", "exact_match", "close_match"}


def add_concept_mapping_link(
    taxonomy: Taxonomy, concept_uri: str, attr: str, target_uri: str
) -> None:
    """Append *target_uri* to one mapping-property list on a concept (dedup).

    *attr* is a Python mapping attribute (e.g. ``exact_match``). One *direction*
    only — the inverse link is a separate call on the target's file. No-op for an
    unknown concept or non-mapping attr."""
    concept = taxonomy.concepts.get(concept_uri)
    if concept is None or attr not in _MAPPING_ATTRS:
        return
    lst: list[str] = getattr(concept, attr)
    if target_uri not in lst:
        lst.append(target_uri)


def remove_concept_mapping_link(
    taxonomy: Taxonomy, concept_uri: str, attr: str, target_uri: str
) -> None:
    """Remove *target_uri* from one mapping-property list on a concept (no-op if absent)."""
    concept = taxonomy.concepts.get(concept_uri)
    if concept is None or attr not in _MAPPING_ATTRS:
        return
    lst: list[str] = getattr(concept, attr)
    if target_uri in lst:
        lst.remove(target_uri)


def set_scheme_field(
    taxonomy: Taxonomy, scheme_uri: str, field_name: str, value: str, lang: str = ""
) -> None:
    """Set one field of a ``skos:ConceptScheme`` (no-op for an unknown scheme or field).

    *field_name* is one of ``base_uri`` / ``title`` / ``desc`` / ``creator`` /
    ``created`` / ``languages``; *lang* applies to the localized ones."""
    scheme = taxonomy.schemes.get(scheme_uri)
    if scheme is None:
        return
    setter = _SCHEME_FIELD_SETTERS.get(field_name)
    if setter is not None:
        setter(scheme, value, lang)


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
