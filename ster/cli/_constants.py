"""Sentinel paths, ANSI menu colours, and other CLI-wide constants."""

from __future__ import annotations

from pathlib import Path

from . import _app

# Sentinels returned by _pick_file_interactive for special menu entries
_HTML_SENTINEL: Path = Path(".__ster_html__")
_GRAPH_SENTINEL: Path = Path(".__ster_graph__")
_CHANGE_FILE_SENTINEL: Path = Path(".__ster_change_file__")  # home menu → reselect the file
_QUERY_SENTINEL: Path = Path(".__ster_query__")
_EXT_ONT_SENTINEL: Path = Path(".__ster_ext_ont__")
_PUBLISH_SENTINEL: Path = Path(".__ster_publish__")
_DEMO_SENTINEL: Path = Path(".__ster_demo__")  # home menu → load the bundled sample
_MCP_SENTINEL: Path = Path(".__ster_mcp__")  # home menu → start MCP + copy endpoint
_HISTORY_SENTINEL: Path = Path(".__ster_history__")  # home menu → semantic history
_QUIT_SENTINEL: Path = Path(".__ster_quit__")
_PICKER_RETRY: Path = Path(
    ".__ster_picker_retry__"
)  # _pick_file_interactive: invalid input, loop again

# The bundled mixed SKOS+OWL sample, shipped inside the package (ster/tui/).
_DEMO_FILE: Path = Path(__file__).parent.parent / "tui" / "mixed-gear-demo.ttl"

# Home action-menu row colours (ANSI), keyed by sentinel; ``True`` = the "open" action.
_MENU_COLOURS: dict[object, str] = {
    True: _app._ANSI_BRIGHT_CYAN,  # bright cyan — TTL Viewer-Editor (the primary action)
    _GRAPH_SENTINEL: _app._ANSI_YELLOW,
    _QUERY_SENTINEL: _app._ANSI_GREEN,
    _EXT_ONT_SENTINEL: _app._ANSI_MAGENTA,
    _HTML_SENTINEL: _app._ANSI_BLUE,
    _PUBLISH_SENTINEL: _app._ANSI_GREEN,
    _DEMO_SENTINEL: _app._ANSI_GREEN,
    _MCP_SENTINEL: _app._ANSI_MAGENTA,
    _HISTORY_SENTINEL: _app._ANSI_YELLOW,
    _CHANGE_FILE_SENTINEL: _app._ANSI_CYAN,
    _QUIT_SENTINEL: _app._ANSI_RED,
}
