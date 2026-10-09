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
    from ..plugins.semanticdiff.history import open_history
    from ..plugins.semanticdiff.screen import run_history

    if not files:
        _app.err.print("[red]No taxonomy files found.[/red]")
        return
    # _resolve_file, not _pick_file: it honours the file already chosen for this
    # session and only asks when there is nothing to reuse. Picking again after
    # the home screen had already been answered was the same question twice.
    selected = _file_picker._resolve_file(None)
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


def _explain_missing_package(_files: list[Path]) -> None:
    """The menu row of a plugin that is on but cannot run: what is missing and the command that fixes it."""
    from .. import plugins

    problem = (
        plugins.missing_dependency("semanticdiff")
        or "Semantic History is installed now: reopen this menu."
    )
    console.print(f"\n  [yellow]{problem}[/yellow]\n")
