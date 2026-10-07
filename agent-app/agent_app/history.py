"""Conversations rebuilt from what ster recorded, for the ones this page has no copy of.

ster's trace folder holds every query any agent ran on the graph (``run-*.jsonl``) and, for answers this page's runner
reported, the answer text, resume id and the runs it rests on (``answers/*.json``). Read together they give back a
conversation list: the page's own copy is the live one, and this fills in what it lacks (another machine's history,
a copy that was deleted, a session an agent ran in a terminal without the page). Everything here is read-only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

_TITLE = 70
_ID_LENGTH = 12  # a conversation id: twelve hex digits
_HEX = "0123456789abcdef"


def _epoch(stamp: str | None) -> float:
    try:
        return datetime.fromisoformat((stamp or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _first_event(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as f:
            line = f.readline()
        return json.loads(line) if line.strip() else None
    except (OSError, ValueError):
        return None


def _runs(traces: Path) -> dict[str, dict]:
    """Every recorded run: id -> {tool, input, started, agent_session_id, question, usage}."""
    out: dict[str, dict] = {}
    for path in traces.glob("run-*.jsonl") if traces.is_dir() else []:
        first = _first_event(path)
        if not first or first.get("event") != "run_started":
            continue
        payload = first.get("payload", {})
        try:
            asked = json.loads(payload.get("question") or "{}")
        except ValueError:
            asked = {}
        usage = payload.get("token_usage")
        out[path.stem] = {
            "id": path.stem,
            "tool": payload.get("tool") or asked.get("tool") or "tool",
            "input": asked.get("arguments") if isinstance(asked, dict) else {},
            "started": _epoch(first.get("timestamp")),
            "agent_session_id": payload.get("agent_session_id"),
            "question": payload.get("agent_question") or payload.get("agent_session_question"),
            "usage": usage if isinstance(usage, dict) else None,
        }
    return out


def _answers(traces: Path) -> list[dict]:
    found = []
    for path in (traces / "answers").glob("*.json") if (traces / "answers").is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            found.append(data)
    return found


def _session_id(agent_session_id: str) -> str:
    return hashlib.sha256(agent_session_id.encode()).hexdigest()[:_ID_LENGTH]


def _turn(prompt: str, started: float, answer: dict | None, runs: list[dict]) -> dict:
    ordered = sorted(runs, key=lambda r: r["started"])
    turn = {
        "id": (answer or {}).get("id") or _session_id(prompt + str(started)),
        "prompt": prompt,
        "status": (answer or {}).get("status", "completed"),
        "agent": (answer or {}).get("agent"),
        "started": started,
        "usage": (answer or {}).get("token_usage"),
        "cost_usd": (answer or {}).get("cost_usd"),
        "answer": (answer or {}).get("answer"),
        "duration_ms": (answer or {}).get("duration_ms"),
        "graph": (answer or {}).get("graph_fingerprint"),
        "run_ids": [r["id"] for r in ordered],
        "_runs": ordered,
        "events": [],
    }
    return turn


def conversations(traces: Path) -> list[dict]:
    """Conversations without their events (``_runs`` holds what builds them), newest first."""
    runs = _runs(traces)
    by_conv: dict[str, dict] = {}
    claimed: set[str] = set()
    for a in sorted(_answers(traces), key=lambda a: str(a.get("started") or a.get("recorded"))):
        cid = a.get("conversation_id") or a["id"]
        if len(cid) != _ID_LENGTH or any(c not in _HEX for c in cid):
            cid = _session_id(cid)
        mine = [runs[r] for r in a.get("run_ids", []) if r in runs]
        claimed.update(r["id"] for r in mine)
        started = _epoch(a.get("started")) or _epoch(a.get("recorded"))
        conv = by_conv.setdefault(
            cid,
            {"id": cid, "title": a.get("question", "")[:_TITLE], "created": started, "turns": []},
        )
        conv["turns"].append(_turn(a.get("question", ""), started, a, mine))
        conv["session_id"] = a.get("resume_session_id") or conv.get("session_id")
    by_agent: dict[str, list[dict]] = {}
    for r in (
        runs.values()
    ):  # sessions an agent ran without this page: grouped by the id its calls carried
        if r["id"] not in claimed and r["agent_session_id"]:
            by_agent.setdefault(r["agent_session_id"], []).append(r)
    for sid, group in by_agent.items():
        group.sort(key=lambda r: r["started"])
        prompt = (
            next((r["question"] for r in group if r["question"]), None) or "(no question recorded)"
        )
        cid = _session_id(sid)
        by_conv[cid] = {
            "id": cid,
            "title": prompt[:_TITLE],
            "created": group[0]["started"],
            "turns": [_turn(prompt, group[0]["started"], None, group)],
        }
    for conv in by_conv.values():
        conv["updated"] = max([t["started"] for t in conv["turns"]] + [conv["created"]])
        conv["readonly"] = True
        conv["source"] = "traces"
    return sorted(by_conv.values(), key=lambda c: c["updated"], reverse=True)


def with_events(conv: dict, trace_of: Callable[[str], dict | None]) -> dict:
    """*conv* with each turn's events: a step and a tool call per run, its trace, and the answer."""
    out = {k: v for k, v in conv.items() if k != "turns"}
    out["turns"] = []
    for turn in conv["turns"]:
        base = turn["started"]
        events: list[dict] = [
            {"e": "turn_start", "t": 0, "prompt": turn["prompt"], "resumed": False}
        ]
        for n, run in enumerate(turn["_runs"], 1):
            t = max(0, int((run["started"] - base) * 1000))
            step = f"s{n}"
            events.append({"e": "step_start", "t": t, "step": step})
            if run["usage"]:
                events.append({"e": "usage", "t": t, "step": step, **run["usage"]})
            events.append(
                {
                    "e": "tool_call",
                    "t": t,
                    "step": step,
                    "id": run["id"],
                    "name": run["tool"],
                    "input": run["input"] or {},
                }
            )
            if trace := trace_of(run["id"]):
                events.append({"e": "trace", "t": t, "id": run["id"], **trace})
        events.append(
            {
                "e": "done",
                "t": turn.get("duration_ms") or 0,
                "status": turn["status"],
                "answer": turn["answer"],
                "usage": turn["usage"],
                "cost_usd": turn["cost_usd"],
            }
        )
        shown = {k: v for k, v in turn.items() if k not in ("_runs",)}
        shown["events"] = events
        out["turns"].append(shown)
    return out
