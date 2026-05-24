"""Step definitions for cache_warming.feature."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import rdflib
from pytest_bdd import given, scenarios, then, when

from ster.sparql_query import (
    _cache_key,
    _graph_cache,
    _uri_index_cache,
    run_query,
    warm_graph_caches,
)

scenarios("../features/perf/cache_warming.feature")

_VALID_TTL = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix kai: <https://ex.org/kai/> .\n"
    "kai:Digital a owl:Class .\n"
)


@pytest.fixture
def ctx(tmp_path: Path) -> dict:
    _graph_cache.clear()
    _uri_index_cache.clear()
    return {"tmp_path": tmp_path}


@given("a valid TTL file on disk")
def given_valid_ttl(ctx: dict) -> None:
    ttl = ctx["tmp_path"] / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    ctx["paths"] = [ttl]


@given("the graph and URI caches are empty")
def given_caches_empty(ctx: dict) -> None:
    _graph_cache.clear()
    _uri_index_cache.clear()


@given("a valid TTL file on disk with an outdated cache entry")
def given_ttl_with_stale_entry(ctx: dict) -> None:
    ttl = ctx["tmp_path"] / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    ctx["paths"] = [ttl]
    stale_key = ((str(ttl), 0.0),)
    _graph_cache[stale_key] = rdflib.Graph()
    _uri_index_cache[stale_key] = {}
    ctx["stale_key"] = stale_key


@given("warm_graph_caches has already been called")
def given_already_warmed(ctx: dict) -> None:
    warm_graph_caches(ctx["paths"])


@when("warm_graph_caches is called with that file")
def when_warm(ctx: dict) -> None:
    warm_graph_caches(ctx["paths"])


@when("run_query is called with that file")
def when_run_query(ctx: dict) -> None:
    with patch("ster.sparql_query.load_graph") as mock_load:
        ctx["mock_load"] = mock_load
        run_query(ctx["paths"], "SELECT ?s WHERE { ?s a ?t }")


@then("the graph cache contains a fresh entry for that file")
def then_graph_cache_has_entry(ctx: dict) -> None:
    key = _cache_key(ctx["paths"])
    assert key in _graph_cache


@then("the URI index cache contains a fresh entry for that file")
def then_uri_cache_has_entry(ctx: dict) -> None:
    key = _cache_key(ctx["paths"])
    assert key in _uri_index_cache


@then("the stale entry is gone and a fresh entry is present in the graph cache")
def then_stale_gone_fresh_present(ctx: dict) -> None:
    assert ctx["stale_key"] not in _graph_cache
    fresh_key = _cache_key(ctx["paths"])
    assert fresh_key in _graph_cache


@then("load_graph is not invoked a second time")
def then_load_graph_not_called(ctx: dict) -> None:
    ctx["mock_load"].assert_not_called()
