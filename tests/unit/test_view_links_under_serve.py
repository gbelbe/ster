"""Regression: a view link asked for over HTTP must work under `ster serve`.

Root cause: `view_links.link_for` decided whether the server was up by asking
for the *background* server (`api_server.is_running()`, i.e. `_bg.app`), which
only the TUI starts. `ster serve` never sets it, so an agent connected to
`ster serve` was told "ster's HTTP server is not running" by that very server.
The link also took its port from the saved config, not from `--port`.

A request that arrived over HTTP proves the server is up and names its own
address, so the link is built on the address the caller used.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ster import view_links
from ster.api import SSEBroadcaster, create_app
from ster.model import Label, LabelType, RDFClass, Taxonomy
from ster.sparql_query import QueryResult

TOKEN = "test-token"
CONSTRUCT = "CONSTRUCT { ?s a ?t } WHERE { ?s a ?t }"


def _taxonomy() -> Taxonomy:
    t = Taxonomy()
    uri = "https://x/Thing"
    t.owl_classes[uri] = RDFClass(
        uri=uri, labels=[Label(lang="en", value="Thing", type=LabelType.PREF)]
    )
    return t


@pytest.fixture
def client() -> TestClient:
    # Deliberately *not* patching view_links._server_running: under `ster serve`
    # there is no background server, which is the case being reproduced.
    app = create_app(_taxonomy(), TOKEN, SSEBroadcaster(), save_fn=lambda _t: None)
    return TestClient(app, base_url="http://127.0.0.1:9123")


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_view_links_rest_graph_link_under_serve_regression(client) -> None:
    body = client.post(
        "/api/sparql_query", json={"query": CONSTRUCT, "view": "graph"}, headers=_auth()
    ).json()

    assert body["view_unavailable"] is None
    assert body["view_url"].startswith("http://127.0.0.1:9123/viz?q=")


def test_view_links_mcp_graph_link_under_serve_regression(client) -> None:
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "run_sparql", "arguments": {"query": CONSTRUCT, "view": "graph"}},
    }
    reply = client.post("/mcp", json=call, headers=_auth()).json()
    import json

    payload = json.loads(reply["result"]["content"][0]["text"])

    assert payload["view_unavailable"] is None
    assert payload["view_url"].startswith("http://127.0.0.1:9123/viz?q=")


def test_view_links_explicit_base_wins_over_saved_config() -> None:
    result = QueryResult(columns=["s"], rows=[["https://x/Thing"]], query_type="CONSTRUCT")
    url, reason = view_links.link_for(
        _taxonomy(), result, CONSTRUCT, "graph", base="http://127.0.0.1:9123"
    )

    assert reason is None
    assert url is not None and url.startswith("http://127.0.0.1:9123/viz?q=")


def test_view_links_trailing_slash_in_base_is_not_doubled() -> None:
    result = QueryResult(columns=["s"], rows=[["https://x/Thing"]], query_type="CONSTRUCT")
    url, _ = view_links.link_for(
        _taxonomy(), result, CONSTRUCT, "graph", base="http://127.0.0.1:9123/"
    )

    assert url is not None and url.startswith("http://127.0.0.1:9123/viz?q=")


def test_view_links_without_base_still_needs_the_background_server() -> None:
    """The TUI path is unchanged: no request, no base, so the running check stays."""
    result = QueryResult(columns=["s"], rows=[["https://x/Thing"]], query_type="CONSTRUCT")
    url, reason = view_links.link_for(_taxonomy(), result, CONSTRUCT, "graph")

    assert url is None
    assert "ster serve" in reason
