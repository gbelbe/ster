"""Unified-diff rendering for the terminal."""

from __future__ import annotations

from . import _console


def render_diff(diff: str, max_lines: int = 60) -> None:
    """Print a unified diff using Rich markup colours."""
    lines = diff.splitlines()[:max_lines]
    for line in lines:
        if line.startswith("+") and not line.startswith("+++"):
            _console.console.print(f"[green]{line}[/green]")
        elif line.startswith("-") and not line.startswith("---"):
            _console.console.print(f"[red]{line}[/red]")
        elif line.startswith("@@"):
            _console.console.print(f"[cyan]{line}[/cyan]")
        else:
            _console.console.print(f"[dim]{line}[/dim]")
    if len(diff.splitlines()) > max_lines:
        _console.console.print(f"[dim]… {len(diff.splitlines()) - max_lines} more lines[/dim]")
