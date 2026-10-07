"""The "talk to graph" half of the MCP plugin: a local page where the user's own agent answers about this graph.

The page is its own package (``agent_app``, shipped in the same wheel) and runs in its own process. This adapter is
all ster knows of it: whether the option is on, whether an agent could answer, and how to open the page for a file.
It imports nothing of the page's web server, so a menu redraw stays cheap.
"""

from __future__ import annotations

from pathlib import Path

from ster import plugins as _plugins

PLUGIN_ID = "mcp"  # one switch: the page lives on the traces the MCP plugin records


def is_enabled() -> bool:
    """True when the MCP plugin is on in the config's Plugins tab (it records the traces and offers the page)."""
    return _plugins.is_enabled(PLUGIN_ID)


def agent_ready() -> bool:
    """True when the option is on *and* an agent or a tool-capable model server is usable right now."""
    if not is_enabled():
        return False
    from agent_app.launcher import has_usable_agent  # noqa: PLC0415

    return has_usable_agent()


def page_url(taxonomy_file: Path, ster_url: str, ster_port: int) -> tuple[str | None, str | None]:
    """``(address, None)`` of the page for the ster on *ster_port*, started if needed; or ``(None, why)``.

    One page per open graph: it follows whatever that ster serves. The project folder of *taxonomy_file* (see
    ``ster.project.home_of``) is where its history and the traces live.
    """
    from agent_app.launcher import ensure_running  # noqa: PLC0415

    from ster.project import home_of  # noqa: PLC0415

    launch = ensure_running(home_of(taxonomy_file), ster_url.split("://", 1)[-1], ster_port)
    return launch.url, launch.error


__all__ = ["PLUGIN_ID", "agent_ready", "is_enabled", "page_url"]
