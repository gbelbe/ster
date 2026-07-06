"""Persistent enable/disable state for plugins.

Backed by the shared, merged ``~/.config/ster/prefs.json`` (the same file that
stores ``theme``), using a flat dotted key per plugin so a write never clobbers
other preferences.
"""

from __future__ import annotations

from ster.nav.prefs import _load_prefs, _save_prefs


def _key(plugin_id: str) -> str:
    return f"plugin.{plugin_id}.enabled"


def is_enabled(plugin_id: str) -> bool:
    """Whether *plugin_id* is currently activated (disabled by default)."""
    return bool(_load_prefs().get(_key(plugin_id), False))


def set_enabled(plugin_id: str, value: bool) -> None:
    """Persist the activation state for *plugin_id* (merged into prefs.json)."""
    _save_prefs({_key(plugin_id): bool(value)})
