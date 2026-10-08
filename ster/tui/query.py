"""Thin adapter between the New-TUI query screen and the SPARQL engine.

Isolates :mod:`ster.sparql_query` (and rdflib) behind one module so the screen
imports our API, never the engine directly. Queries run against the *in-memory*
taxonomy (``taxonomy_to_graph``) so unsaved edits are reflected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ster.model import Taxonomy
from ster.sparql_query import PRESET_QUERIES, PresetQuery, QueryResult, run_query_on_graph
from ster.store import taxonomy_to_graph

from .sparql_complete import EntityIndex

if TYPE_CHECKING:
    from pathlib import Path

    import rdflib

# Well-known local names to offer under the standard prefixes even when unused in the file.
_STANDARD: dict[str, dict[str, list[str]]] = {
    "owl": {"classes": ["Class", "Thing", "Nothing", "NamedIndividual"]},
    "rdfs": {"classes": ["Class", "Resource"], "properties": ["label", "comment", "subClassOf"]},
    "rdf": {"properties": ["type", "Property"]},
    "skos": {"classes": ["Concept", "ConceptScheme"], "properties": ["prefLabel", "broader"]},
}


def presets() -> list[PresetQuery]:
    """The built-in preset queries (label · description · sparql)."""
    return list(PRESET_QUERIES)


# Prefixes worth declaring in the starter query when the file binds them ("" = the file's
# own default namespace, so `:Local` resolves without the user adding a PREFIX line).
_STARTER_PREFIXES = ("", "rdf", "rdfs", "owl", "skos")


def main_prefix(index: EntityIndex) -> str:
    """The file's own prefix name — instance data (individuals / concepts) is weighted far
    above classes/properties so the file's namespace wins over standard-prefix boilerplate
    (owl:Class …). Empty string when nothing qualifies."""

    def score(prefix: str) -> int:
        return (
            (len(index.individuals.get(prefix, [])) + len(index.concepts.get(prefix, []))) * 1000
            + len(index.classes.get(prefix, [])) * 10
            + len(index.properties.get(prefix, []))
        )

    best = max(index.prefixes, key=score, default="")
    return best if score(best) else ""


def starter_query(index: EntityIndex) -> str:
    """A starter query: PREFIX lines for the file's namespaces + a sample query listing
    instances of the file's first few classes (so it is useful and runnable out of the box),
    falling back to ``SELECT ?s ?p ?o`` when the file declares no classes."""
    pfx = main_prefix(index)
    wanted = list(dict.fromkeys([pfx, *_STARTER_PREFIXES]))  # the file's own prefix first
    lines = [f"PREFIX {p}: <{index.prefixes[p]}>" for p in wanted if index.prefixes.get(p)]
    header = ("\n".join(lines) + "\n\n") if lines else ""
    classes = index.classes.get(pfx, [])[:5]  # the first five classes of the file's namespace
    if not classes:
        return f"{header}SELECT ?s ?p ?o\nWHERE {{ ?s ?p ?o }}\nLIMIT 50\n"
    values = " ".join(f"{pfx}:{name}" for name in classes)
    return (
        f"{header}# sample: instances of the first {len(classes)} classes\n"
        "SELECT ?class ?instance WHERE {\n"
        "  ?instance a ?class .\n"
        f"  VALUES ?class {{ {values} }}\n"
        "}\nORDER BY ?class\nLIMIT 25\n"
    )


def build_graph(tax: Taxonomy) -> rdflib.Graph:
    """The rdflib graph for *tax* — built once per query session and reused for the entity
    index and every run, so a large ontology isn't re-serialised on each query."""
    return taxonomy_to_graph(tax)


def run(tax: Taxonomy, sparql: str) -> QueryResult:
    """Run *sparql* against *tax* in memory, returning a normalised ``QueryResult``."""
    return run_query_on_graph(taxonomy_to_graph(tax), sparql)


