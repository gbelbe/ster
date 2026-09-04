"""Typer CLI — load, operate, save pattern for every mutating command."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from . import operations, store
from ._version import __version__ as _VERSION
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


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"ster v{_VERSION}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _app_callback(
    ctx: typer.Context,
    version: bool = typer.Option(  # noqa: ARG001
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Suppress Typer's default no-args behaviour; main() handles it."""


_AUTHOR = "ster contributors"
_TAXONOMY_FILE_HELP = "Taxonomy file."
_ANSI_RESET = "\033[0m"
_ANSI_BOLD = "\033[1m"
_ANSI_DIM = "\033[2m"
_ANSI_INVERSE = "\033[7m"
_ANSI_RED = "\033[31m"
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_BLUE = "\033[34m"
_ANSI_CYAN = "\033[36m"
_ANSI_MAGENTA = "\033[35m"
_ANSI_BRIGHT_CYAN = "\033[1;36m"
_CLEAR_LINE = "\r\033[2K"
_CANCELLED_MESSAGE = "\n[dim]Cancelled.[/dim]"

_PYPI_URL = "https://pypi.org/pypi/ster/json"
_VERSION_CACHE = Path(tempfile.gettempdir()) / "ster_version_check.json"


def _newer(a: str, b: str) -> bool:
    """Return True if version string *a* is greater than *b*."""

    def _t(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)

    return _t(a) > _t(b)


def _parse_changelog_section(description: str, version: str, max_bullets: int = 5) -> str:
    """Extract bullet points from the ## Changelog section matching *version*.

    Looks for a header like "### 0.3.2" or "### 0.3.2 — …" and collects the
    bullet lines that follow it, stopping at the next header.
    Returns a Rich-formatted string ready for display, or "" if not found.
    """
    bullets: list[str] = []
    in_section = False
    version_pat = re.compile(r"^#{1,4}\s+" + re.escape(version) + r"(\s|$)")
    header_pat = re.compile(r"^#{1,4}\s+")
    for line in description.splitlines():
        if version_pat.match(line):
            in_section = True
            continue
        if in_section:
            if header_pat.match(line):
                break
            stripped = line.strip()
            if stripped.startswith(("- ", "* ", "+ ")):
                text = stripped[2:].strip()
                text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
                text = re.sub(r"`(.+?)`", r"\1", text)
                bullets.append(text)
    trimmed = bullets[:max_bullets]
    if len(bullets) > max_bullets:
        trimmed.append(f"… and {len(bullets) - max_bullets} more")
    return "\n".join(f"  [dim]·[/dim] {b}" for b in trimmed)


def _check_new_version() -> tuple[str, str] | None:
    """Return (latest_version, release_notes_summary) if newer than installed, else None.

    Makes a single call to the PyPI JSON API (at most once per 24 h; result is
    cached in a temp file).  Release notes are parsed from the package description
    (README ## Changelog section) returned by the same API response.
    The network fetch always runs in a background daemon thread — never blocks.
    """
    now = datetime.now()
    cached_latest: str | None = None
    cached_notes: str = ""

    if _VERSION_CACHE.exists():
        try:
            data = json.loads(_VERSION_CACHE.read_text())
            checked = datetime.fromisoformat(data["checked"])
            if now - checked < timedelta(hours=12):
                cached_latest = data.get("latest")
                cached_notes = data.get("notes", "")
        except Exception:
            pass

    def _fetch() -> None:
        try:
            with urllib.request.urlopen(_PYPI_URL, timeout=3) as resp:  # noqa: S310
                payload = json.loads(resp.read())
            latest = payload["info"]["version"]
            description = payload["info"].get("description") or ""
            notes = _parse_changelog_section(description, latest)
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
        notes_block = f"\n{notes}" if notes.strip() else ""
        update_section = (
            f"\n[yellow]↑ v{new_ver} available[/yellow]  "
            f"[dim]pip install --upgrade ster[/dim]{notes_block}"
        )
    else:
        update_section = ""

    _LOGO = (
        "[bold cyan]   _____ ______ ______ ____  [/bold cyan]\n"
        "[bold cyan]  / ___//_  __// ____// __ \\ [/bold cyan]\n"
        "[bold cyan]  \\__ \\  / /  / __/  / /_/ / [/bold cyan]\n"
        "[bold cyan] ___/ / / /  / /___ / _, _/  [/bold cyan]\n"
        "[bold cyan]/____/ /_/  /_____//_/ |_|   [/bold cyan]"
    )
    console.print()
    console.print(
        Panel(
            f"{_LOGO}\n\n"
            f'[dim][ Breton: "Meaning" or "Sense" ][/dim]\n'
            f"[dim][  Semantic Knowledge Editor  ][/dim]  "
            f"[dim]v{_VERSION}[/dim]"
            f"{update_section}\n\n"
            "[dim]terminal tool for building and exploring SKOS taxonomies and OWL ontologies[/dim]\n\n"
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
        "log",
        "init-ci",
        "convert",
    }
)

_TAXONOMY_SUFFIXES = {".ttl", ".rdf", ".jsonld", ".owl", ".n3", ".trig", ".nt"}
_TAXONOMY_GLOBS = ("*.ttl", "*.rdf", "*.jsonld", "*.owl", "*.n3", "*.trig", "*.nt")

# Sentinels returned by _pick_file_interactive for special menu entries
_HTML_SENTINEL: Path = Path(".__ster_html__")
_GRAPH_SENTINEL: Path = Path(".__ster_graph__")
_CHANGE_FILE_SENTINEL: Path = Path(".__ster_change_file__")  # home menu → reselect the file
_QUERY_SENTINEL: Path = Path(".__ster_query__")
_EXT_ONT_SENTINEL: Path = Path(".__ster_ext_ont__")
_PUBLISH_SENTINEL: Path = Path(".__ster_publish__")
_DEMO_SENTINEL: Path = Path(".__ster_demo__")  # home menu → load the bundled sample
_ALL_FILES_SENTINEL: Path = Path(".__ster_all_files__")
_QUIT_SENTINEL: Path = Path(".__ster_quit__")

# The bundled mixed SKOS+OWL sample, shipped inside the package (ster/tui/).
_DEMO_FILE: Path = Path(__file__).parent / "tui" / "mixed-gear-demo.ttl"

# Home action-menu row colours (ANSI), keyed by sentinel; ``True`` = the "open" action.
_MENU_COLOURS: dict[object, str] = {
    True: _ANSI_BRIGHT_CYAN,  # bright cyan — TTL Viewer-Editor (the primary action)
    _GRAPH_SENTINEL: _ANSI_YELLOW,
    _QUERY_SENTINEL: _ANSI_GREEN,
    _EXT_ONT_SENTINEL: _ANSI_MAGENTA,
    _HTML_SENTINEL: _ANSI_BLUE,
    _PUBLISH_SENTINEL: _ANSI_GREEN,
    _DEMO_SENTINEL: _ANSI_GREEN,
    _CHANGE_FILE_SENTINEL: _ANSI_CYAN,
    _QUIT_SENTINEL: _ANSI_RED,
}

_session_file: Path | None = None  # in-process cache
_ci_check_done: bool = False  # guard: prompt at most once per process
_rdfxml_checked: bool = False  # guard: RDF/XML conversion prompt fires once per process
_converted_from: Path | None = None  # original RDF/XML path when a TTL was auto-converted


# ──────────────────────────── RDF/XML conversion helpers ─────────────────────


