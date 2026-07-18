"""The multi-select checklist modal (native SelectionList) used for bulk tagging."""

from __future__ import annotations

import asyncio

from textual.app import App
from textual.widgets import Input, SelectionList

from ster.tui.multi_picker_modal import MultiPickerModal

OPTS = [("prod-1", "u1"), ("prod-2", "u2"), ("prod-3", "u3")]


class _Host(App):
    def compose(self):  # type: ignore[no-untyped-def]
        return iter(())


def _run(coro) -> None:  # noqa: ANN001
    asyncio.run(coro())


def test_confirm_returns_the_ticked_values() -> None:
    result: dict = {}

    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(MultiPickerModal("Tag", OPTS), lambda r: result.__setitem__("v", r))
            await pilot.pause()
            await pilot.pause()
            sel = app.screen.query_one(SelectionList)
            sel.select(sel.get_option_at_index(0))  # tick prod-1
            sel.select(sel.get_option_at_index(2))  # tick prod-3
            await pilot.pause()
            app.screen.action_confirm()
            await pilot.pause()
        assert result["v"] == ["u1", "u3"]

    _run(scenario)


def test_cancel_returns_none() -> None:
    result: dict = {}

    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(MultiPickerModal("Tag", OPTS), lambda r: result.__setitem__("v", r))
            await pilot.pause()
            app.screen.action_cancel()
            await pilot.pause()
        assert result["v"] is None

    _run(scenario)


def test_ticks_survive_filtering_then_confirm() -> None:
    """A tick made before filtering is remembered even when that row is filtered out."""
    result: dict = {}

    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(MultiPickerModal("Tag", OPTS), lambda r: result.__setitem__("v", r))
            await pilot.pause()
            await pilot.pause()
            sel = app.screen.query_one(SelectionList)
            sel.select(sel.get_option_at_index(0))  # tick prod-1
            await pilot.pause()
            app.screen.query_one(Input).value = "prod-2"  # filter prod-1 out of view
            await pilot.pause()
            app.screen.action_confirm()
            await pilot.pause()
        assert result["v"] == ["u1"]  # the off-screen tick was kept

    _run(scenario)
