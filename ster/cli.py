"""Typer CLI — load, operate, save pattern for every mutating command."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from . import operations, store
from .display import console, render_handle_list, render_tree
from .exceptions import SkostaxError
from .model import LabelType, Taxonomy
from .project import Project, _git_root
from .workspace import TaxonomyWorkspace

app = typer.Typer(
    name="ster",
    help="Terminal editor and site generator for SKOS taxonomies and OWL ontologies.",
    no_args_is_help=False,
    invoke_without_command=True,
)
err = Console(stderr=True)


@app.callback(invoke_without_command=True)
def _app_callback(ctx: typer.Context) -> None:
    """Suppress Typer's default no-args behaviour; main() handles it."""
    pass


_VERSION = "0.3.1"
_AUTHOR = "ster contributors"

_PYPI_URL = "https://pypi.org/pypi/ster/json"
_GH_RELEASE_URL = "https://api.github.com/repos/gbelbe/ster/releases/tags/v{version}"
_VERSION_CACHE = Path(tempfile.gettempdir()) / "ster_version_check.json"


def _newer(a: str, b: str) -> bool:
    """Return True if version string *a* is greater than *b*."""

    def _t(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)

    return _t(a) > _t(b)


def _trim_release_notes(body: str, max_bullets: int = 5) -> str:
    """Extract up to *max_bullets* bullet lines from a markdown release-notes body."""
    bullets: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        # Accept lines starting with common markdown bullet markers
        if stripped.startswith(("- ", "* ", "+ ", "• ")):
            # Strip the marker and any bold/backtick markdown for clean terminal display
            text = stripped[2:].strip()
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # **bold**
            text = re.sub(r"`(.+?)`", r"\1", text)  # `code`
            bullets.append(text)
    trimmed = bullets[:max_bullets]
    if len(bullets) > max_bullets:
        trimmed.append(f"… and {len(bullets) - max_bullets} more")
    return "\n".join(f"  [dim]·[/dim] {b}" for b in trimmed)


def _check_new_version() -> tuple[str, str] | None:
    """Return (latest_version, release_notes_summary) if newer than installed, else None.

    Result is cached for 24 hours.  The network fetch (PyPI + GitHub releases)
    always runs in a background daemon thread — this function never blocks.
    """
    now = datetime.now()
    cached_latest: str | None = None
    cached_notes: str = ""

    if _VERSION_CACHE.exists():
        try:
            data = json.loads(_VERSION_CACHE.read_text())
            checked = datetime.fromisoformat(data["checked"])
            if now - checked < timedelta(hours=24):
                cached_latest = data.get("latest")
                cached_notes = data.get("notes", "")
        except Exception:
            pass

    def _fetch() -> None:
        try:
            with urllib.request.urlopen(_PYPI_URL, timeout=3) as resp:  # noqa: S310
                latest = json.loads(resp.read())["info"]["version"]

            notes = ""
            gh_url = _GH_RELEASE_URL.format(version=latest)
            try:
                req = urllib.request.Request(
                    gh_url,
                    headers={"Accept": "application/vnd.github+json", "User-Agent": "ster-cli"},
                )
                with urllib.request.urlopen(req, timeout=3) as gh_resp:  # noqa: S310
                    notes = json.loads(gh_resp.read()).get("body", "")
            except Exception:
                pass

            _VERSION_CACHE.write_text(
                json.dumps({"checked": now.isoformat(), "latest": latest, "notes": notes})
            )
        except Exception:
            pass

    threading.Thread(target=_fetch, daemon=True).start()

    if cached_latest and _newer(cached_latest, _VERSION):
        return cached_latest, cached_notes
    return None


def _print_welcome() -> None:
    from rich.panel import Panel

    update_info = _check_new_version()
    if update_info:
        new_ver, notes = update_info
        notes_block = f"\n{_trim_release_notes(notes)}" if notes.strip() else ""
        update_section = (
            f"\n[yellow]↑ v{new_ver} available[/yellow]  "
            f"[dim]pip install --upgrade ster[/dim]{notes_block}"
        )
    else:
        update_section = ""

    console.print()
    console.print(
        Panel(
            f"[bold cyan]ster[/bold cyan]  [dim]v{_VERSION}[/dim]{update_section}\n\n"
            "[dim]Semantic knowledge editor — SKOS · OWL · D3 · Site generator[/dim]\n\n"
            "[dim]Select a file to open, or use the menu to generate a site or graph.[/dim]\n"
            "[dim]Press [bold]Ctrl+C[/bold] at the menu to exit.[/dim]",
            border_style="cyan",
            padding=(1, 4),
        )
    )


# Commands that must NOT be mistaken for a file path
_SUBCOMMANDS = frozenset(
    {
        "show",
        "add",
        "remove",
        "move",
        "label",
        "define",
        "relate",
        "rename",
        "init",
        "handles",
        "validate",
        "nav",
        "log",
    }
)

_TAXONOMY_SUFFIXES = {".ttl", ".rdf", ".jsonld", ".owl", ".n3"}
_TAXONOMY_GLOBS = ("*.ttl", "*.rdf", "*.jsonld", "*.owl", "*.n3")

# Sentinels returned by _pick_file_interactive for special menu entries
_GIT_LOG_SENTINEL: Path = Path(".__ster_log__")
_HTML_SENTINEL: Path = Path(".__ster_html__")
_SITE_SENTINEL: Path = Path(".__ster_site__")
_GRAPH_SENTINEL: Path = Path(".__ster_graph__")
_AI_CONFIG_SENTINEL: Path = Path(".__ster_ai_config__")
_QUERY_SENTINEL: Path = Path(".__ster_query__")
_QUIT_SENTINEL: Path = Path(".__ster_quit__")

