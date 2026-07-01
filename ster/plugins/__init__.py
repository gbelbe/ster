"""In-tree, opt-in feature plugins for ster.

ster has no external plugin-discovery mechanism; instead a small registry lists
the available in-tree plugins as lightweight metadata (:class:`PluginSpec`), and a
global enable flag (persisted in ``~/.config/ster/prefs.json``) turns each one on
or off. The heavy implementation of a plugin (and any optional third-party
dependency it needs) is imported lazily, only when the plugin is enabled — so a
disabled plugin costs nothing and leaves no UI or import behind.

The public surface is intentionally tiny::

    plugins.all_plugins()          # -> list[PluginSpec]
    plugins.get("semanticlint")    # -> PluginSpec | None
    plugins.is_enabled("semanticlint")
    plugins.set_enabled("semanticlint", True)
"""

from __future__ import annotations

from .registry import PluginSpec, all_plugins, get
from .state import is_enabled, set_enabled

__all__ = ["PluginSpec", "all_plugins", "get", "is_enabled", "set_enabled"]
