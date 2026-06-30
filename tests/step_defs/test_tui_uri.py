"""BDD step definitions for shared fragment-only URI editing (ster.tui)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store
from ster.nav.logic import DetailField
from ster.tui.app import OntologyApp
from ster.tui.uri_modal import FragmentInput, UriModal

scenarios("../features/tui/uri_editing.feature")

DEMO = Path(__file__).resolve().parents[1].parent / "ster" / "tui" / "demo.ttl"


@pytest.fixture
def ctx():
    return {}


def _write(tmp_path: Path, text: str) -> Path:
    src = tmp_path / "o.ttl"
    src.write_text(text, encoding="utf-8")
    return src


def _app_for(ctx: dict, src: Path) -> OntologyApp:
    return OntologyApp(store.load(src), source="o.ttl", path=src)


async def _type_fragment_and_submit(pilot, app, fragment: str) -> None:
    """The current screen is a UriModal: type *fragment* (replacing any preselection)
    and submit."""
    assert isinstance(app.screen, UriModal)
    await pilot.pause()
    inp = app.screen.query_one(FragmentInput)
    ctx_prefix = inp.value[: len(inp.value) - len(inp.fragment)]
    inp.value = ctx_prefix + fragment  # validators keep the prefix locked
    await pilot.press("enter")
    for _ in range(3):
        await pilot.pause()


def _synth_action(action: str) -> DetailField:
    return DetailField("x", "", "", editable=False, meta={"type": "action", "action": action})


# ── Given ─────────────────────────────────────────────────────────────────────


@given("the zoo ontology is open in the New-TUI", target_fixture="src")
def _zoo_open(tmp_path: Path) -> Path:
    return _write(tmp_path, DEMO.read_text(encoding="utf-8"))


@given(
    parsers.parse('a SKOS taxonomy whose scheme mints under "{base}"'),
    target_fixture="src",
)
def _skos_scheme(tmp_path: Path, base: str) -> Path:
    ttl = (
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        f"@prefix wind: <{base}> .\n\n"
        "wind:scheme a skos:ConceptScheme ; skos:prefLabel 'Wind'@en .\n"
    )
    return _write(tmp_path, ttl)


@given(parsers.parse('an entity whose URI is "{uri}"'), target_fixture="src")
def _foreign_entity(tmp_path: Path, uri: str) -> Path:
    ttl = f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n\n<{uri}> a owl:Class .\n"
    return _write(tmp_path, ttl)


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I add a class with the fragment "{fragment}"'))
def _add_class(ctx: dict, src: Path, fragment: str) -> None:
    async def scenario() -> None:
        from ster.tui.class_modal import ClassModal

        app = _app_for(ctx, src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._run_field_action(_synth_action("create_owl_class"))
            await pilot.pause()
            modal = app.screen  # creating a class opens the full ClassModal
            assert isinstance(modal, ClassModal)
            modal._uri.value = modal._uri.value + fragment  # base is locked; append fragment
            modal._submit()
            for _ in range(3):
                await pilot.pause()
            ctx["tax"] = app.tax

    asyncio.run(scenario())


@when(parsers.parse('I add a top concept with the fragment "{fragment}"'))
def _add_top_concept(ctx: dict, src: Path, fragment: str) -> None:
    async def scenario() -> None:
        app = _app_for(ctx, src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            scheme_uri = next(iter(app.tax.schemes))
            app._show(scheme_uri)  # so the action targets this scheme
            await pilot.pause()
            app._run_field_action(_synth_action("add_top_concept"))
            await pilot.pause()
            await _type_fragment_and_submit(pilot, app, fragment)
            ctx["tax"] = app.tax

    asyncio.run(scenario())


@when(parsers.parse('I rename it changing the fragment to "{fragment}"'))
def _rename(ctx: dict, src: Path, fragment: str) -> None:
    async def scenario() -> None:
        app = _app_for(ctx, src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            uri = next(iter(app.tax.owl_classes))
            app._rename_entity(uri)
            await pilot.pause()
            await _type_fragment_and_submit(pilot, app, fragment)
            ctx["tax"] = app.tax

    asyncio.run(scenario())


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('a class "{uri}" exists'))
def _class_exists(ctx: dict, uri: str) -> None:
    assert uri in ctx["tax"].owl_classes


@then(parsers.parse('a concept "{uri}" exists'))
def _concept_exists(ctx: dict, uri: str) -> None:
    assert uri in ctx["tax"].concepts


@then(parsers.parse('the entity URI becomes "{uri}"'))
def _entity_renamed(ctx: dict, uri: str) -> None:
    assert uri in ctx["tax"].owl_classes