_session_file: Path | None = None  # in-process cache


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
      2. In-process session cache (_session_file).
      3. Persisted session cache (temp file keyed on CWD).
      4. Auto-discovery: single file → confirm; multiple → interactive picker.
    """
    global _session_file

    if path is not None:
        _session_file = path
        _save_session(path)
        return path

    if _session_file is not None:
        return _session_file

    saved = _load_session()
    if saved is not None:
        _session_file = saved
        return _session_file

    # Discover taxonomy files in CWD
    found: list[Path] = []
    for pattern in _TAXONOMY_GLOBS:
        found.extend(Path.cwd().glob(pattern))
    found = sorted(set(found))

    if not found:
        err.print("[red]No taxonomy file found in the current directory.[/red]")
        err.print("[dim]Pass --file <path> or run 'ster init' to create one.[/dim]")
        raise typer.Exit(1)

    if len(found) == 1:
        console.print(f"[dim]Auto-detected:[/dim] [bold]{found[0].name}[/bold]")
        if not Confirm.ask("Use this file for this session?", default=True):
            raise typer.Abort()
        _save_session(found[0])
        _session_file = found[0]
        return _session_file

    selected = _pick_file(found)
    _save_session(selected)
    _session_file = selected
    return _session_file


def _pick_file(files: list[Path]) -> Path:
    """Interactive file picker (used by _resolve_file for multiple files)."""
    result = _pick_file_interactive(files)
    if result is None:
        # User chose "create new" from a sub-command context — abort gracefully
        raise typer.Exit(0)
    return result


def _pick_file_interactive(
    files: list[Path],
    preselect: Path | None = None,
    show_log_option: bool = False,
) -> Path | None:
    """Display numbered file list; return chosen Path or None for 'create new'.

    The last entry is always '+ Create new taxonomy'.
    If *show_log_option* is True, a 'Browse git history' entry is shown just before it,
    and selecting it returns _GIT_LOG_SENTINEL.

    Supports arrow-key navigation in interactive terminals; also accepts typed numbers
    and filename prefixes (original behaviour).
    """
    import sys

    LOG_IDX = len(files) + 1 if show_log_option else None  # 1-based
    CREATE_IDX = len(files) + (2 if show_log_option else 1)  # 1-based
    QUIT_IDX = len(files) + (3 if show_log_option else 2)  # 1-based

    # Flat ordered list of return values matching the numbered items
    item_values: list[Path | None] = list(files)
    if show_log_option:
        item_values.append(_GIT_LOG_SENTINEL)
    item_values.append(None)  # "Create new taxonomy"
    item_values.append(_QUIT_SENTINEL)  # "Quit"

    # Initial arrow selection (0-based index into item_values)
    initial_sel = 0
    if preselect and preselect in files:
        initial_sel = files.index(preselect)

    # ── Arrow-key mode (requires interactive tty + tty/termios) ──────────────
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            import termios as _termios  # noqa: F401 – import tests availability on this platform
            import tty as _tty  # noqa: F401

            return _arrow_file_picker(
                files,
                item_values,
                initial_sel,
                preselect,
                show_log_option,
                LOG_IDX,
                CREATE_IDX,
            )
        except ImportError:
            pass  # Windows or restricted environment → fall through

    # ── Fallback: plain Rich Prompt.ask ──────────────────────────────────────
    for i, f in enumerate(files, 1):
        marker = (
            " [bold green]←[/bold green] [dim](last session)[/dim]"
            if preselect and f == preselect
            else ""
        )
        console.print(f"  [cyan]{i:>2}[/cyan]  {f.name}{marker}")
    if show_log_option:
        console.print(
            f"  [cyan]{LOG_IDX:>2}[/cyan]  [bold magenta]⎇  Browse git history[/bold magenta]"
        )
    console.print(f"  [cyan]{CREATE_IDX:>2}[/cyan]  [bold green]+ Create new taxonomy[/bold green]")
    console.print(f"  [cyan]{QUIT_IDX:>2}[/cyan]  [bold red]✕  Quit[/bold red]")
    console.print()

    default_num: str | None = str(initial_sel + 1) if (preselect and preselect in files) else None

    if default_num:
        prompt_text = (
            f"Select [bold](number or filename)[/bold]"
            f" [dim](Enter → {files[initial_sel].name})[/dim]"
        )
    else:
        prompt_text = f"Select [bold](1–{QUIT_IDX})[/bold]"

    while True:
        try:
            choice = Prompt.ask(prompt_text, default=default_num or "")
        except (KeyboardInterrupt, EOFError):
            raise typer.Exit(0)

        if not choice and default_num:
            return files[initial_sel]

        if choice.isdigit():
            idx = int(choice)
            if idx == QUIT_IDX:
                return _QUIT_SENTINEL
            if idx == CREATE_IDX:
                return None
            if show_log_option and idx == LOG_IDX:
                return _GIT_LOG_SENTINEL
            if 1 <= idx <= len(files):
                return files[idx - 1]
            err.print(f"[red]Enter a number between 1 and {QUIT_IDX}.[/red]")
            continue

        matches = [f for f in files if f.name == choice or f.name.startswith(choice)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            err.print(
                f"[yellow]Ambiguous — {[f.name for f in matches]}. Be more specific.[/yellow]"
            )
        else:
            err.print(f"[red]{choice!r} not found.[/red]")


def _arrow_file_picker(
    files: list[Path],
    item_values: list[Path | None],
    initial_sel: int,
    preselect: Path | None,
    show_log_option: bool,
    log_idx: int | None,
    create_idx: int,
) -> Path | None:
    """Arrow-key file picker using raw terminal I/O + ANSI codes.

    Redraws the list in place as the user navigates.  Digits accumulate into a
    number that auto-moves the selection; Enter confirms.
    """
    import sys
    import termios
    import tty

    R = "\033[0m"  # reset all
    B = "\033[1m"  # bold
    D = "\033[2m"  # dim
    CY = "\033[36m"  # cyan
    BCY = "\033[1;36m"  # bold cyan
    GR = "\033[32m"  # green
    MG = "\033[35m"  # magenta
    INV = "\033[7m"  # reverse video (readable on any background)

    # \r\033[2K: go to column 0 then erase entire line — works in both cooked
    # and raw terminal modes (raw mode does NOT auto-add CR before LF).
    CLEAR = "\r\033[2K"
    NL = "\r\n"  # explicit CR+LF so raw mode doesn't drift columns

    n = len(item_values)
    sel = initial_sel

    def _label(idx: int, selected: bool) -> str:
        num = idx + 1
        val = item_values[idx]
        num_s = f"{num:>2}"

        if val == _QUIT_SENTINEL:
            plain = "✕  Quit"
            coloured = f"\033[31m{plain}{R}"  # red
        elif val is None:
            plain = "+ Create new taxonomy"
            coloured = f"{GR}{plain}{R}"
        elif val == _GIT_LOG_SENTINEL:
            plain = "⎇  Browse git history"
            coloured = f"{MG}{plain}{R}"
        else:
            last = "  ← last session" if preselect and val == preselect else ""
            plain = f"{val.name}{last}"  # type: ignore[union-attr]
            coloured = f"{val.name}{f'  {D}← last session{R}' if last else ''}"

        if selected:
            # Reverse-video highlight on number + plain text — readable on any theme
            return f"  {BCY}{INV} {num_s} {R}  {B}{plain}{R}"
        return f"    {CY}{num_s}{R}  {coloured}"

    def render(typed: str, first: bool = False) -> None:
        if not first:
            # cursor-up n+1: n items + 1 hint line, each ended with NL below
            sys.stdout.write(f"\033[{n + 1}A")
        for i in range(n):
            sys.stdout.write(f"{CLEAR}{_label(i, i == sel)}{NL}")
        if typed:
            sys.stdout.write(
                f"{CLEAR}  {D}type:{R} {B}{typed}▌{R}  {D}Enter: confirm  Esc: clear{R}"
            )
        else:
            sys.stdout.write(f"{CLEAR}  {D}↑↓ navigate  Enter select  or type a number{R}")
        # Always end with NL so cursor is at a consistent position one line
        # below the hint — makes every cursor-up land at the same start row.
        sys.stdout.write(NL)
        sys.stdout.flush()

    render(typed="", first=True)
    # cursor is already below the hint (render() wrote NL); no extra write needed

    typed = ""
    fd = sys.stdin.fileno()
    old_cfg = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.buffer.read(1)

            if ch in (b"\r", b"\n"):
                if typed:
                    try:
                        num = int(typed)
                        if 1 <= num <= n:
                            sel = num - 1
                    except ValueError:
                        pass
                break

            elif ch == b"\x1b":  # escape / arrow keys
                nxt = sys.stdin.buffer.read(1)
                if nxt == b"[":
                    code = sys.stdin.buffer.read(1)
                    if code == b"A":  # up
                        typed = ""
                        sel = (sel - 1) % n
                    elif code == b"B":  # down
                        typed = ""
                        sel = (sel + 1) % n
                # plain Esc: clear typed number if any, otherwise keep sel
                elif nxt in (b"\r", b"\n"):
                    break
                else:
                    typed = ""

            elif ch in (b"\x7f", b"\x08"):  # backspace
                typed = typed[:-1]

            elif ch == b"\x03":  # Ctrl+C
                termios.tcsetattr(fd, termios.TCSADRAIN, old_cfg)
                raise KeyboardInterrupt

            elif ch.isdigit():
                typed += ch.decode()
                try:
                    num = int(typed)
                    if 1 <= num <= n:
                        sel = num - 1
                except ValueError:
                    pass

            render(typed)

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_cfg)
        sys.stdout.write(NL)
        sys.stdout.flush()

    return item_values[sel]


# ──────────────────────────── helpers ────────────────────────────────────────


def _load(path: Path) -> Taxonomy:
    try:
        return store.load(path)
    except Exception as exc:
        err.print(f"[red]Cannot load {path}: {exc}[/red]")
        raise typer.Exit(1)


def _save(taxonomy: Taxonomy, path: Path) -> None:
    try:
        store.save(taxonomy, path)
        console.print(f"[green]✓ Saved[/green] {path}")
    except Exception as exc:
        err.print(f"[red]Cannot save {path}: {exc}[/red]")
        raise typer.Exit(1)


def _resolve(taxonomy: Taxonomy, ref: str) -> str:
    try:
        return operations.resolve(taxonomy, ref)
    except SkostaxError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


def _run(fn, *args, **kwargs):
    """Call an operations function, converting SkostaxError to a clean exit."""
    try:
        return fn(*args, **kwargs)
    except SkostaxError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


# ──────────────────────────── multi-file / workspace helpers ─────────────────


def _multi_file_picker(
    found: list[Path],
) -> list[Path] | Path | None:
    """File list display + action menu picker.

    Shows all taxonomy files with ✓ checkmarks (read-only display).
    The navigable cursor is placed directly on the action menu items.

    Returns:
      list[Path]         — all found files (user chose Open Tree View)
      _GIT_LOG_SENTINEL  — user chose Browse git history
      _HTML_SENTINEL     — user chose Generate webpage
      _QUIT_SENTINEL     — user chose Quit
    Ctrl+C / plain Esc also returns _QUIT_SENTINEL.
    Falls back to a plain prompt in non-interactive terminals.
    """
    import sys

    if not found:
        return []

    # Action items — cursor lives here only
    _ACTIONS: list[tuple[object, str]] = [
        (True, "↵  Open Tree View"),  # True = "open" sentinel
        (_GIT_LOG_SENTINEL, "⎇  Browse git history"),
        (_HTML_SENTINEL, "🌐 Generate Web-Documentation"),
        (_SITE_SENTINEL, "🔗 Generate Browsable Website"),
        (_GRAPH_SENTINEL, "⬡  Open Graph Viz"),
        (_AI_CONFIG_SENTINEL, "⚙  Configure AI"),
        (_QUERY_SENTINEL, "🔍 Query taxonomy (SPARQL)"),
        (_QUIT_SENTINEL, "✕  Quit"),
    ]
    n_files = len(found)
    n_actions = len(_ACTIONS)

    # ── Non-TTY fallback ──────────────────────────────────────────────────────
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        for f in found:
            console.print(f"  ✓  {f.name}")
        console.print("  [cyan] 1[/cyan]  ↵  Open Tree View")
        console.print("  [cyan] 2[/cyan]  [magenta]⎇  Browse git history[/magenta]")
        console.print("  [cyan] 3[/cyan]  [blue]🌐 Generate Web-Documentation[/blue]")
        console.print("  [cyan] 4[/cyan]  [green]🔗 Generate Browsable Website[/green]")
        console.print("  [cyan] 5[/cyan]  [yellow]⬡  Open Graph Viz[/yellow]")
        console.print("  [cyan] 6[/cyan]  [cyan]⚙  Configure AI[/cyan]")
        console.print("  [cyan] 7[/cyan]  [green]🔍 Query taxonomy (SPARQL)[/green]")
        console.print("  [cyan] 8[/cyan]  [red]✕  Quit[/red]")
        console.print()
        choice = Prompt.ask("Action (1–8)", default="1")
        s = choice.strip().lower()
        if s == "1" or s == "all":
            return list(found)
        if s == "2":
            return _GIT_LOG_SENTINEL  # type: ignore[return-value]
        if s == "3":
            return _HTML_SENTINEL  # type: ignore[return-value]
        if s == "4":
            return _SITE_SENTINEL  # type: ignore[return-value]
        if s == "5":
            return _GRAPH_SENTINEL  # type: ignore[return-value]
        if s == "6":
            return _AI_CONFIG_SENTINEL  # type: ignore[return-value]
        if s == "7":
            return _QUERY_SENTINEL  # type: ignore[return-value]
        if s == "8":
            return _QUIT_SENTINEL  # type: ignore[return-value]
        return list(found)

    try:
        import termios
        import tty
    except ImportError:
        return list(found)

    R = "\033[0m"
    B = "\033[1m"
    D = "\033[2m"
    CY = "\033[36m"
    GR = "\033[32m"
    MG = "\033[35m"
    RE = "\033[31m"
    INV = "\033[7m"
    BCY = "\033[1;36m"
    CLEAR = "\r\033[2K"
    NL = "\r\n"

    # Cursor operates only on action items (0-based index into _ACTIONS)
    action_cursor = 0

    def _action_colour(sentinel: object) -> str:
        if sentinel == _GIT_LOG_SENTINEL:
            return MG
        if sentinel == _HTML_SENTINEL:
            return "\033[34m"  # blue
        if sentinel == _SITE_SENTINEL:
            return GR  # green
        if sentinel == _GRAPH_SENTINEL:
            return "\033[33m"  # yellow
        if sentinel == _QUIT_SENTINEL:
            return RE
        if sentinel == _AI_CONFIG_SENTINEL:
            return CY
        if sentinel == _QUERY_SENTINEL:
            return GR  # green
        return CY  # "open tree view"

    def render(first: bool = False) -> None:
        total_lines = n_files + 1 + n_actions + 1  # files + blank sep + actions + hint
        if not first:
            sys.stdout.write(f"\033[{total_lines}A")

        # File rows — static display with ✓, no cursor
        for f in found:
            row = f"       {GR}✓{R}  {f.name}"
            sys.stdout.write(f"{CLEAR}{row}{NL}")

        # Blank separator line
        sys.stdout.write(f"{CLEAR}{NL}")

        # Action rows — cursor navigates here
        for j, (sentinel, label) in enumerate(_ACTIONS):
            col = _action_colour(sentinel)
            num_s = f"{j + 1:>2}"
            if j == action_cursor:
                row = f"  {BCY}{INV} {num_s} {R}  {col}{B}{label}{R}"
            else:
                row = f"    {CY}{num_s}{R}  {col}{label}{R}"
            sys.stdout.write(f"{CLEAR}{row}{NL}")

        # Hint line
        sys.stdout.write(f"{CLEAR}  {D}↑↓ navigate  Enter: select{R}{NL}")
        sys.stdout.flush()

    render(first=True)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    result: list[Path] | Path | None = _QUIT_SENTINEL

    try:
        tty.setraw(fd)
        # Discard any bytes left in the OS input buffer from a previous curses
        # session (e.g. a second Escape pressed quickly while quitting the tree
        # view). Without this flush the stray \x1b is read here and interpreted
        # as Quit, causing the picker to exit immediately.
        termios.tcflush(fd, termios.TCIFLUSH)
        while True:
            ch = sys.stdin.buffer.read(1)

            if ch in (b"\r", b"\n"):
                sentinel, _ = _ACTIONS[action_cursor]
                if sentinel is True:
                    result = list(found)
                else:
                    result = sentinel  # type: ignore[assignment]
                break

            elif ch in (b"q", b"Q", b"\x03"):
                result = _QUIT_SENTINEL
                break

            elif ch == b"\x1b":
                nxt = sys.stdin.buffer.read(1)
                if nxt == b"[":
                    code = sys.stdin.buffer.read(1)
                    if code == b"A":
                        action_cursor = (action_cursor - 1) % n_actions
                    elif code == b"B":
                        action_cursor = (action_cursor + 1) % n_actions
                else:
                    result = _QUIT_SENTINEL
                    break

            render()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write(NL)
        sys.stdout.flush()

    return result


def _resolve_broken_mappings_at_load(
    workspace: TaxonomyWorkspace,
    found_files: list[Path],
) -> None:
    """Before opening the TUI, ask user to load any files referenced by mappings."""
    from .validator import SkosValidator

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


# ──────────────────────────── AI config launcher ─────────────────────────────


def _launch_ai_config(found: list[Path]) -> None:
    """Open the TUI with the AI model configuration wizard pre-triggered."""
    from .nav import TaxonomyViewer
    from .workspace import TaxonomyWorkspace

    if found:
        try:
            workspace = TaxonomyWorkspace.from_files([found[0]])
            primary = found[0]
        except Exception:
            workspace = TaxonomyWorkspace.from_files([])
            primary = found[0]
    else:
        primary = Path.cwd() / "taxonomy.ttl"
        workspace = TaxonomyWorkspace.from_files([])

    from .model import Taxonomy

    if found and found[0] in workspace.taxonomies:
        taxonomy = workspace.taxonomies[found[0]]
    else:
        taxonomy = Taxonomy()

    from .git_manager import GitManager

    gm = GitManager(primary)

    viewer = TaxonomyViewer(
        taxonomy,
        primary,
        workspace=workspace,
        git_manager=gm,
    )
    viewer._trigger_action("open_ai_config")
    viewer.run()


# ──────────────────────────── SPARQL query launcher ─────────────────────────


def _launch_query(found: list[Path]) -> None:
    """Open the TUI in SPARQL query mode for the given files."""
    from .git_manager import GitManager
    from .nav import TaxonomyViewer
    from .workspace import TaxonomyWorkspace

    if not found:
        err.print("[red]No taxonomy files to query.[/red]")
        return

    try:
        workspace = TaxonomyWorkspace.from_files(found)
    except Exception as exc:
        err.print(f"[red]Failed to load files: {exc}[/red]")
        return

    primary = found[0]
    if primary in workspace.taxonomies:
        taxonomy = workspace.taxonomies[primary]
    else:
        from .model import Taxonomy

        taxonomy = Taxonomy()

    gm = GitManager(primary)
    viewer = TaxonomyViewer(taxonomy, primary, workspace=workspace, git_manager=gm)
    viewer._trigger_action("open_query")
    viewer.run()


# ──────────────────────────── viewer helper ──────────────────────────────────


def _open_viewer(
    taxonomy_file: Path,
    lang: str = "en",
    jump_concept: str | None = None,
    workspace: TaxonomyWorkspace | None = None,
) -> None:
    """Open the interactive taxonomy viewer for *taxonomy_file* and handle git."""
    from .git_manager import GitManager, render_diff
    from .nav import TaxonomyViewer

    taxonomy = _load(taxonomy_file)

    gm = GitManager(taxonomy_file)
    if gm.is_enabled():
        if not gm.is_configured():
            gm.setup()
        if gm.is_configured():
            diff = gm.pre_edit_check()
            if diff:
                console.print("\n[bold]Changes pulled from remote:[/bold]")
                render_diff(diff)
                console.print()
            gm.record_head()

    viewer = TaxonomyViewer(
        taxonomy,
        taxonomy_file,
        lang=lang,
        git_manager=gm,
        workspace=workspace,
    )

    # Auto-open graph viz for OWL ontologies (no SKOS schemes)
    if taxonomy.owl_classes and not taxonomy.schemes:
        from . import viz as _viz

        try:
            _viz.open_in_browser(taxonomy, taxonomy_file)
        except Exception:
            pass

    if jump_concept:
        uri = _resolve(taxonomy, jump_concept)
        for i, line in enumerate(viewer._flat):
            if line.uri == uri:
                viewer._cursor = i
                break
    viewer.run()

    if gm.is_enabled() and gm.is_configured():
        gm.commit_and_push()
    elif gm.is_enabled() and not gm.is_configured():
        try:
            want_git = Confirm.ask("\nAdd taxonomy to git repository?", default=False)
        except (KeyboardInterrupt, EOFError):
            want_git = False
        if want_git:
            gm.setup()
            if gm.is_configured():
                msg = _make_taxonomy_commit_msg(taxonomy, taxonomy_file)
                gm.commit_new_taxonomy(msg)


# ──────────────────────────── show ───────────────────────────────────────────


@app.command("show")
def cmd_show(
    file: Path | None = typer.Argument(
        None, help="Taxonomy file (.ttl / .rdf / .jsonld). Auto-detected if omitted."
    ),
    concept: str | None = typer.Option(
        None,
        "--concept",
        "-c",
        metavar="HANDLE",
        help="Open interactive viewer at this concept.",
    ),
    lang: str = typer.Option("en", "--lang", "-l", help="Label language."),
    handles: bool = typer.Option(
        False, "--handles", "-H", help="Print handle index table then exit."
    ),
    plain: bool = typer.Option(
        False,
        "--plain",
        "-p",
        help="Print static tree and exit (no interactive viewer).",
    ),
) -> None:
    """Open the interactive taxonomy viewer.

    Navigate with ↑↓, open detail with → or Enter, go back with ←,
    edit fields with i, delete with d, quit with Esc or q.

    Pass --plain to print the tree non-interactively and exit.
    """
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)

    if handles:
        console.print(render_handle_list(taxonomy, lang))
        return

    if plain:
        if concept:
            console.print(render_tree(taxonomy, root_handle=concept, lang=lang))
        else:
            console.print(render_tree(taxonomy, lang=lang))
        return

    _open_viewer(taxonomy_file, lang=lang, jump_concept=concept)


# ──────────────────────────── add ────────────────────────────────────────────


@app.command("add")
def cmd_add(
    name: str = typer.Argument(
        ...,
        help="Local name or full URI for the new concept. "
        "A local name (e.g. 'SpadeRudder') is automatically expanded "
        "with the taxonomy's base URI.",
    ),
    parent: str | None = typer.Option(
        None,
        "--parent",
        "-p",
        metavar="HANDLE|NAME",
        help="Parent concept handle or name (omit for primary scheme top level).",
    ),
    en: str | None = typer.Option(None, "--en", help="English preferred label."),
    fr: str | None = typer.Option(None, "--fr", help="French preferred label."),
    def_en: str | None = typer.Option(None, "--def-en", help="English definition."),
    def_fr: str | None = typer.Option(None, "--def-fr", help="French definition."),
    lang: str = typer.Option("en", "--lang", "-l", help="Display language for confirmation."),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Add a new concept to the taxonomy.

    The concept name is expanded to a full URI using the taxonomy's base URI.
    You can also pass a full URI directly.
    """
    labels: dict[str, str] = {}
    if en:
        labels["en"] = en
    if fr:
        labels["fr"] = fr
    if not labels:
        labels[lang] = _humanize(name)
        console.print(f"[dim]No label provided — using default: {labels[lang]!r}[/dim]")

    definitions: dict[str, str] = {}
    if def_en:
        definitions["en"] = def_en
    if def_fr:
        definitions["fr"] = def_fr

    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri = _run(operations.expand_uri, taxonomy, name)
    concept = _run(operations.add_concept, taxonomy, uri, labels, parent, definitions or None)
    console.print(
        f"[green]Added[/green]  [{taxonomy.uri_to_handle(uri)}]  {concept.pref_label(lang)}  [dim]({uri})[/dim]"
    )
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── remove ─────────────────────────────────────────


