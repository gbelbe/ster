"""Load/save/resolve helpers shared by every mutating command."""

from __future__ import annotations

from pathlib import Path
from typing import Final

import typer

from .. import operations, store
from ..display import console
from ..exceptions import SkostaxError
from ..model import Taxonomy

_LIT_RED_CLOSE: Final = "[/red]"
_LIT_RED_OPEN: Final = "[red]"


from . import _app

# ──────────────────────────── helpers ────────────────────────────────────────


def _load_safe(path: Path) -> Taxonomy | None:
    """Load *path*, printing errors and returning None on failure (never raises)."""
    mismatch = store.detect_format_mismatch(path)
    if mismatch:
        _, actual = mismatch
        console.print(
            f"[yellow]⚠[/yellow]  [bold]{path.name}[/bold] has a "
            f"[bold].{path.suffix.lstrip('.')}[/bold] extension but content looks like "
            f"[bold]{actual}[/bold] format — loading anyway.\n"
            f"   [dim]Rename the file or use [bold]ster convert[/bold] to fix this.[/dim]"
        )
    try:
        with console.status(f"Loading {path.name}…"):
            return store.load(path)
    except Exception as exc:
        _app.err.print(f"{_LIT_RED_OPEN}{store.format_parse_error(exc, path)}{_LIT_RED_CLOSE}")
        return None


def _report_unreadable(path: Path, taxonomy: Taxonomy) -> bool:
    """Say why *taxonomy* came out empty and how to fix it. True when it was empty.

    Printing a blank tree (or "0 concepts validated") for a file ster failed to
    model tells the user nothing is wrong when something is; this is the text
    counterpart of the TUI's unreadable-file modal.
    """
    unreadable = store.diagnose(taxonomy)
    if unreadable is None:
        return False
    summary = store.describe_unreadable(unreadable, path.name)
    _app.err.print(f"{_LIT_RED_OPEN}✗ {summary}{_LIT_RED_CLOSE}")
    lines = store.type_lines(unreadable)
    if lines:
        _app.err.print("\n   Used as a type, but never declared:\n")
        for line in lines:
            # soft_wrap: a URI must stay in one piece to be copyable.
            _app.err.print(f"       [bold]{line}[/bold]", soft_wrap=True)
    turtle = store.declaration_turtle(unreadable)
    if turtle:
        _app.err.print("\n   Declare it and ster can read the file:\n")
        for line in turtle.splitlines():
            # soft_wrap: these lines are meant to be copied, so they must not fold.
            _app.err.print(f"       [green]{line}[/green]", soft_wrap=True)
    return True


def _load(path: Path, *, diagnose: bool = True) -> Taxonomy:
    """Load *path* for CLI commands — exits the process on failure.

    *diagnose* is off for the interactive viewer, which shows the same finding in
    a modal that can also apply the fix.
    """
    taxonomy = _load_safe(path)
    if taxonomy is None:
        raise typer.Exit(1)
    if diagnose and _report_unreadable(path, taxonomy):
        raise typer.Exit(1)
    return taxonomy


def _save(taxonomy: Taxonomy, path: Path) -> None:
    try:
        store.save(taxonomy, path)
        console.print(f"[green]✓ Saved[/green] {path}")
    except Exception as exc:
        _app.err.print(f"[red]Cannot save {path}: {exc}{_LIT_RED_CLOSE}")
        raise typer.Exit(1)


def _resolve(taxonomy: Taxonomy, ref: str) -> str:
    try:
        return operations.resolve(taxonomy, ref)
    except SkostaxError as exc:
        _app.err.print(f"{_LIT_RED_OPEN}{exc}{_LIT_RED_CLOSE}")
        raise typer.Exit(1)


def _run(fn, *args, **kwargs):
    """Call an operations function, converting SkostaxError to a clean exit."""
    try:
        return fn(*args, **kwargs)
    except SkostaxError as exc:
        _app.err.print(f"{_LIT_RED_OPEN}{exc}{_LIT_RED_CLOSE}")
        raise typer.Exit(1)
