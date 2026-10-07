"""Options several commands share, declared once."""

from __future__ import annotations

from pathlib import Path

import typer

CONTEXT_HELP = (
    "Load these files read-only alongside FILE (repeatable). "
    "Their entities are visible but locked, and saving never writes to them."
)


def context_files() -> list[Path] | None:
    """The ``--context-files/-x`` option of every command that opens a graph."""
    return typer.Option(None, "--context-files", "-x", help=CONTEXT_HELP)  # type: ignore[return-value]
