"""SPARQL has an API endpoint, and MCP is a way in rather than where it lives.

The map used to POST JSON-RPC to /mcp, because that was the only route on the
server that accepted a query. A page speaking an agent protocol to the backend
that rendered it is the wrong shape twice over: the map's contract ended up
defined by a tool schema instead of by the API, and every call paid for an
envelope it then had to parse an answer back out of.

So the logic moved to one function both transports call, and the map calls the
endpoint. What these tests hold in place:

  * both routes answer identically — that is the whole point of the extraction
  * the read-only guard is in the shared layer, not on one path
  * the Origin check came across with the endpoint; it is what stops a page the
    user merely visits from scripting arbitrary SPARQL at their local server
  * oxigraph answers by default and rdflib answers the same when it cannot
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ster import store
from ster.api import SSEBroadcaster, create_app

pytestmark = pytest.mark.mutation

E = "https://example.org/#"
TOKEN = "t"
LOCAL = {"Authorization": f"Bearer {TOKEN}", "Origin": "http://localhost:8000"}

TTL = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/#> .
ex:O a owl:Ontology ; rdfs:label "Q"@en .
ex:Shop a owl:Class ; rdfs:label "Shop"@en .
ex:Paint a owl:Class ; rdfs:label "Paint"@en .
ex:alpha a owl:NamedIndividual, ex:Shop ; rdfs:label "Alpha"@en .
"""

SELECT_CLASSES = "SELECT ?s WHERE { ?s a <http://www.w3.org/2002/07/owl#Class> }"


@pytest.fixture
def tax(tmp_path):
    path = tmp_path / "q.ttl"
    path.write_text(TTL, encoding="utf-8")
    return store.load(path)


@pytest.fixture
def client(tax, tmp_path):
    app = create_app(tax, TOKEN, SSEBroadcaster(), lambda t: None, file_path=tmp_path / "q.ttl")
    return TestClient(app)


def _query(client, sparql, **kw):
    headers = {**LOCAL, **kw.pop("headers", {})}
    return client.post("/api/sparql_query", json={"query": sparql}, headers=headers)


# ── the endpoint ─────────────────────────────────────────────────────────────


def test_a_select_returns_columns_and_rows(client):
    body = _query(client, SELECT_CLASSES).json()

    expected = {E + "Shop", E + "Paint"}
    assert body["columns"] == ["s"]
    assert body["row_count"] == len(expected)
    assert {r[0] for r in body["rows"]} == expected


def test_an_ask_returns_a_boolean(client):
    body = _query(client, "ASK { ?s ?p ?o }").json()

    assert body["query_type"] == "ASK"
    assert body["rows"] == [["true"]]


def test_a_syntax_error_is_the_callers_fault_not_a_500(client):
    r = _query(client, "SELECT ?s WHERE {{{")

    assert r.status_code == 200
    assert r.json()["error"] == "query_error"


# ── the guards ───────────────────────────────────────────────────────────────


def test_a_write_query_is_refused(client):
    """The guard lives in the shared layer, so it cannot hold on one route only."""
    assert _query(client, "DELETE WHERE { ?s ?p ?o }").json()["error"] == "read_only"


def test_a_query_without_a_token_is_rejected(client):
    r = client.post("/api/sparql_query", json={"query": SELECT_CLASSES})

    assert r.status_code == 401


def test_a_query_from_another_origin_is_rejected(client):
    """Carried over from /mcp on purpose: this is the one endpoint that runs an
    arbitrary query against a server on the user's own machine."""
    r = _query(client, SELECT_CLASSES, headers={"Origin": "http://evil.example"})

    assert r.status_code == 403


def test_a_request_with_no_origin_is_allowed(client):
    """Not browser-initiated — curl and agent CLIs send no Origin."""
    r = client.post(
        "/api/sparql_query",
        json={"query": SELECT_CLASSES},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert r.status_code == 200


# ── one implementation, two transports ───────────────────────────────────────


def test_the_endpoint_and_the_mcp_tool_agree(client):
    """If these ever differ, the extraction failed."""
    via_api = _query(client, SELECT_CLASSES).json()

    mcp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "run_sparql",
                "arguments": {"query": SELECT_CLASSES},
                "_meta": {
                    "com.adeo/agent-session-question": "Compare API and MCP query results.",
                    "com.adeo/agent-question": "What classes does the query return?",
                },
            },
        },
        headers=LOCAL,
    ).json()
    via_mcp = json.loads(mcp["result"]["content"][0]["text"])
    for key in (
        "agent_question",
        "agent_question_hint",
        "agent_question_required",
        "agent_session_question",
        "agent_session_question_hint",
        "agent_session_question_required",
        "warning",
    ):
        via_mcp.pop(key, None)

    # Same answer, compared as a set of rows: without ORDER BY, SPARQL leaves the
    # order unspecified, and the MCP tool runs in a sandboxed copy of the graph
    # (see ster.sparql_query._sandbox) whose internal order may differ.
    assert sorted(via_api.pop("rows")) == sorted(via_mcp.pop("rows"))
    assert via_api == via_mcp


