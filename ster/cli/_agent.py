"""The home menu's "Agent: talk to graph" entry (the talk_to_graph plugin)."""

from __future__ import annotations

from pathlib import Path

from . import _app


def _run_agent_page_interactive(files: list[Path]) -> None:  # pragma: no cover - interactive tty
    """Start ster's server if needed, start the page for this file's folder, and open it in the browser."""
    from ..api_server import load_server_config
    from ..plugins import talk_to_graph
    from ..tui.query import open_browser
    from . import _publish

    if not files:
        _app.err.print("[red]No taxonomy files found.[/red]")
        return
    if not _publish._reuse_or_start_server(files[0]):
        return
    url, port = load_server_config()
    address, why = talk_to_graph.page_url(files[0], url, port)
    if address is None:
        _app.err.print(f"[red]{why}[/red]")
        return
    if not open_browser(address):
        _app.err.print(f"Open {address} in your browser.")
