"""Build the graph payload from a SPARQL CONSTRUCT rather than from the model.

The model walk in :mod:`._graph_builders` answers "what does ster understand
about this ontology". This answers "what did you ask for" — and the two are not
the same question. The model knows only what it types; a query reaches anything
in the graph, including the statements a context file makes, whatever a reasoner
added, and relations no dataclass has a field for.

CONSTRUCT rather than SELECT, deliberately. A CONSTRUCT returns triples, and
triples already *are* nodes and edges — nothing has to agree in advance on
which column means "source". The map takes SELECT because it needs ?lat and
?long by name; a graph wants a subgraph. Each view asks in the shape of its
answer.

The payload is identical to the model builder's, so the page renders either
without knowing which produced it.
"""

from __future__ import annotations

import itertools
from typing import Any, Final

# Predicates that describe a node rather than link two, so they become labels
# and types instead of edges. Anything else with a URI object is a real edge.
_LABEL_PREDICATES = frozenset(
    {
        "http://www.w3.org/2000/01/rdf-schema#label",  # NOSONAR - RDF predicate IRI
        "http://www.w3.org/2004/02/skos/core#prefLabel",  # NOSONAR - RDF predicate IRI
    }
)
_TYPE_PREDICATE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"  # NOSONAR - RDF predicate IRI
_SUBCLASS_PREDICATE = "http://www.w3.org/2000/01/rdf-schema#subClassOf"  # NOSONAR - RDF predicate

# Payload keys, named once: the ratchet counts a third repeat of a literal as
# duplication, and these are the keys every node and edge carries.
_LIT_LABEL: Final = "label"
_LIT_NODES: Final = "nodes"
_LIT_EDGES: Final = "edges"
_LIT_LAYOUT: Final = "layout"

_CLASS_TYPES = frozenset(
    {
        "http://www.w3.org/2002/07/owl#Class",  # NOSONAR - RDF class IRI
        "http://www.w3.org/2000/01/rdf-schema#Class",  # NOSONAR - RDF class IRI
    }
)


def _plain(literal: str) -> str:
    """A literal as the reader sees it: no surrounding quotes, no language tag.

    CONSTRUCT output is stringified N-Triples, so a label arrives as
    ``"Castorama"@en``. The quoting and the tag are machinery; putting them on
    a node would show the reader the serialisation rather than the name.
    """
    text = literal.strip()
    if text.startswith('"'):
        closing = text.rfind('"')
        if closing > 0:
            return text[1:closing]
    return text


def _local(uri: str) -> str:
    """The readable tail of a URI, for a node with no label of its own."""
    return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] or uri


def graph_from_triples(
    triples: list[tuple[str, str, str]], context: set[str] | None = None
) -> dict:
    """A Cytoscape payload built from CONSTRUCT output.

    *context* names URIs that came from a read-only file, so they can be dimmed
    exactly as the model builder dims them — a node you cannot edit must not
    look like one you can, whichever path drew it.
    """
    context = context or set()
    labels: dict[str, str] = {}
    types: dict[str, set[str]] = {}
    links: list[tuple[str, str, str]] = []
    subjects: set[str] = set()

    for subject, predicate, obj in triples:
        subjects.add(subject)
        if predicate in _LABEL_PREDICATES:
            labels.setdefault(subject, _plain(obj))
        elif predicate == _TYPE_PREDICATE:
            types.setdefault(subject, set()).add(obj)
        elif predicate == _SUBCLASS_PREDICATE:
            links.append((subject, obj, "subClassOf"))
        elif obj.startswith(("http://", "https://", "urn:")):  # NOSONAR - scheme test
            links.append((subject, obj, _local(predicate)))

    # A link's target is a node too, even when the query said nothing else about
    # it — dropping it would leave an edge pointing at nothing and Cytoscape
    # silently discards the edge, so the answer would look smaller than it is.
    for source, target, _kind in links:
        subjects.update((source, target))

    nodes = [
        {
            "id": uri,
            _LIT_LABEL: labels.get(uri, _local(uri)),
            "type": "class" if types.get(uri, set()) & _CLASS_TYPES else "individual",
            "readOnly": 1 if uri in context else 0,
            "rootClass": 0,
        }
        for uri in sorted(subjects)
    ]
    eid = itertools.count()
    edges = [
        {"id": f"q{next(eid)}", "source": s, "target": t, "type": kind, _LIT_LABEL: ""}
        for s, t, kind in links
        if s in subjects and t in subjects
    ]
    return {_LIT_NODES: nodes, _LIT_EDGES: edges, _LIT_LAYOUT: "fcose"}


def graph_from_query(taxonomy: Any, sparql: str) -> dict:
    """Run *sparql* against the session's graph and shape the result for the page.

    Goes through the same executor the SPARQL endpoint uses, so the engine
    choice — oxigraph by default, rdflib when it is absent — is made in one
    place and this never has to know which answered.
    """
    from ..sparql_query import run_query_on_taxonomy  # noqa: PLC0415

    result = run_query_on_taxonomy(taxonomy, sparql)
    if result.error:
        return {_LIT_NODES: [], _LIT_EDGES: [], _LIT_LAYOUT: "fcose", "error": result.error}
    triples = [_split(row[0]) for row in result.rows if row and row[0]]
    context = {str(u) for u in getattr(taxonomy, "context_source", {})}
    graph = graph_from_triples([t for t in triples if t], context)
    _name_from_model(graph, taxonomy)
    return graph


def _name_from_model(graph: dict, taxonomy: Any) -> None:
    """Give a node the label the model knows, when the query did not ask for one.

    A query about relations — "who competes with whom" — has no reason to
    select labels, and without this every node reads as a URI tail. The model
    already holds the name, so the reader gets it whether or not the query
    thought to ask. Only nodes still showing their local name are touched: a
    label the query *did* return is the one it meant.
    """
    for node in graph[_LIT_NODES]:
        if node[_LIT_LABEL] != _local(node["id"]):
            continue  # the query supplied a name; keep it
        label = _model_label(taxonomy, node["id"])
        if label:
            node[_LIT_LABEL] = label


def _model_label(taxonomy: Any, uri: str) -> str:
    for registry in ("owl_classes", "owl_individuals", "owl_properties", "concepts"):
        entity = getattr(taxonomy, registry, {}).get(uri)
        labels = getattr(entity, "labels", None) if entity is not None else None
        if labels:
            return str(labels[0].value)
    return ""


def _split(line: str) -> tuple[str, str, str] | None:
    """One N-Triples-ish line back into (subject, predicate, object).

    The executor stringifies a CONSTRUCT's triples, so they arrive as text. Only
    URI subjects and predicates make a graph; a blank node has nothing to draw
    and a malformed line is skipped rather than guessed at.
    """
    parts = line.split(None, 2)
    if len(parts) != 3:
        return None
    subject, predicate, obj = (p.strip() for p in parts)
    obj = obj.rstrip(" .").strip()
    for token in (subject, predicate, obj):
        if token.startswith("_:"):
            return None
    return (subject.strip("<>"), predicate.strip("<>"), obj.strip("<>"))
