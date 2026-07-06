"""The semanticlint plugin: all of ster's semanticlint usage lives here.

Importing this package is cheap — it does **not** import the ``semanticlint`` library
(that happens lazily inside :mod:`runner`/:mod:`checks`, only once the plugin is both
enabled and installed). Ster code asks :func:`is_active` before touching any lint
functionality, so a disabled or uninstalled plugin is inert everywhere.
"""

from __future__ import annotations

from ster import plugins as _plugins

from . import deps

PLUGIN_ID = "semanticlint"


def is_active() -> bool:
    """True when the plugin is enabled in prefs *and* semanticlint is installed."""
    return _plugins.is_enabled(PLUGIN_ID) and deps.is_installed()


__all__ = ["PLUGIN_ID", "deps", "is_active"]
