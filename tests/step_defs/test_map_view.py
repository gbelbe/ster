"""BDD step definitions for tests/features/tui/map_view.feature."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pytest_bdd import given, scenarios, then, when

from ster import store
from ster.tui import query
from ster.tui.app import OntologyApp

from ..unit.test_tui_data import DEMO

scenarios("../features/tui/map_view.feature")


# A file with something to place, and one with nothing. The demo taxonomy has
# no geography, which is the case the guard exists for.
LOCATED = """
@prefix ex:   <https://ex.org/m#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .

ex:Shop  a owl:Class ; rdfs:label "Shop"@en .
ex:shop1 a owl:NamedIndividual , ex:Shop ; rdfs:label "Shop One"@en ;
         wgs:lat 48.11 ; wgs:long -1.68 .
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


@given("the file carries coordinates")
def file_has_coordinates(ctx: dict[str, Any], tmp_path) -> None:
    source = tmp_path / "located.ttl"
    source.write_text(LOCATED, encoding="utf-8")
    ctx["ttl"] = source


@given("the file carries no geography at all")
def file_has_no_geography(ctx: dict[str, Any]) -> None:
    ctx["ttl"] = None  # the demo taxonomy: concepts and classes, no coordinates


@when("the map shortcut is pressed in the ontology view")
def press_map(ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query, "server_is_running", lambda: ctx["server_ok"])
    monkeypatch.setattr(query, "open_browser", lambda url: bool(ctx["opened"].append(url) or True))

    async def scenario() -> None:
        taxonomy = store.load(ctx["ttl"]) if ctx["ttl"] else store.load(DEMO)
        app = OntologyApp(taxonomy, source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            app.notify = lambda msg, **kw: ctx["notices"].append(str(msg))  # type: ignore[method-assign]
            await pilot.pause()
            app.action_open_map()
            await pilot.pause()

    asyncio.run(scenario())


@then("a browser is opened on the map page")
def browser_opened(ctx: dict[str, Any]) -> None:
    assert ctx["opened"], "expected a browser to be opened"
    assert "/map" in ctx["opened"][0]


@then("no browser is opened")
def no_browser(ctx: dict[str, Any]) -> None:
    assert ctx["opened"] == []


@then("the TUI reports that nothing can be mapped")
def reports_nothing_mappable(ctx: dict[str, Any]) -> None:
    assert ctx["notices"], "expected a message in the TUI"
    assert "map" in ctx["notices"][0].lower()


@then("the TUI reports that the server is not running")
def reports_server_down(ctx: dict[str, Any]) -> None:
    assert ctx["notices"], "expected a message in the TUI"
    assert "server" in ctx["notices"][0].lower()
