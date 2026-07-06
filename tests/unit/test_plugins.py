"""Unit tests for the lightweight in-tree plugin registry + enable-state."""

from __future__ import annotations

import pytest

from ster import plugins


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    """Redirect prefs.json to a temp dir so plugin toggles don't touch real config."""
    from ster.nav import prefs

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")


def test_registry_lists_the_semanticlint_plugin() -> None:
    ids = {spec.id for spec in plugins.all_plugins()}
    assert "semanticlint" in ids
    spec = plugins.get("semanticlint")
    assert spec is not None
    assert spec.name and spec.description  # human-facing metadata present


def test_unknown_plugin_is_none() -> None:
    assert plugins.get("nope") is None


def test_plugins_are_disabled_by_default() -> None:
    assert plugins.is_enabled("semanticlint") is False


def test_set_enabled_round_trips_through_prefs() -> None:
    plugins.set_enabled("semanticlint", True)
    assert plugins.is_enabled("semanticlint") is True
    plugins.set_enabled("semanticlint", False)
    assert plugins.is_enabled("semanticlint") is False


def test_enabling_one_plugin_leaves_prefs_intact() -> None:
    from ster.nav.prefs import _load_prefs, _save_prefs

    _save_prefs({"theme": "solarized-light"})
    plugins.set_enabled("semanticlint", True)
    assert _load_prefs().get("theme") == "solarized-light"  # merge, not overwrite
