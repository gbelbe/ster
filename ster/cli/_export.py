"""The graph viewer's launcher from the home menu, and the helpers the edit commands share."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from .. import ask
from ..display import console
from ..model import Taxonomy

_LIT_GREEN: Final = "  [green]✓[/green]  "
_LIT_BOLD: Final = "[/bold]…"
_LIT_RED: Final = "[/red]"


from . import _app, _taxonomy_io

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
    from .. import viz_vowl as _viz

    if not files:
        _app.err.print("[red]No taxonomy files found.[/red]")
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
            choice = ask.text(
                "File to visualise",
                default="1",
            )
        except (KeyboardInterrupt, EOFError):
            console.print(_app._CANCELLED_MESSAGE)
            return
        try:
            idx = int(choice.strip()) - 1
            taxonomy_file = files[idx]
        except (ValueError, IndexError):
            _app.err.print("[red]Invalid choice.[/red]")
            return

    taxonomy = _taxonomy_io._load_safe(taxonomy_file)
    if taxonomy is None:
        return
    console.print(f"\n[dim]Opening graph for[/dim] [bold]{taxonomy_file.name}{_LIT_BOLD}")
    if not _free_graph_port(taxonomy_file):  # a held port would block the live view
        return
    try:
        out = _viz.open_in_browser(taxonomy, taxonomy_file)
        console.print(f"{_LIT_GREEN}{out}")
    except Exception as exc:
        _app.err.print(f"[red]Graph error: {exc}{_LIT_RED}")


def _free_graph_port(taxonomy_file: Path) -> bool:
    """Make the live-server port usable for the graph; False when it cannot be.

    A previous ``ster serve`` is closed only after the reader agrees (it may be a
    view they are looking at); an interactive ster session or a process that is
    not ster is never closed — the reason is printed instead. No-op when our own
    server is already live or the port is free.
    """
    from .. import viz_vowl as _viz
    from ._publish import _confirm_replace

    if _viz.is_live_server():
        return True
    claim = _viz.claim_port(taxonomy_file, _confirm_replace)
    if claim.outcome == "blocked":
        _app.err.print(f"[red]Graph error: {claim.message}{_LIT_RED}")
        return False
    return True
