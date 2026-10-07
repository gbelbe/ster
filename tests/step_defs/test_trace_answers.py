"""BDD step definitions for tests/features/api/trace_answers.feature."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from ster import query_trace

scenarios("../features/api/trace_answers.feature")

NS = "https://example.org/onto#"
AUTH = {"Authorization": "Bearer tok"}


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.delenv("STER_QUERY_TRACE", raising=False)
    monkeypatch.setattr(query_trace.recorder, "_recorder", query_trace.NoOpTraceRecorder())
    return {"dir": tmp_path / ".ster" / "query-traces", "project": tmp_path}


@given("a running ster API with a minimal taxonomy")
def api(ctx: dict[str, Any], api_client: TestClient) -> None:
    ctx["client"] = api_client


@given("query tracing is on")  # noqa: V103
def tracing_on(ctx: dict[str, Any]) -> None:
    query_trace.configure(True, str(ctx["dir"]))


@given("query tracing is off")  # noqa: V103
def tracing_off(ctx: dict[str, Any]) -> None:
    query_trace.configure(False)


@given(parsers.parse('a recorded run "{run}" in the project'))  # noqa: V103
def recorded_run(ctx: dict[str, Any], run: str) -> None:
    ctx["dir"].mkdir(parents=True, exist_ok=True)
    (ctx["dir"] / f"{run}.jsonl").write_text(
        f'{{"event":"run_started","event_id":"e1","run_id":"{run}","trace_id":"t","sequence":1,'
        '"timestamp":"2026-01-01T00:00:00Z","payload":{"question":"q"}}\n'
        f'{{"event":"run_completed","event_id":"e2","run_id":"{run}","trace_id":"t","sequence":2,'
        '"timestamp":"2026-01-01T00:00:01Z","payload":{"status":"completed"}}\n',
        encoding="utf-8",
    )


@when(
    parsers.parse(
        'the runner reports the answer "{turn}" to "{question}" saying "{answer}" '
        'from run "{run}" resumable as "{resume}"'
    )
)
def report(  # noqa: PLR0913 - the step's captured values
    ctx: dict[str, Any], turn: str, question: str, answer: str, run: str, resume: str
) -> None:
    body = {
        "question": question,
        "answer": answer,
        "status": "completed",
        "run_ids": [run],
        "resume_session_id": resume,
    }
    ctx["response"] = ctx["client"].post(
        f"/api/query_trace/answers/{turn}", json=body, headers=AUTH
    )


@when("the runner reports an answer with no question")  # noqa: V103
def report_blank(ctx: dict[str, Any]) -> None:
    ctx["response"] = ctx["client"].post(
        "/api/query_trace/answers/turn2", json={"question": "  ", "answer": "x"}, headers=AUTH
    )


@when("a client reports an answer without the token")  # noqa: V103
def report_anonymously(ctx: dict[str, Any]) -> None:
    ctx["response"] = ctx["client"].post("/api/query_trace/answers/turn1", json={"question": "q"})


@then("the API accepts it")
def accepted(ctx: dict[str, Any]) -> None:
    assert ctx["response"].status_code == HTTPStatus.CREATED, ctx["response"].text


@then(parsers.parse("the API refuses with status {code:d}"))
def refused(ctx: dict[str, Any], code: int) -> None:
    assert ctx["response"].status_code == code


@then(
    parsers.parse(
        'the listed answers hold "{turn}" with answer "{answer}" and resume id "{resume}"'
    )
)
def listed(ctx: dict[str, Any], turn: str, answer: str, resume: str) -> None:
    rows = ctx["client"].get("/api/query_trace/answers", headers=AUTH).json()
    [row] = [r for r in rows if r["id"] == turn]
    assert (row["answer"], row["resume_session_id"]) == (answer, resume)


@then(parsers.parse('the agent session of that run carries the answer "{answer}"'))  # noqa: V103
def attached(ctx: dict[str, Any], answer: str) -> None:
    from ster.plugins.query_trace.sessions import agent_sessions_for_project

    [session] = agent_sessions_for_project(ctx["project"])
    assert [a["answer"] for a in session.answers] == [answer]
