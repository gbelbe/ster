"""The optional rdfdiff-backed semantic history plugin."""

from __future__ import annotations

from ster import plugins as _plugins

from . import deps

PLUGIN_ID = "semanticdiff"


def is_active() -> bool:
    """True when semantic history is enabled and rdfdiff is importable."""
    return _plugins.is_enabled(PLUGIN_ID) and deps.is_installed()


__all__ = ["PLUGIN_ID", "deps", "is_active"]
