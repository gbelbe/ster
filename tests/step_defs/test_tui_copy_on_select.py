"""BDD step defs for copy-on-select (tests/features/tui/copy_on_select.feature).

The whole scenario runs inside one Pilot session: steps queue async actions on
``ctx["steps"]``, and the final ``Then``-phase checks run against state captured
by a single ``_play`` call, so the app is never started twice for one scenario.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from pytest_bdd import given, scenarios, then, when
from textual.geometry import Offset
from textual.screen import ModalScreen
from textual.widgets import Static

from ster import store
from ster.tui.app import OntologyApp
from ster.tui.app._copy_on_select import CopiedFlash

scenarios("../features/tui/copy_on_select.feature")

DEMO = """
@prefix ex:   <https://ex.org/s#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Thing  a owl:Class ; rdfs:label "Thing"@en .
ex:Other  a owl:Class ; rdfs:subClassOf ex:Thing .
"""


class _TextDialog(ModalScreen):
    def compose(self):  # type: ignore[no-untyped-def]
        yield Static("Some dialog text worth copying", id="dialog-text")


@pytest.fixture
def ctx(tmp_path) -> dict:
    source = tmp_path / "demo.ttl"
    source.write_text(DEMO, encoding="utf-8")
    return {"app": OntologyApp(store.load(source), source=str(source)), "steps": []}


def _turtle(app) -> Static:
    return next(w for w in app.query("#source Static") if "owl:Class" in str(w.render()))


async def _drag(app, pilot, widget) -> None:
    await pilot.mouse_down(widget, offset=(0, 0))
    await pilot.hover(widget, offset=(12, 0))
    await pilot.mouse_up(widget, offset=(12, 0))
    await pilot.pause()
    app._released_at = widget.region.offset + Offset(12, 0)


def _play(ctx: dict) -> None:
    """Run every queued step in one session, then capture what the Thens need."""
    app = ctx["app"]

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show("https://ex.org/s#Thing")
            await pilot.press("r")
            await pilot.pause(0.2)
            with (
                patch.object(app, "copy_to_clipboard") as terminal,
                patch("ster.tui.clipboard.copy_to_system_clipboard", return_value=True),
            ):
                for step in ctx["steps"]:
                    await step(app, pilot)
            flashes = list(app.screen.query(CopiedFlash))
            ctx.update(
                copied=terminal.call_args.args[0] if terminal.called else None,
                selected=app.screen.get_selected_text(),
                selections=bool(app.screen.selections),
                flash=(str(flashes[0].render()), flashes[0].region) if flashes else None,
                released=getattr(app, "_released_at", None),
            )

    asyncio.run(scenario())
    ctx["played"] = True


def _played(ctx: dict) -> dict:
    if not ctx.get("played"):
        _play(ctx)
    return ctx


@given("the ontology browser is open on the source pane")
def given_open(ctx):
    pass  # _play opens it; nothing to queue


@given("a dialog showing some text is open")
def given_dialog(ctx):
    async def step(app, pilot):
        app.push_screen(_TextDialog())
        await pilot.pause()

    ctx["steps"].append(step)


@when("I drag the mouse across some Turtle")
def when_drag_turtle(ctx):
    async def step(app, pilot):
        await _drag(app, pilot, _turtle(app))

    ctx["steps"].append(step)


@when("I drag the mouse across the dialog's text")
def when_drag_dialog(ctx):
    async def step(app, pilot):
        await _drag(app, pilot, app.screen.query_one("#dialog-text"))

    ctx["steps"].append(step)


@when("I press escape")
def when_escape(ctx):
    async def step(app, pilot):
        await pilot.press("escape")
        await pilot.pause()

    ctx["steps"].append(step)


@when("I click somewhere else")
def when_click(ctx):
    async def step(app, pilot):
        await pilot.click(app.query_one("#source"), offset=(2, 30))
        await pilot.pause()

    ctx["steps"].append(step)


@then("the selected text is on the clipboard")
def then_on_clipboard(ctx):
    state = _played(ctx)
    assert state["copied"] and state["copied"] == state["selected"]


@then('"Copied to clipboard" appears where I released the mouse')
def then_flash_at_release(ctx):
    state = _played(ctx)
    assert state["flash"] is not None
    text, region = state["flash"]
    assert "Copied to clipboard" in text
    assert abs(region.y - state["released"].y) <= 1


@then("nothing is selected")
def then_nothing_selected(ctx):
    assert not _played(ctx)["selections"]


@then("the message is gone")
def then_message_gone(ctx):
    assert _played(ctx)["flash"] is None
