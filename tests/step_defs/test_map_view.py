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


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {"server_ok": True, "opened": [], "notices": []}


@given("the ster server is running")
def server_up(ctx: dict[str, Any]) -> None:
    ctx["server_ok"] = True


@given("the ster server is not running")
def server_down(ctx: dict[str, Any]) -> None:
    ctx["server_ok"] = False


@when("the map shortcut is pressed in the ontology view")
def press_map(ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query, "server_is_running", lambda: ctx["server_ok"])
    monkeypatch.setattr(query, "open_browser", lambda url: bool(ctx["opened"].append(url) or True))

    async def scenario() -> None:
        app = OntologyApp(store.load(DEMO), source="demo.ttl")
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


@then("the TUI reports that the server is not running")
def reports_server_down(ctx: dict[str, Any]) -> None:
    assert ctx["notices"], "expected a message in the TUI"
    assert "server" in ctx["notices"][0].lower()
