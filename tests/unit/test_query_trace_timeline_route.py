"""The /query-trace/timeline page: its date bounds are dates, never markup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Taxonomy

pytestmark = pytest.mark.mutation

TOKEN = "test-token"
ATTACK = '"><script>alert(1)</script>'


def _client(file_path: Path | None = None) -> TestClient:
    app = create_app(
        Taxonomy(), TOKEN, SSEBroadcaster(), save_fn=lambda _t: None, file_path=file_path
    )
    return TestClient(app)


def _journal(folder: Path, run_id: str, at: str) -> None:
    first = {
        "event": "run_started", "event_id": f"{run_id}-1", "run_id": run_id, "trace_id": f"t-{run_id}",
        "sequence": 1, "timestamp": at, "payload": {"question": f"question {run_id}", "agent_session_id": "same"},
    }  # fmt: skip
    last = {
        "event": "run_completed", "event_id": f"{run_id}-2", "run_id": run_id, "trace_id": f"t-{run_id}",
        "sequence": 2, "timestamp": at, "payload": {"status": "completed"},
    }  # fmt: skip
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{run_id}.jsonl").write_text(json.dumps(first) + "\n" + json.dumps(last) + "\n")


@pytest.mark.parametrize("field", ["after", "before"])
def test_a_bound_that_is_not_a_date_is_refused(field: str) -> None:
    response = _client().get("/query-trace/timeline", params={field: ATTACK})
    assert response.status_code == 400
    assert "<script>alert(1)" not in response.text


@pytest.mark.parametrize(
    "value", ["2026", "2026-10", "2026-10-01", "2026-10-01T10:00", "2026-10-01T10:00:00Z"]
)
def test_a_date_is_accepted_and_shown_in_the_form(value: str) -> None:
    response = _client().get("/query-trace/timeline", params={"after": value, "before": value})
    assert response.status_code == 200
    assert f'name="after" value="{value}"' in response.text


def test_no_bounds_is_the_whole_history() -> None:
    response = _client().get("/query-trace/timeline", params={"after": "", "before": ""})
    assert response.status_code == 200
    assert 'name="after" value=""' in response.text


def test_the_bounds_still_filter_the_sessions(tmp_path: Path) -> None:
    traces = tmp_path / ".ster" / "query-traces"
    _journal(traces, "run-old", "2026-01-01T10:00:00Z")
    _journal(traces, "run-new", "2026-10-01T10:00:00Z")
    client = _client(tmp_path / "f.ttl")
    assert "question run-old" in client.get("/query-trace/timeline").text
    page = client.get("/query-trace/timeline", params={"after": "2026-06-01"}).text
    assert "question run-new" in page and "question run-old" not in page
    page = client.get("/query-trace/timeline", params={"before": "2026-06-01"}).text
    assert "question run-old" in page and "question run-new" not in page


def test_the_pager_links_carry_only_dates(tmp_path: Path) -> None:
    traces = tmp_path / ".ster" / "query-traces"
    for n in range(3):  # three sessions, a window of one apart, two to a page
        _journal(traces, f"run-{n}", f"2026-10-0{n + 1}T10:00:00Z")
    page = (
        _client(tmp_path / "f.ttl")
        .get(
            "/query-trace/timeline",
            params={"after": "2026-09-01", "page_size": 1, "idle_seconds": 1},
        )
        .text
    )
    assert "after=2026-09-01" in page
    assert "<script>" not in page


def test_the_numbers_of_the_page_are_numbers_whatever_called() -> None:
    from ster.query_trace.timeline import render_timeline_html

    assert render_timeline_html(
        [], page="1", page_size="10", idle_seconds="60"
    ) == render_timeline_html([])
    for bad in ("<script>", "1; alert(1)", ""):
        with pytest.raises(ValueError):
            render_timeline_html([], idle_seconds=bad)  # type: ignore[arg-type]
