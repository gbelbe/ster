"""A tool call that is not SPARQL is journalled as one run: planned, started, then completed or failed."""

from __future__ import annotations

import json

import pytest

from ster import mcp_server as ms
from ster.model import Taxonomy
from ster.query_trace.jsonl import JsonlTraceRecorder, read_events
from ster.query_trace.recorder import configure, set_recorder

pytestmark = pytest.mark.mutation  # noqa: V107  # pytest reads it to select the mutation tests

TOOL = "search_entities"
ARGS = {"query": "dog", "lang": "fr"}
ROWS = 7
HITS = [{"uri": f"https://example.org/{n}"} for n in range(ROWS)]
GONE = "the graph is gone"
STATUS = "status"
USAGE = {"input_tokens": 12, "output_tokens": 3}
HOW = ms.CallContext(token_usage=USAGE)


@pytest.fixture
def journal(tmp_path):
    set_recorder(JsonlTraceRecorder(tmp_path))
    yield tmp_path
    configure(False)


def _events(folder) -> list:
    return list(read_events(next(folder.glob("run-*.jsonl"))))


def _impl(_tax, _call, _args):
    return {"items": HITS}


def _broken(_tax, _call, _args):
    raise RuntimeError(GONE)


def test_a_successful_call_is_planned_started_and_completed_in_order(journal):
    ms._traced_tool_call(TOOL, _impl, Taxonomy(), HOW, ARGS)
    events = _events(journal)
    assert [e.event for e in events] == [
        "run_started",
        "step_planned",
        "step_started",
        "step_completed",
        "run_completed",
    ]
    assert [e.sequence for e in events[1:4]] == [2, 3, 4]
    assert {e.step_id for e in events[1:4]} == {TOOL}


def test_the_run_says_which_tool_was_asked_what_and_over_which_transport(journal):
    ms._traced_tool_call(TOOL, _impl, Taxonomy(), HOW, ARGS)
    started = _events(journal)[0].payload
    assert (started["transport"], started["tool"]) == ("mcp", TOOL)
    assert json.loads(started["question"]) == {"tool": TOOL, "arguments": ARGS}


def test_the_question_keeps_accents_as_written(journal):
    ms._traced_tool_call(TOOL, _impl, Taxonomy(), HOW, {"query": "été"})
    assert "été" in _events(journal)[0].payload["question"]


def test_the_step_is_titled_after_the_tool(journal):
    ms._traced_tool_call(TOOL, _impl, Taxonomy(), HOW, ARGS)
    assert _events(journal)[1].payload == {"objective": f"Execute MCP tool {TOOL}."}


def test_the_completed_step_carries_the_tool_result_and_the_token_use(journal):
    ms._traced_tool_call(TOOL, _impl, Taxonomy(), HOW, ARGS)
    done = _events(journal)[3].payload
    assert done[STATUS] == "completed"
    assert done["token_usage"] == USAGE
    assert (done["row_count"], done["result_rows"]) == (ROWS, HITS)


def test_the_run_ends_completed_with_the_row_count(journal):
    ms._traced_tool_call(TOOL, _impl, Taxonomy(), HOW, ARGS)
    last = _events(journal)[-1]
    assert (last.event, last.payload[STATUS], last.payload["row_count"]) == (
        "run_completed",
        "completed",
        ROWS,
    )


def test_the_token_use_of_the_call_is_on_the_run_too(journal):
    ms._traced_tool_call(TOOL, _impl, Taxonomy(), HOW, ARGS)
    assert _events(journal)[0].payload["token_usage"] == USAGE


def test_a_tool_that_fails_is_journalled_as_a_failed_step_and_a_failed_run(journal):
    with pytest.raises(RuntimeError, match=GONE):
        ms._traced_tool_call(TOOL, _broken, Taxonomy(), HOW, ARGS)
    events = _events(journal)
    assert [e.event for e in events] == [
        "run_started",
        "step_planned",
        "step_started",
        "step_failed",
        "run_failed",
    ]
    failed = events[3]
    assert (failed.sequence, failed.step_id) == (4, TOOL)
    assert failed.payload == {STATUS: "failed", "error": GONE}
    assert events[-1].payload == {STATUS: "failed", "error": GONE}
