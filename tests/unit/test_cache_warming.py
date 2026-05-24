"""Unit tests for proactive cache warming after ontology save."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import rdflib

import ster.sparql_query as _sq
from ster import store
from ster.sparql_query import (
    _cache_key,
    _graph_cache,
    _uri_index_cache,
    run_query,
    warm_graph_caches,
)

_VALID_TTL = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix kai: <https://ex.org/kai/> .\n"
    "kai:Digital a owl:Class .\n"
)


@pytest.fixture(autouse=True)
def _clear_caches():
    _graph_cache.clear()
    _uri_index_cache.clear()
    yield
    _graph_cache.clear()
    _uri_index_cache.clear()


def test_warm_populates_graph_cache(tmp_path: Path) -> None:
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    warm_graph_caches([ttl])
    key = _cache_key([ttl])
    assert key in _graph_cache


def test_warm_populates_uri_index_cache(tmp_path: Path) -> None:
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    warm_graph_caches([ttl])
    key = _cache_key([ttl])
    assert key in _uri_index_cache


def test_warm_evicts_stale_graph_entry(tmp_path: Path) -> None:
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    # Insert a stale entry with a fake old mtime key
    stale_key = ((str(ttl), 0.0),)
    import rdflib

    _graph_cache[stale_key] = rdflib.Graph()
    warm_graph_caches([ttl])
    assert stale_key not in _graph_cache
    fresh_key = _cache_key([ttl])
    assert fresh_key in _graph_cache


def test_warm_evicts_stale_uri_index_entry(tmp_path: Path) -> None:
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    stale_key = ((str(ttl), 0.0),)
    _uri_index_cache[stale_key] = {}
    warm_graph_caches([ttl])
    assert stale_key not in _uri_index_cache
    fresh_key = _cache_key([ttl])
    assert fresh_key in _uri_index_cache


def test_run_query_hits_cache_after_warm(tmp_path: Path) -> None:
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    warm_graph_caches([ttl])
    with patch("ster.sparql_query.load_graph") as mock_load:
        run_query([ttl], "SELECT ?s WHERE { ?s a ?t }")
    mock_load.assert_not_called()


# ── wiring: Viewer.__init__ ───────────────────────────────────────────────────


def _join_warm_threads(threads: list[threading.Thread], timeout: float = 5.0) -> None:
    for t in threads:
        t.join(timeout=timeout)


def test_viewer_init_spawns_background_warm(tmp_path: Path) -> None:
    """Viewer.__init__ must start a ster-cache-warm thread that populates the cache."""
    from ster.nav.viewer import TaxonomyViewer as Viewer

    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    tax = store.load(ttl)

    warm_threads: list[threading.Thread] = []
    orig_start = threading.Thread.start

    def _capture(self: threading.Thread, *a: object, **kw: object) -> None:
        if self.name == "ster-cache-warm":
            warm_threads.append(self)
        orig_start(self, *a, **kw)

    with patch.object(threading.Thread, "start", _capture):
        Viewer(taxonomy=tax, file_path=ttl)

    assert warm_threads, "Viewer.__init__ must spawn at least one ster-cache-warm thread"
    _join_warm_threads(warm_threads)
    assert _cache_key([ttl]) in _graph_cache


# ── wiring: _save_file ────────────────────────────────────────────────────────


def test_save_file_spawns_background_warm(tmp_path: Path) -> None:
    """_save_file must start a ster-cache-warm thread that re-populates the cache."""
    from ster.nav.viewer import TaxonomyViewer as Viewer

    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    tax = store.load(ttl)

    # Create viewer (startup warm runs and populates cache)
    viewer = Viewer(taxonomy=tax, file_path=ttl)
    # Wait for startup warm to finish before clearing
    _join_warm_threads(
        [t for t in threading.enumerate() if t.name == "ster-cache-warm"], timeout=5.0
    )
    _graph_cache.clear()
    _uri_index_cache.clear()

    warm_threads: list[threading.Thread] = []
    orig_start = threading.Thread.start

    def _capture(self: threading.Thread, *a: object, **kw: object) -> None:
        if self.name == "ster-cache-warm":
            warm_threads.append(self)
        orig_start(self, *a, **kw)

    with patch.object(threading.Thread, "start", _capture):
        viewer._save_file()

    assert warm_threads, "_save_file must spawn a ster-cache-warm thread"
    _join_warm_threads(warm_threads)
    assert _cache_key([ttl]) in _graph_cache


# ── plugin pre-load ───────────────────────────────────────────────────────────


def test_warm_executes_preload_query_on_cached_graph(tmp_path: Path) -> None:
    """warm_graph_caches calls g.query() with a LIMIT 0 query after populating the cache."""
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")

    recorded: list[str] = []
    orig = rdflib.Graph.query

    def _track(self: rdflib.Graph, sparql: object, *a: object, **kw: object) -> object:
        recorded.append(str(sparql))
        return orig(self, sparql, *a, **kw)  # type: ignore[arg-type]

    with patch.object(rdflib.Graph, "query", _track):
        warm_graph_caches([ttl])

    assert any("LIMIT 0" in q for q in recorded), (
        f"Expected a LIMIT 0 preload call, got: {recorded}"
    )


def test_warm_preload_survives_query_exception(tmp_path: Path) -> None:
    """If g.query() raises during pre-load, warm_graph_caches still completes and cache is populated."""
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")

    with patch.object(rdflib.Graph, "query", side_effect=Exception("plugin error")):
        warm_graph_caches([ttl])  # must not raise

    assert _cache_key([ttl]) in _graph_cache


def test_warm_preload_skipped_when_no_graph_in_cache(tmp_path: Path) -> None:
    """If the graph is absent from _graph_cache at pre-load time, no query is attempted."""
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")

    orig_build = _sq.build_uri_index_cached

    def _build_then_clear(paths: list[Path]) -> object:
        result = orig_build(paths)
        _graph_cache.clear()  # simulate eviction between build and pre-load
        return result

    recorded: list[str] = []
    orig = rdflib.Graph.query

    def _track(self: rdflib.Graph, sparql: object, *a: object, **kw: object) -> object:
        recorded.append(str(sparql))
        return orig(self, sparql, *a, **kw)  # type: ignore[arg-type]

    with (
        patch.object(_sq, "build_uri_index_cached", _build_then_clear),
        patch.object(rdflib.Graph, "query", _track),
    ):
        warm_graph_caches([ttl])

    preload_calls = [q for q in recorded if "LIMIT 0" in q]
    assert preload_calls == [], (
        f"Expected no LIMIT 0 call when cache is empty, got: {preload_calls}"
    )
