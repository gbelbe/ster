"""Graph and URI-index caching, keyed by file path + mtime.

Two module-level caches back the query engine: a parsed-graph cache
(``_graph_cache``) and a URI-completion-index cache (``_uri_index_cache``).
``warm_graph_caches`` is called from a background thread after every file
save so the next query/autocomplete hits an already-warm cache; it also
pre-loads rdflib's SPARQL plugin registry, since the first ``g.query()`` call
in a process is otherwise expensive (Python 3.13 ``importlib.metadata``
re-scans all installed package metadata on first ``entry_points()`` call).

``_SPARQL_LOCK`` guards every SPARQL parse/compile in ``ster``: rdflib's
SPARQL parser (a pyparsing packrat cache + parse-action binding) is a
process-wide global and is not thread-safe — see
``tests/unit/test_sparql_thread_safety.py``.
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import rdflib

from ..single_flight import single_flight
from ._types import UriIndex
from ._uri_index import build_uri_index


def load_graph(paths: list[Path]) -> rdflib.Graph:
    """Load one or more RDF files into a single merged in-memory graph."""
    g = rdflib.Graph()
    for p in paths:
        g.parse(str(p), format=_detect_format(p))
    return g


_graph_cache: dict[tuple, rdflib.Graph] = {}


_graph_cache_lock = threading.Lock()


_uri_index_cache: dict[tuple, UriIndex] = {}


_uri_index_cache_lock = threading.Lock()


_SPARQL_LOCK = threading.RLock()


def _cache_key(paths: list[Path]) -> tuple:
    """Build a cache key from paths and their current modification times."""
    return tuple((str(p), p.stat().st_mtime if p.exists() else 0) for p in sorted(paths))


_TRACE_LOG = Path(tempfile.gettempdir()) / "ster_cache.log"


def _trace(msg: str) -> None:
    try:
        with _TRACE_LOG.open("a") as f:
            f.write(f"{time.time():.3f} [{threading.current_thread().name}] {msg}\n")
    except OSError:
        pass


def load_graph_cached(paths: list[Path]) -> rdflib.Graph:
    """Return a cached graph, re-parsing only when a file has changed on disk.

    Callers that arrive while a parse is running wait for it rather than parsing the same files again.
    """
    key = _cache_key(paths)

    def parse() -> rdflib.Graph:
        _trace(f"load_graph_cached MISS — parsing {[p.name for p in paths]}")
        t0 = time.time()
        g = load_graph(paths)
        _trace(f"load_graph_cached parse done in {time.time() - t0:.2f}s")
        with _graph_cache_lock:
            return _graph_cache.setdefault(key, g)

    return single_flight(("graph", key), lambda: _graph_cache.get(key), parse)


def build_uri_index_cached(paths: list[Path]) -> UriIndex:
    """Return a cached URI completion index, rebuilding when any file changes."""
    key = _cache_key(paths)
    return single_flight(
        ("uri-index", key),
        lambda: _uri_index_cache.get(key),
        lambda: _build_uri_index(paths, key),
    )


def _build_uri_index(paths: list[Path], key: tuple) -> UriIndex:
    from ..model import Taxonomy  # avoid circular at module level  # noqa: PLC0415

    _trace(f"build_uri_index_cached MISS — building index {[p.name for p in paths]}")
    t0 = time.time()
    load_graph_cached(paths)
    tax = Taxonomy()
    for p in paths:
        try:
            from .. import store as _store  # noqa: PLC0415

            t1 = time.time()
            loaded = _store.load(p)
            _trace(f"  store.load({p.name}) took {time.time() - t1:.2f}s")
            tax.owl_classes.update(loaded.owl_classes)
            tax.owl_individuals.update(loaded.owl_individuals)
            tax.concepts.update(loaded.concepts)
            tax.schemes.update(loaded.schemes)
            tax.owl_properties.update(loaded.owl_properties)
            tax.namespace_bindings.update(loaded.namespace_bindings)
        except Exception:
            pass
    idx = build_uri_index(tax)
    _trace(f"build_uri_index_cached total {time.time() - t0:.2f}s")
    with _uri_index_cache_lock:
        if key not in _uri_index_cache:
            _uri_index_cache[key] = idx
    return _uri_index_cache.get(key, idx)


def warm_graph_caches(paths: list[Path]) -> None:
    """Evict stale cache entries for *paths* and rebuild both caches.

    Intended to be called from a background thread after every file save so
    that the next Ctrl+R query finds warm caches and skips re-parsing.
    Also runs a trivial SPARQL query to force rdflib to discover and load
    its plugin modules (Python 3.13 importlib.metadata re-scans all package
    metadata on every entry_points() call, costing ~23 s on first use).
    """
    _trace(f"warm_graph_caches START {[p.name for p in paths]}")
    path_strs = {str(p) for p in paths}
    with _graph_cache_lock:
        stale = [k for k in _graph_cache if any(str(e[0]) in path_strs for e in k)]
        for k in stale:
            del _graph_cache[k]
    with _uri_index_cache_lock:
        stale = [k for k in _uri_index_cache if any(str(e[0]) in path_strs for e in k)]
        for k in stale:
            del _uri_index_cache[k]
    build_uri_index_cached(paths)
    # Pre-load rdflib SPARQL plugins: first g.query() triggers importlib.metadata
    # to scan all installed packages.  Doing it here (background) means the user's
    # first Ctrl+R hits an already-warm plugin cache.
    key = _cache_key(paths)
    g = _graph_cache.get(key)
    if g is not None:
        try:
            t0 = time.time()
            with _SPARQL_LOCK:  # rdflib SPARQL parser is not thread-safe
                g.query("SELECT * WHERE { ?s ?p ?o } LIMIT 0")
            _trace(f"warm_graph_caches plugin pre-load done in {time.time() - t0:.2f}s")
        except Exception:
            pass
    _trace(f"warm_graph_caches DONE {[p.name for p in paths]}")


def _detect_format(path: Path) -> str:
    return {
        ".ttl": "turtle",
        ".n3": "n3",
        ".jsonld": "json-ld",
        ".rdf": "xml",
        ".owl": "xml",
    }.get(path.suffix.lower(), "turtle")
