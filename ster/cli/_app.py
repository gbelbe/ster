"""Typer app instance, global --version handling, and the startup welcome banner."""

from __future__ import annotations

import json
import re
import tempfile
import threading
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console

from .._version import __version__ as _VERSION
from ..display import console

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
    ask_again: bool = typer.Option(  # noqa: ARG001
        False,
        "--ask-again",
        help="Forget the remembered subfolder answer and context-file choices, then ask afresh.",
    ),
) -> None:
    """Suppress Typer's default no-args behaviour; main() handles it.

    ``--ask-again`` is declared here only so ``ster --help`` lists it: main()
    takes it out of the arguments before Typer ever sees them.
    """


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
    """Return True if version string *a* is greater than *b*, by PEP 440.

    The hand-rolled split this replaces called ``int()`` on every dot-separated
    part, so a local build — ``0.22.1.dev14+g3c6ac5c3a`` — raised on
    ``dev14+g3c6ac5c3a`` and fell back to ``(0,)``. Every PyPI release then
    compared as newer, and anyone working from a checkout was told on every
    launch to "upgrade" to a version years behind their own.

    PEP 440 gets the cases that matter here right: 0.22.1.dev14 is ahead of a
    0.10.0 release, and behind a 0.22.1 final — which is exactly when someone on
    a dev build *should* hear about a release.
    """
    from packaging.version import InvalidVersion, Version  # noqa: PLC0415

    try:
        return Version(a) > Version(b)
    except InvalidVersion:
        # An unparseable version is not grounds for nagging someone to upgrade.
        return False


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
