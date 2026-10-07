"""Bounded process/domain graph exports for query-trace visualisation."""

from __future__ import annotations

from rdflib import Dataset, Graph, URIRef

from .materialize import KAIQ


def trace_subgraph(
    trace: Dataset,
    run_id: str,
    domain: Graph | None = None,
    domain_hops: int = 0,
) -> Graph:
    """Return the process graph and referenced domain resources, bounded by hops."""
    output = Graph()
    trace_graph = trace.graph(URIRef(f"urn:kaiq:trace:{run_id}"))
    for triple in trace_graph:
        output.add(triple)
    if domain is None or domain_hops < 1:
        return output
    resources = {
        obj
        for _, predicate, obj in output
        if predicate == KAIQ.referencesResource and isinstance(obj, URIRef)
    }
    for _ in range(domain_hops):
        next_resources = set(resources)
        for subject, predicate, obj in domain:
            if subject in resources or obj in resources:
                output.add((subject, predicate, obj))
                next_resources.update(term for term in (subject, obj) if isinstance(term, URIRef))
        resources = next_resources
    return output
