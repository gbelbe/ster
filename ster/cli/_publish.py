"""The home menu's MCP connection screen: starting or reusing the server, the connection details, port conflicts."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Final

from .. import ask
from ..display import console
from . import _app


def mcp_connection_info(base_url: str, token: str) -> tuple[str, str]:
    """Return (endpoint, config_snippet) for an MCP client.

    The snippet is the ``mcpServers`` object every MCP-capable client reads —
    the endpoint is plain JSON-RPC over HTTP with a bearer token, so nothing
    here is specific to one vendor's CLI.
    """
    endpoint = f"{base_url.rstrip('/')}/mcp"
    snippet = json.dumps(
        {
            "mcpServers": {
                "ster": {
                    "type": "http",
                    "url": endpoint,
                    "headers": {"Authorization": f"Bearer {token}"},
                }
            }
        },
        indent=2,
    )
    return endpoint, snippet


def _print_mcp_connection(endpoint: str, token: str, snippet: str, copied: bool) -> None:
    """Show the endpoint, how to connect, and whether the copy landed."""
    console.print()
    console.print(f"  [bold]MCP endpoint[/bold]   [cyan]{endpoint}[/cyan]")
    console.print("  [bold]Transport[/bold]      HTTP (JSON-RPC 2.0)")
    console.print(f"  [bold]Auth header[/bold]    Authorization: Bearer {token}")
    console.print()
    console.print("  Point any MCP-capable agent at it — add this to its config:")
    console.print()
    # markup=False throughout: these lines carry a URL, a token and JSON, and a
    # "[" anywhere in them would otherwise be parsed as a Rich tag. It is also what
    # keeps the trailing "\" below intact — Rich reads "\[" as an escaped bracket,
    # so the continuation backslash used to be swallowed and "[/dim]" printed as
    # text, leaving a command that could not be pasted.
    for line in snippet.splitlines():
        console.print(f"    {line}", style="dim", markup=False)
    console.print()
    console.print("  Claude Code, for example:")
    console.print(
        f"    claude mcp add --transport http ster {endpoint} \\", style="dim", markup=False
    )
    console.print(
        '      --header "Authorization: Bearer $(cat ~/.config/ster/api_token)"',
        style="dim",
        markup=False,
    )
    console.print()
    if copied:
        console.print("  [green]✓[/green] endpoint copied to clipboard")
    else:
        console.print("  [yellow]![/yellow] could not reach the clipboard — copy the URL above")
    console.print()


def _pause_until_acknowledged(
    read: Callable[[str], object] | None = None, is_tty: bool | None = None
) -> None:
    """Hold the screen until the reader is done with what was just printed.

    Returning to the home menu reprints the banner and the action list — about 30
    lines — directly over whatever an action left on screen. Without this pause a
    25-line block like the MCP connection details is gone before it can be read on
    any terminal shorter than 55 rows.

    Skipped when there is no terminal: a piped or scripted run has nobody to press
    Enter, and waiting would hang it.
    """
    import sys

    if is_tty is None:
        is_tty = sys.stdin.isatty() and sys.stdout.isatty()
    if not is_tty:
        return
    reader = read if read is not None else input
    try:
        reader("  Press Enter to return to the menu… ")
    except (EOFError, KeyboardInterrupt):
        console.print()


def _print_problem(reason: str) -> None:
    """Print a reason clause (see ``unavailable_reason``) as a red, capitalised sentence."""
    _app.err.print(f"[red]{reason[:1].upper()}{reason[1:]}[/red]")


def _report_unavailable(host: str, port: int) -> None:
    """Print why the server at *host*:*port* is not something we can use."""
    from ..viz_vowl import unavailable_reason

    _print_problem(unavailable_reason(host, port))


# Sentinel: the port is usable and the caller should start a fresh server —
# distinct from a reused URL (a str) and "give up" (None).
_START_FRESH: Final = object()


def _confirm_replace(question: str) -> bool:
    """Ask before closing another ``ster serve`` — default no, it may be someone's open view."""
    return ask.confirm(question, default=False, console=console)


