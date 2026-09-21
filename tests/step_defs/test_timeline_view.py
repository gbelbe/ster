"""BDD step definitions for tests/features/tui/timeline_view.feature."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pytest_bdd import given, scenarios, then, when

from ster import store
from ster.tui import query
from ster.tui.app import OntologyApp

from ..unit.test_tui_data import DEMO

scenarios("../features/tui/timeline_view.feature")


# A file with something to place on an axis, and one with nothing. The demo
# taxonomy carries no dates, which is the case the guard exists for.
DATED = """
@prefix ex:   <https://ex.org/t#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

ex:Event   a owl:Class ; rdfs:label "Event"@en .
ex:deposit a owl:NamedIndividual , ex:Event ; rdfs:label "Deposit"@en ;
           ex:on "2026-08-18"^^xsd:date .
"""


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {"server_ok": True, "opened": [], "notices": [], "ttl": None}


@given("the ster server is running")
def server_up(ctx: dict[str, Any]) -> None:
    ctx["server_ok"] = True


@given("the ster server is not running")
def server_down(ctx: dict[str, Any]) -> None:
    ctx["server_ok"] = False


@given("the file carries dates")
def file_has_dates(ctx: dict[str, Any], tmp_path) -> None:
    source = tmp_path / "dated.ttl"
    source.write_text(DATED, encoding="utf-8")
    ctx["ttl"] = source


@given("the file carries no dates at all")
def file_has_no_dates(ctx: dict[str, Any]) -> None:
    ctx["ttl"] = None  # the demo taxonomy: concepts and classes, no dates


@when("the timeline shortcut is pressed in the ontology view")
def press_timeline(ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query, "server_is_running", lambda: ctx["server_ok"])
    monkeypatch.setattr(query, "open_browser", lambda url: bool(ctx["opened"].append(url) or True))

    async def scenario() -> None:
        taxonomy = store.load(ctx["ttl"]) if ctx["ttl"] else store.load(DEMO)
        app = OntologyApp(taxonomy, source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            app.notify = lambda msg, **kw: ctx["notices"].append(str(msg))  # type: ignore[method-assign]
            await pilot.pause()
            app.action_open_timeline()
            await pilot.pause()

    asyncio.run(scenario())


@then("a browser is opened on the timeline page")
def browser_opened(ctx: dict[str, Any]) -> None:
    assert ctx["opened"], "expected a browser to be opened"
    assert "/timeline" in ctx["opened"][0]


@then("no browser is opened for the timeline")
def no_browser(ctx: dict[str, Any]) -> None:
    assert ctx["opened"] == []


@then("the TUI reports that nothing can be dated")
def reports_nothing_datable(ctx: dict[str, Any]) -> None:
    assert ctx["notices"], "expected a message in the TUI"
    assert "timeline" in ctx["notices"][0].lower()


@then("the TUI reports that the timeline server is not running")
def reports_server_down(ctx: dict[str, Any]) -> None:
    assert ctx["notices"], "expected a message in the TUI"
    assert "server" in ctx["notices"][0].lower()