def _maybe_prompt_rdfxml_convert(resolved: Path) -> Path:
    """If *resolved* is RDF/XML and not yet checked this session, prompt the user
    to convert it to Turtle.  Returns the path to use (may be the new .ttl file).
    """
    global _rdfxml_checked, _converted_from
    if _rdfxml_checked or not store.is_rdfxml_path(resolved):
        return resolved
    _rdfxml_checked = True
    original = resolved
    try:
        want = Confirm.ask(
            f"RDF/XML format detected ({resolved.name}), convert to Turtle (.ttl) to use ster?",
            default=True,
        )
    except (KeyboardInterrupt, EOFError):
        want = False
    if not want:
        return resolved
    ttl_path = store.convert_to_ttl(original)
    _converted_from = original
    from rich.panel import Panel

    console.print(
        Panel(
            f"All edits will be saved to [bold]{ttl_path.name}[/bold].\n"
            f"The original [bold]{original.name}[/bold] will not be updated automatically.\n"
            f"[dim]Use 'ster convert' to convert between formats at any time.[/dim]",
            title="[yellow]Note[/yellow]",
            border_style="yellow",
        )
    )
    return ttl_path


def _maybe_backconvert(ttl_path: Path, pre_hash: str, original_path: Path) -> None:
    """After a viewer session: if *ttl_path* changed, offer to convert back to *original_path*."""
    if store.file_hash(ttl_path) == pre_hash:
        return
    try:
        want = Confirm.ask(
            f"Changes detected in [bold]{ttl_path.name}[/bold]. "
            f"Convert back to [bold]{original_path.name}[/bold] and overwrite?",
            default=False,
        )
    except (KeyboardInterrupt, EOFError):
        want = False
    if want:
        store.convert(ttl_path, original_path)
        console.print(f"[green]✓[/green] Converted {ttl_path.name} → {original_path.name}")


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
    global _session_file, _ci_check_done

    if not _ci_check_done:
        _ci_check_done = True
        from .init_ci import prompt_if_missing
        from .project import _git_root as _find_git_root

        _root = _find_git_root(Path.cwd())
        if _root and prompt_if_missing(_root):
            console.print(
                "[green]✓[/green] .github/workflows/taxonomy-ci.yml — "
                "commit and push to activate CI\n"
            )

    if path is not None:
        path = _maybe_prompt_rdfxml_convert(path)
        _session_file = path
        _save_session(path)
        return path

    if _session_file is not None:
        return _session_file

    saved = _load_session()
    if saved is not None:
        saved = _maybe_prompt_rdfxml_convert(saved)
        _session_file = saved
        _save_session(saved)
        return _session_file

    found = _found_taxonomy_files()
    if not found:
        err.print("[red]No taxonomy file found in the current directory.[/red]")
        err.print("[dim]Pass --file <path> or run 'ster init' to create one.[/dim]")
        raise typer.Exit(1)

    if len(found) == 1:
        console.print(f"[dim]Auto-detected:[/dim] [bold]{found[0].name}[/bold]")
        if not Confirm.ask("Use this file for this session?", default=True):
            raise typer.Abort()
        found0 = _maybe_prompt_rdfxml_convert(found[0])
        _save_session(found0)
        _session_file = found0
        return _session_file

    selected_choice = _pick_file(found)
    selected = selected_choice[0] if isinstance(selected_choice, list) else selected_choice
    selected = _maybe_prompt_rdfxml_convert(selected)
    _save_session(selected)
    _session_file = selected
    return _session_file


def _pick_file(files: list[Path]) -> Path | list[Path]:
    """Interactive file picker (used by _resolve_file for multiple files)."""
    result = _pick_file_interactive(files)
    if result is None:
        # User chose "create new" from a sub-command context — abort gracefully
        raise typer.Exit(0)
    return result


def _parse_numeric_picker_choice(
    idx: int, create_idx: int, quit_idx: int, files: list[Path]
) -> tuple[bool, Path | None | object]:
    if idx == quit_idx:
        return True, _QUIT_SENTINEL
    if idx == create_idx:
        return True, None
    if 1 <= idx <= len(files):
        return True, files[idx - 1]
    err.print(f"[red]Enter a number between 1 and {quit_idx}.[/red]")
    return False, None


def _parse_file_picker_choice(
    choice: str, files: list[Path], create_idx: int, quit_idx: int
) -> tuple[bool, Path | None | object]:
    """Parse string input for _pick_file_interactive. Returns (handled, value)."""
    if choice.isdigit():
        return _parse_numeric_picker_choice(int(choice), create_idx, quit_idx, files)

    matches = [f for f in files if f.name == choice or f.name.startswith(choice)]
    if len(matches) == 1:
        return True, matches[0]
    if len(matches) > 1:
        err.print(f"[yellow]Ambiguous — {[f.name for f in matches]}. Be more specific.[/yellow]")
    else:
        err.print(f"[red]{choice!r} not found.[/red]")
    return False, None


def _print_fallback_options(
    files: list[Path], preselect: Path | None, create_idx: int, quit_idx: int
) -> None:
    for i, f in enumerate(files, 1):
        marker = (
            " [bold green]←[/bold green] [dim](last session)[/dim]"
            if preselect and f == preselect
            else ""
        )
        console.print(f"  [cyan]{i:>2}[/cyan]  {f.name}{marker}")
    console.print(f"  [cyan]{create_idx:>2}[/cyan]  [bold green]+ Create new taxonomy[/bold green]")
    console.print(f"  [cyan]{quit_idx:>2}[/cyan]  [bold red]✕  Quit[/bold red]\n")


def _fallback_file_picker(
    files: list[Path], preselect: Path | None, initial_sel: int
) -> Path | list[Path] | None:
    create_idx, quit_idx = len(files) + 1, len(files) + 2
    _print_fallback_options(files, preselect, create_idx, quit_idx)

    default_num = str(initial_sel + 1) if (preselect and preselect in files) else ""
    prompt_text = (
        f"Select [bold](number or filename)[/bold] [dim](Enter → {files[initial_sel].name})[/dim]"
        if default_num
        else f"Select [bold](1–{quit_idx})[/bold]"
    )
    while True:
        try:
            choice = Prompt.ask(prompt_text, default=default_num)
        except (KeyboardInterrupt, EOFError):
            raise typer.Exit(0)
        if not choice and default_num:
            return files[initial_sel]
        handled, val = _parse_file_picker_choice(choice, files, create_idx, quit_idx)
        if handled:
            return val  # type: ignore[return-value]


def _pick_file_interactive(
    files: list[Path],
    preselect: Path | None = None,
) -> Path | list[Path] | None:
    """Display numbered file list; return chosen Path or None for 'create new'.

    The last entry is always '+ Create new taxonomy'.

    Supports arrow-key navigation in interactive terminals; also accepts typed numbers
    and filename prefixes (original behaviour).
    """
    import sys

    item_values: list[Path | None] = [*files, None, _QUIT_SENTINEL]
    initial_sel = files.index(preselect) if (preselect and preselect in files) else 0

    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            import termios as _termios  # noqa: F401 – import tests availability on this platform
            import tty as _tty  # noqa: F401

            return _arrow_file_picker(files, item_values, initial_sel, preselect)
        except ImportError:
            pass

    return _fallback_file_picker(files, preselect, initial_sel)


def _is_toggleable_file(val: Path | None) -> bool:
    return isinstance(val, Path) and val not in (
        _ALL_FILES_SENTINEL,
        _DEMO_SENTINEL,
        _QUIT_SENTINEL,
    )


def _collect_checked_paths(item_values: list[Path | None], checked: set[int]) -> list[Path]:
    res: list[Path] = []
    for i in sorted(checked):
        val = item_values[i]
        if _is_toggleable_file(val) and isinstance(val, Path):
            res.append(val)
    return res


