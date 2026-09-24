"""`open_view` over the real `/mcp` route, going through the real HTTP API.

The fake-API unit tests check the tool's decisions; these check the wiring:
that the call really travels through `POST /api/sparql_query` (auth and all),
that a view is judged by what that endpoint finds in a loaded file, and that
"is the caller on this machine" is read from the request.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from tests._places_and_dates import (
    CONSTRUCT,
    DATED,
    NOTHING_PLACED,
    PLACES,
    load_places_and_dates,
)

TOKEN = "test-token"


@pytest.fixture
def opened(monkeypatch) -> list[str]:
    urls: list[str] = []

    def fake_open(url: str) -> bool:
        urls.append(url)
        return True

    monkeypatch.setattr("ster.mcp_views.open_in_browser", fake_open)
    return urls


def _client(tmp_path, host: str = "127.0.0.1") -> TestClient:
    app = create_app(load_places_and_dates(tmp_path), TOKEN, SSEBroadcaster(), lambda _t: None)
    return TestClient(app, base_url="http://127.0.0.1:9123", client=(host, 50000))


def _open_view(client: TestClient, **arguments) -> dict:
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "open_view", "arguments": arguments},
    }
    reply = client.post("/mcp", json=call, headers={"Authorization": f"Bearer {TOKEN}"})
    return json.loads(reply.json()["result"]["content"][0]["text"])


def _recording_client(tmp_path) -> tuple[TestClient, list[tuple[str, bool]]]:
    """A client whose app records every HTTP request it serves, with whether it
    carried a bearer token — the in-process API call shows up here like any other."""
    app = create_app(load_places_and_dates(tmp_path), TOKEN, SSEBroadcaster(), lambda _t: None)
    seen: list[tuple[str, bool]] = []

    @app.middleware("http")
    async def record(request, call_next):
        auth = request.headers.get("authorization", "")
        seen.append((request.url.path, auth == f"Bearer {TOKEN}"))
        return await call_next(request)

    client = TestClient(app, base_url="http://127.0.0.1:9123", client=("127.0.0.1", 50000))
    return client, seen


def test_open_view_goes_through_the_http_api(tmp_path, opened):
    client, seen = _recording_client(tmp_path)
    result = _open_view(client, view="map", query=PLACES)

    assert [path for path, _ in seen] == ["/mcp", "/api/sparql_query"]
    assert result["opened"] is True
    assert result["summary"] == "2 places"


def test_the_api_call_is_authenticated_like_any_other(tmp_path, opened):
    """The in-process call carries the server's own token: a route that checks
    auth is not skipped just because the caller is ster."""
    client, seen = _recording_client(tmp_path)
    _open_view(client, view="timeline", query=DATED)

    assert ("/api/sparql_query", True) in seen


def test_map_timeline_and_graph_open_their_own_pages(tmp_path, opened):
    client = _client(tmp_path)
    for view, query, page in (
        ("map", PLACES, "/map?q="),
        ("timeline", DATED, "/timeline?q="),
        ("graph", CONSTRUCT, "/viz?q="),
    ):
        result = _open_view(client, view=view, query=query)
        assert result["url"].startswith("http://127.0.0.1:9123" + page), view

    assert len(opened) == 3


def test_a_view_that_would_be_empty_is_not_opened(tmp_path, opened):
    result = _open_view(_client(tmp_path), view="map", query=NOTHING_PLACED)

    assert opened == []
    assert result["url"] is None
    assert "coordinates" in result["view_unavailable"]


def test_the_graph_refuses_a_select_with_a_construct_hint(tmp_path, opened):
    result = _open_view(_client(tmp_path), view="graph", query=PLACES)

    assert opened == []
    assert "CONSTRUCT" in result["view_unavailable"]


@pytest.mark.parametrize(
    ("host", "local"),
    [("127.0.0.1", True), ("127.0.0.2", True), ("::1", True), ("192.168.1.20", False)],
)
def test_only_a_caller_on_this_machine_gets_a_browser(tmp_path, opened, host, local):
    result = _open_view(_client(tmp_path, host), view="map", query=PLACES)

    assert result["opened"] is local
    assert bool(opened) is local
    assert result["url"].startswith("http://127.0.0.1:9123/map?q=")


def test_existing_tools_still_answer_from_the_worker_thread(tmp_path):
    """Regression guard for moving /mcp onto a worker thread."""
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "get_overview", "arguments": {}},
    }
    reply = (
        _client(tmp_path)
        .post("/mcp", json=call, headers={"Authorization": f"Bearer {TOKEN}"})
        .json()
    )

    assert reply["result"]["isError"] is False
