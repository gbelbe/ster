"""BDD step definitions for annotation-property criticity in the config modal."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store
from ster.metadata_coverage import MetaProp
from ster.tui.app import OntologyApp
from ster.tui.config_modal import _MetaCatalog, _MetaPropRow

scenarios("../features/tui/annotation_criticity.feature")

DEMO = Path(__file__).resolve().parents[1].parent / "ster" / "tui" / "demo.ttl"


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    """Redirect the catalog preference files to a temp dir (no real config touched)."""
    from ster.nav import prefs

    monkeypatch.setattr(prefs, "_metadata_props_path", lambda: tmp_path / "metaprops.json")
    monkeypatch.setattr(
        prefs, "_entity_metadata_props_path", lambda: tmp_path / "entity_metaprops.json"
    )


@pytest.fixture
def ctx(tmp_path):
    return {"tmp": tmp_path}


def _app(tmp_path) -> tuple:
    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src, lang="en"), src


# ── Given ─────────────────────────────────────────────────────────────────────


@given("the config modal is open on a fresh catalog")
def _open_fresh(ctx):
    pass  # a fresh (unconfigured) catalog is the default; each step opens its own app


def _inspect_catalog(ctx, cid: str, check) -> None:
    """Open a fresh app + config modal and run *check(catalog)* inside its run_test.

    Each step gets its own app so no OntologyApp is reused across event loops."""

    async def scenario():
        app, _src = _app(ctx["tmp"])
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.pause()
            await pilot.pause()
            await pilot.press("comma")
            await pilot.pause()
            check(app.screen.query_one(cid, _MetaCatalog))

    asyncio.run(scenario())


@given("a saved ontology catalog whose entries have no criticity")
def _legacy_saved(ctx):
    path = ctx["tmp"] / "metaprops.json"
    path.write_text(
        json.dumps([{"predicate": "http://x/a", "label": "ex:a"}]), encoding="utf-8"
    )  # legacy shape: no "criticity" field


# ── When ──────────────────────────────────────────────────────────────────────


def _set_first(ctx, cid: str, level: str) -> None:
    async def scenario():
        app, _src = _app(ctx["tmp"])
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.pause()
            await pilot.pause()
            await pilot.press("comma")
            await pilot.pause()
            row = app.screen.query_one(cid, _MetaCatalog).query(_MetaPropRow).first()
            ctx["target"] = row.checkbox.predicate
            row.set_criticity(level)  # posts Changed → app auto-saves
            for _ in range(3):
                await pilot.pause()

    asyncio.run(scenario())


@when(parsers.parse("I set the first ontology-metadata property to {level}"))
def _set_ont(ctx, level):
    _set_first(ctx, "#cfg-ont-meta", level)


@when(parsers.parse("I set the first entity-metadata property to {level}"))
def _set_entity(ctx, level):
    _set_first(ctx, "#cfg-entity-meta", level)


@when("the app loads the ontology catalog")
def _load_ont(ctx):
    from ster.nav.prefs import load_metadata_props

    ctx["loaded"] = load_metadata_props()


# ── Then ──────────────────────────────────────────────────────────────────────


@then("every ontology-metadata property offers mandatory, important and optional")
def _offers_three(ctx):
    from ster.tui.config_modal import _CritOption

    def check(cat):
        rows = cat.query(_MetaPropRow)
        assert rows
        for row in rows:
            assert [o.level for o in row.query(_CritOption)] == [
                "mandatory",
                "important",
                "optional",
            ]

    _inspect_catalog(ctx, "#cfg-ont-meta", check)


def _all_optional(cat) -> None:
    assert all(mp.criticity == "optional" for mp in cat.props())


@then("every ontology-metadata property defaults to optional")
def _defaults_optional(ctx):
    _inspect_catalog(ctx, "#cfg-ont-meta", _all_optional)


@then(parsers.parse("the saved catalog records that property as {level}"))
def _saved_ont(ctx, level):
    from ster.nav.prefs import load_metadata_props

    saved = {mp.predicate: mp.criticity for mp in (load_metadata_props() or [])}
    assert saved.get(ctx["target"]) == level


@then(parsers.parse("the saved entity catalog records that property as {level}"))
def _saved_entity(ctx, level):
    from ster.nav.prefs import load_entity_metadata_props

    saved = {mp.predicate: mp.criticity for mp in (load_entity_metadata_props() or [])}
    assert saved.get(ctx["target"]) == level


@then(parsers.parse("reopening the app loads that property as {level}"))
def _reopen_loads(ctx, level):
    app2, _src = _app(ctx["tmp"])  # a new app instance re-reads the persisted catalog
    saved = {mp.predicate: mp.criticity for mp in app2.metadata_props}
    assert saved.get(ctx["target"]) == level


@then("every loaded property is optional")
def _loaded_optional(ctx):
    assert ctx["loaded"] == [MetaProp("http://x/a", "ex:a", "optional")]
