"""A health check says it is one, and ster answers it without leaving a trace."""

from __future__ import annotations

import pytest

from ster import mcp_server as ms
from ster.model import Taxonomy
from ster.query_trace.jsonl import JsonlTraceRecorder
from ster.query_trace.recorder import configure, set_recorder

pytestmark = pytest.mark.mutation  # noqa: V107  # pytest reads it to select the mutation tests

OVERVIEW = "get_overview"
QUERY = {"query": "SELECT * WHERE { ?s ?p ?o } LIMIT 1"}


@pytest.fixture
def journal(tmp_path):
    set_recorder(JsonlTraceRecorder(tmp_path))
    yield tmp_path
    configure(False)


def _call(tool, arguments=None, meta=None):
    params = {
        "name": tool,
        "arguments": arguments or {},
        **({"_meta": meta} if meta is not None else {}),
    }
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
    return ms.handle_message(message, Taxonomy())["result"]


def _runs(folder) -> int:
    return len(list(folder.glob("run-*.jsonl")))


def test_the_meta_key_is_in_the_project_namespace():
    assert ms.UNTRACED_META == "com.adeo/untraced"


def test_a_call_marked_untraced_leaves_no_trace_and_still_answers(journal):
    reply = _call(OVERVIEW, meta={ms.UNTRACED_META: True})
    assert reply["isError"] is False
    assert "counts" in reply["content"][0]["text"]
    assert _runs(journal) == 0


def test_an_ordinary_call_is_traced(journal):
    _call(OVERVIEW)
    assert _runs(journal) == 1


@pytest.mark.parametrize("value", [False, None, "true", 1, "yes"])
def test_only_a_real_true_counts_so_a_stray_value_does_not_hide_a_call(journal, value):
    _call(OVERVIEW, meta={ms.UNTRACED_META: value})
    assert _runs(journal) == 1


def test_marking_one_call_does_not_mark_the_next(journal):
    _call(OVERVIEW, meta={ms.UNTRACED_META: True})
    _call(OVERVIEW)
    assert _runs(journal) == 1


def test_a_query_is_always_traced_whatever_the_mark(journal):
    _call("run_sparql", QUERY, meta={ms.UNTRACED_META: True})
    assert _runs(journal) == 1
