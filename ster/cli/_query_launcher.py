"""SPARQL query launcher and the home-screen action-menu dispatcher."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from rich.prompt import Confirm, Prompt

from ..display import console
from . import _app, _constants, _export, _publish

# ──────────────────────────── SPARQL query launcher ─────────────────────────


def _launch_ext_ontologies(found: list[Path]) -> None:  # noqa: ARG001
    """Home-menu action: open the external-ontologies import screen."""
    from ..ext_ontologies_ui import run_ext_ontologies_screen

    run_ext_ontologies_screen(taxonomy=None)


def _dispatch_menu_action(selected: object, found: list[Path]) -> bool:
    """Run the home-menu handler for a sentinel selection. True when handled.

    A plain list/file selection (not a sentinel) returns False so the caller
    falls through to the open-file path.
    """
    actions: dict[Path, Callable[[list[Path]], None]] = {
        _constants._HTML_SENTINEL: _export._run_html_export_interactive,
        _constants._GRAPH_SENTINEL: _export._run_graph_viz_interactive,
        _constants._QUERY_SENTINEL: _launch_query,
        _constants._EXT_ONT_SENTINEL: _launch_ext_ontologies,
        _constants._PUBLISH_SENTINEL: _publish._run_publish_interactive,
        _constants._MCP_SENTINEL: _publish._run_mcp_connect_interactive,
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

    dest = Path.cwd() / _constants._DEMO_FILE.name
    if dest.exists() and dest.read_bytes() != _constants._DEMO_FILE.read_bytes():
        _offer_keep_demo_edits(dest)  # the local copy diverged → let the user keep it
    shutil.copyfile(_constants._DEMO_FILE, dest)  # reset to a fresh demo every time
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

    if not Confirm.ask(
        "The demo has your edits — save them to a new file before resetting?",
        default=True,
        console=console,
    ):
        return
    name = Prompt.ask("Save your work as", default="my-ontology.ttl", console=console).strip()
    if not name or Path(name).name == _constants._DEMO_FILE.name:  # never clobber the demo itself
        name = "my-ontology.ttl"
    if not name.endswith(".ttl"):
        name += ".ttl"
    target = Path.cwd() / Path(name).name
    shutil.copyfile(dest, target)
    console.print(f"[green]Saved your work → {target.name}[/green]")


def _launch_query(found: list[Path]) -> None:
    """Open the New-TUI straight into the SPARQL query screen for the primary file."""
    if not found:
        _app.err.print("[red]No taxonomy files to query.[/red]")
        return
    primary = found[0]
    from ..tui import launch_file

    launch_file(primary, source=primary.name, open_query=True)
