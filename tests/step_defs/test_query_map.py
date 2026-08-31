"""BDD step definitions for tests/features/tui/query_map.feature."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import rdflib
from pytest_bdd import given, scenarios, then, when
from textual.app import App
from textual.widgets import TextArea

from ster.model import Label, RDFClass, Taxonomy
from ster.tui.query_screen import QueryScreen

scenarios("../features/tui/query_map.feature")

BASE = "https://example.org/onto/"
WGS = "http://www.w3.org/2003/01/geo/wgs84_pos#"
GEO_QUERY = f"SELECT ?i WHERE {{ ?i <{WGS}lat> ?lat }}"
PLAIN_QUERY = "SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }"


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {"graph": None, "status": "", "opened": [], "notices": [], "server_ok": True}


def _tax() -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = BASE.rstrip("/")
    t.owl_classes[BASE + "Person"] = RDFClass(uri=BASE + "Person", labels=[Label("en", "Person")])
    return t


def _geo_graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(
        data=f"""
        @prefix wgs:  <{WGS}> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix ex:   <{BASE}> .
        ex:Brest   rdfs:label "Brest"   ; wgs:lat 48.39 ; wgs:long -4.48 .
        ex:Lorient rdfs:label "Lorient" ; wgs:lat 47.75 ; wgs:long -3.37 .
        """,
        format="turtle",
    )
    return g


def _drive(ctx: dict[str, Any], sparql: str, *, press_map: bool = False) -> None:
    """Open the query screen, run *sparql*, optionally trigger the map action."""

    async def scenario() -> None:
        app: App[None] = App()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = QueryScreen(_tax())
            app.push_screen(screen)
            await pilot.pause()
            if ctx["graph"] is not None:
                screen._graph = ctx["graph"]
            screen.query_one("#query-editor", TextArea).text = sparql
            screen.action_run()
            await pilot.pause()
            ctx["status"] = screen._status_line
            if press_map:
                screen._open = ctx["opened"].append
                screen._server_ok = lambda: ctx["server_ok"]
                screen.notify = lambda msg, **kw: ctx["notices"].append(str(msg))
                screen.action_map()
                await pilot.pause()

    asyncio.run(scenario())


@given("a taxonomy whose individuals carry WGS84 coordinates")
def taxonomy_with_coordinates(ctx: dict[str, Any]) -> None:
    ctx["graph"] = _geo_graph()


@when("a query returning those individuals is run in the query screen")
def run_geo_query(ctx: dict[str, Any]) -> None:
    ctx["sparql"] = GEO_QUERY
    _drive(ctx, GEO_QUERY)


@when("a query returning no coordinates is run in the query screen")
def run_plain_query(ctx: dict[str, Any]) -> None:
    ctx["sparql"] = PLAIN_QUERY
    _drive(ctx, PLAIN_QUERY)


@when("the map shortcut is pressed")
def press_map_shortcut(ctx: dict[str, Any]) -> None:
    _drive(ctx, ctx["sparql"], press_map=True)


@then("the status line reports how many rows can be mapped")
def status_reports_count(ctx: dict[str, Any]) -> None:
    assert "2" in ctx["status"]
    assert "mappable" in ctx["status"]


@then("the status line mentions the map shortcut")
def status_mentions_shortcut(ctx: dict[str, Any]) -> None:
    assert "ctrl+g" in ctx["status"]


@then("the status line does not mention the map shortcut")
def status_omits_shortcut(ctx: dict[str, Any]) -> None:
    assert "ctrl+g" not in ctx["status"]


@then("a browser is opened on the map page")
def browser_opened_on_map(ctx: dict[str, Any]) -> None:
    assert ctx["opened"], "expected a browser to be opened"
    assert "/map" in ctx["opened"][0]


@then("the opened address carries the query")
def address_carries_query(ctx: dict[str, Any]) -> None:
    assert "wgs84_pos" in ctx["opened"][0]


@given("the ster server is not running")
def server_down(ctx: dict[str, Any]) -> None:
    ctx["server_ok"] = False


@then("no browser is opened")
def no_browser_opened(ctx: dict[str, Any]) -> None:
    assert ctx["opened"] == []


@then("the TUI reports that the server is not running")
def tui_reports_server_down(ctx: dict[str, Any]) -> None:
    assert ctx["notices"], "expected a message in the TUI"
    assert "server" in ctx["notices"][0].lower()
