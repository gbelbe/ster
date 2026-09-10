"""Unit tests for the modal that blocks the browser on a file ster could not model."""

from __future__ import annotations

import asyncio

from textual.app import App
from textual.widgets import Button, Static

from ster.store import NO_TRIPLES, Unreadable
from ster.tui.unreadable_modal import UnreadableModal

_CAPABILITY = "https://example.com/business-capability/BusinessCapability"
_DOMAIN = "https://example.com/business-capability/Domain"

_UNREADABLE = Unreadable(
    reason="no_recognised_types",
    total_triples=3184,
    undeclared_types=((_CAPABILITY, 532), (_DOMAIN, 9)),
)
_EMPTY = Unreadable(reason=NO_TRIPLES, total_triples=0)


def _drive(factory) -> None:  # noqa: ANN001
    asyncio.run(factory())


def _screen_text(app: App) -> str:
    return " ".join(str(node.render()) for node in app.screen.query(Static))


async def _open(app: App, unreadable: Unreadable, captured: list, pilot) -> None:  # noqa: ANN001
    app.push_screen(UnreadableModal(unreadable, "business_capabilities.ttl"), captured.append)
    await pilot.pause()
    await pilot.pause()


def test_modal_lists_each_undeclared_type_and_count() -> None:
    seen: list[str] = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            await _open(app, _UNREADABLE, [], pilot)
            seen.append(_screen_text(app))

    _drive(scenario)
    text = seen[0]
    assert _CAPABILITY in text
    assert "532" in text
    assert _DOMAIN in text
    assert "9" in text


def test_modal_names_the_file_and_the_triple_count() -> None:
    seen: list[str] = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            await _open(app, _UNREADABLE, [], pilot)
            seen.append(_screen_text(app))

    _drive(scenario)
    assert "business_capabilities.ttl" in seen[0]
    assert "3184" in seen[0]


def test_modal_offers_no_fix_when_nothing_is_declarable() -> None:
    ids: list[list[str]] = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            await _open(app, _EMPTY, [], pilot)
            ids.append([b.id or "" for b in app.screen.query(Button)])

    _drive(scenario)
    assert UnreadableModal.DECLARE not in ids[0]
    assert UnreadableModal.OPEN in ids[0]


def test_declare_choice_returns_declare() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            await _open(app, _UNREADABLE, captured, pilot)
            app.screen.query_one(f"#{UnreadableModal.DECLARE}", Button).press()
            await pilot.pause()

    _drive(scenario)
    assert captured == [UnreadableModal.DECLARE]


def test_open_anyway_choice_returns_open() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            await _open(app, _UNREADABLE, captured, pilot)
            app.screen.query_one(f"#{UnreadableModal.OPEN}", Button).press()
            await pilot.pause()

    _drive(scenario)
    assert captured == [UnreadableModal.OPEN]


def test_escape_cancels() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            await _open(app, _UNREADABLE, captured, pilot)
            await pilot.press("escape")
            await pilot.pause()

    _drive(scenario)
    assert captured == [None]
