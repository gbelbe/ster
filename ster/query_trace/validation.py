"""Validation for append-only query trace journals."""

from __future__ import annotations

from collections.abc import Iterable

from .model import Event


def validate_events(events: Iterable[Event]) -> list[str]:
    """Return stable validation errors; an empty list means the journal is valid."""
    items = list(events)
    errors: list[str] = []
    if not items:
        return ["trace contains no events"]
    runs = {event.run_id for event in items}
    traces = {event.trace_id for event in items}
    if len(runs) != 1:
        errors.append("trace contains multiple run IDs")
    if len(traces) != 1:
        errors.append("trace contains multiple trace IDs")
    sequences = [event.sequence for event in items]
    if sequences != list(range(1, len(items) + 1)):
        errors.append("event sequences must be contiguous starting at 1")
    if items[0].event != "run_started":
        errors.append("trace must start with run_started")
    if items[-1].event not in {"run_completed", "run_failed"}:
        errors.append("trace must end with run_completed or run_failed")
    if sum(event.event == "run_started" for event in items) != 1:
        errors.append("trace must contain exactly one run_started event")
    if sum(event.event in {"run_completed", "run_failed"} for event in items) != 1:
        errors.append("trace must contain exactly one terminal event")
    if len({event.event_id for event in items}) != len(items):
        errors.append("event IDs must be unique")
    return errors
