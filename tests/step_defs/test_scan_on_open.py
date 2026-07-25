"""BDD step definitions for scan-on-open (the Problems fix-it worklist)."""

from __future__ import annotations

import asyncio

import pytest
from pytest_bdd import given, scenarios, then, when
from textual.widgets import Button

from ster import store
from ster.model import LabelType
from ster.plugins.semanticlint import config
from ster.tui.app import OntologyApp
from ster.tui.plugins.semanticlint_ui.problems_modal import ProblemRow, ProblemsModal

scenarios("../features/tui/scan_on_open.feature")

DUP_LABEL_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://ex.org/> .
ex:Scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Dog .
ex:Dog a skos:Concept ; skos:inScheme ex:Scheme ; skos:topConceptOf ex:Scheme ;
  skos:prefLabel "Dog"@en ; skos:altLabel "Dog"@en .
"""

CLEAN_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://ex.org/> .
ex:Scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Dog .
ex:Dog a skos:Concept ; skos:inScheme ex:Scheme ; skos:topConceptOf ex:Scheme ;
  skos:prefLabel "Dog"@en .
"""


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from ster import api_server
    from ster.nav import prefs

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(prefs, "_lang_prefs_path", lambda: tmp_path / "lang.json")
    monkeypatch.setattr(prefs, "_configured_langs_path", lambda: tmp_path / "clangs.json")
    monkeypatch.setattr(api_server, "_SERVER_CONFIG_FILE", tmp_path / "server_config.json")
    monkeypatch.setattr(api_server, "_TOKEN_FILE", tmp_path / "api_token")
    monkeypatch.setattr(config, "_config_path", lambda: tmp_path / "quality.json")
    return {"dir": tmp_path}


async def _settle(pilot, predicate, *, tries=80) -> bool:
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return predicate()


def _write(ctx, ttl: str) -> None:
    src = ctx["dir"] / "onto.ttl"
    src.write_text(ttl, encoding="utf-8")
    ctx["path"] = src


# ── Given ───────────────────────────────────────────────────────────────────────


@given("the semanticlint plugin is enabled")
def _enable_plugin(ctx) -> None:
    from ster.plugins import state

    state.set_enabled("semanticlint", True)


@given('"check file on open" is turned off')
def _turn_off(ctx) -> None:
    config.set_feature("check_on_open", False)


@given("an ontology file that has a duplicate-label error")
def _dup_file(ctx) -> None:
    _write(ctx, DUP_LABEL_TTL)


@given("an ontology file with no blocking errors")
def _clean_file(ctx) -> None:
    _write(ctx, CLEAN_TTL)


@given("I have opened it in the TUI")
def _opened(ctx) -> None:
    _open(ctx)


# ── When ────────────────────────────────────────────────────────────────────────


@when("I open it in the TUI")
def _open(ctx) -> None:
    app = OntologyApp(store.load(ctx["path"]), source="onto.ttl", path=ctx["path"])
    ctx["app"] = app

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(pilot, lambda: isinstance(app.screen, ProblemsModal))
            for _ in range(20):  # give a clean file time to prove it stays silent
                await pilot.pause()
            ctx["modal_open"] = isinstance(app.screen, ProblemsModal)
            ctx["rows"] = len(app.screen.query(ProblemRow)) if ctx["modal_open"] else 0

    asyncio.run(scenario())


@when("I apply the inline fix")
def _apply(ctx) -> None:
    app = OntologyApp(store.load(ctx["path"]), source="onto.ttl", path=ctx["path"])
    ctx["app"] = app

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(pilot, lambda: isinstance(app.screen, ProblemsModal))
            app.screen.query_one(".problem-fix", Button).press()
            ctx["closed"] = await _settle(pilot, lambda: not isinstance(app.screen, ProblemsModal))
            dog = app.tax.concepts["http://ex.org/Dog"]
            ctx["alts"] = [lbl.value for lbl in dog.labels if lbl.type == LabelType.ALT]

    asyncio.run(scenario())


# ── Then ────────────────────────────────────────────────────────────────────────


@then("the Problems modal lists 1 error")
def _lists_one(ctx) -> None:
    assert ctx["modal_open"] is True
    assert ctx["rows"] == 1


@then("no Problems modal appears")
def _no_modal(ctx) -> None:
    assert ctx["modal_open"] is False


@then("the duplicate label is removed")
def _removed(ctx) -> None:
    assert "Dog" not in ctx["alts"]


@then("the Problems modal closes")
def _closed(ctx) -> None:
    assert ctx["closed"] is True
