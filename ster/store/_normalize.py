"""Post-load hierarchy normalization (symmetric broader/narrower, top-concept
bookkeeping) and the namespace/prefix helpers shared by serialization."""

from __future__ import annotations

from rdflib import Graph, Namespace

from ..model import Taxonomy


def _normalize_hierarchy(taxonomy: Taxonomy) -> None:
    """Ensure skos:broader/narrower and skos:topConceptOf/hasTopConcept are symmetric."""
    _normalize_concept_links(taxonomy)
    _normalize_scheme_links(taxonomy)
    _assign_orphan_top_concepts(taxonomy)


def _normalize_concept_links(taxonomy: Taxonomy) -> None:
    for uri, concept in taxonomy.concepts.items():
        for child_uri in concept.narrower:
            child = taxonomy.concepts.get(child_uri)
            if child and uri not in child.broader:
                child.broader.append(uri)
        for parent_uri in concept.broader:
            parent = taxonomy.concepts.get(parent_uri)
            if parent and uri not in parent.narrower:
                parent.narrower.append(uri)


def _normalize_scheme_links(taxonomy: Taxonomy) -> None:
    for scheme_uri, scheme in taxonomy.schemes.items():
        for tc_uri in scheme.top_concepts:
            tc_concept = taxonomy.concepts.get(tc_uri)
            if tc_concept and tc_concept.top_concept_of is None:
                tc_concept.top_concept_of = scheme_uri

    for concept_uri, concept in taxonomy.concepts.items():
        if concept.top_concept_of:
            tc_scheme = taxonomy.schemes.get(concept.top_concept_of)
            if tc_scheme and concept_uri not in tc_scheme.top_concepts:
                tc_scheme.top_concepts.append(concept_uri)


def _assign_orphan_top_concepts(taxonomy: Taxonomy) -> None:
    primary = taxonomy.primary_scheme()
    for concept_uri, concept in taxonomy.concepts.items():
        if concept.broader or concept.top_concept_of:
            continue
        in_any_scheme = any(concept_uri in s.top_concepts for s in taxonomy.schemes.values())
        if not in_any_scheme and primary:
            primary.top_concepts.append(concept_uri)
            concept.top_concept_of = primary.uri
            taxonomy.inferred_top_concepts.add(concept_uri)


def _concept_scheme_uri(
    taxonomy: Taxonomy, uri: str, _visited: frozenset[str] | None = None
) -> str | None:
    """Return the scheme URI for a concept by traversing up to a top concept."""
    if _visited is None:
        _visited = frozenset()
    if uri in _visited:
        return None
    concept = taxonomy.concepts.get(uri)
    if not concept:
        return None
    if concept.top_concept_of:
        return concept.top_concept_of
    _visited = _visited | {uri}
    for parent_uri in concept.broader:
        s = _concept_scheme_uri(taxonomy, parent_uri, _visited)
        if s:
            return s
    return None


def _bind_namespace(g: Graph, taxonomy: Taxonomy) -> None:
    """Bind a short 'wv' fallback prefix for the primary concept namespace —
    unless the user already bound a prefix to it (don't clobber their choice)."""
    uris = list(taxonomy.concepts) + list(taxonomy.schemes)
    if not uris:
        return
    # Find the common base by taking the longest common prefix ending in / or #
    first = uris[0]
    for sep in ("#", "/"):
        if sep in first:
            base = first.rsplit(sep, 1)[0] + sep
            if all(u.startswith(base) for u in uris):
                base_root = base.rstrip("#/")
                if any(ns.rstrip("#/") == base_root for ns in taxonomy.namespace_bindings.values()):
                    return  # a user prefix is already bound to this namespace
                g.bind("wv", Namespace(base))
                return
