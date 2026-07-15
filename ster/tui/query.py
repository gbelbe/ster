"""Thin adapter between the New-TUI query screen and the SPARQL engine.

Isolates :mod:`ster.sparql_query` (and rdflib) behind one module so the screen
imports our API, never the engine directly. Queries run against the *in-memory*
taxonomy (``taxonomy_to_graph``) so unsaved edits are reflected.
"""

from __future__ import annotations

from ster.model import Taxonomy
from ster.sparql_query import PRESET_QUERIES, PresetQuery, QueryResult, run_query_on_graph
from ster.store import taxonomy_to_graph

from .sparql_complete import EntityIndex

# Well-known local names to offer under the standard prefixes even when unused in the file.
_STANDARD: dict[str, dict[str, list[str]]] = {
    "owl": {"classes": ["Class", "Thing", "Nothing", "NamedIndividual"]},
    "rdfs": {"classes": ["Class", "Resource"], "properties": ["label", "comment", "subClassOf"]},
    "rdf": {"properties": ["type", "Property"]},
    "skos": {"classes": ["Concept", "ConceptScheme"], "properties": ["prefLabel", "broader"]},
}

# A starter query: the common prefixes plus a SELECT skeleton to edit.
DEFAULT_QUERY = """\
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>

SELECT ?s ?p ?o
WHERE { ?s ?p ?o }
LIMIT 50
"""


def presets() -> list[PresetQuery]:
    """The built-in preset queries (label · description · sparql)."""
    return list(PRESET_QUERIES)


# Prefixes worth declaring in the starter query when the file binds them ("" = the file's
# own default namespace, so `:Local` resolves without the user adding a PREFIX line).
_STARTER_PREFIXES = ("", "rdf", "rdfs", "owl", "skos")


def starter_query(index: EntityIndex) -> str:
    """A starter query: PREFIX lines for the file's own namespaces + a SELECT skeleton, so
    entity completions like ``:Animal`` run without the user hand-writing the prefix."""
    lines = [
        f"PREFIX {pfx}: <{index.prefixes[pfx]}>"
        for pfx in _STARTER_PREFIXES
        if index.prefixes.get(pfx)
    ]
    header = ("\n".join(lines) + "\n\n") if lines else ""
    return f"{header}SELECT ?s ?p ?o\nWHERE {{ ?s ?p ?o }}\nLIMIT 50\n"


def run(tax: Taxonomy, sparql: str) -> QueryResult:
    """Run *sparql* against *tax* in memory, returning a normalised ``QueryResult``."""
    return run_query_on_graph(taxonomy_to_graph(tax), sparql)


def _split_namespace(uri: str) -> str | None:
    """The namespace part of *uri* (up to and including the last ``#`` or ``/``)."""
    cut = max(uri.rfind("#"), uri.rfind("/"))
    return uri[: cut + 1] if cut >= 0 else None


def _primary_namespace(tax: Taxonomy, bound: set[str]) -> str | None:
    """The ontology's own namespace — the most common *unbound* entity namespace. Files
    that declare it as the default ``:`` prefix lose it on load (store drops ``""``), so we
    recover it here to make the file's own entities qname-completable."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for uri in (*tax.owl_classes, *tax.owl_individuals, *tax.owl_properties, *tax.concepts):
        ns = _split_namespace(uri)
        if ns and ns not in bound:
            counts[ns] += 1
    return counts.most_common(1)[0][0] if counts else None


def build_entity_index(tax: Taxonomy) -> EntityIndex:
    """Build the autocomplete index from *tax* via rdflib: the graph's namespace manager
    splits each entity URI into ``prefix:local`` (rdflib's qname logic), and the model
    classifies it (class / individual / property / concept). Built once per query session."""
    graph = taxonomy_to_graph(tax)
    nm = graph.namespace_manager
    bound_ns = {str(ns) for _, ns in graph.namespaces()}
    base = _primary_namespace(tax, bound_ns)
    if base is not None:  # re-bind the file's default (':') namespace, dropped on load
        nm.bind("", base, override=True, replace=True)
    index = EntityIndex(prefixes={p: str(ns) for p, ns in graph.namespaces()})

    def add(uri: str, bucket: dict[str, list[str]]) -> None:
        try:
            prefix, _, local = nm.compute_qname(uri, generate=False)
        except (ValueError, KeyError):
            return  # no bound prefix for this namespace → not qname-completable
        if local:
            bucket.setdefault(prefix, []).append(local)

    for uri in tax.owl_classes:
        add(uri, index.classes)
    for uri in tax.owl_individuals:
        add(uri, index.individuals)
    for uri in tax.owl_properties:
        add(uri, index.properties)
    for uri in tax.concepts:
        add(uri, index.concepts)
    _merge_standard(index)
    for bucket in (index.classes, index.individuals, index.properties, index.concepts):
        for prefix, locals_ in bucket.items():
            bucket[prefix] = sorted(dict.fromkeys(locals_))  # dedupe + sort
    return index


def _merge_standard(index: EntityIndex) -> None:
    """Fold the well-known standard-prefix names into the index (owl:Thing, rdf:type, …)."""
    buckets = {"classes": index.classes, "properties": index.properties}
    for prefix, kinds in _STANDARD.items():
        if prefix not in index.prefixes:
            continue
        for kind, locals_ in kinds.items():
            buckets[kind].setdefault(prefix, []).extend(locals_)
