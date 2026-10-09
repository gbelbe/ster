"""A read-only taxonomy built from RDF bytes already in memory.

For a SPARQL endpoint's response: there is no file to read, re-read or save to,
so the two costs the file loader pays for round-tripping are skipped — the
rdflib parse that records what the model cannot describe (it exists so a later
*save* loses nothing), and the cache. The bytes also go straight into the
oxigraph query store, so the SPARQL screen, map and timeline answer from exactly
what arrived rather than from a graph rebuilt out of the model.
"""

from __future__ import annotations

import io

from rdflib import Graph

from ..handles import assign_handles
from ..model import Taxonomy
from ._from_graph import _taxonomy_from_index, graph_to_taxonomy
from ._graph_io import _OX_FORMATS, _bindings_graph, _native_index_from_stream


def taxonomy_from_bytes(data: bytes, fmt: str = "turtle") -> Taxonomy:
    """The taxonomy described by *data* (RDF in format *fmt*), with handles assigned.

    Parsed in Rust when pyoxigraph can; otherwise by rdflib, which raises on
    bytes that are not RDF at all — the caller reports that.
    """
    ox_format = _OX_FORMATS.get(fmt)
    native = _native_index_from_stream(io.BytesIO(data), ox_format) if ox_format else None
    if native is not None:
        parsed, prefixes = native
        taxonomy = _taxonomy_from_index(parsed, _bindings_graph(prefixes))
    else:
        graph = Graph()
        graph.parse(data=data, format=fmt)
        taxonomy = graph_to_taxonomy(graph)
    assign_handles(taxonomy)
    return taxonomy


def attach_query_store(taxonomy: Taxonomy, data: bytes, fmt: str = "turtle") -> int | None:
    """Load *data* into the oxigraph store the query engine prefers; its triple count.

    None when the native engine is absent or rejects the bytes — the engine then
    falls back to rdflib, as it does for any file.
    """
    ox_format = _OX_FORMATS.get(fmt)
    if ox_format is None:
        return None
    try:
        import pyoxigraph as ox  # noqa: PLC0415

        store = ox.Store()
        store.bulk_load(io.BytesIO(data), format=getattr(ox.RdfFormat, ox_format))
    except Exception:  # noqa: BLE001 — a missing or unhappy native engine is not an error
        return None
    taxonomy._ster_graph_oxigraph = store  # type: ignore[attr-defined]
    return len(store)
