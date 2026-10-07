"""Persistent enable/disable state for plugins.

Backed by the shared, merged ``~/.config/ster/prefs.json`` (the same file that
stores ``theme``), using a flat dotted key per plugin so a write never clobbers
other preferences.
"""

from __future__ import annotations

import os

from ster.nav.prefs import _load_prefs, _save_prefs

# For this process only, never written to prefs.json. Set by a command-line option (``ster serve --mcp``) or by the
# environment (``STER_PLUGIN_MCP=1``), so a launch can switch a plugin on or off without touching the saved choice.
# A choice made in the config screen afterwards replaces it: the person at the keyboard has the last word.
_overrides: dict[str, bool] = {}
_env_read = False
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def override(plugin_id: str, value: bool | None) -> None:
    """Force *plugin_id* on or off for this run (``None`` removes the override)."""
    global _env_read
    _env_read = True  # an explicit call outranks the environment
    if value is None:
        _overrides.pop(plugin_id, None)
    else:
        _overrides[plugin_id] = bool(value)


def _read_environment() -> None:
    global _env_read
    if _env_read:
        return
    _env_read = True
    for name, raw in os.environ.items():
        if name.startswith("STER_PLUGIN_") and (word := raw.strip().lower()) in _TRUE | _FALSE:
            _overrides.setdefault(name.removeprefix("STER_PLUGIN_").lower(), word in _TRUE)


def _key(plugin_id: str) -> str:
    return f"plugin.{plugin_id}.enabled"


# Plugins that were renamed: the new id reads the old id's saved choice until it
# has one of its own, so nobody has to switch the plugin on again.
_FORMER_IDS = {"mcp": "mcp_query_trace"}


def is_enabled(plugin_id: str) -> bool:
    """Whether *plugin_id* is currently activated (disabled by default)."""
    _read_environment()
    if plugin_id in _overrides:
        return _overrides[plugin_id]
    prefs = _load_prefs()
    if _key(plugin_id) not in prefs and plugin_id in _FORMER_IDS:
        return bool(prefs.get(_key(_FORMER_IDS[plugin_id]), False))
    return bool(prefs.get(_key(plugin_id), False))


def set_enabled(plugin_id: str, value: bool) -> None:
    """Persist the activation state for *plugin_id* (merged into prefs.json)."""
    _overrides.pop(plugin_id, None)  # the explicit choice replaces any launch-time override
    _save_prefs({_key(plugin_id): bool(value)})
