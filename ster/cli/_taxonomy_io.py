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


def _load(path: Path) -> Taxonomy:
    """Load *path* for CLI commands — exits the process on failure."""
    taxonomy = _load_safe(path)
    if taxonomy is None:
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
