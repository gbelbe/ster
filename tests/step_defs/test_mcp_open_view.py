"""Steps for tests/features/mcp/mcp_open_view.feature.

Driven through the real `/mcp` route, so every scenario exercises the whole
path: the MCP call, the in-process call to `POST /api/sparql_query`, and the
decision to open a browser or hand back a link. Only the browser is replaced.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from ster.api import SSEBroadcaster, create_app
from tests._places_and_dates import (
    CONSTRUCT,
    DATED,
    NOTHING_PLACED,
    PLACES,
    load_places_and_dates,
)

scenarios("../features/mcp/mcp_open_view.feature")

TOKEN = "test-token"
BASE = "http://127.0.0.1:9123"
_PAGES = {"map": "/map?q=", "timeline": "/timeline?q=", "graph": "/viz?q="}
_QUERIES = {
    "a query that finds places": PLACES,
    "a query that finds dated things": DATED,
    "a CONSTRUCT query": CONSTRUCT,
    "a query that finds nothing with a place": NOTHING_PLACED,
    "a SELECT query": PLACES,
    "a query longer than a link can carry": PLACES + "#" + "x" * 9000,
}


@pytest.fixture
def world(tmp_path, monkeypatch) -> dict:
    opened: list[str] = []

    def fake_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr("ster.mcp_views.open_in_browser", fake_open)
    return {"tmp_path": tmp_path, "host": "127.0.0.1", "opened": opened, "result": None}


def _call_open_view(world: dict, arguments: dict) -> None:
    taxonomy = load_places_and_dates(world["tmp_path"])
    app = create_app(taxonomy, TOKEN, SSEBroadcaster(), lambda _t: None)
    client = TestClient(app, base_url=BASE, client=(world["host"], 50000))
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "open_view", "arguments": arguments},
    }
    reply = client.post("/mcp", json=call, headers={"Authorization": f"Bearer {TOKEN}"})
    world["result"] = json.loads(reply.json()["result"]["content"][0]["text"])
    world["query"] = arguments["query"]


@given("a small ontology with places and dates served by ster")
def _served(world):
    return world


@given("the agent runs on the same machine as ster")
def _local(world):
    world["host"] = "127.0.0.1"


@given("the agent runs on another machine")
def _remote(world):
    world["host"] = "192.168.1.20"


@when(parsers.parse('the agent opens the "{view}" view on {what}'))
def _open(world, view, what):
    _call_open_view(world, {"view": view, "query": _QUERIES[what]})


@when(parsers.parse('the agent asks for the link to the "{view}" view on {what}'))
def _link_only(world, view, what):
    _call_open_view(world, {"view": view, "query": _QUERIES[what], "open": False})


@then(parsers.parse("a browser is opened on the {view} page for that query"))
def _browser_opened(world, view):
    assert len(world["opened"]) == 1
    assert world["opened"][0].startswith(BASE + _PAGES[view])
    assert world["result"]["opened"] is True


@then("no browser is opened")
def _no_browser(world):
    assert world["opened"] == []
    assert world["result"].get("opened", False) is False


@then(parsers.parse("the agent gets the link to the {view} page for that query"))
def _gets_link(world, view):
    assert world["result"]["url"].startswith(BASE + _PAGES[view])
    assert world["result"]["hint"]


@then(parsers.parse("the agent is told how many {noun} the {view} shows"))
def _told_count(world, noun, view):
    count = world["result"]["count"]
    assert count > 0
    assert world["result"]["summary"] in {f"{count} {noun}", f"1 {noun[:-1]}"}


@then("the agent is told the map would be empty and why")
def _told_empty(world):
    assert world["result"]["url"] is None
    assert "coordinates" in world["result"]["view_unavailable"]


@then("the agent is told the graph view needs a CONSTRUCT query")
def _told_construct(world):
    assert "CONSTRUCT" in world["result"]["view_unavailable"]


@then("the agent is told the query is too long for a link")
def _told_too_long(world):
    assert world["result"]["error"] == "query_too_long"
