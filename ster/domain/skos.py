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
