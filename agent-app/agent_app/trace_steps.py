"""One run's journal, as ster's query trace wrote it, folded into the steps the page draws.

A step ends completed (columns, rows, duration) or failed (why: a code, the message, the kind of fault and where it
broke). A failed step used to show nothing at all, because only the completed shape was read.
"""

from __future__ import annotations

import json

EVENT, STEP, PAYLOAD, STATUS, DURATION = "event", "step_id", "payload", "status", "duration_ms"
MAX_ROWS = 300  # rows of a result kept for the page; the trace file holds what ster recorded
PLANNED, GENERATED, COMPLETED, FAILED = (
    "step_planned",
    "query_generated",
    "step_completed",
    "step_failed",
)


def failure_of(payload: dict) -> dict:
    """The fields of a failed step the page shows: its status, code, message, kind of fault, traceback and duration."""
    return {
        STATUS: payload.get(STATUS) or "failed",
        "error_code": payload.get("error_code"),
        "error_message": payload.get("error_message") or payload.get("error"),
        "error_type": payload.get("error_type"),
        "traceback": payload.get("traceback"),
        DURATION: payload.get(DURATION),
    }


def result_of(payload: dict) -> dict:
    """The fields of a completed step the page shows: its columns, rows (capped), count, duration and status."""
    return {
        "columns": payload.get("columns"),
        "rows": (payload.get("result_rows") or [])[:MAX_ROWS],
        "row_count": payload.get("row_count"),
        DURATION: payload.get(DURATION),
        "truncated": payload.get("result_truncated"),
        STATUS: payload.get(STATUS),
    }


def _started(info: dict, payload: dict) -> None:
    info["query_type"] = payload.get("query_type")
    info["agent_question"] = payload.get(
        "agent_question"
    )  # in plain words, as the MCP asks the agent for it


def _run_failed(info: dict, payload: dict) -> None:
    """When the run itself failed, say why on the run too: a step may never have been reached."""
    info["failure"] = failure_of(payload)


def fold(lines: list[str], run_id: str, file: str) -> dict:
    """The run *run_id* as the page reads it: its question, steps in order, and a failure if the run failed."""
    steps: dict[str, dict] = {}
    info: dict = {"run_id": run_id, "file": file, "steps": []}
    for line in lines:
        entry = json.loads(line)
        payload = entry.get(PAYLOAD, {})
        kind = entry[EVENT]
        if kind == "run_started":
            _started(info, payload)
        elif kind == "run_failed":
            _run_failed(info, payload)
        elif kind == PLANNED:
            steps[entry[STEP]] = {
                "kind": payload.get("step_kind"),
                "goal": payload.get("natural_language"),
            }
        elif kind == GENERATED:
            steps.setdefault(entry[STEP], {})["query"] = payload.get("query")
        elif kind == COMPLETED:
            steps.setdefault(entry[STEP], {}).update(result_of(payload))
        elif kind == FAILED:
            steps.setdefault(entry[STEP], {}).update(failure_of(payload))
    info["steps"] = list(steps.values())
    return info
