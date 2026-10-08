"""What the traces cannot see: the answer an agent gave, and the session it can be resumed with.

A trace records what was asked of the graph (each tool call, its query, its rows, its token use). The agent's final
text and its own session id never pass through ster, so whoever ran the agent reports them here after the fact. One small
JSON file per answer, in an ``answers/`` folder beside the run journals (the journals are matched with ``*.jsonl`` in
the folder itself, so these never look like a malformed run). ``run_ids`` is the join: it names the runs the answer rests on.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .model import utc_now

ANSWERS_DIR = "answers"
_QUESTION = "question"
_RUN_IDS = "run_ids"
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_TEXT = 200_000

# field -> accepted type(s); anything else a caller sends is dropped, not stored.
_FIELDS: dict[str, type | tuple[type, ...]] = {
    _QUESTION: str,
    "answer": (str, type(None)),
    "status": str,
    "agent": (str, type(None)),
    "model": (str, type(None)),  # the model that answered, when the agent reports it
    "conversation_id": (str, type(None)),
    "resume_session_id": (str, type(None)),  # the id the agent resumes this conversation with
    "agent_session_id": (
        str,
        type(None),
    ),  # the id its MCP calls carried (com.adeo/agent-session-id)
    "graph_fingerprint": (
        str,
        type(None),
    ),  # the stamp of the graph it was answered on (get_overview's graph)
    _RUN_IDS: list,
    "token_usage": (dict, type(None)),
    "cost_usd": (int, float, type(None)),
    "duration_ms": (int, float, type(None)),
    "started": (str, type(None)),
    "ended": (str, type(None)),
}


def clean_answer(answer_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """The record to store for *answer_id*; raises ValueError naming what is wrong."""
    if not _ID.fullmatch(answer_id or ""):
        raise ValueError("id must be 1-64 letters, digits, '-' or '_'")
    record: dict[str, Any] = {"id": answer_id}
    for name, kinds in _FIELDS.items():
        if name not in data:
            continue
        value = data[name]
        if isinstance(value, bool) or not isinstance(value, kinds):
            raise ValueError(f"{name} has the wrong type")
        if isinstance(value, str) and len(value) > MAX_TEXT:
            raise ValueError(f"{name} is longer than {MAX_TEXT} characters")
        record[name] = value
    if not isinstance(record.get(_QUESTION), str) or not record[_QUESTION].strip():
        raise ValueError("question is required")
    runs = record.get(_RUN_IDS, [])
    if not all(isinstance(r, str) and _ID.fullmatch(r) for r in runs):
        raise ValueError("run_ids must be run identifiers")
    record[_RUN_IDS] = runs
    record["recorded"] = utc_now()
    return record


def _inside(folder: Path, name: str) -> Path:
    """*folder*/*name*, refusing anything that resolves outside *folder* (the id is also checked by its shape)."""
    base = os.path.realpath(folder)
    path = os.path.realpath(os.path.join(base, name))
    if not path.startswith(base + os.sep):
        raise ValueError("id must name a file inside the answers folder")
    return Path(path)


def record_answer(directory: str | Path, answer_id: str, data: dict[str, Any]) -> Path:
    """Store the answer (replacing an earlier one with the same id) and return its file."""
    record = clean_answer(answer_id, data)
    folder = Path(directory) / ANSWERS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = _inside(folder, f"{answer_id}.json")
    tmp = _inside(folder, f"{answer_id}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def read_answers(directory: str | Path) -> list[dict[str, Any]]:
    """Every stored answer, oldest first. A file that is not a valid answer is skipped."""
    folder = Path(directory) / ANSWERS_DIR
    found: list[dict[str, Any]] = []
    for path in folder.glob("*.json") if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            found.append(data)
    return sorted(found, key=lambda a: (str(a.get("started") or a.get("recorded")), a["id"]))


def answer_for_run(directory: str | Path, run_id: str) -> dict[str, Any] | None:
    """The stored answer that rests on *run_id*, if an agent reported one (the latest, when several did)."""
    for answer in reversed(read_answers(directory)):
        if run_id in answer.get(_RUN_IDS, []):
            return answer
    return None
