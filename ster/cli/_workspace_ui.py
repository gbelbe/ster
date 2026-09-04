"""Multi-file workspace helpers: context-file prompts and the home action menu."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from rich.prompt import Confirm, Prompt

from ..display import console
from ..workspace import TaxonomyWorkspace

_LIT_CYAN_OPEN: Final = "  [cyan]"
_LIT_CYAN_CLOSE: Final = "[/cyan]  "


from . import _app, _constants, _file_picker

# ──────────────────────────── multi-file / workspace helpers ─────────────────


def parse_context_choice(answer: str, options: list[Path]) -> list[Path]:
    """Read a context-file answer: "all", "none"/"" , or numbers like "1,3".

    Unparseable or out-of-range entries are ignored rather than rejected — the
    prompt is an optional extra, and refusing the whole answer over one typo
    would be worse than loading the files that were named clearly.
    """
    reply = answer.strip().lower()
    if reply in {"", "none", "n"}:
        return []
    if reply in {"all", "a"}:
        return list(options)
    chosen: list[Path] = []
    for part in reply.replace(" ", ",").split(","):
        if part.isdigit() and 1 <= int(part) <= len(options):
            candidate = options[int(part) - 1]
            if candidate not in chosen:
                chosen.append(candidate)
    return chosen


def prompt_for_context_files(editable: Path, found: list[Path]) -> list[Path]:
    """Ask which other files to load read-only alongside *editable*.

    Skipped entirely when there is nothing else to offer, so the common
    single-file case is unchanged.
    """
    options = [f for f in found if f != editable]
    if not options:
        return []
    console.print()
    console.print(
        f"  [bold]{editable.name}[/bold] is editable. "
        "Load others as [bold]read-only context[/bold] to see the connected graph?"
    )
    for i, f in enumerate(options, 1):
        console.print(f"    [cyan]{i}{_LIT_CYAN_CLOSE}{f.name}")
    console.print("  [dim]numbers (1,3) · all · none[/dim]")
    try:
        answer = Prompt.ask("  Context files", default="none")
    except (KeyboardInterrupt, EOFError):
        return []
    return parse_context_choice(answer, options)


def _select_home_file(found: list[Path]) -> Path | None:
    """Step 1 of the home menu: pick the file every action will operate on — from the local
    files *plus* a 'Load demo' entry. Always shown (even for one file), so the demo is always
    reachable. Returns the chosen file, ``_constants._DEMO_SENTINEL`` (load a fresh demo), or ``None`` on
    Quit / Ctrl+C.
    """
    import sys

    console.print("[bold]Select a file:[/bold]\n")
    # Local files, then the (fresh-each-time) demo, then Quit.
    item_values: list[Path | None] = [*found, _constants._DEMO_SENTINEL, _constants._QUIT_SENTINEL]

    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            import termios as _t  # noqa: F401 — availability probe
            import tty as _tt  # noqa: F401

            chosen = _file_picker._arrow_file_picker(found, item_values, 0, None)
            return None if chosen == _constants._QUIT_SENTINEL else chosen
        except ImportError:
            pass

    return _select_home_file_numeric(found)


def _select_home_file_numeric(found: list[Path]) -> Path | None:
    """Numbered-prompt fallback for :func:`_select_home_file` when no arrow-key TTY is
    available. Files 1..n, then the demo, then Quit; a non-numeric reply picks the default
    (first file, or the demo when the folder is empty)."""
    for i, f in enumerate(found, 1):
        console.print(f"{_LIT_CYAN_OPEN}{i}{_LIT_CYAN_CLOSE}{f.name}")
    demo_idx, quit_idx = len(found) + 1, len(found) + 2
    console.print(
        f"{_LIT_CYAN_OPEN}{demo_idx}[/cyan]  [green]🎒 Load demo ontology / taxonomy[/green]"
    )
    console.print(f"{_LIT_CYAN_OPEN}{quit_idx}[/cyan]  [red]✕  Quit[/red]")
    choice = Prompt.ask(f"Select (1–{quit_idx})", default=str(demo_idx if not found else 1))
    try:
        idx = int(choice.strip()) - 1
    except ValueError:
        return _constants._DEMO_SENTINEL if not found else found[0]
    if idx == quit_idx - 1:
        return None  # Quit
    if idx == demo_idx - 1:
        return _constants._DEMO_SENTINEL
    return found[idx] if 0 <= idx < len(found) else _constants._DEMO_SENTINEL


def _home_actions() -> list[tuple[object, str]]:
    """The home action rows for the selected file, in display order. 'Change file' returns
    to the file list (which now holds the local files *and* the demo); True = the primary
    'open' action (the Textual viewer)."""
    return [
        (_constants._CHANGE_FILE_SENTINEL, "🔀 Change file"),
        (True, "🖥  TTL Viewer-Editor"),  # True = "open" sentinel → the Textual viewer
        (_constants._QUERY_SENTINEL, "🔍 SPARQL Query"),
        (_constants._PUBLISH_SENTINEL, "📦 Linked Data Publish & Version"),
        (_constants._HTML_SENTINEL, "🌐 HTML Data Catalog"),
        (_constants._GRAPH_SENTINEL, "◈  Load Graph Viewer"),
        (_constants._EXT_ONT_SENTINEL, "📥 Import External Ontology"),
        (_constants._MCP_SENTINEL, "🔌 Connect AI Agent (MCP)"),
        (_constants._QUIT_SENTINEL, "✕  Quit"),
    ]


def _home_menu_fallback(selected: Path, actions: list[tuple[object, str]]) -> object:
    """Non-TTY action menu: a plain numbered prompt. Returns the chosen action sentinel."""
    console.print(f"  [green]✓[/green]  [bold]{selected.name}[/bold]\n")
    for i, (_s, label) in enumerate(actions, 1):
        console.print(f"{_LIT_CYAN_OPEN}{i}{_LIT_CYAN_CLOSE}{label}")
    console.print()
    open_idx = next((i for i, (s, _) in enumerate(actions) if s is True), 0)
    choice = Prompt.ask(f"Action (1–{len(actions)})", default=str(open_idx + 1))
    try:
        idx = int(choice.strip()) - 1
    except ValueError:
        idx = -1
    if not (0 <= idx < len(actions)):
        idx = open_idx  # default → TTL Viewer-Editor (open the file)
    return actions[idx][0]


def _render_arrow_menu(
    selected: Path,
    actions: list[tuple[object, str]],
    cursor: int,
    first: bool,
    colors: tuple[str, str, str, str, str, str, str],
) -> None:
    import sys

    reset, bold, dim, cyan, green, inverse, bright_cyan = colors
    if not first:
        sys.stdout.write(f"\033[{len(actions) + 3}A")
    sys.stdout.write(
        f"{_app._CLEAR_LINE}  {green}✓{reset}  {bold}{selected.name}{reset}\r\n{_app._CLEAR_LINE}\r\n"
    )
    for index, (sentinel, label) in enumerate(actions):
        color = _constants._MENU_COLOURS.get(sentinel, cyan)
        number = f"{index + 1:>2}"
        row = (
            f"  {bright_cyan}{inverse} {number} {reset}  {color}{bold}{label}{reset}"
            if index == cursor
            else f"    {cyan}{number}{reset}  {color}{label}{reset}"
        )
        sys.stdout.write(f"{_app._CLEAR_LINE}{row}\r\n")
    sys.stdout.write(f"{_app._CLEAR_LINE}  {dim}↑↓ navigate  Enter: select{reset}\r\n")
    sys.stdout.flush()


def _run_arrow_menu(selected: Path, actions: list[tuple[object, str]]) -> int | None:
    """Arrow-key action menu for *selected*. Returns the chosen index, or None on Quit/Esc."""
    import sys
    import termios
    import tty

    colors = (
        _app._ANSI_RESET,
        _app._ANSI_BOLD,
        _app._ANSI_DIM,
        _app._ANSI_CYAN,
        _app._ANSI_GREEN,
        _app._ANSI_INVERSE,
        _app._ANSI_BRIGHT_CYAN,
    )
    n = len(actions)
    cursor = next((i for i, (s, _) in enumerate(actions) if s is True), 0)  # start on "open"
    _render_arrow_menu(selected, actions, cursor, first=True, colors=colors)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    result: int | None = None
    try:
        tty.setraw(fd)
        # Discard bytes left in the OS buffer from a previous curses session (a stray
        # Escape would otherwise be read as Quit and exit the menu immediately).
        termios.tcflush(fd, termios.TCIFLUSH)
        while True:
            ch = sys.stdin.buffer.read(1)
            if ch in (b"\r", b"\n"):
                result = cursor
                break
            if ch in (b"q", b"Q", b"\x03"):
                break  # → None (quit)
            if ch == b"\x1b":
                nxt = sys.stdin.buffer.read(1)
                if nxt != b"[":
                    break  # bare Esc → quit
                code = sys.stdin.buffer.read(1)
                if code == b"B":
                    cursor += 1
                elif code == b"A":
                    cursor -= 1
                cursor %= n
            _render_arrow_menu(selected, actions, cursor, first=False, colors=colors)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\r\n")
        sys.stdout.flush()
    return result


def _home_action_menu(selected: Path) -> list[Path] | Path | None:
    """Step 2 of the home menu: the action menu for the *selected* file.

    Every action operates on *selected*. Returns:
      [selected]             — TTL Viewer-Editor (the file to open)
      <action sentinel>      — SPARQL / Publish / HTML / Graph / Import
      _constants._CHANGE_FILE_SENTINEL  — reselect the file (the file list holds files + the demo)
      _constants._QUIT_SENTINEL         — Quit / Ctrl+C / plain Esc
    Falls back to a plain numbered prompt in non-interactive terminals.
    """
    import sys

    actions = _home_actions()

    def _chosen(sentinel: object) -> list[Path] | Path:
        return [selected] if sentinel is True else sentinel  # type: ignore[return-value]

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return _chosen(_home_menu_fallback(selected, actions))
    try:
        import termios  # noqa: F401 — availability probe for the raw-tty menu
        import tty  # noqa: F401
    except ImportError:
        return [selected]  # no raw-tty UI available → default to opening the file
    idx = _run_arrow_menu(selected, actions)
    return _constants._QUIT_SENTINEL if idx is None else _chosen(actions[idx][0])


def _resolve_broken_mappings_at_load(
    workspace: TaxonomyWorkspace,
    found_files: list[Path],
) -> None:
    """Before opening the TUI, ask user to load any files referenced by mappings."""
    from ..validator import SkosValidator

    issues = SkosValidator().validate(workspace)
    broken = [i for i in issues if i.code == "broken_mapping"]
    if not broken:
        return

    # Collect unique missing URIs
    missing_uris: set[str] = {i.related_uri for i in broken if i.related_uri}

    # Which files in this folder might contain them?
    unloaded = [f for f in found_files if f not in workspace.taxonomies]
    if not unloaded:
        console.print(
            f"[yellow]⚠  {len(missing_uris)} unresolved mapping reference(s) — "
            "no additional files available in this folder.[/yellow]"
        )
        return

    console.print(
        f"\n[yellow]⚠  Found {len(missing_uris)} unresolved mapping reference(s).[/yellow]"
    )
    console.print("[dim]The following files in this folder may contain them:[/dim]")
    for f in unloaded:
        console.print(f"  • {f.name}")

    try:
        want = Confirm.ask("Load these files to resolve references?", default=True)
    except (KeyboardInterrupt, EOFError):
        want = False

    if want:
        for f in unloaded:
            try:
                workspace.add_file(f)
                console.print(f"  [green]✓ Loaded[/green] {f.name}")
            except Exception as exc:
                console.print(f"  [red]✗ Failed to load {f.name}: {exc}[/red]")


def _load_workspace(
    files: list[Path],
    all_found: list[Path],
) -> TaxonomyWorkspace:
    """Load all *files* into a workspace, then resolve broken mappings."""
    workspace = TaxonomyWorkspace.from_files(files)
    _resolve_broken_mappings_at_load(workspace, all_found)
    return workspace
