"""A query that fails leaves a failed step and a failed run with every detail, and the agent is told the same."""

from __future__ import annotations

import json

import pytest

from ster import mcp_context as ctx
from ster import mcp_server as ms
from ster.model import Taxonomy
from ster.query_trace.jsonl import JsonlTraceRecorder, read_events
from ster.query_trace.recorder import configure, set_recorder
from ster.sparql_query import QueryResult

pytestmark = pytest.mark.mutation  # noqa: V107  # pytest reads it to select the mutation tests

SPAWN = "bad value(s) in fds_to_keep"
VALUE_ERROR = "ValueError"
WRAPPED = f"{VALUE_ERROR}: {SPAWN}"
SYNTAX = "Query error: bad syntax"
ERR, IS_ERROR, MSG = "error", "isError", "message"
QUERY_FAILED, STEP_FAILED, RUN_FAILED = "query_failed", "step_failed", "run_failed"
SELECT = "SELECT * WHERE { ?s ?p ?o } LIMIT 1"
STATUS = "status"
CODE, MESSAGE, KIND, TRACEBACK = "error_code", "error_message", "error_type", "traceback"
FAILED = "failed"
RUN_SPARQL = "run_sparql"


@pytest.fixture
def journal(tmp_path):
    set_recorder(JsonlTraceRecorder(tmp_path))
    yield tmp_path
    configure(False)


def _events(folder) -> list:
    return list(read_events(next(folder.glob("run-*.jsonl"))))


def _spawn_refused(*_a, **_k):
    raise ValueError(SPAWN)


def _answers(result: QueryResult):
    return lambda *_a, **_k: result


def _run(monkeypatch, behaviour, query=SELECT):
    monkeypatch.setattr("ster.sparql_query.run_query_on_taxonomy", behaviour)
    return ctx.sparql_payload(Taxonomy(), query)


# ── a fault while running the query ───────────────────────────────────────────


def test_a_fault_while_running_is_handed_back_as_the_error_the_agent_reads(journal, monkeypatch):
    out = _run(monkeypatch, _spawn_refused)
    assert out[ERR] == QUERY_FAILED
    assert out[MSG] == WRAPPED
    assert out[KIND] == VALUE_ERROR
    assert VALUE_ERROR in out[TRACEBACK]
    assert out["trace"]["run_id"].startswith("run-")


def test_a_fault_leaves_a_failed_step_with_every_detail(journal, monkeypatch):
    _run(monkeypatch, _spawn_refused)
    step = next(e for e in _events(journal) if e.event == STEP_FAILED)
    assert step.step_id == "raw-sparql"
    assert step.sequence == 5  # noqa: PLR2004
    assert (step.payload[STATUS], step.payload[CODE]) == (FAILED, QUERY_FAILED)
    assert step.payload[MESSAGE] == WRAPPED
    assert step.payload[KIND] == VALUE_ERROR
    assert VALUE_ERROR in step.payload[TRACEBACK]
    assert step.payload["duration_ms"] >= 0


def test_a_fault_ends_the_run_failed_with_the_same_details_and_never_leaves_it_open(
    journal, monkeypatch
):
    _run(monkeypatch, _spawn_refused)
    events = _events(journal)
    assert [e.event for e in events][-2:] == [STEP_FAILED, RUN_FAILED]
    final = events[-1].payload
    assert (final[STATUS], final[CODE], final[MESSAGE]) == (
        FAILED,
        QUERY_FAILED,
        WRAPPED,
    )
    assert final[KIND] == VALUE_ERROR


# ── the other ways a query fails ──────────────────────────────────────────────


def test_a_query_the_engine_rejects_is_a_failed_step_with_its_message(journal, monkeypatch):
    out = _run(monkeypatch, _answers(QueryResult(columns=[], rows=[], error=SYNTAX)))
    assert (out[ERR], out[MSG]) == ("query_error", SYNTAX)
    step = next(e for e in _events(journal) if e.event == STEP_FAILED)
    assert (step.payload[CODE], step.payload[MESSAGE]) == ("query_error", SYNTAX)
    assert step.payload["duration_ms"] >= 0
    assert _events(journal)[-1].payload[MESSAGE] == SYNTAX


def test_a_query_that_ran_too_long_says_so_with_its_own_code(journal, monkeypatch):
    stopped = QueryResult(columns=[], rows=[], error="Query stopped after 10s.", timed_out=True)
    out = _run(monkeypatch, _answers(stopped))
    assert out[ERR] == "timeout"
    assert _events(journal)[-1].payload[CODE] == "timeout"


def test_an_update_is_refused_and_the_refusal_is_recorded_with_its_reason(journal):
    out = ctx.sparql_payload(Taxonomy(), "DELETE WHERE { ?s ?p ?o }")
    assert out[ERR] == "read_only"
    step = next(e for e in _events(journal) if e.event == STEP_FAILED)
    assert step.sequence == 3  # noqa: PLR2004
    assert step.payload[MESSAGE] == "This server accepts SELECT/ASK queries only."
    assert _events(journal)[-1].payload[CODE] == "read_only"


# ── what the MCP client is told ───────────────────────────────────────────────


def _call(tool, arguments):
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    reply = ms.handle_message(message, Taxonomy(), call=ms.CallContext())["result"]
    return reply, json.loads(reply["content"][0]["text"])


def test_a_failed_query_is_an_error_result_that_carries_the_real_reason(journal, monkeypatch):
    monkeypatch.setattr("ster.sparql_query.run_query_on_taxonomy", _spawn_refused)
    reply, body = _call(RUN_SPARQL, {"query": SELECT})
    assert reply[IS_ERROR] is True
    assert body[MSG] == WRAPPED
    assert body[KIND] == VALUE_ERROR


def test_a_query_that_works_is_not_an_error_result(journal):
    reply, body = _call(RUN_SPARQL, {"query": SELECT})
    assert reply[IS_ERROR] is False
    assert ERR not in body


def test_a_tool_that_raises_says_what_kind_of_fault_it_was(journal, monkeypatch):
    def broken(*_a):
        raise OSError("disk gone")

    monkeypatch.setitem(ms._IMPLS, "get_overview", broken)
    reply, body = _call("get_overview", {})
    assert reply[IS_ERROR] is True
    assert (body[ERR], body[MSG], body[KIND]) == ("tool_failed", "disk gone", "OSError")


# ── the details themselves ────────────────────────────────────────────────────


def _deep(depth: int):
    if depth == 0:
        raise RuntimeError("bottom")
    _deep(depth - 1)


def test_the_traceback_keeps_the_end_where_it_broke_and_is_bounded():
    with pytest.raises(RuntimeError) as caught:
        _deep(40)
    tail = ctx.exception_details(caught.value)[TRACEBACK]
    assert "RuntimeError: bottom" in tail
    assert tail.count("_deep") <= ctx._TRACEBACK_FRAMES
    assert len(tail) <= ctx._TRACEBACK_CHARS


def test_the_details_name_the_type_of_the_fault():
    assert ctx.exception_details(KeyError("k"))[KIND] == "KeyError"
