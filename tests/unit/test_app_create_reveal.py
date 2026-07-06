"""Regression: creating an entity must navigate to and reveal it in the tree.

Root cause of the reported 'add individual doesn't work': the create succeeded but
``_apply_command`` re-showed the *parent* class and rebuilt the tree collapsed, so
the new individual was invisible. The background lint recompute (when the
semanticlint plugin is active) then rebuilt the tree a second time, undoing any
reveal — so the fix must survive both the plugin-off and plugin-on paths.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ster import store
from ster.core.commands import OwlCreateIndividualFull
from ster.tui.app import OntologyApp

DEMO = Path(__file__).resolve().parents[1].parent / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    from ster.nav import prefs
    from ster.plugins.semanticlint import config

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(prefs, "_lang_prefs_path", lambda: tmp_path / "lang.json")
    monkeypatch.setattr(prefs, "_configured_langs_path", lambda: tmp_path / "clangs.json")
    monkeypatch.setattr(prefs, "_metadata_props_path", lambda: tmp_path / "metaprops.json")
    monkeypatch.setattr(prefs, "_entity_metadata_props_path", lambda: tmp_path / "emeta.json")
    monkeypatch.setattr(config, "_config_path", lambda: tmp_path / "quality.json")


def _app(tmp_path: Path) -> OntologyApp:
    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src)


def _reveals(tmp_path, lint_active: bool) -> tuple[str | None, bool]:
    app = _app(tmp_path)
    buddy = ZOO + "Buddy"
    dog = ZOO + "Dog"

    async def scenario():
        import ster.plugins.semanticlint as sl

        orig = sl.is_active
        sl.is_active = lambda: lint_active  # type: ignore[assignment]
        try:
            async with app.run_test(size=(120, 44)) as pilot:
                await pilot.pause()
                app._apply_command(
                    OwlCreateIndividualFull(app._path, buddy, dog, (("en", "Buddy"),)),
                    select=buddy,
                )
                for _ in range(6):
                    await pilot.pause()
                node = app._uri_nodes.get(buddy)
                return app._detail_uri, bool(node and node.parent and node.parent.is_expanded)
        finally:
            sl.is_active = orig  # type: ignore[assignment]

    return asyncio.run(scenario())


def test_create_reveals_new_individual_plugin_off(tmp_path):
    detail_uri, ancestor_expanded = _reveals(tmp_path, lint_active=False)
    assert detail_uri == ZOO + "Buddy"
    assert ancestor_expanded


def test_create_reveals_new_individual_survives_background_lint(tmp_path):
    # The background recompute must not collapse the tree / clobber the reveal.
    detail_uri, ancestor_expanded = _reveals(tmp_path, lint_active=True)
    assert detail_uri == ZOO + "Buddy"
    assert ancestor_expanded
