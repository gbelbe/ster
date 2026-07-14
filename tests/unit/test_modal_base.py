"""Shared modal chrome (ModalBase): every modal gets a ✕ and click-away-to-close."""

from __future__ import annotations

import asyncio

from textual.app import App

from ster.tui.choice_modal import ChoiceModal


class _Host(App):
    def compose(self):  # type: ignore[no-untyped-def]
        return iter(())


def _run(coro_factory) -> None:  # noqa: ANN001
    asyncio.run(coro_factory())


def test_every_modal_has_a_close_button() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(ChoiceModal("Pick one", [("A", "a"), ("B", "b")]))
            await pilot.pause()
            assert app.screen.query(".modal-close")  # ✕ mounted by ModalBase

    _run(scenario)


def test_clicking_the_close_button_cancels_the_modal() -> None:
    async def scenario() -> None:
        app = _Host()
        results: list = []
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(ChoiceModal("Pick one", [("A", "a"), ("B", "b")]), results.append)
            await pilot.pause()
            await pilot.click(".modal-close")
            await pilot.pause()
            assert results == [None]  # ✕ dismisses with the cancel result

    _run(scenario)


def test_clicking_outside_the_box_cancels_the_modal() -> None:
    async def scenario() -> None:
        app = _Host()
        results: list = []
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(ChoiceModal("Pick one", [("A", "a"), ("B", "b")]), results.append)
            await pilot.pause()
            await pilot.click(offset=(1, 1))  # the dim, outside the centred box
            await pilot.pause()
            assert results == [None]

    _run(scenario)


def test_clicking_inside_the_box_does_not_cancel() -> None:
    async def scenario() -> None:
        app = _Host()
        results: list = []
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(ChoiceModal("Pick one", [("A", "a"), ("B", "b")]), results.append)
            await pilot.pause()
            await pilot.click(".hint-label")  # a non-interactive footer spot inside the box
            await pilot.pause()
            assert results == []  # click-away does not fire for clicks inside the box

    _run(scenario)


def test_escape_still_cancels_via_the_modal_itself() -> None:
    async def scenario() -> None:
        app = _Host()
        results: list = []
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(ChoiceModal("Pick one", [("A", "a"), ("B", "b")]), results.append)
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert results == [None]

    _run(scenario)
