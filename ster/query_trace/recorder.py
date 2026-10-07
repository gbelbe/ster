"""Recorder port and process-wide default used by ster integrations."""

from __future__ import annotations

import os
from typing import Any, Protocol

from .model import Event, TraceRef, new_id


class QueryTraceRecorder(Protocol):
    """Minimal port implemented by portable and application-specific recorders."""

    def start_run(self, question: str, **context: Any) -> TraceRef: ...

    def record(self, event: Event) -> None: ...

    def finish(self, ref: TraceRef, status: str = "completed", **payload: Any) -> None: ...

    def enabled(self) -> bool: ...


class NoOpTraceRecorder:
    """Disabled recorder; it never creates files or changes query behaviour."""

    def start_run(self, question: str, **context: Any) -> TraceRef:
        return TraceRef(new_id("run"), new_id("trace"))

    def record(self, event: Event) -> None:
        return None

    def finish(self, ref: TraceRef, status: str = "completed", **payload: Any) -> None:
        return None

    def enabled(self) -> bool:
        return False


_recorder: QueryTraceRecorder = NoOpTraceRecorder()


def get_recorder() -> QueryTraceRecorder:
    return _recorder


def set_recorder(recorder: QueryTraceRecorder) -> None:
    global _recorder
    _recorder = recorder


def configure(enabled: bool, directory: str = ".ster/query-traces") -> None:
    """Select the process recorder without coupling callers to implementations."""
    if enabled:
        from .jsonl import JsonlTraceRecorder

        set_recorder(JsonlTraceRecorder(directory))
    else:
        set_recorder(NoOpTraceRecorder())


def configure_from_environment() -> None:
    """Configure tracing for a ster server without importing ster settings."""
    enabled = os.environ.get("STER_QUERY_TRACE", "").strip().lower() in {"1", "true", "yes", "on"}
    configure(enabled, os.environ.get("STER_QUERY_TRACE_DIR", ".ster/query-traces"))


def environment_configured() -> bool:
    """Whether the environment explicitly selected a tracing state."""
    return "STER_QUERY_TRACE" in os.environ