def _resolve_port_conflict(
    taxonomy_file: Path, base_url: str, host: str, port: int
) -> str | object | None:
    """Settle a process already holding the configured server port.

    Returns the base URL to reuse when a healthy server of this build already
    serves *taxonomy_file*, None when connecting should be abandoned, or
    :data:`_START_FRESH` when the port is usable (it was free, or a stale
    ``ster serve`` was closed) and the caller should start a server.
    """
    from ..viz_vowl import claim_port
    from ..viz_vowl._claim import BLOCKED, REUSE

    claim = claim_port(taxonomy_file, _confirm_replace, host, port)
    if claim.outcome == REUSE:
        console.print(
            f"\n  [green]✓[/green] ster is already serving [bold]{taxonomy_file.name}[/bold] "
            f"at {base_url} — reusing it."
        )
        return base_url
    if claim.outcome == BLOCKED:
        _print_problem(claim.message)
        return None
    return _START_FRESH


def _reuse_or_start_server(taxonomy_file: Path) -> str | None:  # pragma: no cover - interactive tty
    """The running server's base URL for *taxonomy_file*, starting one if needed.

    Ster's own server is idempotent in-process — a second ``ensure_published_server``
    call just republishes onto it. But a *separate* ster process — an earlier
    ``ster serve``, or a previous interactive session that never exited — can
    already hold the configured port. Binding then fails with "address in use",
    which used to be reported as a broken fastapi/uvicorn install even though a
    perfectly good MCP endpoint was sitting right there.

    Detect that case via :func:`_resolve_port_conflict`: a healthy server already
    serving *taxonomy_file* is reused as-is (nothing to ask), one serving a
    different file is offered a restart, and anything else falls back to the
    same accurate reason :func:`ster.viz_vowl.unavailable_reason` gives the
    graph viewer.
    """
    from .. import store
    from ..api_server import is_running, load_server_config
    from ..project import Project
    from ..viz_vowl import ensure_published_server

    url, port = load_server_config()
    host = url.split("://", 1)[-1]
    base_url = f"{url}:{port}"

    if not is_running():
        outcome = _resolve_port_conflict(taxonomy_file, base_url, host, port)
        if outcome is not _START_FRESH:
            return outcome  # type: ignore[return-value]  # a reused URL, or None (abandoned)

    # An MCP agent queries the whole connected graph, same as the graph viewer —
    # not just the one writable file. The other files a project already merges
    # in read-only beside it (ster edit / ster serve -x, remembered per-project
    # in .ster/project.json) come along here too, or SPARQL against an ontology
    # or provenance file split out from the taxonomy would silently see nothing.
    project = Project.load(Path.cwd())
    context = project.remembered_context(taxonomy_file) if project else []
    context_note = (
        f" [dim](+ {', '.join(f.name for f in context)} as read-only context)[/dim]"
        if context
        else ""
    )
    console.print(
        f"\n  Starting the ster server for [bold]{taxonomy_file.name}[/bold]{context_note}…"
    )
    result = ensure_published_server(store.load(taxonomy_file, context=context), taxonomy_file)
    if not result:
        _report_unavailable(host, port)
    return result


def _run_mcp_connect_interactive(files: list[Path]) -> None:  # pragma: no cover - interactive tty
    """Start the live server if needed, then show and copy the MCP endpoint.

    The action menu has already narrowed the session to one file — this
    connects *that* file rather than asking again which one to use.
    """
    from ..api_server import load_token
    from ..tui.clipboard import copy_to_system_clipboard

    if not files:
        _app.err.print("[red]No taxonomy files found.[/red]")
        return
    taxonomy_file = files[0]

    base_url = _reuse_or_start_server(taxonomy_file)
    if not base_url:
        return

    endpoint, snippet = mcp_connection_info(base_url, load_token())
    _print_mcp_connection(endpoint, load_token(), snippet, copy_to_system_clipboard(endpoint))
    _pause_until_acknowledged()
