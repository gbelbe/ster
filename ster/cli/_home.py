"""Entry point (`main`) and the bare `ster` interactive home-screen loop."""

from __future__ import annotations

from pathlib import Path
from typing import Final

import typer

from ..display import console
from ..project import Project, _git_root
from . import _app, _constants, _file_picker, _query_launcher, _state, _viewer, _workspace_ui
from ._discovery import discover_rdf_files, subfolder_rdf_files


def _launch_place(arg: str) -> tuple[Path, Path | None] | None:
    """Where ``ster ARG`` should run as though launched there, and what to open.

    A folder is ``cd FOLDER && ster``; an existing RDF file is the same in its
    folder, with that file opened first. Anything else is not a place.
    """
    path = Path(arg)
    if path.is_dir():
        return path.resolve(), None
    if path.suffix.lower() in _app._TAXONOMY_SUFFIXES and path.exists():
        target = path.resolve()
        return target.parent, target
    return None


def _is_path_like(arg: str) -> bool:
    """Not a subcommand and not an option — so it was meant as a path."""
    return arg not in _app._SUBCOMMANDS and not arg.startswith("-")


# ``--ask-again``: forget the remembered subfolder answer and context choices,
# then start as usual, so both are asked afresh. Handled here rather than by
# Typer because it applies to every way of starting ster, bare launch included.
ASK_AGAIN: Final = "--ask-again"


def _take_flag(flag: str) -> bool:
    """Remove *flag* from sys.argv, reporting whether it was there."""
    import sys  # noqa: PLC0415

    if flag not in sys.argv[1:]:
        return False
    sys.argv[1:] = [arg for arg in sys.argv[1:] if arg != flag]
    return True


def _forget_choices(root: Path) -> None:
    """Drop the answers remembered for *root*'s project; nothing to do without one."""
    project = Project.load(root)
    if project is not None:
        project.forget_choices()
        _workspace_ui._save_quietly(project)


def main() -> None:
    """Entry point.

    • ``ster``                   — interactive home screen (loops until Ctrl+C)
    • ``ster FOLDER``            — the same, as if launched from inside FOLDER
    • ``ster taxonomy.ttl``      — open the file, then the home screen for its folder
    • ``ster show taxonomy.ttl`` — one-shot viewer (plus the other subcommands)
    • ``ster <subcommand> …``    — delegate to Typer
    • ``--ask-again``            — with any of these: forget remembered choices first
    """
    import os
    import sys

    ask_again = _take_flag(ASK_AGAIN)
    args = sys.argv[1:]
    first = args[0] if args else None
    place = _launch_place(first) if first and len(args) == 1 and _is_path_like(first) else None
    if place is not None:
        os.chdir(place[0])
    if ask_again:
        _forget_choices(Path.cwd())
    if not args:
        _home_screen()
    elif place is not None and place[1] is not None:
        _home_screen(initial_file=Path.cwd() / place[1].name)
    elif place is not None:
        _home_screen()
    else:
        _run_command(args)


def _run_command(args: list[str]) -> None:
    """A subcommand, or ``ster file.ttl --option`` (the one-shot viewer), via Typer."""
    import sys  # noqa: PLC0415

    first = args[0]
    if _is_path_like(first) and Path(first).suffix.lower() in _app._TAXONOMY_SUFFIXES:
        sys.argv.insert(1, "show")  # `ster file.ttl --lang fr` → the one-shot viewer
    elif len(args) == 1 and _is_path_like(first):
        # Typer would say "No such command", which misleads when a folder was
        # meant — the likelier intent for a lone path-shaped argument.
        typer.echo(f"ster: no such folder, RDF file or command: {first}", err=True)
        raise SystemExit(2)
    _app.app()


def _found_taxonomy_files() -> list[Path]:
    """Every taxonomy file in the current folder, and one level down if agreed."""
    root = Path.cwd()
    return discover_rdf_files(root, include_subfolders=_include_subfolders(root))


def _include_subfolders(root: Path) -> bool:
    """Whether to offer files one level down — asked once per project, then remembered.

    No question when no subfolder holds an RDF file, and none without a
    terminal: an answer nobody gave is not saved, so it is asked for real later.
    """
    import sys  # noqa: PLC0415

    below = subfolder_rdf_files(root)
    if not below:
        return False
    project = Project.load(root) or Project(root=_git_root(root) or root)
    if project.include_subfolders is not None:
        return project.include_subfolders
    if not sys.stdin.isatty():
        return False
    project.include_subfolders = _workspace_ui.ask_include_subfolders(below)
    _workspace_ui._save_quietly(project)
    return project.include_subfolders


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
    # Rebuilt for the new file list, but carrying what the user already answered:
    # a fresh Project here would forget the subfolder answer and every context.
    updated_project = Project(
        root=git_root,
        files=[],
        lang=project.lang if project else "en",
        include_subfolders=project.include_subfolders if project else None,
        context=dict(project.context) if project else {},
    )
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
    # Asked here rather than in the file list: the answer belongs to the file
    # just chosen, and a folder holding only that file never sees the question.
    context = _workspace_ui.context_files_for(primary, found, updated_project)
    try:
        _viewer._open_viewer(primary, lang=updated_project.lang, context=context)
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
