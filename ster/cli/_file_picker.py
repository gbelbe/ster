"""Session/file resolution and the interactive terminal file picker."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Final

import typer
from rich.prompt import Confirm, Prompt

from ..display import console

_LIT_CYAN: Final = "  [cyan]"


from . import _app, _constants, _rdfxml, _state

# ──────────────────────────── session / file resolution ──────────────────────


def _session_cache_path() -> Path:
    """Return a per-CWD temp file used to persist the selected taxonomy file."""
    cwd_hash = hashlib.md5(str(Path.cwd()).encode(), usedforsecurity=False).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"ster_{cwd_hash}"


def _load_session() -> Path | None:
    p = _session_cache_path()
    if p.exists():
        try:
            data = json.loads(p.read_text())
            f = Path(data["file"])
            if f.exists():
                return f
        except Exception:
            pass
    return None


def _save_session(path: Path) -> None:
    _session_cache_path().write_text(json.dumps({"file": str(path.resolve())}))


def _resolve_file(path: Path | None) -> Path:
    """Return the taxonomy file to operate on.

    Priority:
      1. Explicit --file argument.
      2. In-process session cache (_state.session_file).
      3. Persisted session cache (temp file keyed on CWD).
      4. Auto-discovery: single file → confirm; multiple → interactive picker.
    """

    if not _state.ci_check_done:
        _state.ci_check_done = True
        from ..init_ci import prompt_if_missing
        from ..project import _git_root as _find_git_root

        _root = _find_git_root(Path.cwd())
        if _root and prompt_if_missing(_root):
            console.print(
                "[green]✓[/green] .github/workflows/taxonomy-ci.yml — "
                "commit and push to activate CI\n"
            )

    if path is not None:
        path = _rdfxml._maybe_prompt_rdfxml_convert(path)
        _state.session_file = path
        _save_session(path)
        return path

    if _state.session_file is not None:
        return _state.session_file

    saved = _load_session()
    if saved is not None:
        saved = _rdfxml._maybe_prompt_rdfxml_convert(saved)
        _state.session_file = saved
        _save_session(saved)
        return _state.session_file

    # Discover taxonomy files in CWD
    found: list[Path] = []
    for pattern in _app._TAXONOMY_GLOBS:
        found.extend(Path.cwd().glob(pattern))
    found = sorted(set(found))

    if not found:
        _app.err.print("[red]No taxonomy file found in the current directory.[/red]")
        _app.err.print("[dim]Pass --file <path> or run 'ster init' to create one.[/dim]")
        raise typer.Exit(1)

    if len(found) == 1:
        console.print(f"[dim]Auto-detected:[/dim] [bold]{found[0].name}[/bold]")
        if not Confirm.ask("Use this file for this session?", default=True):
            raise typer.Abort()
        found0 = _rdfxml._maybe_prompt_rdfxml_convert(found[0])
        _save_session(found0)
        _state.session_file = found0
        return _state.session_file

    selected = _pick_file(found)
    selected = _rdfxml._maybe_prompt_rdfxml_convert(selected)
    _save_session(selected)
    _state.session_file = selected
    return _state.session_file


def _pick_file(files: list[Path]) -> Path:
    """Interactive file picker (used by _resolve_file for multiple files)."""
    result = _pick_file_interactive(files)
    if result is None:
        # User chose "create new" from a sub-command context — abort gracefully
        raise typer.Exit(0)
    return result


def _print_file_picker_prompt(
    files: list[Path], preselect: Path | None, create_idx: int, quit_idx: int
) -> None:
    for i, f in enumerate(files, 1):
        marker = (
            " [bold green]←[/bold green] [dim](last session)[/dim]"
            if preselect and f == preselect
            else ""
        )
        console.print(f"{_LIT_CYAN}{i:>2}[/cyan]  {f.name}{marker}")
    console.print(
        f"{_LIT_CYAN}{create_idx:>2}[/cyan]  [bold green]+ Create new taxonomy[/bold green]"
    )
    console.print(f"{_LIT_CYAN}{quit_idx:>2}[/cyan]  [bold red]✕  Quit[/bold red]")
    console.print()


def _resolve_picker_digit_choice(
    choice: str, files: list[Path], create_idx: int, quit_idx: int
) -> Path | None:
    """Resolve a numeric choice, or _constants._PICKER_RETRY (already reported) to loop again."""
    idx = int(choice)
    if idx == quit_idx:
        return _constants._QUIT_SENTINEL
    if idx == create_idx:
        return None
    if 1 <= idx <= len(files):
        return files[idx - 1]
    _app.err.print(f"[red]Enter a number between 1 and {quit_idx}.[/red]")
    return _constants._PICKER_RETRY


def _resolve_picker_name_choice(choice: str, files: list[Path]) -> Path | None:
    """Resolve a typed filename/prefix, or _constants._PICKER_RETRY (already reported) to loop again."""
    matches = [f for f in files if f.name == choice or f.name.startswith(choice)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        _app.err.print(
            f"[yellow]Ambiguous — {[f.name for f in matches]}. Be more specific.[/yellow]"
        )
    else:
        _app.err.print(f"[red]{choice!r} not found.[/red]")
    return _constants._PICKER_RETRY


def _pick_file_prompt_loop(
    files: list[Path],
    initial_sel: int,
    default_num: str | None,
    prompt_text: str,
    create_idx: int,
    quit_idx: int,
) -> Path | None:
    while True:
        try:
            choice = Prompt.ask(prompt_text, default=default_num or "")
        except (KeyboardInterrupt, EOFError):
            raise typer.Exit(0)

        if not choice and default_num:
            return files[initial_sel]

        if choice.isdigit():
            result = _resolve_picker_digit_choice(choice, files, create_idx, quit_idx)
        else:
            result = _resolve_picker_name_choice(choice, files)

        if result is not _constants._PICKER_RETRY:
            return result


def _pick_file_interactive(
    files: list[Path],
    preselect: Path | None = None,
) -> Path | None:
    """Display numbered file list; return chosen Path or None for 'create new'.

    The last entry is always '+ Create new taxonomy'.

    Supports arrow-key navigation in interactive terminals; also accepts typed numbers
    and filename prefixes (original behaviour).
    """
    import sys

    CREATE_IDX = len(files) + 1  # 1-based
    QUIT_IDX = len(files) + 2  # 1-based

    # Flat ordered list of return values matching the numbered items
    item_values: list[Path | None] = list(files)
    item_values.append(None)  # "Create new taxonomy"
    item_values.append(_constants._QUIT_SENTINEL)  # "Quit"

    # Initial arrow selection (0-based index into item_values)
    initial_sel = 0
    if preselect and preselect in files:
        initial_sel = files.index(preselect)

    # ── Arrow-key mode (requires interactive tty + tty/termios) ──────────────
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            import termios as _termios  # noqa: F401 – import tests availability on this platform
            import tty as _tty  # noqa: F401

            return _arrow_file_picker(files, item_values, initial_sel, preselect)
        except ImportError:
            pass  # Windows or restricted environment → fall through

    # ── Fallback: plain Rich Prompt.ask ──────────────────────────────────────
    _print_file_picker_prompt(files, preselect, CREATE_IDX, QUIT_IDX)

    default_num: str | None = str(initial_sel + 1) if (preselect and preselect in files) else None

    if default_num:
        prompt_text = (
            f"Select [bold](number or filename)[/bold]"
            f" [dim](Enter → {files[initial_sel].name})[/dim]"
        )
    else:
        prompt_text = f"Select [bold](1–{QUIT_IDX})[/bold]"

    return _pick_file_prompt_loop(
        files, initial_sel, default_num, prompt_text, CREATE_IDX, QUIT_IDX
    )


def _picker_item_label(
    item_values: list[Path | None], idx: int, selected: bool, preselect: Path | None
) -> str:
    R = _app._ANSI_RESET
    B = _app._ANSI_BOLD
    D = _app._ANSI_DIM
    CY = _app._ANSI_CYAN
    BCY = _app._ANSI_BRIGHT_CYAN
    GR = _app._ANSI_GREEN
    INV = _app._ANSI_INVERSE

    num = idx + 1
    val = item_values[idx]
    num_s = f"{num:>2}"

    if val == _constants._QUIT_SENTINEL:
        plain = "✕  Quit"
        coloured = f"{_app._ANSI_RED}{plain}{R}"
    elif val == _constants._DEMO_SENTINEL:
        plain = "🎒 Load demo ontology / taxonomy"
        coloured = f"{GR}{plain}{R}"
    elif val is None:
        plain = "+ Create new taxonomy"
        coloured = f"{GR}{plain}{R}"
    else:
        last = "  ← last session" if preselect and val == preselect else ""
        plain = f"{val.name}{last}"  # type: ignore[union-attr]
        coloured = f"{val.name}{f'  {D}← last session{R}' if last else ''}"

    if selected:
        # Reverse-video highlight on number + plain text — readable on any theme
        return f"  {BCY}{INV} {num_s} {R}  {B}{plain}{R}"
    return f"    {CY}{num_s}{R}  {coloured}"


def _render_picker(
    item_values: list[Path | None],
    n: int,
    sel: int,
    preselect: Path | None,
    typed: str,
    first: bool = False,
) -> None:
    import sys

    R = _app._ANSI_RESET
    B = _app._ANSI_BOLD
    D = _app._ANSI_DIM
    CLEAR = _app._CLEAR_LINE
    NL = "\r\n"  # explicit CR+LF so raw mode doesn't drift columns

    if not first:
        # cursor-up n+1: n items + 1 hint line, each ended with NL below
        sys.stdout.write(f"\033[{n + 1}A")
    for i in range(n):
        sys.stdout.write(f"{CLEAR}{_picker_item_label(item_values, i, i == sel, preselect)}{NL}")
    if typed:
        sys.stdout.write(f"{CLEAR}  {D}type:{R} {B}{typed}▌{R}  {D}Enter: confirm  Esc: clear{R}")
    else:
        sys.stdout.write(f"{CLEAR}  {D}↑↓ navigate  Enter select  or type a number{R}")
    # Always end with NL so cursor is at a consistent position one line
    # below the hint — makes every cursor-up land at the same start row.
    sys.stdout.write(NL)
    sys.stdout.flush()


def _parse_typed_number(typed: str, sel: int, n: int) -> int:
    """Best-effort parse of the digits typed so far into a 0-indexed selection."""
    try:
        num = int(typed)
    except ValueError:
        return sel
    if 1 <= num <= n:
        return num - 1
    return sel


def _handle_enter_key(typed: str, sel: int, n: int) -> tuple[str, int, bool]:
    if typed:
        sel = _parse_typed_number(typed, sel, n)
    return typed, sel, True


def _handle_arrow_escape(stdin_buffer, typed: str, sel: int, n: int) -> tuple[str, int, bool]:
    code = stdin_buffer.read(1)
    if code == b"A":  # up
        return "", (sel - 1) % n, False
    if code == b"B":  # down
        return "", (sel + 1) % n, False
    return typed, sel, False


def _handle_escape_key(stdin_buffer, typed: str, sel: int, n: int) -> tuple[str, int, bool]:
    nxt = stdin_buffer.read(1)
    if nxt == b"[":
        return _handle_arrow_escape(stdin_buffer, typed, sel, n)
    # plain Esc: clear typed number if any, otherwise keep sel
    if nxt in (b"\r", b"\n"):
        return typed, sel, True
    return "", sel, False


def _handle_digit_key(ch: bytes, typed: str, sel: int, n: int) -> tuple[str, int, bool]:
    typed = typed + ch.decode()
    sel = _parse_typed_number(typed, sel, n)
    return typed, sel, False


def _handle_picker_key(
    ch: bytes, stdin_buffer, typed: str, sel: int, n: int
) -> tuple[str, int, bool]:
    """Process one keypress; returns (new typed, new sel, should_break)."""
    if ch in (b"\r", b"\n"):
        return _handle_enter_key(typed, sel, n)

    if ch == b"\x1b":  # escape / arrow keys
        return _handle_escape_key(stdin_buffer, typed, sel, n)

    if ch in (b"\x7f", b"\x08"):  # backspace
        return typed[:-1], sel, False

    if ch == b"\x03":  # Ctrl+C — outer finally still restores the terminal
        raise KeyboardInterrupt

    if ch.isdigit():
        return _handle_digit_key(ch, typed, sel, n)

    return typed, sel, False


def _arrow_file_picker(
    _files: list[Path],
    item_values: list[Path | None],
    initial_sel: int,
    preselect: Path | None,
) -> Path | None:
    """Arrow-key file picker using raw terminal I/O + ANSI codes.

    Redraws the list in place as the user navigates.  Digits accumulate into a
    number that auto-moves the selection; Enter confirms.
    """
    import sys
    import termios
    import tty

    NL = "\r\n"  # explicit CR+LF so raw mode doesn't drift columns

    n = len(item_values)
    sel = initial_sel

    _render_picker(item_values, n, sel, preselect, typed="", first=True)
    # cursor is already below the hint (render wrote NL); no extra write needed

    typed = ""
    fd = sys.stdin.fileno()
    old_cfg = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.buffer.read(1)
            typed, sel, should_break = _handle_picker_key(ch, sys.stdin.buffer, typed, sel, n)
            if should_break:
                break
            _render_picker(item_values, n, sel, preselect, typed)

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_cfg)
        sys.stdout.write(NL)
        sys.stdout.flush()

    return item_values[sel]
