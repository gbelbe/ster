"""BDD step definitions for the annotation-property library search & add."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store
from ster.tui import annotation_library as lib
from ster.tui.app import OntologyApp
from ster.tui.config_modal import _MetaCatalog, _MetaCheckbox

scenarios("../features/tui/annotation_library.feature")

DEMO = Path(__file__).resolve().parents[1].parent / "ster" / "tui" / "demo.ttl"


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    """Keep the app off the developer's real config (prefs, plugin flags, quality.json)."""
    from ster.nav import prefs
    from ster.plugins.semanticlint import config

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(prefs, "_lang_prefs_path", lambda: tmp_path / "lang.json")
    monkeypatch.setattr(prefs, "_configured_langs_path", lambda: tmp_path / "clangs.json")
    monkeypatch.setattr(prefs, "_metadata_props_path", lambda: tmp_path / "metaprops.json")
    monkeypatch.setattr(prefs, "_entity_metadata_props_path", lambda: tmp_path / "emeta.json")
    monkeypatch.setattr(config, "_config_path", lambda: tmp_path / "quality.json")


@pytest.fixture
def ctx(tmp_path):
    return {"tmp": tmp_path}


def _app(tmp_path) -> tuple:
    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src, lang="en"), src


# ── search / library ──────────────────────────────────────────────────────────


@when(parsers.parse('I search the annotation library for "{intent}"'), target_fixture="ctx")
def _search(ctx, intent):
    ctx["results"] = {p.label for p in lib.search(intent)}
    return ctx


@then(parsers.parse('"{label}" is among the results'))
def _among_results(ctx, label):
    assert label in ctx["results"]


@given("the annotation library")
def _the_library(ctx):
    ctx["preds"] = {p.predicate for p in lib.all_props()}


@then(parsers.parse('it does not offer "{predicate}"'))
def _not_offered(ctx, predicate):
    assert predicate not in ctx["preds"]


@then(parsers.parse('it offers "{predicate}"'))
def _offered(ctx, predicate):
    assert predicate in ctx["preds"]


# ── add via the config modal ────────────────────────────────────────────────────


@given("the config modal is open on the Annotation properties tab")
def _open_config(ctx):
    ctx["app"], ctx["src"] = _app(ctx["tmp"])


@when(parsers.parse('I pick "{predicate}" from the library'))
def _pick(ctx, predicate):
    async def scenario():
        app = ctx["app"]
        async with app.run_test(size=(120, 48)) as pilot:
            await pilot.pause()
            await pilot.pause()
            await pilot.press("comma")
            await pilot.pause()
            cat = app.screen.query_one("#cfg-ont-meta", _MetaCatalog)
            await cat._on_library_pick(predicate)
            await pilot.pause()
            ctx["preds"] = {cb.predicate for cb in cat.query(_MetaCheckbox)}

    asyncio.run(scenario())


@then(parsers.parse('"{predicate}" is in the ontology-metadata catalog'))
def _in_catalog(ctx, predicate):
    assert predicate in ctx["preds"]
