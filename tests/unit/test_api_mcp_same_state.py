"""REST, the graph pages and MCP are one app over one taxonomy.

`create_app` mounts `/mcp` beside the REST routes, so a process that holds the
port serves all of them from the same state. This pins that: whatever replaces
the loaded taxonomy (the file watcher, a TUI push) is seen by both at once, so
"the MCP server and the FastAPI server are in sync" cannot silently stop being
true inside a process.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Label, LabelType, RDFClass, Taxonomy

TOKEN = "t"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
NS = "https://example.org/zoo#"


def _tax(*names: str) -> Taxonomy:
    tax = Taxonomy()
    tax.ontology_uri = "https://example.org/zoo"
    for name in names:
        tax.owl_classes[NS + name] = RDFClass(
            uri=NS + name, labels=[Label(lang="en", value=name, type=LabelType.PREF)]
        )
    return tax


def _mcp_classes(client: TestClient) -> set[str]:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search_entities", "arguments": {"query": "e"}},
    }
    reply = client.post("/mcp", json=body, headers=AUTH).json()
    payload = json.loads(reply["result"]["content"][0]["text"])
    return {hit["uri"] for hit in payload}


def _rest_classes(client: TestClient) -> set[str]:
    return {c["uri"] for c in client.get("/api/classes", headers=AUTH).json()["classes"]}


def test_rest_and_mcp_see_the_same_replaced_taxonomy():
    app = create_app(_tax("Eel"), TOKEN, SSEBroadcaster(), lambda _t: None)
    client = TestClient(app)
    assert NS + "Eel" in _rest_classes(client)

    # What the file watcher and a TUI push both do: swap the loaded taxonomy.
    app.state._ster["taxonomy"] = _tax("Eel", "Emu")

    assert NS + "Emu" in _rest_classes(client)
    assert NS + "Emu" in _mcp_classes(client)  # same state, same moment
