"""Tests for the shared clickable footer HintBar that every modal inherits via ModalBase."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import Vertical

from ster.tui.hint_bar import Hint, HintBar, HintChip, HintLabel
from ster.tui.modal import ModalBase


def test_hint_actionable_flag() -> None:
    assert Hint("⏎", "save", "save").actionable
    assert not Hint("↑↓", "move").actionable  # no action → informational


class _DemoModal(ModalBase[str | None]):
    def compose(self) -> ComposeResult:
        yield Vertical(classes="modal-box")

    def footer_hints(self) -> list[Hint]:
        return [Hint("⏎", "save", "save"), Hint("↑↓", "move"), Hint("esc", "cancel", "cancel")]

    def action_save(self) -> None:
        self.dismiss("saved")


class _BareModal(ModalBase[None]):
    def compose(self) -> ComposeResult:
        yield Vertical(classes="modal-box")


class _Host(App):
    def compose(self):  # type: ignore[no-untyped-def]
        return iter(())


def _run(coro_factory) -> None:  # noqa: ANN001
    asyncio.run(coro_factory())


def test_modal_auto_mounts_hint_bar_split_into_chips_and_labels() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(_DemoModal())
            await pilot.pause()
            assert app.screen.query_one(HintBar)
            chips = app.screen.query(HintChip)
            labels = app.screen.query(HintLabel)
            assert {c._action for c in chips} == {"save", "cancel"}  # actionable → chips
            assert len(labels) == 1  # informational "↑↓ move" → borderless label

    _run(scenario)


def test_actionable_chip_is_focusable_and_runs_its_action_on_click() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            result: list = []
            app.push_screen(_DemoModal(), result.append)
            await pilot.pause()
            save = next(c for c in app.screen.query(HintChip) if c._action == "save")
            assert save.can_focus  # reachable by Tab
            await pilot.click(save)  # reachable by mouse
            await pilot.pause()
            assert result == ["saved"]  # ran action_save

    _run(scenario)


def test_actionable_chip_runs_on_enter_when_focused() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            result: list = []
            app.push_screen(_DemoModal(), result.append)
            await pilot.pause()
            save = next(c for c in app.screen.query(HintChip) if c._action == "save")
            save.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert result == ["saved"]

    _run(scenario)


def test_informational_label_is_not_focusable() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(_DemoModal())
            await pilot.pause()
            assert not app.screen.query_one(HintLabel).can_focus

    _run(scenario)


def test_default_footer_is_a_single_cancel_chip_when_not_overridden() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(_BareModal())
            await pilot.pause()
            assert [c._action for c in app.screen.query(HintChip)] == ["cancel"]

    _run(scenario)
