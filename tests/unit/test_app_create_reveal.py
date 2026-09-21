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


def _reveals(tmp_path, lint_active: bool, settle) -> tuple[str | None, bool]:
    app = _app(tmp_path)
    buddy = ZOO + "Buddy"
    dog = ZOO + "Dog"

    # What this test is about is the *background* recompute, and the only honest
    # signal that it landed is the callback that applies it. `_lint_computed` is
    # not that signal: something recomputes synchronously during the rebuild, so
    # it is already True the instant the command returns — a predicate naming it
    # holds immediately and waits for nothing, which is how three earlier
    # conversions in this repo ended up vacuous (see #181, #184, d0af901).
    #
    # The old `for _ in range(6): await pilot.pause()` never reached the 1.5 s
    # debounce either, so the test ended with the worker still in flight; it then
    # landed during teardown and blew up rebuilding a tree that was already gone.
    landed: list[object] = []
    original = app._on_lint_ready

    def _record(result: object) -> None:
        original(result)
        landed.append(result)

    app._on_lint_ready = _record  # type: ignore[method-assign]

    def _revealed() -> bool:
        node = app._uri_nodes.get(buddy)
        return bool(node and node.parent and node.parent.is_expanded)

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
                if lint_active:
                    # Wait for the rebuild that could clobber the reveal, then look.
                    assert await settle(pilot, lambda: bool(landed)), (
                        "the background lint never landed"
                    )
                else:
                    # No background rebuild is coming; the reveal is the only thing
                    # to wait for, and a deadline proves it if it never arrives.
                    await settle(pilot, _revealed)
                node = app._uri_nodes.get(buddy)
                return app._detail_uri, bool(node and node.parent and node.parent.is_expanded)
        finally:
            sl.is_active = orig  # type: ignore[assignment]

    return asyncio.run(scenario())


def test_create_reveals_new_individual_plugin_off(tmp_path, settle):
    detail_uri, ancestor_expanded = _reveals(tmp_path, lint_active=False, settle=settle)
    assert detail_uri == ZOO + "Buddy"
    assert ancestor_expanded


def test_create_reveals_new_individual_survives_background_lint(tmp_path, settle):
    # The background recompute must not collapse the tree / clobber the reveal.
    detail_uri, ancestor_expanded = _reveals(tmp_path, lint_active=True, settle=settle)
    assert detail_uri == ZOO + "Buddy"
    assert ancestor_expanded
