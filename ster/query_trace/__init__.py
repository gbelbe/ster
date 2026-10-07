"""Portable query execution tracing and PROV-O materialisation."""

from .jsonl import JsonlTraceRecorder, read_events
from .materialize import materialize_events
from .model import Event, QueryTraceConfig, TraceRef
from .recorder import (
    NoOpTraceRecorder,
    QueryTraceRecorder,
    configure,
    configure_from_environment,
    environment_configured,
    get_recorder,
    set_recorder,
)
from .subgraph import trace_subgraph

__all__ = [
    "Event",
    "JsonlTraceRecorder",
    "NoOpTraceRecorder",
    "QueryTraceConfig",
    "QueryTraceRecorder",
    "TraceRef",
    "get_recorder",
    "configure",
    "configure_from_environment",
    "environment_configured",
    "materialize_events",
    "read_events",
    "set_recorder",
    "trace_subgraph",
]
