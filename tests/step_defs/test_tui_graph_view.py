"""BDD step defs for the "g" graph shortcut (tests/features/tui/graph_view.feature).

Each ``When`` runs one Pilot session against the demo ontology, stubs the two
``viz_vowl`` browser entry points to record how the graph was opened (the focus
URI, or the ``"GLOBAL"`` sentinel), drives the real UI path (select in the tree →
press ``g``), and stores the result for the ``Then`` steps to assert.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store, viz_vowl
from ster.tui import detail
from ster.tui.app import OntologyApp

scenarios("../features/tui/graph_view.feature")

DEMO = Path(__file__).resolve().parents[1].parent / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"


@pytest.fixture
def ctx() -> dict:
    return {}


Drive = Callable[[OntologyApp, object], Awaitable[None]]


def _run(ctx: dict, monkeypatch, do: Drive) -> None:
    """Open the app, record graph calls, run *do*, and capture the recorded calls."""
    calls: list = []
    monkeypatch.setattr(viz_vowl, "port_holder", lambda host=None, port=None: None)  # port free
    monkeypatch.setattr(
        viz_vowl,
        "open_focused_in_browser",
        lambda tax, root, path=None: calls.append(root) or "http://x",
    )
    monkeypatch.setattr(
        viz_vowl,
        "open_in_browser",
        lambda tax, path=None, on_change_fn=None: calls.append("GLOBAL") or "http://g",
    )

    async def scenario() -> None:
        from textual.widgets import Tree

        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")  # expand so every entity is a visible node
            await pilot.pause()
            await do(app, pilot, Tree)
            await pilot.pause()

    asyncio.run(scenario())
    ctx["calls"] = calls


@given("the zoo ontology is open in the browser")
def _open(ctx: dict) -> None:
    ctx.clear()


@when(parsers.parse('I select the class "{name}" in the tree and press "g"'))
def _select_class(ctx: dict, monkeypatch, name: str) -> None:
    async def do(app: OntologyApp, pilot, tree_cls) -> None:  # type: ignore[no-untyped-def]
        app.jump_to(ZOO + name)  # select the class (reveals it in the ontology pane, sets detail)
        await pilot.pause()
        await pilot.press("g")

    _run(ctx, monkeypatch, do)


@when(parsers.parse('I select the individual "{name}" in the tree and press "g"'))
def _select_individual(ctx: dict, monkeypatch, name: str) -> None:
    async def do(app: OntologyApp, pilot, tree_cls) -> None:  # type: ignore[no-untyped-def]
        app.jump_to(ZOO + name)  # select the individual (reveals it in the ontology pane)
        await pilot.pause()
        await pilot.press("g")

    _run(ctx, monkeypatch, do)


@when('I show the ontology overview and press "g"')
def _overview(ctx: dict, monkeypatch) -> None:
    async def do(app: OntologyApp, pilot, tree_cls) -> None:  # type: ignore[no-untyped-def]
        app._show(detail.OVERVIEW_URI)
        await pilot.pause()
        app.action_open_graph()  # what the 'g' binding invokes

    _run(ctx, monkeypatch, do)


@when(parsers.parse('I open the class "{name}" and activate its "Open Graph View" row'))
def _activate_row(ctx: dict, monkeypatch, name: str) -> None:
    async def do(app: OntologyApp, pilot, tree_cls) -> None:  # type: ignore[no-untyped-def]
        from ster.tui.detail_view import DetailRow

        app._show(ZOO + name)
        await pilot.pause()
        row = next(
            r for r in app.query(DetailRow) if r.field.meta.get("action") == "view_focused_graph"
        )
        row.focus()
        await pilot.pause()
        await pilot.press("enter")

    _run(ctx, monkeypatch, do)


@then(parsers.parse('the graph opens focused on "{name}"'))
def _focused(ctx: dict, name: str) -> None:
    assert ctx["calls"] == [ZOO + name]


@then("the whole-ontology graph opens")
def _global(ctx: dict) -> None:
    assert ctx["calls"] == ["GLOBAL"]