def _format_picker_item_label(
    idx: int,
    val: Path | None,
    selected: bool,
    is_checked: bool,
    num_files: int,
    preselect: Path | None,
) -> str:
    R, B, D, CY, BCY, GR, INV = (
        _ANSI_RESET,
        _ANSI_BOLD,
        _ANSI_DIM,
        _ANSI_CYAN,
        _ANSI_BRIGHT_CYAN,
        _ANSI_GREEN,
        _ANSI_INVERSE,
    )
    num_s = f"{idx + 1:>2}"
    chk_mark = f"{GR}[✓]{R} " if is_checked else "[ ] "

    if val == _QUIT_SENTINEL:
        plain = "✕  Quit"
        coloured = f"{_ANSI_RED}{plain}{R}"
    elif val == _ALL_FILES_SENTINEL:
        plain = f"📁 Open all project files ({num_files} files)"
        coloured = f"{GR}{plain}{R}"
    elif val == _DEMO_SENTINEL:
        plain = "🎒 Load demo ontology / taxonomy"
        coloured = f"{GR}{plain}{R}"
    elif val is None:
        plain = "+ Create new taxonomy"
        coloured = f"{GR}{plain}{R}"
    else:
        last = "  ← last session" if preselect and val == preselect else ""
        plain = f"{chk_mark}{val.name}{last}"
        coloured = f"{chk_mark}{val.name}{f'  {D}← last session{R}' if last else ''}"

    if selected:
        return f"  {BCY}{INV} {num_s} {R}  {B}{plain}{R}"
    return f"    {CY}{num_s}{R}  {coloured}"


def _handle_esc_seq(sel: int, n: int) -> tuple[int, str, bool]:
    import sys

    nxt = sys.stdin.buffer.read(1)
    if nxt == b"[":
        code = sys.stdin.buffer.read(1)
        if code == b"A":
            return (sel - 1) % n, "", False
        if code == b"B":
            return (sel + 1) % n, "", False
    return (sel, "", nxt in (b"\r", b"\n"))


def _handle_digit_key(ch: bytes, sel: int, n: int, typed: str) -> tuple[int, str]:
    typed += ch.decode()
    new_sel = int(typed) - 1 if (typed.isdigit() and 1 <= int(typed) <= n) else sel
    return new_sel, typed


def _process_picker_key(
    ch: bytes,
    sel: int,
    n: int,
    typed: str,
    checked: set[int],
    item_values: list[Path | None],
) -> tuple[int, str, bool]:
    """Process a single keypress in the file picker. Returns (new_sel, new_typed, is_done)."""
    if ch in (b"\r", b"\n"):
        return (int(typed) - 1 if (typed.isdigit() and 1 <= int(typed) <= n) else sel), typed, True

    if ch == b" " and _is_toggleable_file(item_values[sel]):
        checked.symmetric_difference_update({sel})
        return sel, typed, False

    if ch == b"\x1b":
        return _handle_esc_seq(sel, n)

    if ch in (b"\x7f", b"\x08"):
        return sel, typed[:-1], False

    if ch.isdigit():
        new_sel, new_typed = _handle_digit_key(ch, sel, n, typed)
        return new_sel, new_typed, False

    return sel, typed, False


def _arrow_file_picker(
    _files: list[Path],
    item_values: list[Path | None],
    initial_sel: int,
    preselect: Path | None,
) -> Path | list[Path] | None:
    """Arrow-key file picker using raw terminal I/O + ANSI codes."""
    import sys
    import termios
    import tty

    R, B, D = _ANSI_RESET, _ANSI_BOLD, _ANSI_DIM
    CLEAR, NL = _CLEAR_LINE, "\r\n"
    n = len(item_values)
    sel = initial_sel
    checked: set[int] = set()

    def render(typed: str, first: bool = False) -> None:
        if not first:
            sys.stdout.write(f"\033[{n + 1}A")
        for i in range(n):
            lbl = _format_picker_item_label(
                i, item_values[i], i == sel, i in checked, len(_files), preselect
            )
            sys.stdout.write(f"{CLEAR}{lbl}{NL}")
        if typed:
            sys.stdout.write(
                f"{CLEAR}  {D}type:{R} {B}{typed}▌{R}  {D}Enter: confirm  Esc: clear{R}"
            )
        elif checked:
            sys.stdout.write(
                f"{CLEAR}  {D}↑↓ nav  Space toggle  Enter open ({len(checked)} selected){R}"
            )
        else:
            sys.stdout.write(
                f"{CLEAR}  {D}↑↓ nav  Space multi-select  Enter open  or type number{R}"
            )
        sys.stdout.write(NL)
        sys.stdout.flush()

    render(typed="", first=True)
    typed = ""
    fd = sys.stdin.fileno()
    old_cfg = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.buffer.read(1)
            if ch == b"\x03":
                termios.tcsetattr(fd, termios.TCSADRAIN, old_cfg)
                raise KeyboardInterrupt

            sel, typed, done = _process_picker_key(ch, sel, n, typed, checked, item_values)
            if done:
                break
            render(typed)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_cfg)
        sys.stdout.write(NL)
        sys.stdout.flush()

    checked_paths = _collect_checked_paths(item_values, checked)
    if checked_paths:
        return checked_paths
    return item_values[sel]


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
        err.print(f"[red]{store.format_parse_error(exc, path)}[/red]")
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


def _select_home_file(found: list[Path]) -> Path | list[Path] | None:
    """Step 1 of the home menu: pick the file every action will operate on — from the local
    files *plus* a 'Load demo' entry. Always shown (even for one file), so the demo is always
    reachable. Returns the chosen file(s), ``_DEMO_SENTINEL`` (load a fresh demo), or ``None`` on
    Quit / Ctrl+C.
    """
    import sys

    console.print("[bold]Select a file:[/bold]\n")
    item_values: list[Path | None] = []
    if len(found) >= 2:
        item_values.append(_ALL_FILES_SENTINEL)
    item_values.extend(found)
    item_values.extend([_DEMO_SENTINEL, _QUIT_SENTINEL])

    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            import termios as _t  # noqa: F401 — availability probe
            import tty as _tt  # noqa: F401

            chosen = _arrow_file_picker(found, item_values, 0, None)
            return None if chosen == _QUIT_SENTINEL else chosen
        except ImportError:
            pass

    return _select_home_file_numeric(found)


def _format_home_item_label(val: Path | None, found: list[Path]) -> str:
    if val == _ALL_FILES_SENTINEL:
        return f"[green]📁 Open all project files ({len(found)} files)[/green]"
    if val == _DEMO_SENTINEL:
        return "[green]🎒 Load demo ontology / taxonomy[/green]"
    if val == _QUIT_SENTINEL:
        return "[red]✕  Quit[/red]"
    return val.name if val else ""


def _parse_comma_selection(raw: str, items: list[Path | None]) -> list[Path] | None:
    selected_files: list[Path] = []
    for part in raw.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(items):
                val = items[idx]
                if _is_toggleable_file(val) and isinstance(val, Path):
                    selected_files.append(val)
        except ValueError:
            pass
    return selected_files if selected_files else None


def _select_home_file_numeric(found: list[Path]) -> Path | list[Path] | None:
    """Numbered-prompt fallback for :func:`_select_home_file` when no arrow-key TTY is
    available. Files 1..n, then the demo, then Quit; a non-numeric reply picks the default
    (first file, or the demo when the folder is empty)."""
    items: list[Path | None] = [_ALL_FILES_SENTINEL] if len(found) >= 2 else []
    items.extend(found)
    items.extend([_DEMO_SENTINEL, _QUIT_SENTINEL])

    for i, val in enumerate(items, 1):
        console.print(f"  [cyan]{i}[/cyan]  {_format_home_item_label(val, found)}")

    choice = Prompt.ask(f"Select (1–{len(items)}, or e.g. 2,3)", default="1")
    raw = choice.strip()
    if "," in raw:
        multi = _parse_comma_selection(raw, items)
        if multi:
            return multi

    try:
        idx = int(raw) - 1
        chosen = items[idx] if 0 <= idx < len(items) else _DEMO_SENTINEL
    except ValueError:
        chosen = found[0] if found else _DEMO_SENTINEL
    return None if chosen == _QUIT_SENTINEL else chosen


