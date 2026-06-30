"""BDD step definitions for configured-language label editing / deletion."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import operations, store
from ster.tui.app import OntologyApp
from ster.tui.detail_view import DetailRow

scenarios("../features/tui/configured_languages.feature")

ZOO = "https://example.org/zoo/"

_TTL = (
    "@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    f"@prefix ex:   <{ZOO}> .\n\n"
    "ex:ontology a owl:Ontology .\n"
    'ex:Animal a owl:Class ; rdfs:label "Animal"@en .\n'
)


@pytest.fixture
def ctx():
    return {}


def _app(tmp_path: Path, configured: list[str], *, with_fr: bool = False) -> tuple:
    ttl = _TTL
    if with_fr:
        ttl = ttl.replace('"Animal"@en', '"Animal"@en, "Animal"@fr')
    src = tmp_path / "o.ttl"
    src.write_text(ttl, encoding="utf-8")
    app = OntologyApp(store.load(src), source="o.ttl", path=src)
    app.configured_langs = configured
    return app, src


def _config(app, configured: list[str]) -> dict:
    return {"display": app.lang, "configured": configured, "theme": app.theme}


# ── Given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('the zoo ontology is open with configured languages "{langs}"'))
def _open(ctx, tmp_path, langs):
    configured = [s.strip() for s in langs.split(",")]
    ctx["app"], ctx["src"] = _app(tmp_path, configured, with_fr=("fr" in configured))


@given("a class has a French label")
def _has_fr(ctx):
    assert operations.language_in_use(ctx["app"].tax, "fr")


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I select a class and configure languages "{langs}"'))
def _select_and_configure(ctx, langs):
    configured = [s.strip() for s in langs.split(",")]

    async def scenario():
        app = ctx["app"]
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Animal")
            await pilot.pause()
            app._apply_config(_config(app, configured))
            await pilot.pause()
            ctx["add_langs"] = {
                r.field.meta.get("lang")
                for r in app.query(DetailRow)
                if r.field.meta.get("action") == "add_rdf_label"
            }

    asyncio.run(scenario())


@when(parsers.parse('I unconfigure language "{lang}" and choose to {decision} its data'))
def _unconfigure(ctx, lang, decision):
    remaining = [c for c in ctx["app"].configured_langs if c != lang]
    choice = "delete" if decision == "delete" else "keep"

    async def scenario():
        from ster.tui.choice_modal import ChoiceModal

        app = ctx["app"]
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._apply_config(_config(app, remaining))
            await pilot.pause()
            assert isinstance(app.screen, ChoiceModal)
            app.screen.dismiss(choice)
            for _ in range(3):
                await pilot.pause()
            ctx["fr_in_use"] = operations.language_in_use(app.tax, "fr")

    asyncio.run(scenario())


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('a "+ Add rdfs:label [{lang}]" row is offered'))
def _add_offered(ctx, lang):
    assert lang in ctx["add_langs"]


@then("no French label remains in the ontology")
def _no_fr(ctx):
    assert ctx["fr_in_use"] is False


@then("the French label still exists in the ontology")
def _fr_kept(ctx):
    assert ctx["fr_in_use"] is True
