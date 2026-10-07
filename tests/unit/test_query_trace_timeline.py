"""HTML details for recorded query timelines."""

from __future__ import annotations

from ster.query_trace.model import Event
from ster.query_trace.timeline import render_timeline_html


def test_timeline_shows_result_count_columns_and_sample_rows() -> None:
    events = [
        Event(
            "run_started",
            "run-1",
            "trace-1",
            1,
            "2026-01-01T00:00:00Z",
            payload={"question": "Count classes"},
        ),
        Event(
            "step_completed",
            "run-1",
            "trace-1",
            2,
            "2026-01-01T00:00:01Z",
            step_id="raw-sparql",
            payload={
                "status": "completed",
                "duration_ms": 12.5,
                "row_count": 25,
                "columns": ["class", "n"],
                "result_rows": [["BusinessUnit", "25"]],
                "result_truncated": True,
                "query": "SELECT ?class ?n WHERE {}",
            },
        ),
    ]

    page = render_timeline_html(events)

    assert "25 total results, truncated to 1" in page
    assert "<th>class</th>" in page
    assert "<th>n</th>" in page
    assert "BusinessUnit" in page
    assert "<td>25</td>" in page
    assert "MCP raw-sparql called" in page
