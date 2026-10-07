"""Append-only JSONL recorder and reader."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .model import Event, TraceRef, new_id


class JsonlTraceRecorder:
    """Write one event journal per query run."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self._sequences: dict[str, int] = {}
        self._paths: dict[str, Path] = {}

    def start_run(self, question: str, **context: Any) -> TraceRef:
        ref = TraceRef(new_id("run"), new_id("trace"))
        self._sequences[ref.run_id] = 0
        self._paths[ref.run_id] = self.directory / f"{ref.run_id}.jsonl"
        self.record(
            Event(
                event="run_started",
                run_id=ref.run_id,
                trace_id=ref.trace_id,
                sequence=self._next(ref.run_id),
                payload={"question": question, **context},
            )
        )
        return ref

    def record(self, event: Event) -> None:
        path = self._paths.get(event.run_id)
        if path is None:
            raise ValueError(f"unknown query run: {event.run_id}")
        self._sequences[event.run_id] = max(self._sequences[event.run_id], event.sequence)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event.as_dict(), ensure_ascii=True, sort_keys=True) + "\n")

    def finish(self, ref: TraceRef, status: str = "completed", **payload: Any) -> None:
        self.record(
            Event(
                event="run_completed" if status == "completed" else "run_failed",
                run_id=ref.run_id,
                trace_id=ref.trace_id,
                sequence=self._next(ref.run_id),
                payload={"status": status, **payload},
            )
        )

    def enabled(self) -> bool:
        return True

    def path_for(self, run_id: str) -> Path:
        """Return a completed run's journal path, or raise a clear error."""
        path = self._paths.get(run_id, self.directory / f"{run_id}.jsonl")
        if not path.exists():
            raise FileNotFoundError(f"unknown query trace: {run_id}")
        return path

    def _next(self, run_id: str) -> int:
        sequence = self._sequences[run_id] + 1
        self._sequences[run_id] = sequence
        return sequence


def read_events(path: str | Path) -> Iterator[Event]:
    """Read and minimally decode a JSONL event journal."""
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                yield Event(
                    event=data["event"],
                    event_id=data["event_id"],
                    run_id=data["run_id"],
                    trace_id=data["trace_id"],
                    sequence=data["sequence"],
                    timestamp=data["timestamp"],
                    schema_version=data.get("schema_version", 1),
                    step_id=data.get("step_id"),
                    payload=data.get("payload", {}),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid event at line {line_number}: {exc}") from exc
