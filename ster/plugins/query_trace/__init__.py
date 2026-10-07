"""Ster adapter for the portable MCP query-trace module."""

from pathlib import Path

from .panel import TracePanel
from .sessions import TraceSession, sessions_for_project


def follow_setting(file_path: Path | None) -> None:
    """Make a server record (or not) as the MCP plugin says, beside the file it serves.

    An environment that names a tracing state (``STER_QUERY_TRACE``) wins, so a runner can set it explicitly.
    Otherwise the plugin's switch in Config decides, and it applies from the first call rather than only after the
    box is toggled, so Talk to graph has its history whichever way ster was started.
    """
    from ster import plugins  # noqa: PLC0415
    from ster.project import home_of  # noqa: PLC0415
    from ster.query_trace import (  # noqa: PLC0415
        configure,
        configure_from_environment,
        environment_configured,
    )

    if environment_configured():
        configure_from_environment()
    elif file_path is not None and plugins.is_enabled("mcp"):
        configure(True, str(home_of(file_path) / ".ster" / "query-traces"))


__all__ = ["TracePanel", "TraceSession", "follow_setting", "sessions_for_project"]
