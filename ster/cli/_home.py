"""Entry point (`main`) and the bare `ster` interactive home-screen loop."""

from __future__ import annotations

from pathlib import Path

import typer

from ..display import console
from ..project import Project, _git_root
from . import _app, _constants, _file_picker, _query_launcher, _state, _viewer, _workspace_ui


def main() -> None:
    """Entry point.

    • ``ster``                   — interactive home screen (loops until Ctrl+C)
    • ``ster taxonomy.ttl``      — open the file, then the home screen for its folder
    • ``ster show taxonomy.ttl`` — one-shot viewer (plus the other subcommands)
    • ``ster <subcommand> …``    — delegate to Typer
    """
    import os
    import sys

    args = sys.argv[1:]

    # Non-bare invocation → delegate to Typer once (no loop)
    if args:
        first = args[0]
        if first not in _app._SUBCOMMANDS and not first.startswith("-"):
            p = Path(first)
            if p.suffix.lower() in _app._TAXONOMY_SUFFIXES:
                # `ster PATH/file.ttl` (no other args) behaves like bare `ster`
                # run inside the file's folder: open the file, then the menu.
                if len(args) == 1 and p.exists():
                    target = p.resolve()
                    os.chdir(target.parent)
                    _home_screen(initial_file=Path.cwd() / target.name)
                    return
                sys.argv.insert(1, "show")
        _app.app()
        return

    # ── Bare invocation → interactive home screen loop ────────────────────────
    _home_screen()


def _found_taxonomy_files() -> list[Path]:
    """Every taxonomy file in the current folder, sorted and de-duplicated."""
    found: list[Path] = []
    for pattern in _app._TAXONOMY_GLOBS:
        found.extend(Path.cwd().glob(pattern))
    return sorted(set(found))


def _print_home_intro() -> None:
    """Welcome banner + the one-time CI-workflow prompt."""
    _app._print_welcome()
    if _state.ci_check_done:
        return
    _state.ci_check_done = True
    from ..init_ci import prompt_if_missing
    from ..project import _git_root as _find_git_root

    _root = _find_git_root(Path.cwd())
    if _root and prompt_if_missing(_root):
        console.print(
            "[green]✓[/green] .github/workflows/taxonomy-ci.yml — commit and push to activate CI\n"
        )


def _open_selected_in_viewer(
    selected: list[Path], found: list[Path], project: Project | None
) -> None:
    """Persist the project, validate the workspace, then open the primary file in the viewer."""
    git_root = _git_root(Path.cwd()) or Path.cwd()
    updated_project = Project(root=git_root, files=[], lang=project.lang if project else "en")
    for f in selected:
        updated_project.add_file(f)
    try:
        updated_project.save()
    except Exception:
        pass  # non-fatal if .ster/ can't be written
    try:
        _workspace_ui._load_workspace(selected, found)  # raises on broken mappings
    except Exception as exc:
        _app.err.print(f"[red]Failed to load workspace: {exc}[/red]")
        return
    primary = selected[0]
    _file_picker._save_session(primary)
    _state.session_file = primary
    try:
        _viewer._open_viewer(primary, lang=updated_project.lang)
    except Exception as exc:
        _app.err.print(f"[red]Viewer error: {exc}[/red]")


def _home_obtain_action(
    pending_open: Path | None, selected_file: Path | None, found: list[Path]
) -> tuple[Path | None, list[Path] | Path | None]:
    """One home-loop turn's ``(file, action)``.

    A pending file (``ster file.ttl``) or a freshly picked file opens straight in the
    viewer — no action menu in between. Once a file is selected and the viewer has
    closed, the next turn shows its action menu (SPARQL / publish / graph / import /
    change file). Returns ``action = _constants._QUIT_SENTINEL`` when the user quits at selection."""
    if pending_open is not None:  # ster PATH/file.ttl → open that file directly
        return pending_open, [pending_open]
    _print_home_intro()
    if selected_file is None or selected_file not in found:
        choice = _workspace_ui._select_home_file(found)
        if choice is None:  # Quit / cancel
            return None, _constants._QUIT_SENTINEL
        if choice == _constants._DEMO_SENTINEL:  # a fresh demo, opened directly
            demo = _query_launcher._load_demo_into_cwd()
            return demo, [demo]
        # A freshly picked file opens straight in the viewer — no action menu in
        # between. The menu (SPARQL / publish / graph / import / change file) is shown
        # only after the viewer closes, on the next loop turn for the same file.
        return choice, [choice]
    return selected_file, _workspace_ui._home_action_menu(selected_file)


def _home_perform(
    action: list[Path] | Path | None,
    selected_file: Path | None,
    found: list[Path],
    project: Project | None,
) -> str:
    """Carry out a chosen home action → "quit", "change", or "continue"."""
    if action is _constants._QUIT_SENTINEL or action is None:
        return "quit"
    if action is _constants._CHANGE_FILE_SENTINEL:  # go back to file selection
        return "change"
    assert selected_file is not None  # set before any menu is shown
    if _query_launcher._dispatch_menu_action(
        action, [selected_file]
    ):  # actions act on the chosen file
        return "continue"
    selected = action if isinstance(action, list) else [selected_file]
    _open_selected_in_viewer(selected, found, project)
    return "continue"


def _home_screen(initial_file: Path | None = None) -> None:
    """Interactive home-screen loop (bare ``ster``).

    Pick a single taxonomy file and it opens straight in the Textual viewer. When the
    viewer closes, its action menu appears — graph / query / publish / import, plus a
    "Change file" entry to switch. ``ster PATH/file.ttl`` opens that file directly first.
    """
    pending_open = initial_file
    selected_file: Path | None = None
    while True:
        try:
            found = _found_taxonomy_files()
            # No `not found` special case: the file list always offers the demo (+ Quit),
            # so an empty folder still gets a working picker — see _workspace_ui._select_home_file.
            project = Project.load(Path.cwd())
            selected_file, action = _home_obtain_action(pending_open, selected_file, found)
            pending_open = None
            outcome = _home_perform(action, selected_file, found, project)
        # typer.Exit too: this loop runs outside typer's own runner, so an Exit
        # raised by a picker deep inside an action had nothing to translate it and
        # reached the user as a raw traceback on what is simply a quit.
        except (KeyboardInterrupt, EOFError, typer.Exit):
            console.print()
            break

        if outcome == "quit":
            break
        if outcome == "change":
            selected_file = None
