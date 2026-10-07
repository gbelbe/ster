"""Current-project query-trace session discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ster.query_trace.jsonl import read_events
from ster.query_trace.validation import validate_events


@dataclass(frozen=True)
class TraceSession:
    run_id: str
    trace_id: str
    question: str
    status: str
    started: str
    ended: str
    path: Path
    event_count: int
    agent_session_id: str | None = None
    agent_question: str | None = None
    agent_session_question: str | None = None


@dataclass(frozen=True)
class AgentSession:
    """A chain of MCP calls separated by no more than the idle window."""

    calls: tuple[tuple[TraceSession, list], ...]

    @property
    def started(self) -> str:
        return self.calls[0][0].started

    @property
    def ended(self) -> str:
        return self.calls[-1][0].ended

    @property
    def event_count(self) -> int:
        return sum(session.event_count for session, _events in self.calls)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def agent_question(self) -> str | None:
        return next(
            (session.agent_question for session, _events in self.calls if session.agent_question),
            None,
        )

    @property
    def session_question(self) -> str | None:
        return next(
            (
                session.agent_session_question
                for session, _events in self.calls
                if session.agent_session_question
            ),
            None,
        )

    @property
    def token_usage(self) -> dict[str, int] | None:
        totals = {"input": 0, "output": 0, "total": 0}
        found = False
        for _session, events in self.calls:
            usage = events[0].payload.get("token_usage") if events else None
            if not isinstance(usage, dict):
                continue
            found = True
            for key in totals:
                if isinstance(usage.get(key), int):
                    totals[key] += usage[key]
        return totals if found else None


_AGENT_IDLE_SECONDS = 120


def events_for_project(project: Path) -> list[tuple[TraceSession, list]]:
    """Return valid project sessions with their decoded events, newest first."""
    directory = project / ".ster" / "query-traces"
    sessions: list[tuple[TraceSession, list]] = []
    for path in sorted(directory.glob("*.jsonl"), reverse=True) if directory.is_dir() else []:
        try:
            events = list(read_events(path))
        except ValueError:
            continue
        if validate_events(events):
            continue
        sessions.append((sessions_for_events(events, path), events))
    return sorted(sessions, key=lambda item: item[0].started, reverse=True)


def agent_sessions_for_project(
    project: Path, idle_seconds: int = _AGENT_IDLE_SECONDS
) -> list[AgentSession]:
    """Group successive MCP calls into agent sessions using a configurable gap."""
    calls = sorted(events_for_project(project), key=lambda item: item[0].started)
    groups: list[list[tuple[TraceSession, list]]] = []
    for call in calls:
        previous = groups[-1][-1][0] if groups else None
        same_external = bool(
            previous
            and previous.agent_session_id
            and previous.agent_session_id == call[0].agent_session_id
        )
        if (
            not groups
            or same_external
            or (
                previous
                and previous.agent_session_id is None
                and call[0].agent_session_id is None
                and _gap_seconds(previous.ended, call[0].started) <= idle_seconds
            )
        ):
            groups.append([call])
        else:
            groups[-1].append(call)
    return [AgentSession(tuple(group)) for group in reversed(groups)]


def _gap_seconds(previous: str, current: str) -> float:
    return (
        datetime.fromisoformat(current.replace("Z", "+00:00"))
        - datetime.fromisoformat(previous.replace("Z", "+00:00"))
    ).total_seconds()


def sessions_for_events(events: list, path: Path) -> TraceSession:
    """Build the session summary shared by discovery and global timeline views."""
    payload = events[0].payload
    session_question = payload.get("agent_session_question")
    token_usage = payload.get("token_usage")
    if isinstance(session_question, dict) and isinstance(token_usage, str):
        session_question, token_usage = token_usage, session_question
    return TraceSession(
        run_id=events[0].run_id,
        trace_id=events[0].trace_id,
        question=str(events[0].payload.get("question", "")),
        status=str(events[-1].payload.get("status", "failed")),
        started=events[0].timestamp,
        ended=events[-1].timestamp,
        path=path,
        event_count=len(events),
        agent_session_id=payload.get("agent_session_id"),
        agent_question=payload.get("agent_question"),
        agent_session_question=session_question,
    )


def sessions_for_project(project: Path) -> list[TraceSession]:
    """List valid trace journals under the current project's ``.ster`` folder."""
    directory = project / ".ster" / "query-traces"
    sessions: list[TraceSession] = []
    for path in sorted(directory.glob("*.jsonl")) if directory.is_dir() else []:
        try:
            events = list(read_events(path))
        except ValueError:
            continue
        if validate_events(events):
            continue
        sessions.append(sessions_for_events(events, path))
    return list(reversed(sessions))


def materialized_path(session: TraceSession) -> Path:
    """Stable PROV-O/TriG output path for a recorded session."""
    output = session.path.parent / "materialized" / f"{session.run_id}.prov.trig"
    output.parent.mkdir(parents=True, exist_ok=True)
    return output
