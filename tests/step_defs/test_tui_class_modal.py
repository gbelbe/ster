"""BDD step definitions for the full add/edit class modal."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store
from ster.tui.app import OntologyApp
from ster.tui.class_modal import ClassModal
from ster.tui.context_menu import ContextMenu

scenarios("../features/tui/class_modal.feature")

DEMO = Path(__file__).resolve().parents[1].parent / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"


@pytest.fixture
def ctx():
    return {}


def _app(tmp_path: Path) -> tuple:
    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src), src


def _class(ctx, name):  # noqa: ANN001
    return ctx["app"].tax.owl_classes.get(ZOO + name)


# ── Given ─────────────────────────────────────────────────────────────────────


@given("the zoo ontology is open")
def _open(ctx, tmp_path):
    ctx["app"], ctx["src"] = _app(tmp_path)


@given(parsers.parse('a class "{name}" with label "{label}"'))
def _seed_class(ctx, name, label):
    from ster.model import Label, RDFClass

    app = ctx["app"]
    app.tax.owl_classes[ZOO + name] = RDFClass(uri=ZOO + name, labels=[Label(app.lang, label)])


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I create a class "{name}" with label "{label}" and comment "{comment}"'))
def _create(ctx, name, label, comment):
    async def scenario():
        app = ctx["app"]
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._open_class_create("create_owl_class", "", app._path)  # top-level class
            await pilot.pause()
            modal: ClassModal = app.screen
            modal._uri.value = ZOO + name
            modal._label_inputs[app.lang].value = label
            modal._comment_inputs[app.lang].value = comment
            modal._submit()
            for _ in range(3):
                await pilot.pause()

    asyncio.run(scenario())


@when(parsers.parse('I edit the class "{name}" renaming it "{new}" with label "{label}"'))
def _edit(ctx, name, new, label):
    async def scenario():
        app = ctx["app"]
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.open_context_menu(ZOO + name)
            await pilot.pause()
            app.on_context_menu_chosen(ContextMenu.Chosen("edit_class"))
            await pilot.pause()
            modal: ClassModal = app.screen
            modal._uri.value = ZOO + new
            modal._label_inputs[app.lang].value = label
            modal._submit()
            for _ in range(3):
                await pilot.pause()

    asyncio.run(scenario())


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('the class "{name}" has the label "{label}"'))
def _has_label(ctx, name, label):
    cls = _class(ctx, name)
    assert cls is not None and label in {lbl.value for lbl in cls.labels}


@then(parsers.parse('the class "{name}" has the comment "{comment}"'))
def _has_comment(ctx, name, comment):
    cls = _class(ctx, name)
    assert cls is not None and comment in {c.value for c in cls.comments}


@then(parsers.parse('the class "{name}" no longer exists'))
def _gone(ctx, name):
    assert _class(ctx, name) is None
