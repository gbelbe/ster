"""Global query-trace timeline contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ster.query_trace.model import Event
from ster.query_trace.timeline import render_timeline_html

pytestmark = pytest.mark.mutation


def _session(run_id: str, started: str) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=run_id,
        question=f"Question {run_id}",
        status="completed",
        started=started,
        event_count=2,
    )


def test_global_timeline_groups_runs_and_paginates() -> None:
    groups = [
        (
            _session("run-1", "2026-10-01T10:00:00Z"),
            [
                Event(
                    "run_started",
                    "run-1",
                    "trace-1",
                    1,
                    "2026-10-01T10:00:00Z",
                    payload={"question": "one"},
                )
            ],
        ),
        (
            _session("run-2", "2026-10-02T10:00:00Z"),
            [
                Event(
                    "run_started",
                    "run-2",
                    "trace-2",
                    1,
                    "2026-10-02T10:00:00Z",
                    payload={"question": "two"},
                )
            ],
        ),
    ]

    page = render_timeline_html(groups, page=1, page_size=1)

    assert "run-1" in page
    assert "run-2" not in page
    assert "Next" in page


def test_global_timeline_orders_most_recent_run_first() -> None:
    groups = [
        (_session("run-old", "2026-10-01T10:00:00Z"), []),
        (_session("run-new", "2026-10-02T10:00:00Z"), []),
    ]

    page = render_timeline_html(list(reversed(groups)))

    assert page.index("run-new") < page.index("run-old")


def test_grouping_window_is_displayed_and_pagination_preserves_it() -> None:
    groups = [
        (_session("run-1", "2026-10-01T10:00:00Z"), []),
        (_session("run-2", "2026-10-01T10:01:00Z"), []),
    ]

    page = render_timeline_html(groups, idle_seconds=60, page=1, page_size=1)

    assert 'name="idle_seconds"' in page
    assert 'value="60"' in page
    assert "60s grouping window" in page
    assert "idle_seconds=60" in page


def test_global_timeline_collapses_result_rows_by_default() -> None:
    events = [
        Event(
            "run_started",
            "run-1",
            "trace-1",
            1,
            "2026-10-01T10:00:00Z",
            payload={"question": "one"},
        ),
        Event(
            "step_completed",
            "run-1",
            "trace-1",
            2,
            "2026-10-01T10:00:01Z",
            step_id="raw-sparql",
            payload={"row_count": 2, "columns": ["x"], "result_rows": [["a"], ["b"]]},
        ),
    ]
    session = _session("run-1", "2026-10-01T10:00:00Z")
    session.event_count = len(events)
    page = render_timeline_html([(session, events)])

    assert '<details class="trace-results">' in page
    assert "Show results (2 loaded)" in page


def test_global_timeline_introduces_query_at_top_without_repeating_it() -> None:
    events = [
        Event(
            "run_started",
            "run-1",
            "trace-1",
            1,
            "2026-10-01T10:00:00Z",
            payload={"question": "old"},
        ),
        Event(
            "query_generated",
            "run-1",
            "trace-1",
            2,
            "2026-10-01T10:00:00Z",
            step_id="raw-sparql",
            payload={"query": "SELECT ?x WHERE {}"},
        ),
        Event(
            "step_completed",
            "run-1",
            "trace-1",
            3,
            "2026-10-01T10:00:01Z",
            step_id="raw-sparql",
            payload={"row_count": 0, "columns": ["x"]},
        ),
    ]
    session = _session("run-1", "2026-10-01T10:00:00Z")
    session.event_count = len(events)
    page = render_timeline_html([(session, events)])

    assert "MCP raw-sparql called at" in page
    assert "language-sparql" in page
    assert (
        page.count(
            '<span class="sparql-keyword">SELECT</span> ?x <span class="sparql-keyword">WHERE</span>'
        )
        == 1
    )


def test_global_timeline_shows_terminal_event_and_hides_intermediate_events() -> None:
    events = [
        Event(
            "run_started",
            "run-1",
            "trace-1",
            1,
            "2026-10-01T10:00:00Z",
            payload={"question": "one"},
        ),
        Event(
            "step_planned",
            "run-1",
            "trace-1",
            2,
            "2026-10-01T10:00:00Z",
            step_id="raw-sparql",
            payload={},
        ),
        Event(
            "query_generated",
            "run-1",
            "trace-1",
            3,
            "2026-10-01T10:00:00Z",
            step_id="raw-sparql",
            payload={"query": "SELECT ?x WHERE {}"},
        ),
        Event(
            "step_started",
            "run-1",
            "trace-1",
            4,
            "2026-10-01T10:00:00Z",
            step_id="raw-sparql",
            payload={},
        ),
        Event(
            "step_completed",
            "run-1",
            "trace-1",
            5,
            "2026-10-01T10:00:01Z",
            step_id="raw-sparql",
            payload={
                "status": "completed",
                "duration_ms": 8.3,
                "row_count": 100,
                "columns": ["p", "o"],
                "result_truncated": True,
                "result_rows": [["a", "b"]],
            },
        ),
    ]
    session = _session("run-1", "2026-10-01T10:00:00Z")
    session.event_count = len(events)
    page = render_timeline_html([(session, events)])

    summary = page.split('<details class="event-history">', 1)[0]
    assert "step completed" in summary
    assert "step planned" not in summary
    assert "query generated" not in summary
    assert "step started" not in summary
    assert "Show all events (5)" in page


def test_global_timeline_names_non_sparql_mcp_tool() -> None:
    events = [
        Event(
            "run_started",
            "run-tool",
            "trace-tool",
            1,
            "2026-10-01T10:00:00Z",
            payload={"question": '{"tool": "get_vocabulary", "arguments": {}}'},
        ),
        Event(
            "step_completed",
            "run-tool",
            "trace-tool",
            2,
            "2026-10-01T10:00:01Z",
            step_id="get_vocabulary",
            payload={"status": "completed", "result": {"shape": "owl"}},
        ),
    ]
    session = _session("run-tool", "2026-10-01T10:00:00Z")
    session.question = events[0].payload["question"]
    session.event_count = len(events)
    page = render_timeline_html([(session, events)])

    assert "MCP get_vocabulary called at" in page
    assert "MCP raw-sparql called at" not in page


def test_global_timeline_uses_compact_call_title() -> None:
    events = [
        Event(
            "run_started",
            "run-title",
            "trace-title",
            1,
            "2026-10-01T09:08:07Z",
            payload={"question": "SELECT * WHERE {}"},
        ),
        Event(
            "step_completed",
            "run-title",
            "trace-title",
            2,
            "2026-10-01T09:08:08Z",
            step_id="raw-sparql",
            payload={"status": "completed", "row_count": 0},
        ),
    ]
    session = _session("run-title", "2026-10-01T09:08:07Z")
    session.question = "SELECT * WHERE {}"
    session.event_count = len(events)
    page = render_timeline_html([(session, events)])

    assert "Step 1: MCP raw-sparql called at 09 h 08 min 07 sec" in page


def test_agent_question_is_displayed_in_session_header() -> None:
    session = _session("run-question", "2026-10-01T10:00:00Z")
    session.agent_question = "Which epics are active in Publication?"
    event = Event(
        "step_completed",
        "run-question",
        "trace-question",
        1,
        "2026-10-01T10:00:01Z",
        step_id="get_vocabulary",
        payload={"status": "completed"},
    )
    page = render_timeline_html([(session, [event])])

    assert "Which epics are active in Publication?" in page
    assert "Original user question" in page


def test_timeline_keeps_session_and_step_questions_separate() -> None:
    session = _session("run-separate-questions", "2026-10-01T10:00:00Z")
    session.agent_session_question = "Investigate the dated entities."
    session.agent_question = "Which entities have date literals?"
    event = Event(
        "step_completed",
        "run-separate-questions",
        "trace-separate-questions",
        1,
        "2026-10-01T10:00:01Z",
        step_id="run_sparql",
        payload={"status": "completed", "query": "SELECT ?entity WHERE {}"},
    )

    page = render_timeline_html([(session, [event])])

    assert "Investigate the dated entities." in page
    assert "Which entities have date literals?" in page
    assert "<b>Original user question</b>" in page
    assert "<b>SPARQL question</b>" in page


def test_timeline_does_not_use_step_question_as_session_question() -> None:
    session = _session("run-missing-session-question", "2026-10-01T10:00:00Z")
    session.agent_question = "Which entities have date literals?"
    event = Event(
        "step_completed",
        "run-missing-session-question",
        "trace-missing-session-question",
        1,
        "2026-10-01T10:00:01Z",
        step_id="run_sparql",
        payload={"status": "completed", "query": "SELECT ?entity WHERE {}"},
    )

    page = render_timeline_html([(session, [event])])

    assert page.count("Which entities have date literals?") == 1
    assert "<b>Original user question</b><br>Not provided by agent." in page


def test_timeline_displays_token_usage_when_provided() -> None:
    session = _session("run-tokens", "2026-10-01T10:00:00Z")
    event = Event(
        "step_completed",
        "run-tokens",
        "trace-tokens",
        1,
        "2026-10-01T10:00:01Z",
        step_id="raw-sparql",
        payload={"status": "completed", "token_usage": {"input": 120, "output": 34, "total": 154}},
    )
    page = render_timeline_html([(session, [event])])

    assert "<b>Tokens:</b> input 120 · output 34 · total 154" in page


def test_global_timeline_marks_missing_agent_question() -> None:
    session = _session("run-no-question", "2026-10-01T10:00:00Z")
    event = Event(
        "step_completed",
        "run-no-question",
        "trace-no-question",
        1,
        "2026-10-01T10:00:01Z",
        step_id="raw-sparql",
        payload={"status": "completed"},
    )

    page = render_timeline_html([(session, [event])])

    assert "Not provided by agent." in page


def test_timeline_only_shows_sparql_question_for_raw_sparql() -> None:
    session = _session("run-vocabulary", "2026-10-01T10:00:00Z")
    session.question = '{"tool": "get_vocabulary", "arguments": {}}'
    session.agent_question = "What vocabulary is loaded?"
    event = Event(
        "step_completed",
        "run-vocabulary",
        "trace-vocabulary",
        1,
        "2026-10-01T10:00:01Z",
        step_id="get_vocabulary",
        payload={"status": "completed"},
    )

    page = render_timeline_html([(session, [event])])

    assert "SPARQL question" not in page
