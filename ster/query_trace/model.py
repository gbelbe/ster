"""Transport-neutral data types for query traces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    """Return an RFC 3339 UTC timestamp suitable for an event."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


@dataclass(frozen=True)
class TraceRef:
    run_id: str
    trace_id: str


@dataclass(frozen=True)
class Event:
    """One append-only trace event.

    ``payload`` is deliberately a plain JSON object. The event envelope remains
    stable while step-specific payloads can evolve independently.
    """

    event: str
    run_id: str
    trace_id: str
    sequence: int
    timestamp: str = field(default_factory=utc_now)
    event_id: str = field(default_factory=lambda: new_id("event"))
    step_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "event": self.event,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "schema_version": self.schema_version,
            "payload": self.payload,
        }
        if self.step_id is not None:
            data["step_id"] = self.step_id
        return data


@dataclass(frozen=True)
class QueryTraceConfig:
    enabled: bool = False
    directory: str = ".ster/query-traces"
    record_queries: bool = True
    record_results: bool = True
    max_inline_rows: int = 100
