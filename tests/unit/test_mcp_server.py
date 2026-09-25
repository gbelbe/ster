"""Unit tests for the MCP JSON-RPC wire layer and its HTTP mount.

The protocol layer (:mod:`ster.mcp_server`) is transport-free, so most of this
exercises ``handle_message`` directly; the last section drives the real ``/mcp``
route through FastAPI's TestClient to cover auth and the notification path.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ster import mcp_server as ms
from ster.api import SSEBroadcaster, create_app
from ster.model import Concept, Label, LabelType, RDFClass, Taxonomy

NS = "https://example.org/zoo#"
TOKEN = "test-token"


def _lbl(value: str, lang: str = "en") -> Label:
    return Label(lang=lang, value=value, type=LabelType.PREF)


@pytest.fixture
def zoo() -> Taxonomy:
    tax = Taxonomy()
    tax.ontology_uri = "https://example.org/zoo"
    tax.concepts[NS + "Animal"] = Concept(
        uri=NS + "Animal", labels=[_lbl("Animal")], narrower=[NS + "Dog"]
    )
    tax.concepts[NS + "Dog"] = Concept(
        uri=NS + "Dog", labels=[_lbl("Dog")], broader=[NS + "Animal"]
    )
    tax.owl_classes[NS + "Enclosure"] = RDFClass(uri=NS + "Enclosure", labels=[_lbl("Enclosure")])
    return tax


def _call(zoo, tool: str, arguments: dict | None = None, selection: str | None = None):
    """Invoke a tool through the wire layer and return its decoded payload."""
    reply = ms.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        },
        zoo,
        selection,
    )
    return json.loads(reply["result"]["content"][0]["text"]), reply["result"]


# ── initialize ────────────────────────────────────────────────────────────────


def test_initialize_reports_tools_capability(zoo):
    reply = ms.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, zoo
    )
    assert "tools" in reply["result"]["capabilities"]
    assert reply["result"]["serverInfo"]["name"] == "ster"


def test_initialize_echoes_a_supported_protocol_version(zoo):
    """A client on an older supported dialect is answered in its own version."""
    reply = ms.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        },
        zoo,
    )
    assert reply["result"]["protocolVersion"] == "2025-03-26"


def test_initialize_does_not_claim_an_unsupported_protocol_version(zoo):
    """Echoing any string back would claim support for a dialect we never wrote."""
    reply = ms.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2099-01-01"},
        },
        zoo,
    )
    assert reply["result"]["protocolVersion"] == ms.DEFAULT_PROTOCOL_VERSION


def test_initialize_falls_back_to_a_default_version(zoo):
    reply = ms.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, zoo
    )
    assert reply["result"]["protocolVersion"] == ms.DEFAULT_PROTOCOL_VERSION


# ── JSON-RPC envelope ─────────────────────────────────────────────────────────


def test_notification_gets_no_reply(zoo):
    """An id-less message (notifications/initialized) must not be answered."""
    assert ms.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}, zoo) is None


def test_unknown_method_returns_method_not_found(zoo):
    reply = ms.handle_message({"jsonrpc": "2.0", "id": 7, "method": "nope"}, zoo)
    assert reply["error"]["code"] == ms.METHOD_NOT_FOUND
    assert reply["id"] == 7


def test_non_object_message_is_an_invalid_request(zoo):
    assert ms.handle_message(["not", "an", "object"], zoo)["error"]["code"] == ms.INVALID_REQUEST


def test_missing_method_is_an_invalid_request(zoo):
    assert (
        ms.handle_message({"jsonrpc": "2.0", "id": 1}, zoo)["error"]["code"] == ms.INVALID_REQUEST
    )


def test_non_object_params_is_invalid_params(zoo):
    reply = ms.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": []}, zoo
    )
    assert reply["error"]["code"] == ms.INVALID_PARAMS


# ── tools/list ────────────────────────────────────────────────────────────────


def test_tools_are_registered_with_expected_names(zoo):
    reply = ms.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, zoo)
    names = {t["name"] for t in reply["result"]["tools"]}
    assert names == {
        "get_current_context",
        "get_overview",
        "get_entity",
        "search_entities",
        "get_vocabulary",
        "get_timeline",
        "run_sparql",
        "open_view",
    }


def test_open_view_is_listed_with_its_schema(zoo):
    reply = ms.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, zoo)
    tool = next(t for t in reply["result"]["tools"] if t["name"] == "open_view")
    schema = tool["inputSchema"]

    assert set(schema["properties"]["view"]["enum"]) == {"graph", "map", "timeline"}
    assert set(schema["required"]) == {"view", "query"}
    assert schema["properties"]["open"]["type"] == "boolean"


def test_instructions_no_longer_claim_no_side_effects(zoo):
    """The server still never edits the file, but open_view can open a tab:
    telling agents it only reads would be the one false line in its hint."""
    reply = ms.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, zoo
    )
    instructions = reply["result"]["instructions"]

    assert "never edits the file" in instructions
    assert "open_view" in instructions
    assert "read-only:" not in instructions


def test_open_view_without_the_http_api_refuses_instead_of_calling_ster(zoo):
    """Outside an HTTP request there is no API to go through; the tool must say
    so rather than fall back to calling ster's code directly."""
    call = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "open_view", "arguments": {"view": "map", "query": "SELECT ?s {}"}},
    }
    reply = ms.handle_message(call, zoo)

    assert '"no_api"' in reply["result"]["content"][0]["text"]


