"""The Check widget: a clear bracketed mark ([ ] off / [✓] on) instead of Textual's
dim-'X' block, so an unchecked box never reads like a faint mark."""

from __future__ import annotations

import asyncio

from textual.app import App
from textual.widgets import Checkbox

from ster.tui.check import Check


class _Host(App):
    def compose(self):  # type: ignore[no-untyped-def]
        yield Check("off-label", value=False, id="off")
        yield Check("on-label", value=True, id="on")


def test_check_renders_empty_and_ticked_brackets() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            off = str(app.query_one("#off", Check).render())
            on = str(app.query_one("#on", Check).render())
            assert "[ ]" in off and "✓" not in off  # unchecked → empty brackets
            assert "[✓]" in on  # checked → ticked brackets
            assert "X" not in off and "X" not in on  # never the dim-'X' block

    asyncio.run(scenario())


def test_check_is_a_checkbox_so_queries_and_toggling_still_work() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.query(Checkbox)) == 2  # Check matches a Checkbox query
            box = app.query_one("#off", Check)
            box.toggle()
            await pilot.pause()
            assert box.value is True
            assert "[✓]" in str(box.render())  # mark follows the value

    asyncio.run(scenario())
