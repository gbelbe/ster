"""Home-menu action: open the semantic history of the selected file."""

from __future__ import annotations

from pathlib import Path

from ..display import console
from . import _app, _file_picker


def _run_history_interactive(files: list[Path]) -> None:  # pragma: no cover - interactive tty
    """Open the history screen for one tracked file.

    A file outside a git repository has no history to show, and saying so beats
    opening an empty screen the reader then has to interpret.
    """
    from ..history import open_history
    from ..tui.history_screen import run_history

    if not files:
        _app.err.print("[red]No taxonomy files found.[/red]")
        return
    selected = _file_picker._pick_file(files)
    history = open_history(selected)
    if history is None:
        console.print(
            f"\n  [yellow]{selected.name} is not inside a git repository,[/yellow] "
            "so it has no history to read.\n"
        )
        return
    if not history.rows:
        console.print(f"\n  [yellow]No commit has touched {selected.name} yet.[/yellow]\n")
        return
    run_history(history)
