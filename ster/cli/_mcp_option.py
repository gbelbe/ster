"""The ``--mcp/--no-mcp`` option: the MCP plugin (query traces and Talk to graph) for one run, from the command line."""

from __future__ import annotations

import typer

HELP = (
    "Switch the MCP plugin on or off for this run: record agents' queries as traces and offer "
    "Talk to graph. Not saved; without it the Config > Plugins choice applies "
    "(or STER_PLUGIN_MCP=1)."
)


def option() -> object:
    """The typer option, shared by every command that starts a server or the viewer."""
    return typer.Option(None, "--mcp/--no-mcp", help=HELP)


def apply(mcp: bool | None) -> None:
    """Make *mcp* the plugin's state for this process; ``None`` leaves the saved choice alone."""
    if mcp is not None:
        from ..plugins import override  # noqa: PLC0415

        override("mcp", mcp)
