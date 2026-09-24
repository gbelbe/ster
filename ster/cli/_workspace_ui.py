"""Multi-file workspace helpers: context-file prompts and the home action menu."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, Final

from .. import ask
from ..display import console
from ..project import Project
from ..workspace import TaxonomyWorkspace

_LIT_CYAN_OPEN: Final = "  [cyan]"
_LIT_CYAN_CLOSE: Final = "[/cyan]  "
_ABORT_KEY: Final = "abort"


from . import _app, _constants, _file_picker
from ._discovery import shown
from ._tty_input import _read_after_escape

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


def _toggled(ticked: list[bool], sel: int) -> list[bool]:
    """*ticked* with the row under the cursor flipped."""
    out = list(ticked)
    out[sel] = not out[sel]
    return out


# One key, one move over (ticks, cursor). A table rather than a chain of elifs:
# every entry is the same shape, so adding a key is adding a row. "none" is not
# here: unlike a move, it confirms on its own — see the loop in
# _context_checkbox_picker.
_CHECKBOX_MOVES: dict[str, Callable[[list[bool], int], tuple[list[bool], int]]] = {
    "space": lambda ticked, sel: (_toggled(ticked, sel), sel),
    "all": lambda ticked, sel: ([True] * len(ticked), sel),
    "up": lambda ticked, sel: (ticked, (sel - 1) % len(ticked)),
    "down": lambda ticked, sel: (ticked, (sel + 1) % len(ticked)),
}


def _read_checkbox_key(stream: BinaryIO) -> str:
    """One keypress as a name, with the escape dance decoded here.

    The caller should not have to know that an arrow is three bytes, nor that a
    lone Esc is the same intent as Ctrl+C. It asks for a key and gets a word.
    """
    ch = stream.read(1)
    if not ch:
        # stdin is closed — a pipe ended, or the terminal went away. There is no
        # next key coming, so leave rather than spin redrawing forever.
        return _ABORT_KEY
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch == b" ":
        return "space"
    if ch in (b"a", b"A"):
        return "all"
    if ch in (b"n", b"N"):
        return "none"
    if ch == b"\x03":  # Ctrl+C — leave with nothing rather than raising
        return _ABORT_KEY
    if ch != b"\x1b":
        return ""
    if _read_after_escape(stream) != b"[":
        return _ABORT_KEY  # plain Esc (nothing followed): skip the step entirely
    return {b"A": "up", b"B": "down"}.get(_read_after_escape(stream), "")


def _render_checkboxes(
    options: list[Path], ticked: list[bool], sel: int, first: bool = False
) -> None:
    """Redraw the list in place, cursor on *sel*, ticks from *ticked*."""
    import sys

    R, B, D, BCY, GR = (
        _app._ANSI_RESET,
        _app._ANSI_BOLD,
        _app._ANSI_DIM,
        _app._ANSI_BRIGHT_CYAN,
        _app._ANSI_GREEN,
    )
    CLEAR, NL = _app._CLEAR_LINE, "\r\n"
    if not first:
        sys.stdout.write(f"\033[{len(options) + 1}A")
    for i, path in enumerate(options):
        box = f"{GR}[x]{R}" if ticked[i] else f"{D}[ ]{R}"
        row = f"{box} {shown(path)}"
        sys.stdout.write(
            f"{CLEAR}  {BCY}❯{R} {B}{row}{R}{NL}" if i == sel else f"{CLEAR}    {row}{NL}"
        )
    sys.stdout.write(
        f"{CLEAR}  {D}↑↓ move  space toggle  a all  n none  Enter confirm  Esc skip{R}{NL}"
    )
    sys.stdout.flush()


def _context_checkbox_picker(options: list[Path], ticked: list[Path] | None = None) -> list[Path]:
    """Tick which files to load read-only, with arrows and space.

    Checkboxes rather than a typed list: the answer is a *set*, and a set is
    chosen by toggling it, not by remembering which numbers you already said.
    Same raw-tty idiom as the file picker above, so both menus feel like one UI.
    Enter confirms what is ticked; Esc leaves with nothing ticked.

    Reading a key, drawing the list and deciding what a key means are three
    separate jobs and live in three functions; this one only owns the loop and
    the terminal mode.

    'n' confirms with nothing ticked immediately, the same outcome as Esc —
    it does not wait for a following Enter the way 'a'/space do. Esc *should*
    reach the same result in one key too, but detecting a bare Esc on a real
    terminal means telling it apart from the start of an arrow-key sequence,
    which needs a short timing window and isn't airtight on every terminal.
    'n' is a plain byte with no such ambiguity — a guaranteed one-key way out
    that does not depend on that detection working.
    """
    import sys
    import termios
    import tty

    remembered = set(ticked or ())
    ticks = [path in remembered for path in options]
    sel = 0

    _render_checkboxes(options, ticks, sel, first=True)
    fd = sys.stdin.fileno()
    old_cfg = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        # Discard bytes left in the OS buffer from a previous raw-tty screen (a
        # stray Esc would otherwise be read as this screen's first keypress) —
        # same guard _run_arrow_menu uses.
        termios.tcflush(fd, termios.TCIFLUSH)
        while True:
            key = _read_checkbox_key(sys.stdin.buffer)
            if key == "enter":
                break
            if key in (_ABORT_KEY, "none"):
                ticks = [False] * len(options)
                break
            move = _CHECKBOX_MOVES.get(key)
            if move:
                ticks, sel = move(ticks, sel)
            _render_checkboxes(options, ticks, sel)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_cfg)
        sys.stdout.write("\r\n")
    return [path for path, on in zip(options, ticks, strict=True) if on]


def context_files_for(
    editable: Path, found: list[Path], project: Project | None = None
) -> list[Path]:
    """Which files to load read-only beside *editable*, asking only when useful.

    One file in the folder means there is nothing to offer, so the question is
    skipped rather than answered "none" — the single-file case, which is most of
    them, keeps exactly the keystrokes it had.

    With a *project*, the files chosen last time for *editable* start ticked
    (Enter accepts them) and the confirmed choice is saved for next time.
    """
    offered = [f for f in found if f != editable]
    if not offered:
        return []
    remembered = project.remembered_context(editable) if project else []
    ticked = [path for path in remembered if path in offered]
    chosen = prompt_for_context_files(editable, found, ticked=ticked)
    if project is not None:
        project.remember_context(editable, chosen)
        _save_quietly(project)
    return chosen


def _save_quietly(project: Project) -> None:
    """Remembering is a convenience: a read-only project folder must not stop ster."""
    try:
        project.save()
    except OSError:
        pass


def prompt_for_context_files(
    editable: Path, found: list[Path], ticked: list[Path] | None = None
) -> list[Path]:
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
    import sys

    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            import termios  # noqa: F401 — availability probe for the raw-tty picker
            import tty  # noqa: F401

            return _context_checkbox_picker(options, ticked=ticked)
        except ImportError:
            pass  # no raw-tty UI here — fall through to the numbered prompt

    for i, f in enumerate(options, 1):
        console.print(f"    [cyan]{i}{_LIT_CYAN_CLOSE}{shown(f)}")
    console.print("  [dim]numbers (1,3) · all · none[/dim]")
    last = ",".join(str(options.index(p) + 1) for p in (ticked or ()) if p in options)
    try:
        answer = ask.text("  Context files", default=last or "none")
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
    choice = ask.text(f"Select (1–{quit_idx})", default=str(demo_idx if not found else 1))
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
        (_constants._HISTORY_SENTINEL, "🕘 Semantic History"),
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
    choice = ask.text(f"Action (1–{len(actions)})", default=str(open_idx + 1))
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
                nxt = _read_after_escape(sys.stdin.buffer)
                if nxt != b"[":
                    break  # bare Esc (nothing followed) → quit
                code = _read_after_escape(sys.stdin.buffer)
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
        want = ask.confirm("Load these files to resolve references?", default=True)
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


def ask_include_subfolders(below: list[Path]) -> bool:
    """Ask whether to offer *below*, the RDF files one level down. No by default."""
    folders = sorted({path.parent.name for path in below})
    names = ", ".join(f"{name}/" for name in folders)
    noun = "subfolder" if len(folders) == 1 else "subfolders"
    console.print(f"\n  Found {len(below)} RDF file(s) in {len(folders)} {noun} ({names}).")
    try:
        return ask.confirm("  Include them?", default=False)
    except (KeyboardInterrupt, EOFError):
        return False
