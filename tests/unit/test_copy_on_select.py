"""Selecting text anywhere in the TUI copies it, and says so beside the selection.

One app-level handler does it: Textual's Screen posts ``TextSelected`` after
every mouse release, on every screen, and it bubbles to the app — so no widget
needs to know. A plain click posts it too, with the selection already cleared,
which is what takes the message down again.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from textual.geometry import Offset
from textual.screen import ModalScreen
from textual.widgets import Static

from ster import store
from ster.tui.app import OntologyApp
from ster.tui.app import _copy_on_select as copy_on_select
from ster.tui.app._copy_on_select import CopiedFlash

pytestmark = pytest.mark.tui

DEMO = """
@prefix ex:   <https://ex.org/s#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Thing  a owl:Class ; rdfs:label "Thing"@en .
ex:Other  a owl:Class ; rdfs:label "Other"@en ; rdfs:subClassOf ex:Thing .
"""
THING = "https://ex.org/s#Thing"


def _run(scenario) -> None:
    asyncio.run(scenario())


def _app(tmp_path) -> OntologyApp:
    source = tmp_path / "demo.ttl"
    source.write_text(DEMO, encoding="utf-8")
    return OntologyApp(store.load(source), source=str(source))


@contextmanager
def _clipboard(app):
    with (
        patch.object(app, "copy_to_clipboard") as terminal,
        patch("ster.tui.clipboard.copy_to_system_clipboard", return_value=True),
    ):
        yield terminal


async def _open_source(app, pilot) -> None:
    await pilot.pause()
    app._show(THING)
    await pilot.press("r")
    await pilot.pause(0.2)


def _turtle(app, text: str) -> Static:
    return next(w for w in app.query("#source Static") if text in str(w.render()))


async def _drag(pilot, widget, start=(0, 0), end=(12, 0)) -> None:
    await pilot.mouse_down(widget, offset=start)
    await pilot.hover(widget, offset=end)
    await pilot.mouse_up(widget, offset=end)
    await pilot.pause()


def _flash(app) -> CopiedFlash | None:
    found = list(app.screen.query(CopiedFlash))
    return found[0] if found else None


def test_a_mouse_selection_is_copied_to_the_clipboard(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_source(app, pilot)
            with _clipboard(app) as terminal:
                await _drag(pilot, _turtle(app, "owl:Class"))
            selected = app.screen.get_selected_text()
            assert selected
            terminal.assert_called_once_with(selected)

    _run(scenario)


def test_the_message_appears_where_the_mouse_was_released(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_source(app, pilot)
            widget = _turtle(app, "owl:Class")
            with _clipboard(app):
                await _drag(pilot, widget)
            await pilot.pause()
            flash = _flash(app)
            assert flash is not None
            assert "Copied to clipboard" in str(flash.render())
            released = widget.region.offset + Offset(12, 0)
            assert abs(flash.region.y - released.y) <= 1
            assert abs(flash.region.x - released.x) <= 2

    _run(scenario)


def test_the_message_is_kept_inside_the_screen_near_its_edge(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_source(app, pilot)
            with _clipboard(app):
                app._show_copied_flash(Offset(119, 39))
            await pilot.pause()
            flash = _flash(app)
            assert flash is not None
            assert app.screen.region.contains_region(flash.region)

    _run(scenario)


def test_an_empty_selection_copies_nothing_and_shows_nothing(tmp_path) -> None:
    """A plain click also ends in TextSelected — with nothing selected."""
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_source(app, pilot)
            with _clipboard(app) as terminal:
                await pilot.click(_turtle(app, "owl:Class"))
                await pilot.pause()
            terminal.assert_not_called()
            assert _flash(app) is None

    _run(scenario)


def test_escape_clears_the_selection_and_the_message(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_source(app, pilot)
            with _clipboard(app):
                await _drag(pilot, _turtle(app, "owl:Class"))
            await pilot.press("escape")
            await pilot.pause()
            assert not app.screen.selections
            assert _flash(app) is None

    _run(scenario)


def test_escape_without_a_selection_is_left_to_the_focused_widget(tmp_path) -> None:
    """The binding only claims Escape while there is something to clear."""
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert not app.check_action("clear_text_selection", ())

    _run(scenario)


def test_a_click_clears_the_message(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_source(app, pilot)
            with _clipboard(app):
                await _drag(pilot, _turtle(app, "owl:Class"))
                assert _flash(app) is not None
                await pilot.click(_turtle(app, "rdfs:subClassOf"))
                await pilot.pause()
            assert _flash(app) is None
            assert not app.screen.selections

    _run(scenario)


def test_the_message_goes_away_on_its_own(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(copy_on_select, "FLASH_SECONDS", 0.05)
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_source(app, pilot)
            with _clipboard(app):
                await _drag(pilot, _turtle(app, "owl:Class"))
            await pilot.pause(0.3)
            assert _flash(app) is None
            assert app.screen.selections, "the selection itself stays until dismissed"

    _run(scenario)


class _TextDialog(ModalScreen):
    def compose(self):  # type: ignore[no-untyped-def]
        yield Static("Some dialog text worth copying", id="dialog-text")


def test_it_works_on_a_modal_screen(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.push_screen(_TextDialog())
            await pilot.pause()
            with _clipboard(app) as terminal:
                await _drag(pilot, app.screen.query_one("#dialog-text"))
            assert terminal.call_args.args[0].startswith("Some dialog")
            assert _flash(app) is not None

    _run(scenario)