def test_every_advertised_tool_has_an_implementation():
    """A tool in TOOLS with no impl would fail only at call time."""
    assert {t["name"] for t in ms.TOOLS} == set(ms._IMPLS)


def test_every_tool_declares_a_description_and_schema():
    for tool in ms.TOOLS:
        assert tool["description"].strip()
        assert tool["inputSchema"]["type"] == "object"


# ── tools/call ────────────────────────────────────────────────────────────────


def test_call_get_overview_returns_counts(zoo):
    payload, _ = _call(zoo, "get_overview")
    assert payload["counts"]["concepts"] == 2


def test_call_get_entity_returns_the_entity(zoo):
    payload, _ = _call(zoo, "get_entity", {"uri": NS + "Dog"})
    assert payload["label"] == "Dog"


def test_call_search_entities_finds_by_label(zoo):
    payload, _ = _call(zoo, "search_entities", {"query": "dog"})
    assert [h["uri"] for h in payload] == [NS + "Dog"]


def test_call_get_current_context_uses_the_published_selection(zoo):
    payload, _ = _call(zoo, "get_current_context", selection=NS + "Dog")
    assert payload["focused"]["label"] == "Dog"


def test_call_get_current_context_without_selection_falls_back(zoo):
    payload, _ = _call(zoo, "get_current_context")
    assert payload["focused"] is None


def test_call_unknown_tool_is_an_error_result_not_an_exception(zoo):
    payload, result = _call(zoo, "no_such_tool")
    assert result["isError"] is True
    assert payload["error"] == "unknown_tool"


def test_call_missing_required_argument_reports_it(zoo):
    payload, result = _call(zoo, "get_entity", {})
    assert result["isError"] is True
    assert payload["argument"] == "uri"


def test_call_run_sparql_refuses_updates(zoo):
    payload, _ = _call(zoo, "run_sparql", {"query": "INSERT DATA { <a> <b> <c> }"})
    assert payload["error"] == "read_only"


def test_tool_failure_is_reported_as_an_error_result(zoo, monkeypatch):
    """A crash inside a tool must not take down the JSON-RPC session."""
    monkeypatch.setattr(
        ms.ctx, "overview", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    payload, result = _call(zoo, "get_overview")
    assert result["isError"] is True
    assert "boom" in payload["message"]


# ── HTTP mount ────────────────────────────────────────────────────────────────


@pytest.fixture
def client(zoo) -> TestClient:
    return TestClient(create_app(zoo, TOKEN, SSEBroadcaster(), lambda t: None))


def _rpc(client, body: dict, token: str = TOKEN):
    return client.post("/mcp", json=body, headers={"Authorization": f"Bearer {token}"})


def test_mcp_mounted_at_slash_mcp(client):
    resp = _rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp.status_code == 200
    assert len(resp.json()["result"]["tools"]) == len(ms.TOOLS)


def test_mcp_requires_bearer_token(client):
    assert (
        client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code
        == 401
    )


def test_mcp_rejects_wrong_token(client):
    assert (
        _rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "nope").status_code == 401
    )


