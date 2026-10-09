"""The ``ster cache`` commands."""

from __future__ import annotations

import typer

from ..display import console
from ..store import _cache
from . import _app

cache_app = typer.Typer(help="Manage ster's saved graphs.", no_args_is_help=True)
_app.app.add_typer(cache_app, name="cache")


@cache_app.command("clear")
def cmd_cache_clear() -> None:
    """Delete the saved graphs; the next open of each project rebuilds from its files."""
    removed = _cache.clear_merged_caches()
    console.print(f"[green]Cleared[/green] {removed} saved file{'s' if removed != 1 else ''}.")
