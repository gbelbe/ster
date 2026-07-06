"""BDD step definitions for the full add/edit individual modal."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store
from ster.tui.app import OntologyApp
from ster.tui.context_menu import ContextMenu
from ster.tui.individual_modal import IndividualModal

scenarios("../features/tui/individual_modal.feature")

DEMO = Path(__file__).resolve().parents[1].parent / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"


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
def ctx():
    return {}


def _app(tmp_path: Path) -> tuple:
    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src), src


def _ind(ctx, name):  # noqa: ANN001
    return ctx["app"].tax.owl_individuals.get(ZOO + name)


# ── Given ─────────────────────────────────────────────────────────────────────


@given("the zoo ontology is open")
def _open(ctx, tmp_path):
    ctx["app"], ctx["src"] = _app(tmp_path)


# ── When ──────────────────────────────────────────────────────────────────────


@when(
    parsers.parse(
        'I add an individual "{name}" of "{cls}" with label "{label}" and comment "{comment}"'
    )
)
def _add_full(ctx, name, cls, label, comment):
    async def scenario():
        app = ctx["app"]
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            app._open_individual_create(ZOO + cls, app._path)
            await pilot.pause()
            modal: IndividualModal = app.screen
            modal._uri.value = ZOO + name
            modal._label_inputs[app.lang].value = label
            modal._comment_inputs[app.lang].value = comment
            modal._submit()
            for _ in range(5):
                await pilot.pause()
            ctx["detail_uri"] = app._detail_uri

    asyncio.run(scenario())


@when(parsers.parse('I add an individual "{name}" of "{cls}" with owner "{owner}"'))
def _add_owner(ctx, name, cls, owner):
    async def scenario():
        app = ctx["app"]
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            app._open_individual_create(ZOO + cls, app._path)
            await pilot.pause()
            modal: IndividualModal = app.screen
            modal._uri.value = ZOO + name
            modal._value_widgets[ZOO + "hasOwner"].value = ZOO + owner
            modal._submit()
            for _ in range(5):
                await pilot.pause()

    asyncio.run(scenario())


@when(parsers.parse('I open the add-individual modal for "{cls}"'))
def _open_modal(ctx, cls):
    async def scenario():
        app = ctx["app"]
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            app._open_individual_create(ZOO + cls, app._path)
            await pilot.pause()
            ctx["props"] = set(app.screen._value_widgets)

    asyncio.run(scenario())


@when(parsers.parse('I edit the individual "{name}" renaming it "{new}" with label "{label}"'))
def _edit(ctx, name, new, label):
    async def scenario():
        app = ctx["app"]
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            app.open_context_menu(ZOO + name)
            await pilot.pause()
            app.on_context_menu_chosen(ContextMenu.Chosen("edit_individual"))
            await pilot.pause()
            modal: IndividualModal = app.screen
            modal._uri.value = ZOO + new
            modal._label_inputs[app.lang].value = label
            modal._submit()
            for _ in range(5):
                await pilot.pause()

    asyncio.run(scenario())


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('the individual "{name}" exists'))
def _exists(ctx, name):
    assert _ind(ctx, name) is not None


@then(parsers.parse('the individual "{name}" no longer exists'))
def _gone(ctx, name):
    assert _ind(ctx, name) is None


@then(parsers.parse('the individual "{name}" is typed as "{cls}"'))
def _typed(ctx, name, cls):
    ind = _ind(ctx, name)
    assert ind is not None and ZOO + cls in ind.types


@then(parsers.parse('the individual "{name}" has the label "{label}"'))
def _has_label(ctx, name, label):
    ind = _ind(ctx, name)
    assert ind is not None and label in {lbl.value for lbl in ind.labels}


@then(parsers.parse('the individual "{name}" has owner "{owner}"'))
def _has_owner(ctx, name, owner):
    ind = _ind(ctx, name)
    assert ind is not None and (ZOO + "hasOwner", ZOO + owner) in ind.property_values


@then(parsers.parse('the individual "{name}" is selected in the tree'))
def _selected(ctx, name):
    assert ctx.get("detail_uri") == ZOO + name


@then(parsers.parse('the modal offers the property "{prop}"'))
def _offers(ctx, prop):
    assert ZOO + prop in ctx["props"]