def test_mcp_notification_returns_202_with_no_body(client):
    resp = _rpc(client, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp.status_code == 202
    assert not resp.content


def test_mcp_malformed_json_is_a_parse_error(client):
    resp = client.post(
        "/mcp",
        content=b"{not json",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    assert resp.json()["error"]["code"] == ms.PARSE_ERROR


# ── Origin validation (DNS-rebinding defence required by the MCP spec) ────────


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:3000", "http://127.0.0.1:8765", "https://localhost"],
)
def test_origin_allowed_for_localhost(origin):
    assert ms.origin_allowed(origin) is True


def test_origin_allowed_when_absent():
    """Agent CLIs and curl send no Origin — they must not be blocked."""
    assert ms.origin_allowed(None) is True


@pytest.mark.parametrize("origin", ["https://evil.example.com", "http://attacker.test", "null"])
def test_origin_rejected_for_foreign_sites(origin):
    assert ms.origin_allowed(origin) is False


def test_mcp_route_rejects_a_foreign_origin(client):
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Authorization": f"Bearer {TOKEN}", "Origin": "https://evil.example.com"},
    )
    assert resp.status_code == 403


def test_mcp_route_allows_a_localhost_origin(client):
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Authorization": f"Bearer {TOKEN}", "Origin": "http://localhost:3000"},
    )
    assert resp.status_code == 200


def test_mcp_get_returns_405_since_no_sse_stream_is_offered(client):
    """The spec allows either an SSE stream or 405 on GET; we offer no stream."""
    assert client.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 405


def test_mcp_reads_the_live_selection_from_app_state(client):
    """The TUI publishes into app.state._ster['selection']; the route must read it."""
    client.app.state._ster["selection"] = NS + "Dog"
    resp = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_current_context", "arguments": {}},
        },
    )
    payload = json.loads(resp.json()["result"]["content"][0]["text"])
    assert payload["focused"]["label"] == "Dog"


# ── get_vocabulary wiring + the hints that route agents to it ─────────────────


def test_tools_list_includes_get_vocabulary(zoo):
    reply = ms.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, zoo)
    assert "get_vocabulary" in {t["name"] for t in reply["result"]["tools"]}


def test_get_vocabulary_is_callable_via_tools_call(zoo):
    reply = ms.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_vocabulary", "arguments": {}},
        },
        zoo,
    )
    # The zoo fixture has no source file, so the tool reports that rather than
    # failing the call — same contract as run_sparql.
    payload = json.loads(reply["result"]["content"][0]["text"])
    assert payload["error"] == "no_source_file"


def test_initialize_returns_instructions(zoo):
    """Every MCP client gets the querying discipline at session start."""
    reply = ms.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, zoo
    )
    assert "get_vocabulary" in reply["result"]["instructions"]


def test_run_sparql_description_points_at_get_vocabulary():
    """Locks the hint: without it agents guess predicates and get empty results."""
    desc = next(t for t in ms.TOOLS if t["name"] == "run_sparql")["description"]
    assert "get_vocabulary" in desc
    assert "LIMIT" in desc


def test_initialize_instructs_agents_to_project_semantic_graphs(zoo):
    """Graph guidance must keep default visualizations free of technical metadata."""
    reply = ms.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, zoo
    )
    instructions = reply["result"]["instructions"]

    assert "focused\nsemantic neighborhood" in instructions
    assert "class hierarchy" in instructions
    assert "object-property links" in instructions
    assert "Exclude provenance" in instructions
    assert "images, logos, URLs" in instructions
    assert "explicit CONSTRUCT\nallowlist" in instructions
