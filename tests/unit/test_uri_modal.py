"""Unit tests for the locked-prefix URI modal (ster.tui.uri_modal)."""

from __future__ import annotations

import asyncio

from textual.app import App

from ster.tui.uri_modal import FragmentInput, UriModal

PREFIX = "https://ex.org/onto#"


def _drive(coro_factory) -> None:  # noqa: ANN001 - test helper
    asyncio.run(coro_factory())


def test_fragment_preselected_and_value_composed() -> None:
    async def scenario() -> None:
        app: App = App()
        async with app.run_test() as pilot:
            app.push_screen(UriModal("Rename URI", PREFIX, "Wheel"))
            await pilot.pause()
            await pilot.pause()
            inp = app.screen.query_one(FragmentInput)
            assert inp.value == PREFIX + "Wheel"
            assert inp.fragment == "Wheel"
            # The fragment (and only the fragment) is selected, ready to overtype.
            assert (inp.selection.start, inp.selection.end) == (len(PREFIX), len(inp.value))

    _drive(scenario)


def test_typing_replaces_the_preselected_fragment() -> None:
    async def scenario() -> None:
        app: App = App()
        async with app.run_test() as pilot:
            app.push_screen(UriModal("Rename URI", PREFIX, "Wheel"))
            await pilot.pause()
            await pilot.pause()
            await pilot.press("A", "x", "l", "e")
            await pilot.pause()
            inp = app.screen.query_one(FragmentInput)
            assert inp.value == PREFIX + "Axle"  # the whole old fragment was replaced

    _drive(scenario)


def test_backspace_cannot_eat_into_the_prefix() -> None:
    async def scenario() -> None:
        app: App = App()
        async with app.run_test() as pilot:
            app.push_screen(UriModal("New class URI", PREFIX, ""))  # empty fragment
            await pilot.pause()
            await pilot.pause()
            for _ in range(10):  # hammer backspace at the boundary
                await pilot.press("backspace")
            await pilot.pause()
            inp = app.screen.query_one(FragmentInput)
            assert inp.value == PREFIX  # prefix intact
            assert inp.fragment == ""

    _drive(scenario)


def test_home_lands_at_the_fragment_start() -> None:
    async def scenario() -> None:
        app: App = App()
        async with app.run_test() as pilot:
            app.push_screen(UriModal("Rename URI", PREFIX, "Wheel"))
            await pilot.pause()
            await pilot.pause()
            await pilot.press("end")
            await pilot.press("home")
            await pilot.pause()
            inp = app.screen.query_one(FragmentInput)
            assert inp.cursor_position == len(PREFIX)
            # Typing at "home" still keeps the prefix first.
            await pilot.press("Z")
            await pilot.pause()
            assert inp.value.startswith(PREFIX)

    _drive(scenario)


def test_submit_returns_full_uri_and_empty_fragment_cancels() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test() as pilot:
            app.push_screen(UriModal("New class URI", PREFIX, ""), captured.append)
            await pilot.pause()
            await pilot.pause()
            await pilot.press("V", "e", "h")
            await pilot.press("enter")
            await pilot.pause()

    _drive(scenario)
    assert captured == [PREFIX + "Veh"]


def test_empty_fragment_submit_returns_none() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test() as pilot:
            app.push_screen(UriModal("New class URI", PREFIX, ""), captured.append)
            await pilot.pause()
            await pilot.pause()
            await pilot.press("enter")  # nothing typed
            await pilot.pause()

    _drive(scenario)
    assert captured == [None]