def run_on_graph(graph: rdflib.Graph, sparql: str) -> QueryResult:
    """Run *sparql* against an already-built *graph* (reuses the session graph)."""
    return run_query_on_graph(graph, sparql)


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


def build_entity_index(tax: Taxonomy, graph: rdflib.Graph | None = None) -> EntityIndex:
    """Build the autocomplete index from *tax* via rdflib: the graph's namespace manager
    splits each entity URI into ``prefix:local`` (rdflib's qname logic), and the model
    classifies it (class / individual / property / concept). Reuses *graph* when given."""
    graph = graph if graph is not None else taxonomy_to_graph(tax)
    _rebind_default_namespace(tax, graph)
    index = EntityIndex(prefixes={p: str(ns) for p, ns in graph.namespaces()})
    _classify_entities(tax, graph.namespace_manager, index)
    _merge_standard(index)
    for bucket in (index.classes, index.individuals, index.properties, index.concepts):
        for prefix, locals_ in bucket.items():
            bucket[prefix] = sorted(dict.fromkeys(locals_))  # dedupe + sort
    return index


def _rebind_default_namespace(tax: Taxonomy, graph: rdflib.Graph) -> None:
    """Re-bind the file's default (``:``) namespace, which store drops on load, so its
    entities are qname-completable."""
    bound_ns = {str(ns) for _, ns in graph.namespaces()}
    base = _primary_namespace(tax, bound_ns)
    if base is not None:
        graph.namespace_manager.bind("", base, override=True, replace=True)


def _classify_entities(tax: Taxonomy, nm: object, index: EntityIndex) -> None:
    """Bucket each entity's ``prefix:local`` (via rdflib's namespace manager) by model kind."""

    def add(uri: str, bucket: dict[str, list[str]]) -> None:
        try:
            prefix, _, local = nm.compute_qname(uri, generate=False)  # type: ignore[attr-defined]
        except (ValueError, KeyError):
            return  # no bound prefix for this namespace → not qname-completable
        if local:
            bucket.setdefault(prefix, []).append(local)

    for entities, bucket in (
        (tax.owl_classes, index.classes),
        (tax.owl_individuals, index.individuals),
        (tax.owl_properties, index.properties),
        (tax.concepts, index.concepts),
    ):
        for uri in entities:
            add(uri, bucket)


def _merge_standard(index: EntityIndex) -> None:
    """Fold the well-known standard-prefix names into the index (owl:Thing, rdf:type, …)."""
    buckets = {"classes": index.classes, "properties": index.properties}
    for prefix, kinds in _STANDARD.items():
        if prefix not in index.prefixes:
            continue
        for kind, locals_ in kinds.items():
            buckets[kind].setdefault(prefix, []).extend(locals_)


def located_count(graph: rdflib.Graph, result: QueryResult) -> int:
    """How many result rows carry geographic coordinates.

    Detection lives in :mod:`ster.geo_results` and knows only WGS84, so this
    works for any ontology rather than one vocabulary.
    """
    from ster.geo_results import located_count as _located_count  # noqa: PLC0415

    return _located_count(graph, result)


def dated_count(graph: rdflib.Graph, result: QueryResult) -> int:
    """How many result rows can be put on a time axis.

    Detection lives in :mod:`ster.time_results` and keys on literal datatypes,
    so it works for any ontology rather than one vocabulary — the counterpart of
    :func:`located_count` for the timeline.
    """
    from ster.time_results import dated_count as _dated_count  # noqa: PLC0415

    return _dated_count(graph, result)


def timeline_url(sparql: str, focus: str | None = None) -> str:
    """Address of the running server's timeline page, carrying *sparql*.

    Same shape as :func:`map_url`, and for the same reasons: served by ster so
    the page's own calls are same-origin, and the token stays out of the URL.
    """
    from urllib.parse import quote  # noqa: PLC0415

    from ster.api_server import load_server_config  # noqa: PLC0415

    url, port = load_server_config()
    page = f"{url}:{port}/timeline?q={quote(sparql)}"
    return page + (f"&focus={quote(focus)}" if focus else "")