# ── engine selection ─────────────────────────────────────────────────────────


def test_oxigraph_answers_by_default(tax):
    from ster.store import full_graph_oxigraph

    assert full_graph_oxigraph(tax) is not None, "pyoxigraph is a core dependency"


def test_rdflib_returns_the_same_rows_when_oxigraph_is_absent(tax, monkeypatch):
    """The fallback has to be a real answer, not a degraded one."""
    from ster.sparql_query import run_query_on_taxonomy

    with_native = run_query_on_taxonomy(tax, SELECT_CLASSES)

    import ster.store as store_mod

    monkeypatch.setattr(store_mod, "full_graph_oxigraph", lambda _t: None)
    monkeypatch.delattr(tax, "_ster_graph_oxigraph", raising=False)
    without = run_query_on_taxonomy(tax, SELECT_CLASSES)

    assert sorted(without.rows) == sorted(with_native.rows)
    assert without.columns == with_native.columns


# ── the semantic read views ──────────────────────────────────────────────────
#
# Every MCP tool binds an endpoint, so a protocol is a way in and never the only
# way to an answer. These three had none.


def test_overview_is_reachable_over_http(client):
    body = client.get("/api/overview", headers=LOCAL).json()

    assert body["counts"]["classes"] == 2
    assert body["counts"]["individuals"] == 1


def test_vocabulary_is_reachable_over_http(client):
    body = client.get("/api/vocabulary", headers=LOCAL).json()

    assert any(p["prefixed"] == "rdfs:label" for p in body["predicates"])


@pytest.mark.parametrize("endpoint", ["/api/overview", "/api/vocabulary"])
def test_the_read_views_need_a_token(client, endpoint):
    assert client.get(endpoint).status_code == 401


def test_the_overview_endpoint_and_the_mcp_tool_agree(client):
    via_api = client.get("/api/overview", headers=LOCAL).json()

    mcp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_overview",
                "arguments": {},
                "_meta": {
                    "com.adeo/agent-session-question": "Compare API and MCP overview results.",
                    "com.adeo/agent-question": "What does the ontology overview contain?",
                },
            },
        },
        headers=LOCAL,
    ).json()

    via_mcp = json.loads(mcp["result"]["content"][0]["text"])
    for key in (
        "agent_question",
        "agent_question_hint",
        "agent_question_required",
        "agent_session_question",
        "agent_session_question_hint",
        "agent_session_question_required",
        "warning",
    ):
        via_mcp.pop(key, None)
    assert via_mcp == via_api


def test_vocabulary_is_computed_once_per_model(tax):
    """Both tool descriptions tell an agent to call this before every query, so
    the guidance made it a hot path; the answer has to be held."""
    from ster import mcp_context as mc

    first = mc.vocabulary(tax)
    again = mc.vocabulary(tax)

    assert again is first, "vocabulary recomputed instead of memoised"


# ── the read-only guard must not become the way in ──────────────────────────


def test_the_write_guard_does_not_hang_on_a_hostile_query():
    """CodeQL: "Polynomial regular expression used on uncontrolled data".

    is_read_only_sparql strips IRIs before looking for write keywords, and the
    pattern excluded only `>`. An unterminated run of `<` then made every start
    position rescan to the end of the string before failing — quadratic, on a
    string that arrives in a request body. 40k characters took 1.4 seconds; a
    megabyte would take minutes, which is a denial of service against a server
    running on someone's own machine.

    The bound is deliberately loose. The fixed pattern does this in about 30ms
    and the vulnerable one needed roughly 36 seconds, so a second separates them
    by a factor of a thousand either way and cannot flake on a slow runner.
    """
    import time

    from ster.mcp_context import is_read_only_sparql

    start = time.perf_counter()
    is_read_only_sparql("<" * 200_000)
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"took {elapsed:.1f}s — the guard is quadratic again"


@pytest.mark.parametrize(
    ("query", "read_only"),
    [
        ("SELECT ?s WHERE { ?s ?p ?o }", True),
        ("ASK { ?s ?p ?o }", True),
        ("DELETE WHERE { ?s ?p ?o }", False),
        ("INSERT DATA { <a> <b> <c> }", False),
        # An IRI or literal that merely contains a write word is not a write.
        ("SELECT ?s WHERE { ?s <http://ex.org/created> ?o }", True),
        ('SELECT ?s WHERE { ?s ?p "please DROP this" }', True),
    ],
)
def test_the_write_guard_still_reads_queries_correctly(query, read_only):
    """Making the pattern linear must not make it wrong."""
    from ster.mcp_context import is_read_only_sparql

    assert is_read_only_sparql(query) is read_only
