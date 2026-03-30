"""Business logic — all mutations to a Taxonomy live here."""
from __future__ import annotations
from .model import Concept, ConceptScheme, Definition, Label, LabelType, Taxonomy
from .handles import assign_handles, handle_for_uri
from .exceptions import (
    CircularHierarchyError,
    ConceptAlreadyExistsError,
    ConceptNotFoundError,
    DuplicatePrefLabelError,
    HandleNotFoundError,
    HasChildrenError,
    RelatedHierarchyConflictError,
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
        scheme = taxonomy.primary_scheme()
        if scheme:
            if uri not in scheme.top_concepts:
                scheme.top_concepts.append(uri)
            concept.top_concept_of = scheme.uri

    taxonomy.concepts[uri] = concept

    # Assign a handle for the new concept
    used = set(taxonomy.handle_index.keys())
    h = handle_for_uri(uri, used)
    taxonomy.handle_index[h] = uri

    return concept


# ──────────────────────────── remove ─────────────────────────────────────────

def remove_concept(
    taxonomy: Taxonomy, uri: str, *, cascade: bool = False
) -> set[str]:
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
        c.broader  = [u for u in c.broader  if u not in to_remove]
    for scheme in taxonomy.schemes.values():
        scheme.top_concepts = [u for u in scheme.top_concepts if u not in to_remove]

    # Rebuild handle index (removed concepts should no longer appear)
    assign_handles(taxonomy)
    return to_remove


# ──────────────────────────── move ───────────────────────────────────────────

def move_concept(
    taxonomy: Taxonomy, uri: str, new_parent_uri: str | None
) -> None:
    """Move a concept to a new parent (or to top level if new_parent_uri is None)."""
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)

    if new_parent_uri and new_parent_uri not in taxonomy.concepts and new_parent_uri not in taxonomy.schemes:
        raise ConceptNotFoundError(new_parent_uri)

    # Guard against circular hierarchy
    if new_parent_uri and new_parent_uri in taxonomy.concepts:
        if _is_ancestor(taxonomy, uri, new_parent_uri):
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
        scheme = taxonomy.primary_scheme()
        if scheme:
            scheme.top_concepts.append(uri)
            concept.top_concept_of = scheme.uri
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

def add_broader_link(
    taxonomy: Taxonomy, uri: str, new_parent_uri: str
) -> None:
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
            lbl for lbl in concept.labels
            if not (lbl.type == LabelType.PREF and lbl.lang == lang)
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
        lbl for lbl in concept.labels
        if not (lbl.type == label_type and lbl.lang == lang and lbl.value == value)
    ]


# ──────────────────────────── definitions ────────────────────────────────────

def set_definition(taxonomy: Taxonomy, uri: str, lang: str, value: str) -> None:
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        raise ConceptNotFoundError(uri)
    concept.definitions = [d for d in concept.definitions if d.lang != lang]
    concept.definitions.append(Definition(lang=lang, value=value))


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
        descriptions=[Definition(lang=lang, value=val) for lang, val in (descriptions or {}).items()],
        creator=creator,
        created=created,
        languages=languages or list(labels.keys()),
        base_uri=base_uri,
    )
    taxonomy.schemes[uri] = scheme
    assign_handles(taxonomy)
    return scheme


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


def _replace_in_list(lst: list[str], old: str, new: str) -> None:
    for i, v in enumerate(lst):
        if v == old:
            lst[i] = new
