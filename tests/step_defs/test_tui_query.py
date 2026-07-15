"""BDD step defs for the New-TUI SPARQL query workspace.

Each scenario opens one Pilot session on the demo ontology, drives the real UI
path (open the query screen → run / preset / close), and records what the user
would see into ``ctx`` for the Then steps.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from textual.widgets import DataTable, TextArea

from ster import store
from ster.tui import query
from ster.tui.app import OntologyApp
from ster.tui.query_screen import QueryScreen

scenarios("../features/tui/sparql_query.feature")

DEMO = Path(__file__).resolve().parents[1].parent / "ster" / "tui" / "demo.ttl"

QueryCoro = Callable[[OntologyApp, object], Awaitable[None]]


@pytest.fixture
def ctx() -> dict:
    return {}


def _drive(ctx: dict, do: QueryCoro) -> None:
    """Run *do* against a fresh Pilot session on the demo ontology, then snapshot state."""

    async def scenario() -> None:
        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await do(app, pilot)
            for _ in range(2):
                await pilot.pause()
            ctx["screen"] = app.screen
            ctx["app_has_tree"] = bool(app.query("#tree"))
            if isinstance(app.screen, QueryScreen):
                ctx["editor_text"] = app.screen.query_one("#query-editor", TextArea).text
                ctx["rows"] = len(app.screen.query_one("#query-results", DataTable).rows)
                ctx["result"] = app.screen._last_result

    asyncio.run(scenario())


@given("the New-TUI is open on the demo ontology")
def _open(ctx: dict) -> None:
    ctx["steps"] = []


@when("I open the query screen")
def when_open_query(ctx: dict) -> None:
    ctx["steps"].append(("open", None))


@when(parsers.parse('I run the query "{sparql}"'))
def when_run(ctx: dict, sparql: str) -> None:
    ctx["steps"].append(("run", sparql))


@when("I load the first preset")
def when_preset(ctx: dict) -> None:
    ctx["steps"].append(("preset", None))


@when("I close the query screen")
def when_close(ctx: dict) -> None:
    ctx["steps"].append(("close", None))


def _apply_steps(ctx: dict) -> None:
    async def do(app, pilot):  # noqa: ANN001
        for kind, arg in ctx["steps"]:
            if kind == "open":
                app.action_open_query()
            elif kind == "run":
                app.screen.query_one("#query-editor", TextArea).text = arg
                app.screen.action_run()
            elif kind == "preset":
                app.screen._apply_preset(query.presets()[0].sparql)
            elif kind == "close":
                app.screen.action_close()
            await pilot.pause()

    _drive(ctx, do)


@then("the SPARQL editor is shown")
def then_editor_shown(ctx: dict) -> None:
    _apply_steps(ctx)
    assert isinstance(ctx["screen"], QueryScreen)
    assert "SELECT" in ctx["editor_text"]


@then("the results table has more than one row")
def then_rows(ctx: dict) -> None:
    _apply_steps(ctx)
    assert ctx["result"].error == ""
    assert ctx["rows"] > 1


@then("an error is reported and the results are empty")
def then_error(ctx: dict) -> None:
    _apply_steps(ctx)
    assert ctx["result"].error
    assert ctx["rows"] == 0


@then("the editor contains the preset query")
def then_preset(ctx: dict) -> None:
    _apply_steps(ctx)
    assert ctx["editor_text"] == query.presets()[0].sparql


@then("the browser tree is shown again")
def then_tree(ctx: dict) -> None:
    _apply_steps(ctx)
    assert not isinstance(ctx["screen"], QueryScreen)
    assert ctx["app_has_tree"]  # back on the browser (its tree is present again)