def _home_actions() -> list[tuple[object, str]]:
    """The home action rows for the selected file, in display order. 'Change file' returns
    to the file list (which now holds the local files *and* the demo); True = the primary
    'open' action (the Textual viewer)."""
    return [
        (_CHANGE_FILE_SENTINEL, "🔀 Change file"),
        (True, "🖥  TTL Viewer-Editor"),  # True = "open" sentinel → the Textual viewer
        (_QUERY_SENTINEL, "🔍 SPARQL Query"),
        (_PUBLISH_SENTINEL, "📦 Linked Data Publish & Version"),
        (_HTML_SENTINEL, "🌐 HTML Data Catalog"),
        (_GRAPH_SENTINEL, "◈  Load Graph Viewer"),
        (_EXT_ONT_SENTINEL, "📥 Import External Ontology"),
        (_QUIT_SENTINEL, "✕  Quit"),
    ]


def _home_menu_fallback(selected: Path, actions: list[tuple[object, str]]) -> object:
    """Non-TTY action menu: a plain numbered prompt. Returns the chosen action sentinel."""
    console.print(f"  [green]✓[/green]  [bold]{selected.name}[/bold]\n")
    for i, (_s, label) in enumerate(actions, 1):
        console.print(f"  [cyan]{i}[/cyan]  {label}")
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
        f"{_CLEAR_LINE}  {green}✓{reset}  {bold}{selected.name}{reset}\r\n{_CLEAR_LINE}\r\n"
    )
    for index, (sentinel, label) in enumerate(actions):
        color = _MENU_COLOURS.get(sentinel, cyan)
        number = f"{index + 1:>2}"
        row = (
            f"  {bright_cyan}{inverse} {number} {reset}  {color}{bold}{label}{reset}"
            if index == cursor
            else f"    {cyan}{number}{reset}  {color}{label}{reset}"
        )
        sys.stdout.write(f"{_CLEAR_LINE}{row}\r\n")
    sys.stdout.write(f"{_CLEAR_LINE}  {dim}↑↓ navigate  Enter: select{reset}\r\n")
    sys.stdout.flush()