@app.command("remove")
def cmd_remove(
    concept: str = typer.Argument(..., metavar="HANDLE", help="Concept handle or URI."),
    cascade: bool = typer.Option(False, "--cascade", help="Also remove all descendants."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    lang: str = typer.Option("en", "--lang", "-l"),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Remove a concept from the taxonomy."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri = _resolve(taxonomy, concept)
    c = taxonomy.concepts[uri]

    if not yes:
        msg = f"Remove [bold]{c.pref_label(lang)}[/bold]"
        n_children = len(c.narrower)
        if cascade and n_children:
            msg += f" and its {n_children} child(ren)"
        if not Confirm.ask(msg + "?"):
            raise typer.Abort()

    removed = _run(operations.remove_concept, taxonomy, uri, cascade=cascade)
    console.print(f"[green]Removed[/green] {len(removed)} concept(s).")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── move ───────────────────────────────────────────


@app.command("move")
def cmd_move(
    concept: str = typer.Argument(..., metavar="HANDLE", help="Concept to move."),
    parent: str | None = typer.Option(
        None,
        "--parent",
        "-p",
        metavar="HANDLE",
        help="New parent handle (omit to promote to top level).",
    ),
    lang: str = typer.Option("en", "--lang", "-l"),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Move a concept to a new parent."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri = _resolve(taxonomy, concept)
    parent_uri = _resolve(taxonomy, parent) if parent else None

    _run(operations.move_concept, taxonomy, uri, parent_uri)

    dest = (
        taxonomy.concepts[parent_uri].pref_label(lang)
        if parent_uri and parent_uri in taxonomy.concepts
        else "top level"
    )
    console.print(f"[green]Moved[/green]  {taxonomy.concepts[uri].pref_label(lang)}  →  {dest}")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── label ──────────────────────────────────────────


@app.command("label")
def cmd_label(
    concept: str = typer.Argument(..., metavar="HANDLE"),
    lang: str = typer.Argument(..., help="Language code (en, fr, …)"),
    text: str = typer.Argument(..., help="Label text"),
    alt: bool = typer.Option(False, "--alt", help="Add as alt label (default: pref label)."),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Set a preferred or alternative label on a concept."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri = _resolve(taxonomy, concept)
    label_type = LabelType.ALT if alt else LabelType.PREF
    _run(operations.set_label, taxonomy, uri, lang, text, label_type)
    kind = "alt label" if alt else "pref label"
    console.print(f"[green]Set {kind}[/green]  [{lang}]  {text}")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── define ─────────────────────────────────────────


@app.command("define")
def cmd_define(
    concept: str = typer.Argument(..., metavar="HANDLE"),
    lang: str = typer.Argument(..., help="Language code"),
    text: str = typer.Argument(..., help="Definition text"),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Set a definition on a concept."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri = _resolve(taxonomy, concept)
    _run(operations.set_definition, taxonomy, uri, lang, text)
    console.print(f"[green]Set definition[/green]  [{lang}]")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── relate ─────────────────────────────────────────


@app.command("relate")
def cmd_relate(
    concept_a: str = typer.Argument(..., metavar="HANDLE_A"),
    concept_b: str = typer.Argument(..., metavar="HANDLE_B"),
    remove: bool = typer.Option(False, "--remove", help="Remove instead of adding."),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Add or remove a skos:related link between two concepts."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri_a = _resolve(taxonomy, concept_a)
    uri_b = _resolve(taxonomy, concept_b)

    if remove:
        _run(operations.remove_related, taxonomy, uri_a, uri_b)
        console.print("[green]Removed[/green] related link.")
    else:
        _run(operations.add_related, taxonomy, uri_a, uri_b)
        console.print("[green]Added[/green] related link.")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── rename ─────────────────────────────────────────


@app.command("rename")
def cmd_rename(
    concept: str = typer.Argument(
        ..., metavar="HANDLE|NAME", help="Handle or name of concept to rename."
    ),
    new_name: str = typer.Argument(..., help="New local name or full URI."),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Change the URI of a concept (updates all cross-references).

    The new name is expanded to a full URI using the taxonomy's base URI.
    You can also pass a full URI directly.
    """
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    old_uri = _resolve(taxonomy, concept)
    new_uri = _run(operations.expand_uri, taxonomy, new_name)
    _run(operations.rename_uri, taxonomy, old_uri, new_uri)
    console.print(f"[green]Renamed[/green]  {old_uri}  →  {new_uri}")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── log (git history browser) ─────────────────────


@app.command("log")
def cmd_log(
    file: Path | None = typer.Argument(
        None, help="Taxonomy file to scope the diff view. Auto-detected if omitted."
    ),
    repo: Path | None = typer.Option(
        None, "--repo", "-r", help="Git repository root. Detected from file path if omitted."
    ),
) -> None:
    """Browse git commit history in an interactive split-pane viewer.

    Left pane: commit graph with hash, author, and subject.
    Right pane: diff for the selected commit.

    Keys: ↑↓/jk navigate  Tab/d focus diff  r revert  o restore file  ? help  q quit
    """
    from .git_log import launch_git_log

    # Auto-detect file if not given
    if file is None:
        found: list[Path] = []
        for pattern in _TAXONOMY_GLOBS:
            found.extend(Path.cwd().glob(pattern))
        found = sorted(set(found))
        saved = _load_session()
        if saved and saved in found:
            file = saved
        elif len(found) == 1:
            file = found[0]

    launch_git_log(path=file, repo=repo)


# ──────────────────────────── ai config ──────────────────────────────────────


# ──────────────────────────── nav (bash-like REPL) ───────────────────────────


@app.command("nav")
def cmd_nav(
    lang: str = typer.Option("en", "--lang", "-l", help="Display language."),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Start a bash-like REPL for taxonomy navigation and editing.

    Commands: ls  cd  pwd  show  info  add  mv  rm  label  define  quit\n

    For the full-screen interactive viewer use: ster show
    """
    from .nav import TaxonomyShell

    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)

    console.print(
        f"\n[bold cyan]ster nav[/bold cyan]  [dim]{taxonomy_file.name}[/dim]  "
        f"[dim]{len(taxonomy.concepts)} concepts[/dim]\n"
        "[dim]Commands: ls  cd  pwd  show  info  add  mv  rm  label  define  quit[/dim]\n"
        "[dim]Tip: use 'ster show' for the full interactive tree viewer.[/dim]\n"
    )

    shell = TaxonomyShell(taxonomy, taxonomy_file, lang=lang)
    shell.cmdloop()


# ──────────────────────────── handles ────────────────────────────────────────


@app.command("handles")
def cmd_handles(
    lang: str = typer.Option("en", "--lang", "-l"),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Print the full handle → label → URI index."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    console.print(render_handle_list(taxonomy, lang))


# ──────────────────────────── validate ───────────────────────────────────────


@app.command("validate")
def cmd_validate(
    lang: str = typer.Option("en", "--lang", "-l"),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Check SKOS integrity: missing labels, orphans, duplicate prefLabels."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    issues: list[str] = []

    for uri, concept in taxonomy.concepts.items():
        handle = taxonomy.uri_to_handle(uri) or "?"
        pref_langs = [lbl.lang for lbl in concept.labels if lbl.type == LabelType.PREF]
        if not pref_langs:
            issues.append(f"[{handle}] {uri}  — no prefLabel")
        dupes = {lg for lg in pref_langs if pref_langs.count(lg) > 1}
        for lg in dupes:
            issues.append(f"[{handle}]  duplicate prefLabel for lang '{lg}'")
        for ref in concept.narrower + concept.broader + concept.related:
            if ref not in taxonomy.concepts:
                issues.append(f"[{handle}]  broken reference → {ref}")

    # Orphan detection
    reachable: set[str] = set()
    for scheme in taxonomy.schemes.values():
        for tc in scheme.top_concepts:
            _collect_reachable(taxonomy, tc, reachable)
    orphans = [u for u in taxonomy.concepts if u not in reachable]
    for uri in orphans:
        handle = taxonomy.uri_to_handle(uri) or "?"
        issues.append(f"[{handle}] {uri}  — orphan (not reachable from any top concept)")

    if issues:
        console.print(f"[red]Found {len(issues)} issue(s):[/red]")
        for issue in issues:
            console.print(f"  • {issue}")
        raise typer.Exit(1)
    else:
        console.print(
            f"[green]✓ No issues found.[/green]  {len(taxonomy.concepts)} concepts validated."
        )


# ──────────────────────────── export ─────────────────────────────────────────


@app.command("export")
def cmd_export(
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file (.ttl)."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output directory (default: same folder as taxonomy)."
    ),
    lang: str | None = typer.Option(
        None,
        "--lang",
        "-l",
        help="Comma-separated language codes to generate, e.g. en,fr. Defaults to all languages found.",
    ),
) -> None:
    """Export the taxonomy to a browsable HTML website (requires pyLODE).

    Generates one HTML page per language with a language-switcher bar.

    Examples:\n
      ster export                         # auto-detect languages\n
      ster export --lang en               # English only\n
      ster export --lang en,fr --output ./docs\n
    """
    from .html_export import detect_profile, generate_html

    taxonomy_file = _resolve_file(file)
    output_dir = output or taxonomy_file.parent / "html"
    languages = [lg.strip() for lg in lang.split(",")] if lang else None

    if not _ensure_ontology_uri(taxonomy_file):
        raise typer.Exit(1)

    detected = detect_profile(taxonomy_file)
    chosen_profile = detected if detected != "both" else "ontpub"
    if detected == "both":
        console.print(
            f"[yellow]{taxonomy_file.name}[/yellow] contains both skos:ConceptScheme "
            "and owl:Ontology — using OntPub. Pass --profile vocpub to override."
        )

    console.print(f"[dim]Generating HTML from[/dim] [bold]{taxonomy_file.name}[/bold]…")
    try:
        created = generate_html(
            taxonomy_file,
            output_dir,
            languages=languages if chosen_profile == "vocpub" else None,
            profile=chosen_profile,  # type: ignore[arg-type]
        )
    except RuntimeError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        err.print(f"[red]Export failed: {exc}[/red]")
        raise typer.Exit(1)

    import webbrowser

    for path in created:
        console.print(f"  [green]✓[/green]  {path}")

    if created:
        console.print(
            f"\n[bold]Generated {len(created)} file(s)[/bold] in [cyan]{output_dir}[/cyan]"
        )
        entry = next((p for p in created if "_en" in p.name), created[0])
        webbrowser.open(entry.as_uri())
        console.print(f"  [dim]Opened in browser:[/dim] {entry}")


@app.command("site")
def cmd_site(
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file (.ttl)."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output directory (default: <file-stem>-site/)."
    ),
    lang: str = typer.Option("en", "--lang", "-l", help="Display language."),
) -> None:
    """Generate a browsable hub website — one page per concept / class / individual.

    Renders rdfs:comment / skos:definition as Markdown, embeds schema:image as a
    hero photo, schema:video as a YouTube / Vimeo iframe, and schema:url as a
    link card.  All pages link to each other; no server required.

    Examples:\n
      ster site                          # auto-detect file, open in browser\n
      ster site --lang fr --output ./public\n
    """
    from .html_export import generate_site

    taxonomy_file = _resolve_file(file)
    output_dir = output or taxonomy_file.parent / f"{taxonomy_file.stem}-site"

    console.print(f"[dim]Building site from[/dim] [bold]{taxonomy_file.name}[/bold]…")
    try:
        created = generate_site(taxonomy_file, output_dir, lang=lang)
    except Exception as exc:
        err.print(f"[red]Site generation failed: {exc}[/red]")
        raise typer.Exit(1)

    for path in created:
        console.print(f"  [green]✓[/green]  {path.name}")

    if created:
        console.print(
            f"\n[bold]Generated {len(created)} page(s)[/bold] in [cyan]{output_dir}[/cyan]"
        )
        index = (output_dir / "index.html").resolve()
        import webbrowser

        webbrowser.open(index.as_uri())
        console.print(f"  [dim]Opened in browser:[/dim] {index}")


# ──────────────────────────── internal helpers ───────────────────────────────


def _make_taxonomy_commit_msg(taxonomy: Taxonomy, file_path: Path, lang: str = "en") -> str:
    """Build a descriptive git commit message for a newly tracked taxonomy file."""
    scheme = taxonomy.primary_scheme()
    title = scheme.title(lang) if scheme else file_path.stem
    lines = [f'feat: create taxonomy "{title}"', ""]
    lines.append(f"File: {file_path.name}")
    if scheme:
        if scheme.uri:
            lines.append(f"Scheme URI: {scheme.uri}")
        if scheme.base_uri:
            lines.append(f"Base URI: {scheme.base_uri}")
        if scheme.languages:
            lines.append(f"Languages: {', '.join(sorted(scheme.languages))}")
        if scheme.creator:
            lines.append(f"Creator: {scheme.creator}")
        if scheme.created:
            lines.append(f"Created: {scheme.created}")
    n = len(taxonomy.concepts)
    if n:
        lines.append(f"Concepts: {n}")
    return "\n".join(lines)


def _humanize(name: str) -> str:
    """Convert a camelCase/PascalCase local name to a human-readable label.

    Examples:
        SpadeRudder      → "Spade Rudder"
        trimTabOnRudder  → "Trim Tab On Rudder"
        HTTP             → "HTTP"
    """
    local = name.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", local)
    return spaced[0].upper() + spaced[1:] if spaced else local


def _collect_reachable(taxonomy: Taxonomy, uri: str, visited: set[str]) -> None:
    if uri in visited:
        return
    visited.add(uri)
    concept = taxonomy.concepts.get(uri)
    if concept:
        for child in concept.narrower:
            _collect_reachable(taxonomy, child, visited)


def _run_graph_viz_interactive(files: list[Path]) -> None:
    """Open the graph visualisation for a chosen file."""
    from . import viz as _viz

    if not files:
        err.print("[red]No taxonomy files found.[/red]")
        return

    # Pick the file to visualise
    taxonomy_file: Path
    if len(files) == 1:
        taxonomy_file = files[0]
    else:
        console.print()
        for i, f in enumerate(files, 1):
            console.print(f"  [cyan]{i:>2}[/cyan]  {f.name}")
        console.print()
        try:
            choice = Prompt.ask(
                "File to visualise",
                default="1",
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Cancelled.[/dim]")
            return
        try:
            idx = int(choice.strip()) - 1
            taxonomy_file = files[idx]
        except (ValueError, IndexError):
            err.print("[red]Invalid choice.[/red]")
            return

    taxonomy = _load(taxonomy_file)
    console.print(f"\n[dim]Opening graph for[/dim] [bold]{taxonomy_file.name}[/bold]…")
    try:
        out = _viz.open_in_browser(taxonomy, taxonomy_file)
        console.print(f"  [green]✓[/green]  {out}")
    except Exception as exc:
        err.print(f"[red]Graph error: {exc}[/red]")

    try:
        Prompt.ask("\n[dim]Press Enter to return to the menu[/dim]", default="")
    except (KeyboardInterrupt, EOFError):
        pass


def _ensure_pylode() -> bool:
    """Return True if pyLODE is importable, offering to install it if not."""
    from .html_export import _patch_missing_pyproject

    with _patch_missing_pyproject():
        try:
            import pylode  # noqa: F401

            return True
        except ImportError:
            pass

    console.print("\n[yellow]pyLODE is not installed.[/yellow]")
    try:
        answer = Prompt.ask(
            "Install it now?  [dim](pip install pylode)[/dim]",
            choices=["y", "n"],
            default="y",
        )
    except (KeyboardInterrupt, EOFError):
        return False

    if answer != "y":
        return False

    import subprocess
    import sys

    console.print("[dim]Installing pyLODE…[/dim]")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "pylode"],
    )
    if result.returncode != 0:
        err.print("[red]Installation failed.[/red]")
        return False
    console.print("[green]✓ pyLODE installed.[/green]")
    return True


def _ensure_ontology_uri(taxonomy_file: Path) -> bool:
    """If the file has no owl:Ontology/skos:ConceptScheme URI, prompt for one and save it.

    Returns False if the user cancels.
    """
    taxonomy = _load(taxonomy_file)
    if taxonomy.ontology_uri or taxonomy.schemes:
        return True

    console.print()
    console.print(
        f"[yellow]{taxonomy_file.name}[/yellow] has no ontology URI (required by pyLODE)."
    )
    stem = re.sub(r"[^a-z0-9]+", "-", taxonomy_file.stem.lower()).strip("-")
    default_name = taxonomy_file.stem.replace("_", " ").replace("-", " ").title()
    default_uri = f"https://example.org/ontology/{stem}"

    try:
        name = Prompt.ask("Ontology name", default=default_name)
        uri = Prompt.ask("Ontology URI", default=default_uri)
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        return False

    if not uri or " " in uri.strip():
        err.print("[red]Invalid URI — spaces are not allowed.[/red]")
        return False

    taxonomy.ontology_uri = uri.strip()
    taxonomy.ontology_label = name.strip() or None
    store.save(taxonomy, taxonomy_file)
    console.print(f"  [green]✓[/green]  Saved ontology URI to {taxonomy_file.name}")
    return True


def _run_html_export_interactive(files: list[Path]) -> None:
    """Interactive HTML export from the home-screen menu."""
    if not _ensure_pylode():
        return

    from .html_export import _available_languages, detect_profile, generate_html

    if not files:
        err.print("[red]No taxonomy files selected.[/red]")
        return

    console.print()
    for taxonomy_file in files:
        detected = detect_profile(taxonomy_file)
        taxonomy = _load(taxonomy_file)
        langs = _available_languages(taxonomy) if detected != "ontpub" else []
        lang_str = (", ".join(langs) if langs else "en") if detected != "ontpub" else "n/a (OWL)"
        profile_str = {"vocpub": "SKOS/VocPub", "ontpub": "OWL/OntPub", "both": "SKOS+OWL"}.get(
            detected, detected
        )
        console.print(
            f"[bold]{taxonomy_file.name}[/bold]  "
            f"[dim]Profile: {profile_str}  Languages: {lang_str}[/dim]"
        )

    console.print()

    # Per-file profile selection (needed when a file contains both SKOS and OWL)
    file_profiles: dict[Path, str] = {}
    for taxonomy_file in files:
        detected = detect_profile(taxonomy_file)
        if detected == "both":
            console.print(
                f"[yellow]{taxonomy_file.name}[/yellow] contains both "
                "skos:ConceptScheme and owl:Ontology declarations."
            )
            try:
                choice = Prompt.ask(
                    "  Which profile?",
                    choices=["vocpub", "ontpub"],
                    default="ontpub",
                )
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Cancelled.[/dim]")
                return
            file_profiles[taxonomy_file] = choice
        else:
            file_profiles[taxonomy_file] = detected

    # Language prompt — only relevant for VocPub files
    has_vocpub = any(p == "vocpub" for p in file_profiles.values())
    languages: list[str] | None = None
    if has_vocpub:
        try:
            lang_input = Prompt.ask(
                "Languages to export [dim](comma-separated, Enter for all detected)[/dim]",
                default="",
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Cancelled.[/dim]")
            return
        languages = [lg.strip() for lg in lang_input.split(",") if lg.strip()] or None

    output_dir = files[0].parent / "html"
    console.print()
    try:
        out_input = Prompt.ask(
            "Output directory",
            default=str(output_dir),
        )
        output_dir = Path(out_input.strip())
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        return

    console.print()
    all_created: list[Path] = []
    for taxonomy_file in files:
        if not _ensure_ontology_uri(taxonomy_file):
            return
        console.print(f"[dim]Generating[/dim] [bold]{taxonomy_file.name}[/bold]…")
        chosen_profile = file_profiles[taxonomy_file]
        file_langs = languages if chosen_profile == "vocpub" else None
        try:
            created = generate_html(
                taxonomy_file,
                output_dir,
                languages=file_langs,
                profile=chosen_profile,  # type: ignore[arg-type]
            )
            for p in created:
                console.print(f"  [green]✓[/green]  {p}")
            all_created.extend(created)
        except RuntimeError as exc:
            err.print(f"[red]{exc}[/red]")
            return
        except Exception as exc:
            err.print(f"[red]Export failed for {taxonomy_file.name}: {exc}[/red]")

    if all_created:
        import webbrowser

        console.print(
            f"\n[bold]Done.[/bold]  {len(all_created)} file(s) in [cyan]{output_dir}[/cyan]"
        )
        entry = next((p for p in all_created if "_en" in p.name), all_created[0])
        webbrowser.open(entry.as_uri())
        console.print(f"  [dim]Opened in browser:[/dim] {entry}")

    try:
        Prompt.ask("\n[dim]Press Enter to return to the menu[/dim]", default="")
    except (KeyboardInterrupt, EOFError):
        pass


def _run_site_interactive(files: list[Path]) -> None:
    """Interactive browsable site generator from the home-screen menu."""
    from .html_export import generate_site

    if not files:
        err.print("[red]No taxonomy files selected.[/red]")
        return

    taxonomy_file = files[0]
    default_out = taxonomy_file.parent / f"{taxonomy_file.stem}-site"

    console.print()
    console.print(f"[bold]Generate Browsable Website[/bold]  [dim]{taxonomy_file.name}[/dim]")
    console.print()

    try:
        out_input = Prompt.ask("Output directory", default=str(default_out))
        output_dir = Path(out_input.strip())
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        return

    try:
        lang_input = Prompt.ask("Display language", default="en")
        lang = lang_input.strip() or "en"
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        return

    console.print(f"\n[dim]Building site from[/dim] [bold]{taxonomy_file.name}[/bold]…")
    try:
        created = generate_site(taxonomy_file, output_dir, lang=lang)
    except Exception as exc:
        err.print(f"[red]Site generation failed: {exc}[/red]")
        try:
            Prompt.ask("\n[dim]Press Enter to return to the menu[/dim]", default="")
        except (KeyboardInterrupt, EOFError):
            pass
        return

    for path in created:
        console.print(f"  [green]✓[/green]  {path.name}")

    if created:
        import webbrowser

        console.print(
            f"\n[bold]Generated {len(created)} page(s)[/bold] in [cyan]{output_dir}[/cyan]"
        )
        index = (output_dir / "index.html").resolve()
        webbrowser.open(index.as_uri())
        console.print(f"  [dim]Opened in browser:[/dim] {index}")

    try:
        Prompt.ask("\n[dim]Press Enter to return to the menu[/dim]", default="")
    except (KeyboardInterrupt, EOFError):
        pass


def main() -> None:
    """Entry point.

    • ``ster``                   — interactive home screen (loops until Ctrl+C)
    • ``ster taxonomy.ttl``      — shortcut for ``ster show taxonomy.ttl``
    • ``ster <subcommand> …``    — delegate to Typer
    """
    import sys

    args = sys.argv[1:]

    # Non-bare invocation → delegate to Typer once (no loop)
    if args:
        first = args[0]
        if first not in _SUBCOMMANDS and not first.startswith("-"):
            p = Path(first)
            if p.suffix.lower() in _TAXONOMY_SUFFIXES:
                sys.argv.insert(1, "show")
        app()
        return

    # ── Bare invocation → interactive home screen loop ────────────────────────
    from .git_log import launch_git_log

    while True:
        _print_welcome()

        found: list[Path] = []
        for pattern in _TAXONOMY_GLOBS:
            found.extend(Path.cwd().glob(pattern))
        found = sorted(set(found))

        # ── No files in folder → inform user and exit ─────────────────────────
        if not found:
            console.print("[dim]No taxonomy files found in this folder.[/dim]\n")
            break

        # ── Load project for lang preference ──────────────────────────────────
        project = Project.load(Path.cwd())

        console.print("[bold]Taxonomy files in this folder:[/bold]\n")

        try:
            selected = _multi_file_picker(found)
        except (KeyboardInterrupt, EOFError):
            console.print()
            break

        if selected is _QUIT_SENTINEL or selected is None:
            break

        if selected is _GIT_LOG_SENTINEL:
            launch_git_log(path=found[0] if found else None)
            continue

        if selected is _HTML_SENTINEL:
            _run_html_export_interactive(found)
            continue

        if selected is _SITE_SENTINEL:
            _run_site_interactive(found)
            continue

        if selected is _GRAPH_SENTINEL:
            _run_graph_viz_interactive(found)
            continue

        if selected is _AI_CONFIG_SENTINEL:
            _launch_ai_config(found)
            continue

        if selected is _QUERY_SENTINEL:
            _launch_query(found)
            continue

        if not selected:
            continue

        # Normalise: _multi_file_picker may return a single Path or list[Path]
        if isinstance(selected, Path):
            selected = [selected]

        # ── Save / update project ─────────────────────────────────────────────
        git_root = _git_root(Path.cwd()) or Path.cwd()
        updated_project = Project(
            root=git_root,
            files=[],
            lang=project.lang if project else "en",
        )
        for f in selected:
            updated_project.add_file(f)
        try:
            updated_project.save()
        except Exception:
            pass  # non-fatal if .ster/ can't be written

        # ── Load workspace (with broken-mapping resolution) ───────────────────
        try:
            workspace = _load_workspace(selected, found)
        except Exception as exc:
            err.print(f"[red]Failed to load workspace: {exc}[/red]")
            continue

        # ── Open viewer ───────────────────────────────────────────────────────
        primary = selected[0]
        _save_session(primary)
        global _session_file
        _session_file = primary
        try:
            _open_viewer(primary, lang=updated_project.lang, workspace=workspace)
        except Exception as exc:
            err.print(f"[red]Viewer error: {exc}[/red]")
        continue  # return to home after viewer


if __name__ == "__main__":
    main()
