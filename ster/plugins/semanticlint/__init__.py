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


def enforce_active() -> bool:
    """True when SHACL-rule authoring (the write side) is available: the plugin is
    active *and* its opt-in ``enforce`` feature is on. Every enforce entry point
    (property context menu, config catalog buttons) gates on this."""
    if not is_active():
        return False
    from . import config

    return config.feature_enabled("enforce")


__all__ = ["PLUGIN_ID", "deps", "enforce_active", "is_active"]