def _run_arrow_menu(selected: Path, actions: list[tuple[object, str]]) -> int | None:
    """Arrow-key action menu for *selected*. Returns the chosen index, or None on Quit/Esc."""
    import sys
    import termios
    import tty

    colors = (
        _ANSI_RESET,
        _ANSI_BOLD,
        _ANSI_DIM,
        _ANSI_CYAN,
        _ANSI_GREEN,
        _ANSI_INVERSE,
        _ANSI_BRIGHT_CYAN,
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
      _CHANGE_FILE_SENTINEL  — reselect the file (the file list holds files + the demo)
      _QUIT_SENTINEL         — Quit / Ctrl+C / plain Esc
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
    return _QUIT_SENTINEL if idx is None else _chosen(actions[idx][0])


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


# ──────────────────────────── SPARQL query launcher ─────────────────────────


def _launch_ext_ontologies(found: list[Path]) -> None:  # noqa: ARG001
    """Home-menu action: open the external-ontologies import screen."""
    from .ext_ontologies_ui import run_ext_ontologies_screen

    run_ext_ontologies_screen(taxonomy=None)


def _dispatch_menu_action(selected: object, found: list[Path]) -> bool:
    """Run the home-menu handler for a sentinel selection. True when handled.

    A plain list/file selection (not a sentinel) returns False so the caller
    falls through to the open-file path.
    """
    actions: dict[Path, Callable[[list[Path]], None]] = {
        _HTML_SENTINEL: _run_html_export_interactive,
        _GRAPH_SENTINEL: _run_graph_viz_interactive,
        _QUERY_SENTINEL: _launch_query,
        _EXT_ONT_SENTINEL: _launch_ext_ontologies,
        _PUBLISH_SENTINEL: _run_publish_interactive,
    }
    action = actions.get(selected) if isinstance(selected, Path) else None
    if action is None:
        return False
    action(found)
    return True


def _load_demo_into_cwd() -> Path:
    """Drop a **fresh** copy of the bundled sample into the current folder and return its
    path. The demo is a throwaway sandbox — every load resets it to pristine, so you can
    always start clean. If a local copy has edits, offer to save them to a separate .ttl
    first (so real work is kept, then the demo resets)."""
    import shutil

    dest = Path.cwd() / _DEMO_FILE.name
    if dest.exists() and dest.read_bytes() != _DEMO_FILE.read_bytes():
        _offer_keep_demo_edits(dest)  # the local copy diverged → let the user keep it
    shutil.copyfile(_DEMO_FILE, dest)  # reset to a fresh demo every time
    console.print(
        f"[green]Loaded a fresh demo → {dest.name}[/green] "
        "— a mixed SKOS + OWL sandbox (edits reset on reload)."
    )
    return dest


def _offer_keep_demo_edits(dest: Path) -> None:
    """The local demo has edits and is about to be reset — offer to save them under a new
    .ttl name first. No-op (silent reset) in a non-interactive terminal."""
    import shutil
    import sys

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return
    from rich.prompt import Confirm, Prompt

    if not Confirm.ask(
        "The demo has your edits — save them to a new file before resetting?",
        default=True,
        console=console,
    ):
        return
    name = Prompt.ask("Save your work as", default="my-ontology.ttl", console=console).strip()
    if not name or Path(name).name == _DEMO_FILE.name:  # never clobber the demo itself
        name = "my-ontology.ttl"
    if not name.endswith(".ttl"):
        name += ".ttl"
    target = Path.cwd() / Path(name).name
    shutil.copyfile(dest, target)
    console.print(f"[green]Saved your work → {target.name}[/green]")


def _launch_query(found: list[Path]) -> None:
    """Open the New-TUI straight into the SPARQL query screen for the primary file."""
    if not found:
        err.print("[red]No taxonomy files to query.[/red]")
        return
    primary = found[0]
    taxonomy = _load_safe(primary)
    if taxonomy is None:
        return
    from .tui import launch

    launch(taxonomy, source=primary.name, path=primary, open_query=True)


# ──────────────────────────── viewer helper ──────────────────────────────────


def _prewarm_lint(path: Path) -> None:
    """Compute + cache the semanticlint result before the browser opens, so its first
    paint is instant instead of blocking on a ~2 s pyshacl pass. A "Checking…" status
    shows only on a cache miss (first open / after an edit); an unchanged file is a cache
    hit and stays silent. Best-effort — the TUI lints lazily if this fails. Skipped for
    the query workspace, which doesn't use lint at all."""
    try:
        from .plugins import semanticlint

        if not semanticlint.is_active():
            return
        from .plugins.semanticlint import config, lint_cache
        from .plugins.semanticlint.runner import lint_overview

        cfg_hash = lint_cache.config_hash(config.load_config())
        if lint_cache.get_cached(path, cfg_hash) is not None:
            return  # unchanged since last open → already cached, nothing to do
        with console.status(f"Checking {path.name}…"):
            lint_cache.get_or_compute(path, cfg_hash, compute=lambda: lint_overview(path))
    except Exception:  # noqa: BLE001 — pre-warming must never block opening the file
        pass


def _open_viewer(
    taxonomy_file: Path, workspace: TaxonomyWorkspace | None = None, lang: str = "en"
) -> None:
    """Open the New-TUI for *taxonomy_file* (``ster show``) and handle git on exit."""
    from .git.manager import GitManager, render_diff
    from .tui import launch

    taxonomy = _load_safe(taxonomy_file)
    if taxonomy is None:
        return
    _prewarm_lint(taxonomy_file)  # populate the lint cache so the browser paints instantly
    pre_hash = store.file_hash(taxonomy_file) if _converted_from else ""

    gm = GitManager(taxonomy_file)
    fetch_event: threading.Event | None = None

    if gm.is_enabled():
        if not gm.is_configured():
            gm.setup()
        if gm.is_configured():
            gm.record_head()
            fetch_event = threading.Event()
            _ev = fetch_event

            def _do_fetch() -> None:
                try:
                    gm.fetch_remote()
                except Exception:
                    pass
                finally:
                    _ev.set()

            threading.Thread(target=_do_fetch, daemon=True).start()

    launch(
        taxonomy,
        source=taxonomy_file.name,
        lang=lang,
        path=taxonomy_file,
        workspace=workspace,
    )

    if gm.is_enabled() and gm.is_configured():
        if fetch_event is not None:
            fetch_event.wait(timeout=15)
            diff = gm.check_and_pull()
            if diff:
                console.print("\n[bold]Changes pulled from remote:[/bold]")
                render_diff(diff)
                console.print()
        try:
            gm.commit_and_push()
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            console.print(f"\n[red]Commit error:[/red] {exc}")
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

    if _converted_from:
        _maybe_backconvert(taxonomy_file, pre_hash, _converted_from)


# ──────────────────────────── show ───────────────────────────────────────────


@app.command("show")
def cmd_show(
    file: Path | None = typer.Argument(
        None, help="Taxonomy file (.ttl / .rdf / .jsonld / .trig). Auto-detected if omitted."
    ),
    concept: str | None = typer.Option(
        None,
        "--concept",
        "-c",
        metavar="HANDLE",
        help="With --plain, root the printed tree at this concept.",
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
    """Open the interactive taxonomy browser (the Textual New-TUI) and commit on exit.

    A mouse- and keyboard-driven tree of classes / individuals / properties with a
    fuzzy search palette (press ``/``) and a live detail panel. Fully editable:
    create / rename / re-link / delete classes, individuals, properties, concepts
    and schemes — every change is validated and saved. Arrow keys move between the
    tree and the detail rows; Enter edits (or runs) the focused row; ``s`` opens the
    SPARQL query screen. On quit, the git commit/push flow runs.

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

    _open_viewer(taxonomy_file, lang=lang)


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
    file: Path | None = typer.Option(None, "--file", "-f", help=_TAXONOMY_FILE_HELP),
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
    file: Path | None = typer.Option(None, "--file", "-f", help=_TAXONOMY_FILE_HELP),
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
    file: Path | None = typer.Option(None, "--file", "-f", help=_TAXONOMY_FILE_HELP),
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


# ──────────────────────────── subclass ───────────────────────────────────────


@app.command("subclass")
def cmd_subclass(
    child: str = typer.Argument(..., help="Class to make a subclass (handle or URI)."),
    parent: str = typer.Option(..., "--parent", "-p", help="Parent class (handle or URI)."),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file (.ttl)."),
) -> None:
    """Add a rdfs:subClassOf link from a class to a parent class.

    Examples:\n
      ster subclass Dog --parent Animal\n
      ster subclass PER --parent ORG\n
    """
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    child_uri = _resolve(taxonomy, child)
    parent_uri = _resolve(taxonomy, parent)
    _run(operations.add_subclass_of, taxonomy, child_uri, parent_uri)
    child_cls = taxonomy.owl_classes.get(child_uri)
    parent_cls = taxonomy.owl_classes.get(parent_uri)
    child_label = child_cls.label("en") if child_cls else child_uri
    parent_label = parent_cls.label("en") if parent_cls else parent_uri
    console.print(f"[green]Added[/green] {child_label} subClassOf {parent_label}")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── label ──────────────────────────────────────────


@app.command("label")
def cmd_label(
    concept: str = typer.Argument(..., metavar="HANDLE"),
    lang: str = typer.Argument(..., help="Language code (en, fr, …)"),
    text: str = typer.Argument(..., help="Label text"),
    alt: bool = typer.Option(False, "--alt", help="Add as alt label (default: pref label)."),
    file: Path | None = typer.Option(None, "--file", "-f", help=_TAXONOMY_FILE_HELP),
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
    file: Path | None = typer.Option(None, "--file", "-f", help=_TAXONOMY_FILE_HELP),
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
    file: Path | None = typer.Option(None, "--file", "-f", help=_TAXONOMY_FILE_HELP),
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
    file: Path | None = typer.Option(None, "--file", "-f", help=_TAXONOMY_FILE_HELP),
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


# ──────────────────────────── handles ────────────────────────────────────────


@app.command("handles")
def cmd_handles(
    lang: str = typer.Option("en", "--lang", "-l"),
    file: Path | None = typer.Option(None, "--file", "-f", help=_TAXONOMY_FILE_HELP),
) -> None:
    """Print the full handle → label → URI index."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    console.print(render_handle_list(taxonomy, lang))


# ──────────────────────────── validate ───────────────────────────────────────


@app.command("validate")
def cmd_validate(
    lang: str = typer.Option("en", "--lang", "-l"),
    file: Path | None = typer.Option(None, "--file", "-f", help=_TAXONOMY_FILE_HELP),
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


# ──────────────────────────── convert ────────────────────────────────────────


@app.command("convert")
def cmd_convert(
    input_file: Path = typer.Argument(..., help="Input RDF file (any supported format)."),
    output: Path | None = typer.Argument(
        None,
        help="Output file path. Format detected from extension. Defaults to input stem + .ttl.",
    ),
) -> None:
    """Convert an RDF file to a different serialisation format.

    Input format is inferred from the file extension (.rdf, .owl, .xml, .ttl, .jsonld, .n3, .nt).
    Output defaults to Turtle (.ttl).

    Examples:\n
      ster convert onto.rdf                # → onto.ttl\n
      ster convert onto.owl                # → onto.ttl\n
      ster convert onto.ttl onto.nt        # → onto.nt (N-Triples)\n
      ster convert onto.ttl onto.rdf       # → onto.rdf (RDF/XML)\n
    """
    try:
        if output is not None:
            out = store.convert(input_file, output)
        else:
            out = store.convert_to_ttl(input_file)
        console.print(f"[green]✓[/green] {input_file.name} → {out.name}")
    except ValueError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        err.print(f"[red]Cannot convert {input_file}: {exc}[/red]")
        raise typer.Exit(1)


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
    from . import viz_vowl as _viz

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
            console.print(_CANCELLED_MESSAGE)
            return
        try:
            idx = int(choice.strip()) - 1
            taxonomy_file = files[idx]
        except (ValueError, IndexError):
            err.print("[red]Invalid choice.[/red]")
            return

    taxonomy = _load_safe(taxonomy_file)
    if taxonomy is None:
        return
    console.print(f"\n[dim]Opening graph for[/dim] [bold]{taxonomy_file.name}[/bold]…")
    try:
        _free_graph_port()  # a leftover graph process on the port would force a static snapshot
        out = _viz.open_in_browser(taxonomy, taxonomy_file)
        console.print(f"  [green]✓[/green]  {out}")
        if not _viz.is_live_server():
            console.print(
                "  [yellow]![/yellow]  The configured port is busy — showing a static "
                "snapshot (explore-relations disabled). Close the other process or change "
                "the port in Config, then reopen."
            )
    except Exception as exc:
        err.print(f"[red]Graph error: {exc}[/red]")


def _free_graph_port() -> None:
    """Close a previous graph process still holding the live-server port, so the live
    (interactive) graph can start instead of falling back to a static snapshot. No-op when
    our own server is already live or the port is free."""
    from . import viz_vowl as _viz

    if _viz.is_live_server():
        return
    holder = _viz.port_holder()
    if holder is None:
        return
    pid, _desc = holder
    if _viz.free_port(pid):
        console.print(f"  [dim]Closed a previous graph process (PID {pid}) holding the port.[/dim]")


def _ensure_pylode() -> bool:
    """Return True if pyLODE is importable, offering to install it if not."""
    from .html_export import is_pylode_available

    if is_pylode_available():
        return True

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

    import importlib
    import shutil
    import subprocess
    import sys

    # uv-managed tool environments don't bundle pip — prefer uv when available.
    uv_bin = shutil.which("uv")
    if uv_bin:
        cmd = [uv_bin, "pip", "install", "--python", sys.executable, "pylode"]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "pylode"]

    with console.status("[dim]Installing pyLODE…[/dim]"):
        result = subprocess.run(cmd, capture_output=True)
    importlib.invalidate_caches()
    if result.returncode != 0:
        err.print("[red]Installation failed.[/red]")
        err.print(result.stderr.decode(errors="replace"))
        return False
    console.print("[green]✓ pyLODE installed.[/green]")
    return True


def _ensure_ontology_uri(taxonomy_file: Path) -> bool:
    """If the file has no owl:Ontology/skos:ConceptScheme URI, prompt for one and save it.

    Returns False if the user cancels or the file cannot be loaded.
    """
    taxonomy = _load_safe(taxonomy_file)
    if taxonomy is None:
        return False
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
        console.print(_CANCELLED_MESSAGE)
        return False

    if not uri or " " in uri.strip():
        err.print("[red]Invalid URI — spaces are not allowed.[/red]")
        return False

    taxonomy.ontology_uri = uri.strip()
    taxonomy.ontology_label = name.strip() or None
    store.save(taxonomy, taxonomy_file)
    console.print(f"  [green]✓[/green]  Saved ontology URI to {taxonomy_file.name}")
    return True


def _show_html_export_preview(files: list[Path]) -> None:
    from .html_export import _available_languages, detect_profile

    for taxonomy_file in files:
        detected = detect_profile(taxonomy_file)
        taxonomy = _load_safe(taxonomy_file)
        if taxonomy is None:
            continue
        if detected == "ontpub":
            lang_str = "n/a (OWL)"
        else:
            langs = _available_languages(taxonomy)
            lang_str = ", ".join(langs) if langs else "en"
        profile_str = {"vocpub": "SKOS/VocPub", "ontpub": "OWL/OntPub", "both": "SKOS+OWL"}.get(
            detected, detected
        )
        console.print(
            f"[bold]{taxonomy_file.name}[/bold]  "
            f"[dim]Profile: {profile_str}  Languages: {lang_str}[/dim]"
        )

    console.print()


def _choose_html_profiles(files: list[Path]) -> dict[Path, str] | None:
    from .html_export import detect_profile

    file_profiles: dict[Path, str] = {}
    for taxonomy_file in files:
        detected = detect_profile(taxonomy_file)
        if detected != "both":
            file_profiles[taxonomy_file] = detected
            continue
        console.print(
            f"[yellow]{taxonomy_file.name}[/yellow] contains both "
            "skos:ConceptScheme and owl:Ontology declarations."
        )
        try:
            file_profiles[taxonomy_file] = Prompt.ask(
                "  Which profile?", choices=["vocpub", "ontpub"], default="ontpub"
            )
        except (KeyboardInterrupt, EOFError):
            console.print(_CANCELLED_MESSAGE)
            return None
    return file_profiles


def _choose_html_languages(
    file_profiles: dict[Path, str],
) -> tuple[bool, list[str] | None]:
    if not any(profile == "vocpub" for profile in file_profiles.values()):
        return True, None
    try:
        lang_input = Prompt.ask(
            "Languages to export [dim](comma-separated, Enter for all detected)[/dim]",
            default="",
        )
    except (KeyboardInterrupt, EOFError):
        console.print(_CANCELLED_MESSAGE)
        return False, None
    return True, [lg.strip() for lg in lang_input.split(",") if lg.strip()] or None


def _choose_html_output(files: list[Path]) -> Path | None:
    output_dir = files[0].parent / "html"
    console.print()
    try:
        return Path(Prompt.ask("Output directory", default=str(output_dir)).strip())
    except (KeyboardInterrupt, EOFError):
        console.print(_CANCELLED_MESSAGE)
        return None


def _html_export_options(
    files: list[Path],
) -> tuple[dict[Path, str], list[str] | None, Path] | None:
    _show_html_export_preview(files)
    file_profiles = _choose_html_profiles(files)
    if file_profiles is None:
        return None
    accepted, languages = _choose_html_languages(file_profiles)
    if not accepted:
        return None
    output_dir = _choose_html_output(files)
    if output_dir is None:
        return None
    return file_profiles, languages, output_dir


def _run_html_export_interactive(files: list[Path]) -> None:
    """Interactive HTML export from the home-screen menu."""
    if not _ensure_pylode():
        return

    from .html_export import generate_html

    if not files:
        err.print("[red]No taxonomy files selected.[/red]")
        return

    options = _html_export_options(files)
    if options is None:
        return
    file_profiles, languages, output_dir = options

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


@app.command("init-ci")
def cmd_init_ci(
    dest: Path = typer.Argument(Path("."), help="Project root directory (default: current dir)."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
    config: bool = typer.Option(
        True, "--config/--no-config", help="Also write onto-ci.yml config template."
    ),
) -> None:
    """Scaffold a GitHub Actions CI workflow for this taxonomy/ontology project."""
    from .init_ci import scaffold

    dest = dest.resolve()
    workflow_written, config_written = scaffold(dest, force=force, include_config=config)
    workflow_rel = Path(".github") / "workflows" / "taxonomy-ci.yml"

    if not workflow_written:
        console.print(f"[yellow]already exists:[/yellow] {workflow_rel}")
        console.print("[dim]Use --force to overwrite.[/dim]")
    else:
        console.print(f"[green]created:[/green] {workflow_rel}")
    if config_written:
        console.print("[green]created:[/green] onto-ci.yml")


@app.command("serve")
def cmd_serve(
    file: Path = typer.Argument(..., help="Ontology file (.ttl / .rdf / .jsonld)."),
    host: str | None = typer.Option(None, "--host", help="Bind host."),
    port: int | None = typer.Option(None, "--port", "-p", help="Bind port."),
) -> None:
    """Start the live graph viewer and ontology REST API.

    The browser view auto-refreshes when the file is edited via the ster CLI.
    API docs are available at http://<host>:<port>/docs.
    """
    try:
        from .api_server import serve
    except ImportError:  # fastapi/uvicorn are core deps — only a broken install lands here
        err.print(
            "[red]The graph server (fastapi/uvicorn) failed to import — reinstall ster.[/red]"
        )
        raise typer.Exit(1)
    serve(file.resolve(), host=host, port=port)


def _open_dev_artifacts_in_browser(
    taxonomy: object, file_path: Path, publish_dir: Path, artifacts: list[Path]
) -> None:
    """Open the freshly-published dev TTL + HTML on the running graph server.

    Ensures the server is up so the pages are served at /ontology/dev/...; if the live
    server can't start (its port is busy) it falls back to opening the files via file://.
    """
    from . import viz_vowl as _viz
    from .publish import open_dev_artifacts

    base = _viz.ensure_published_server(taxonomy, file_path)  # type: ignore[arg-type]
    urls = open_dev_artifacts(publish_dir, artifacts, base)
    if not urls:
        return
    if base:
        console.print(f"[green]✓[/green]  Opened dev pages: {'  '.join(urls)}")
    else:
        console.print(
            f"[yellow]![/yellow]  No live server (port busy) — "
            f"opened files directly: {'  '.join(urls)}"
        )


def _menu_action_for_key(ch: bytes, stream: BinaryIO) -> str:
    """Map a raw keypress (with continuation bytes from *stream*) to a menu action.

    Returns one of: 'up', 'down', 'select', 'quit', 'none'.
    """
    if ch in (b"\r", b"\n"):
        return "select"
    if ch == b"\x03":  # Ctrl+C
        return "quit"
    if ch != b"\x1b":  # not an escape sequence
        return "none"
    if stream.read(1) != b"[":
        return "quit"  # plain Esc
    code = stream.read(1)
    if code == b"A":
        return "up"
    if code == b"B":
        return "down"
    return "none"


def _render_publish_menu(labels: list[str], sel: int, first: bool) -> None:  # pragma: no cover
    """Redraw the publish menu in place (raw-terminal ANSI)."""
    import sys

    inv, r, b, d = _ANSI_INVERSE, _ANSI_RESET, _ANSI_BOLD, _ANSI_DIM
    clear, nl = _CLEAR_LINE, "\r\n"
    if not first:
        sys.stdout.write(f"\033[{len(labels) + 1}A")
    for i, lab in enumerate(labels):
        if i == sel:
            sys.stdout.write(f"{clear}  {b}{inv} {lab} {r}{nl}")
        else:
            sys.stdout.write(f"{clear}    {lab}{nl}")
    sys.stdout.write(f"{clear}  {d}↑↓ navigate  Enter select  Esc back{r}{nl}")
    sys.stdout.flush()


def _arrow_menu_select(labels: list[str]) -> int | None:  # pragma: no cover
    """Raw-terminal arrow menu over *labels*; return the chosen index or None."""
    import sys
    import termios
    import tty

    if not labels:
        return None
    n, sel = len(labels), 0
    _render_publish_menu(labels, sel, first=True)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            action = _menu_action_for_key(sys.stdin.buffer.read(1), sys.stdin.buffer)
            if action == "up":
                sel = (sel - 1) % n
            elif action == "down":
                sel = (sel + 1) % n
            elif action == "select":
                return sel
            elif action == "quit":
                return None
            _render_publish_menu(labels, sel, first=False)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\r\n")
        sys.stdout.flush()


def _select_publish_target(files: list[Path]) -> tuple[Path, object] | None:  # pragma: no cover
    """Pick a file, load it, and run pre-flight; return (path, taxonomy) or None."""
    from .publish import PublishError, pre_flight
    from .store import load as _load_tax

    if not files:
        err.print("[red]No taxonomy files found. Open a taxonomy file first.[/red]")
        return None
    if len(files) == 1:
        taxonomy_file = files[0]
    else:
        console.print("[bold]Select a file to publish:[/bold]")
        for i, f in enumerate(files, 1):
            console.print(f"  [cyan]{i}[/cyan]  {f.name}")
        try:
            idx = int(Prompt.ask("File number", default="1")) - 1
            taxonomy_file = files[max(0, min(idx, len(files) - 1))]
        except (ValueError, KeyboardInterrupt):
            return None
    try:
        taxonomy = _load_tax(taxonomy_file)
    except Exception as e:
        err.print(f"[red]Failed to load {taxonomy_file.name}:[/red] {e}")
        return None
    try:
        pre_flight(taxonomy)
    except PublishError as e:
        err.print(f"[red]Publish blocked:[/red] {e}")
        return None
    return taxonomy_file, taxonomy


def _publish_stable_flow(taxonomy_file: Path, publish_dir: Path) -> None:  # pragma: no cover
    """Prompt for a semver bump, run the git-tag-driven release, print results."""
    from .git.manager import GitManager
    from .publish import perform_stable_release

    console.print(
        "[bold]Release type[/bold] (Semantic Versioning):\n"
        "  [cyan]major[/cyan] — incompatible API changes\n"
        "  [cyan]minor[/cyan] — backward-compatible new functionality\n"
        "  [cyan]patch[/cyan] — backward-compatible bug fixes"
    )
    try:
        bump = Prompt.ask("Bump", choices=["major", "minor", "patch"], default="patch")
    except (KeyboardInterrupt, EOFError):
        return
    result = perform_stable_release(taxonomy_file, publish_dir, bump, GitManager(taxonomy_file))
    console.print(
        f"[green]✓[/green]  Published [bold]{result.version_str}[/bold], "
        f"tagged [bold]{result.tag}[/bold] ({len(result.artifacts)} files)"
    )
    if result.pushed:
        console.print(f"[dim]Pushed the commit and tag {result.tag} to origin.[/dim]")
    else:
        console.print(
            f"[dim]No remote configured — push manually: "
            f"git push && git push origin {result.tag}[/dim]"
        )


def _run_publish_interactive(files: list[Path]) -> None:  # pragma: no cover - interactive tty
    """Interactive Linked Data Publish & Version screen from the home-screen menu."""
    import webbrowser

    from rich.panel import Panel

    from . import viz_vowl as _viz
    from .publish import build_publish_menu, discover_published_pages

    console.print()

    target = _select_publish_target(files)
    if target is None:
        return
    taxonomy_file, taxonomy = target

    console.print(
        Panel(
            f"[bold]📦 Linked Data Publish & Version[/bold]\n"
            f"[dim]File: {taxonomy_file}[/dim]\n"
            f"[dim]Ontology URI: {taxonomy.ontology_uri}[/dim]"  # type: ignore[attr-defined]
            + (
                f"\n[dim]Current version: {taxonomy.version_info}[/dim]"  # type: ignore[attr-defined]
                if taxonomy.version_info  # type: ignore[attr-defined]
                else ""
            ),
            border_style="green",
        )
    )

    publish_dir = taxonomy_file.parent / "ontology"
    base_url = _viz.ensure_published_server(taxonomy, taxonomy_file)  # type: ignore[arg-type]

    while True:
        pages = discover_published_pages(publish_dir)
        rows = build_publish_menu(pages, base_url, publish_dir)
        console.print()
        sel = _arrow_menu_select([row.label for row in rows])
        if sel is None:
            return
        row = rows[sel]
        if row.action == "back":  # explicit "← Back to menu" row (Esc does the same)
            return
        if row.action == "publish_stable":
            _publish_stable_flow(taxonomy_file, publish_dir)
        elif row.url:
            webbrowser.open(row.url)
            console.print(f"[green]✓[/green]  Opened {row.url}")


@app.command("publish")
def cmd_publish(
    path: Path = typer.Argument(..., help="Taxonomy file to publish."),
    bump: str = typer.Option(
        "patch", "--bump", "-b", help="Semver bump for the stable release: major, minor, or patch."
    ),
    channel: str = typer.Option("stable", "--channel", "-c", help="Channel: stable or dev."),
    publish_dir: Path = typer.Option(
        Path("ontology"), "--dir", "-d", help="Directory to write artifacts."
    ),
    open_pages: bool = typer.Option(
        True, "--open/--no-open", help="Open the published dev pages in the browser (dev channel)."
    ),
) -> None:
    """Publish a new versioned release of the ontology.

    Stable channel: reads the latest ``<stem>/vX.Y.Z`` ontology tag, applies the
    bump, stamps the version into the file, commits, tags, and writes
    ontology/v{version}/ + ontology/latest/.
    Dev channel:    writes ontology/dev/ (overwrites, no history).
    """
    from rich.console import Console

    from .publish import PublishError, pre_flight
    from .store import load

    _con = Console()

    if not path.exists():
        err.print(f"[red]File not found:[/red] {path}")
        raise typer.Exit(1)

    taxonomy = load(path)

    try:
        pre_flight(taxonomy)
    except PublishError as e:
        err.print(f"[red]Publish blocked:[/red] {e}")
        raise typer.Exit(1)

    if channel == "dev":
        _publish_dev_channel(path, taxonomy, publish_dir, open_pages, _con)
    else:
        _publish_stable_channel(path, bump, publish_dir, _con)


def _publish_dev_channel(
    path: Path, taxonomy: object, publish_dir: Path, open_pages: bool, con: object
) -> None:
    """Write the dev channel from the file's current version (no tag, no commit)."""
    from .publish import _git_short_sha, _today_str, build_version_string, write_dev_artifacts

    vi = taxonomy.version_info  # type: ignore[attr-defined]
    base = vi.split("+")[0] if vi and "+" in vi else (vi or "0.1.0")
    version_str = build_version_string(base, _today_str(), _git_short_sha(path.parent))
    con.print(f"Publishing dev channel → [bold]{version_str}[/bold]")  # type: ignore[attr-defined]
    artifacts = write_dev_artifacts(path, publish_dir, version_str)
    con.print(  # type: ignore[attr-defined]
        f"[green]Written {len(artifacts)} artifact(s) → {publish_dir / 'dev'}[/green]"
    )
    if open_pages:
        _open_dev_artifacts_in_browser(taxonomy, path, publish_dir, artifacts)


def _publish_stable_channel(path: Path, bump: str, publish_dir: Path, con: object) -> None:
    """Run the git-tag-driven stable release and report what it published/pushed."""
    from .git.manager import GitManager
    from .publish import perform_stable_release, semver_bump_from_choice

    try:
        kind = semver_bump_from_choice(bump)
    except ValueError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    result = perform_stable_release(path, publish_dir, kind, GitManager(path))
    con.print(  # type: ignore[attr-defined]
        f"[green]✓[/green] Published [bold]{result.version_str}[/bold], "
        f"tagged [bold]{result.tag}[/bold] ({len(result.artifacts)} files)"
    )
    for a in result.artifacts:
        con.print(f"  {a}")  # type: ignore[attr-defined]
    if result.pushed:
        con.print(  # type: ignore[attr-defined]
            f"[dim]Pushed the commit and tag {result.tag} to origin.[/dim]"
        )
    else:
        con.print(  # type: ignore[attr-defined]
            f"[dim]No remote configured — push manually: "
            f"git push && git push origin {result.tag}[/dim]"
        )


def _is_taxonomy_arg(a: str) -> bool:
    return (
        a not in _SUBCOMMANDS
        and not a.startswith("-")
        and Path(a).suffix.lower() in _TAXONOMY_SUFFIXES
    )


def _try_dispatch_file_args(args: list[str]) -> bool:
    """If *args* are taxonomy files, open them in the home screen. Return True if handled."""
    import os
    import sys

    if not args or not _is_taxonomy_arg(args[0]):
        return False

    if not all(_is_taxonomy_arg(a) for a in args):
        sys.argv.insert(1, "show")
        return False

    paths = [p for a in args if (p := Path(a).resolve()).exists()]
    if not paths:
        return False

    os.chdir(paths[0].parent)
    _home_screen(initial_file=paths if len(paths) > 1 else paths[0])
    return True


def main() -> None:
    """Entry point.

    • ``ster``                   — interactive home screen (loops until Ctrl+C)
    • ``ster taxonomy.ttl``      — open the file, then the home screen for its folder
    • ``ster show taxonomy.ttl`` — one-shot viewer (plus the other subcommands)
    • ``ster <subcommand> …``    — delegate to Typer
    """
    import sys

    args = sys.argv[1:]

    # Non-bare invocation → delegate to Typer once (no loop)
    if args:
        if _try_dispatch_file_args(args):
            return
        app()
        return

    # ── Bare invocation → interactive home screen loop ────────────────────────
    _home_screen()


def _found_taxonomy_files() -> list[Path]:
    """Every taxonomy file in project config, current folder, and 1-level subfolders."""
    found: list[Path] = []
    proj = Project.load(Path.cwd())
    if proj:
        found.extend(proj.resolved_files())
    for pattern in _TAXONOMY_GLOBS:
        found.extend(Path.cwd().glob(pattern))
        found.extend(Path.cwd().glob(f"*/{pattern}"))
    return sorted(set(found))


def _print_home_intro() -> None:
    """Welcome banner + the one-time CI-workflow prompt."""
    global _ci_check_done
    _print_welcome()
    if _ci_check_done:
        return
    _ci_check_done = True
    from .init_ci import prompt_if_missing
    from .project import _git_root as _find_git_root

    _root = _find_git_root(Path.cwd())
    if _root and prompt_if_missing(_root):
        console.print(
            "[green]✓[/green] .github/workflows/taxonomy-ci.yml — commit and push to activate CI\n"
        )


def _open_selected_in_viewer(
    selected: list[Path], found: list[Path], project: Project | None
) -> None:
    """Persist the project, validate the workspace, then open the primary file in the viewer."""
    global _session_file
    git_root = _git_root(Path.cwd()) or Path.cwd()
    updated_project = Project(root=git_root, files=[], lang=project.lang if project else "en")
    for f in selected:
        updated_project.add_file(f)
    try:
        updated_project.save()
    except Exception:
        pass  # non-fatal if .ster/ can't be written
    try:
        ws = _load_workspace(selected, found)  # raises on broken mappings
    except Exception as exc:
        err.print(f"[red]Failed to load workspace: {exc}[/red]")
        return
    primary = selected[0]
    _save_session(primary)
    _session_file = primary
    try:
        _open_viewer(primary, workspace=ws, lang=updated_project.lang)
    except Exception as exc:
        err.print(f"[red]Viewer error: {exc}[/red]")


def _home_obtain_action(
    pending_open: Path | list[Path] | None, selected_file: Path | None, found: list[Path]
) -> tuple[Path | None, list[Path] | Path | None]:
    """One home-loop turn's ``(file, action)``.

    A pending file (``ster file.ttl``) or a freshly picked file opens straight in the
    viewer — no action menu in between. Once a file is selected and the viewer has
    closed, the next turn shows its action menu (SPARQL / publish / graph / import /
    change file). Returns ``action = _QUIT_SENTINEL`` when the user quits at selection."""
    if pending_open is not None:  # ster PATH/file.ttl → open directly
        if isinstance(pending_open, list):
            return pending_open[0], pending_open
        return pending_open, [pending_open]
    _print_home_intro()
    if selected_file is None or selected_file not in found:
        choice = _select_home_file(found)
        if choice is None:  # Quit / cancel
            return None, _QUIT_SENTINEL
        if choice == _DEMO_SENTINEL:  # a fresh demo, opened directly
            demo = _load_demo_into_cwd()
            return demo, [demo]
        if choice == _ALL_FILES_SENTINEL:
            return found[0], found
        if isinstance(choice, list):
            return choice[0], choice
        # A freshly picked file opens straight in the viewer — no action menu in
        # between. The menu (SPARQL / publish / graph / import / change file) is shown
        # only after the viewer closes, on the next loop turn for the same file.
        return choice, [choice]
    return selected_file, _home_action_menu(selected_file)


def _home_perform(
    action: list[Path] | Path | None,
    selected_file: Path | None,
    found: list[Path],
    project: Project | None,
) -> str:
    """Carry out a chosen home action → "quit", "change", or "continue"."""
    if action is _QUIT_SENTINEL or action is None:
        return "quit"
    if action is _CHANGE_FILE_SENTINEL:  # go back to file selection
        return "change"
    assert selected_file is not None  # set before any menu is shown
    if _dispatch_menu_action(action, [selected_file]):  # actions act on the chosen file
        return "continue"
    selected = action if isinstance(action, list) else [selected_file]
    _open_selected_in_viewer(selected, found, project)
    return "continue"


def _home_screen(initial_file: Path | list[Path] | None = None) -> None:
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
            # so an empty folder still gets a working picker — see _select_home_file.
            project = Project.load(Path.cwd())
            selected_file, action = _home_obtain_action(pending_open, selected_file, found)
            pending_open = None
        except (KeyboardInterrupt, EOFError):
            console.print()
            break

        outcome = _home_perform(action, selected_file, found, project)
        if outcome == "quit":
            break
        if outcome == "change":
            selected_file = None


if __name__ == "__main__":
    main()