def map_url(sparql: str, focus: str | None = None) -> str:
    """Address of the running server's map page, carrying *sparql* to run there.

    Delegates to :mod:`ster.view_links`, which MCP uses too — one place that
    knows the port, the URL shape and the encoding.
    """
    from ster.view_links import map_url as _map_url  # noqa: PLC0415

    return _map_url(sparql, focus)


def graph_url(sparql: str) -> str:
    """Address of the running server's graph page, drawing *sparql*'s triples."""
    from ster.view_links import graph_url as _graph_url  # noqa: PLC0415

    return _graph_url(sparql)


def is_graphable(result: QueryResult) -> bool:
    """True when *result* is triples the graph view can draw."""
    from ster.view_links import is_graphable as _is_graphable  # noqa: PLC0415

    return _is_graphable(result)


def server_is_running() -> bool:
    """True when ster's HTTP server is up to serve the map page.

    The same probe the graph view uses before opening a browser tab
    (``viz_vowl.is_live_server``), so both views fail the same way: a message in
    the TUI rather than a browser tab on a dead address.
    """
    from ster.api_server import is_running  # noqa: PLC0415

    return is_running()


def ensure_server(tax: Taxonomy, path: Path | None) -> str:
    """Make sure a server is up for the map/timeline pages; "" on success, else why not.

    The TUI starts its server at launch, but that is best-effort: a port held then
    (an earlier ``ster serve``) leaves nothing for the map to open on. Retrying
    here, with the same port claim the graph uses, means the map and timeline work
    whenever the graph would — a stale ``ster serve`` is replaced, a same-file one
    reused, and an open ster session or foreign process is named, never closed.
    """
    if server_is_running():
        return ""
    from ster.viz_vowl import ensure_live_server  # noqa: PLC0415

    try:
        ensure_live_server(tax, path)
    except RuntimeError as exc:
        return f"Couldn't open the map: {exc}"
    return ""


def server_unavailable_reason(what: str = "the map") -> str:
    """Why *what* (the map, by default) cannot open, in terms the reader can act on.

    "The server isn't running" leaves someone staring at a working TUI with no
    idea what to do. The usual cause is that the configured port is already
    held — most often by a `ster show` left running from an earlier session,
    whose static file server answers 404 to everything the map needs. ster can
    already name that process (viz_vowl.port_holder exists to offer closing it
    for the graph view), so the message names it here too rather than leaving
    the reader to go looking.
    """
    from ster.api_server import load_server_config  # noqa: PLC0415

    _url, port = load_server_config()
    try:
        from ster.viz_vowl import port_holder  # noqa: PLC0415

        holder = port_holder(port=port)
    except Exception:  # noqa: BLE001 — a diagnostic must never be the thing that fails
        holder = None
    if holder is not None:
        from ster.viz_vowl import holder_message  # noqa: PLC0415

        return f"Couldn't open {what}: {holder_message(holder[0], holder[1], port)}"
    return f"Couldn't open {what}: the ster server isn't running."


def wait_for_server(seconds: float, every: float = 0.2) -> bool:
    """True once ster's server is up, waiting up to *seconds* for it.

    The TUI starts its server on a thread beside the browser it is building, so for the first moments after the loader
    goes the server is simply not there yet; that is not the same as it being unable to start.
    """
    import time  # noqa: PLC0415

    deadline = time.monotonic() + seconds
    while not server_is_running():
        if time.monotonic() >= deadline:
            return False
        time.sleep(every)
    return True


def open_browser(url: str) -> bool:
    """Open *url* in the user's browser, reporting whether anything opened.

    ``webbrowser.open`` rather than ``App.open_url``: the latter's driver
    indirection silently no-ops in this app, as ``detail_view`` documents.
    """
    import webbrowser  # noqa: PLC0415

    return bool(webbrowser.open(url))
