"""Whole-ontology search (build_search_results), independent of what is
currently rendered.

The client's ``#search-box`` (``searchNodes()`` in ``graph_app.js``) only
ever filtered ``cy.nodes()`` — the elements already on the canvas. Once the
default view is scoped (see ``build_default_vowl_graph``, Phase 0), most of
a large ontology is not on the canvas, so that box would silently miss most
matches. This module is the server-side counterpart: a linear scan over the
in-memory ``Taxonomy`` for classes, individuals, concepts and schemes, used
by ``/api/search`` to find matches regardless of what the client has drawn.

A linear scan is deliberate, not a placeholder for something fancier: at the
node counts these ontologies run at (thousands, not millions — see
CLASS_COLLAPSE_LIMIT and INDIVIDUAL_COLLAPSE_LIMIT), a scan over labels is a
handful of milliseconds. Revisit only if that stops being true on the
largest real ontology (see docs/architecture/graph-editor.md, Phase 2).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

from ..model import Taxonomy
from ..viz import _label_for

_LIT_ID: Final = "id"
_LIT_LABEL: Final = "label"
_LIT_TYPE: Final = "type"

# Matches the default page size a person can usefully scan; a term that
# matches more than this is too broad to be a "find this one thing" search.
_DEFAULT_LIMIT = 50


def _candidate_uris(taxonomy: Taxonomy) -> Iterator[tuple[str, str]]:
    """Yield (uri, node_type) for every entity search can match. Mostly the
    same type vocabulary the client's node data already uses, plus "property"
    — OWL properties are never drawn as their own graph node, but Phase 4's
    relation picker (see docs/architecture/graph-editor.md) needs to search
    them by label too, so they are searchable without being renderable."""
    top_concept_uris = {u for u, c in taxonomy.concepts.items() if c.top_concept_of}
    for uri in taxonomy.schemes:
        yield uri, "scheme"
    for uri in taxonomy.owl_classes:
        yield uri, "class"
    for uri in taxonomy.owl_individuals:
        yield uri, "individual"
    for uri in taxonomy.owl_properties:
        yield uri, "property"
    for uri in taxonomy.concepts:
        yield uri, "topconcept" if uri in top_concept_uris else "concept"


def _label_for_search(uri: str, node_type: str, taxonomy: Taxonomy) -> str:
    # _label_for covers classes/individuals/concepts/properties but not SKOS
    # schemes (there is no per-scheme case in it — schemes aren't a node type
    # it was written for), so schemes are looked up directly here instead of
    # falling through to _label_for's _local(uri) default, which would search
    # the URI's local name rather than the scheme's actual title.
    if node_type == "scheme":
        return taxonomy.schemes[uri].title("en")
    return _label_for(uri, taxonomy)


def build_search_results(
    taxonomy: Taxonomy,
    query: str,
    limit: int = _DEFAULT_LIMIT,
    types: set[str] | None = None,
) -> dict:
    """Return ``{"results": [{"id", "label", "type"}, ...]}`` for every entity
    whose label or URI contains *query* (case-insensitive), capped at *limit*.

    Mirrors the matching rule the client already applies to on-canvas nodes
    (``n.data('label').toLowerCase().includes(t) || n.data('id')...``), so a
    server match and a canvas match never disagree on what "matches" means.

    *types*, when given, restricts the scan to those node types (e.g. Phase
    4's relation picker searching only ``{"property"}`` or ``{"individual"}``
    so a class doesn't show up as a candidate object-property target).
    """
    term = query.strip().lower()
    if not term:
        return {"results": []}

    results: list[dict] = []
    for uri, node_type in _candidate_uris(taxonomy):
        if types is not None and node_type not in types:
            continue
        label = _label_for_search(uri, node_type, taxonomy)
        if term not in label.lower() and term not in uri.lower():
            continue
        results.append({_LIT_ID: uri, _LIT_LABEL: label, _LIT_TYPE: node_type})
        if len(results) >= limit:
            break
    # Local labels read better than raw URIs when two entities tie on
    # relevance; stable-sort keeps scan order (schemes, classes, individuals,
    # concepts) as the tiebreak, which is also roughly "most likely wanted first".
    results.sort(key=lambda r: r[_LIT_LABEL].lower())
    return {"results": results}


__all__ = ["build_search_results"]
