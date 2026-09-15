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
        return {"results": [], "total": 0, "truncated": False}

    scored: list[tuple[tuple[int, int, str], dict]] = []
    for uri, node_type in _candidate_uris(taxonomy):
        if types is not None and node_type not in types:
            continue
        label = _label_for_search(uri, node_type, taxonomy)
        rank = _rank(term, label, uri)
        if rank is None:
            continue
        scored.append(
            (
                (rank, len(label), label.lower()),
                {_LIT_ID: uri, _LIT_LABEL: label, _LIT_TYPE: node_type},
            )
        )

    # Rank first, cut second. Cutting first — which is what stopping the scan at
    # *limit* did — returns whichever 50 the scan reached, so searching "person"
    # in an ontology holding 7,888 matches led with four numeric ids that matched
    # on URI and happened to sort before the letter P. The class actually called
    # Person was in there, indistinguishable from them.
    scored.sort(key=lambda pair: pair[0])
    total = len(scored)
    return {
        "results": [entry for _key, entry in scored[:limit]],
        # So the caller can say "50 of 7,888" instead of showing 50 and implying
        # that is all there is.
        "total": total,
        "truncated": total > limit,
    }


def _rank(term: str, label: str, uri: str) -> int | None:
    """How well *term* matches, lower being better; ``None`` when it does not.

    A search box is judged on its first line, so an exact label beats a prefix
    beats a word-prefix beats any old substring, and a match that exists only in
    the URI comes last — those are usually opaque ids, and a term that appears
    in one by coincidence should never outrank the thing you named.
    """
    low = label.lower()
    if low == term:
        return 0
    if low.startswith(term):
        return 1
    if any(word.startswith(term) for word in low.replace("-", " ").replace("_", " ").split()):
        return 2
    if term in low:
        return 3
    if term in uri.lower():
        return 4
    return None


__all__ = ["build_search_results"]
