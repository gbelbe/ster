"""Result rows that name entities without pointing at them: a label where an IRI would have been.

An agent often answers with a store's name and its city's name and no IRI, and a name cannot be placed or dated by
itself. These helpers look the names up as labels in the graph, so a page can tell a person "these rows name N places"
and offer the map or the timeline, rather than say nothing. Counting only: what is drawn still comes from the IRIs.
"""

from __future__ import annotations

import rdflib
from rdflib.namespace import RDFS, SKOS

MAX_NAMED = 600  # entities looked at per request: a name shared by many entities must not make the call unbounded


def entities_named(graph: rdflib.Graph, labels: list[str]) -> list[str]:
    """The IRIs of the entities whose label is one of *labels* (any language), in the order found."""
    wanted = {label.strip() for label in labels if label.strip()}
    found: dict[str, None] = {}
    for predicate in (SKOS.prefLabel, RDFS.label) if wanted else ():
        for subject, value in graph.subject_objects(predicate):
            if isinstance(subject, rdflib.URIRef) and str(value) in wanted:
                found.setdefault(str(subject), None)
                if len(found) >= MAX_NAMED:
                    return list(found)
    return list(found)


def placed_named(graph: rdflib.Graph, labels: list[str]) -> int:
    """How many entities named by *labels* have somewhere to be drawn."""
    from .geo_shapes import geometry_of  # noqa: PLC0415

    return sum(
        1
        for uri in entities_named(graph, labels)
        if geometry_of(graph, rdflib.URIRef(uri)) is not None
    )


def dated_named(
    graph: rdflib.Graph, labels: list[str], after: str | None, before: str | None
) -> int:
    """How many entities named by *labels* carry a moment on the timeline."""
    from .time_shapes import timeline_items  # noqa: PLC0415

    items = timeline_items(graph, entities_named(graph, labels), after, before)
    return len({item["uri"] for item in items})
