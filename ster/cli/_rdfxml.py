"""RDF/XML <-> Turtle conversion prompts."""

from __future__ import annotations

from pathlib import Path

from rich.prompt import Confirm

from .. import store
from ..display import console
from . import _state

# ──────────────────────────── RDF/XML conversion helpers ─────────────────────


def _maybe_prompt_rdfxml_convert(resolved: Path) -> Path:
    """If *resolved* is RDF/XML and not yet checked this session, prompt the user
    to convert it to Turtle.  Returns the path to use (may be the new .ttl file).
    """
    if _state.rdfxml_checked or not store.is_rdfxml_path(resolved):
        return resolved
    _state.rdfxml_checked = True
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
    _state.converted_from = original
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
