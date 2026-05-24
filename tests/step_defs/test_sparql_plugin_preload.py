"""Step definitions for sparql_plugin_preload.feature."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import rdflib
from pytest_bdd import given, scenarios, then, when

import ster.sparql_query as _sq
from ster.sparql_query import (
    _cache_key,
    _graph_cache,
    _uri_index_cache,
    warm_graph_caches,
)

scenarios("../features/perf/sparql_plugin_preload.feature")

_VALID_TTL = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix kai: <https://ex.org/kai/> .\n"
    "kai:Digital a owl:Class .\n"
)


@pytest.fixture
def ctx(tmp_path: Path) -> dict:
    _graph_cache.clear()
    _uri_index_cache.clear()
    return {"tmp_path": tmp_path, "patches": []}


# ── given ────────────────────────────────────────────────────────────────────


@given("a valid TTL file on disk")
def given_valid_ttl(ctx: dict) -> None:
    ttl = ctx["tmp_path"] / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    ctx["paths"] = [ttl]


@given("the graph and URI caches are empty")
def given_caches_empty(ctx: dict) -> None:
    _graph_cache.clear()
    _uri_index_cache.clear()


@given("rdflib SPARQL queries are being tracked")
def given_queries_tracked(ctx: dict) -> None:
    recorded: list[str] = []
    orig = rdflib.Graph.query

    def _track(self: rdflib.Graph, sparql: object, *a: object, **kw: object) -> object:
        recorded.append(str(sparql))
        return orig(self, sparql, *a, **kw)  # type: ignore[arg-type]

    p = patch.object(rdflib.Graph, "query", _track)
    p.start()
    ctx["patches"].append(p)
    ctx["query_calls"] = recorded


@given("rdflib SPARQL queries will raise an exception")
def given_queries_raise(ctx: dict) -> None:
    p = patch.object(rdflib.Graph, "query", side_effect=Exception("plugin error"))
    p.start()
    ctx["patches"].append(p)


@given("the graph cache is cleared between build and pre-load")
def given_cache_cleared_after_build(ctx: dict) -> None:
    orig_build = _sq.build_uri_index_cached

    def _build_then_clear(paths: list[Path]) -> object:
        result = orig_build(paths)
        _graph_cache.clear()
        return result

    p = patch.object(_sq, "build_uri_index_cached", _build_then_clear)
    p.start()
    ctx["patches"].append(p)


# ── when ─────────────────────────────────────────────────────────────────────


@when("warm_graph_caches is called with that file")
def when_warm(ctx: dict) -> None:
    try:
        warm_graph_caches(ctx["paths"])
        ctx["raised"] = False
    except Exception as exc:
        ctx["raised"] = exc
    finally:
        for p in ctx.get("patches", []):
            p.stop()


# ── then ─────────────────────────────────────────────────────────────────────


@then("a LIMIT 0 query was executed on the cached graph")
def then_limit0_query_fired(ctx: dict) -> None:
    calls = ctx.get("query_calls", [])
    assert any("LIMIT 0" in q for q in calls), f"Expected a LIMIT 0 call, got: {calls}"


@then("warm_graph_caches completes without raising")
def then_no_raise(ctx: dict) -> None:
    assert ctx["raised"] is False, f"warm_graph_caches raised: {ctx['raised']}"


@then("the graph cache contains a fresh entry for that file")
def then_graph_cache_has_entry(ctx: dict) -> None:
    key = _cache_key(ctx["paths"])
    assert key in _graph_cache


@then("no LIMIT 0 query was attempted")
def then_no_limit0_query(ctx: dict) -> None:
    calls = ctx.get("query_calls", [])
    preload_calls = [q for q in calls if "LIMIT 0" in q]
    assert preload_calls == [], f"Expected no LIMIT 0 call, got: {preload_calls}"
