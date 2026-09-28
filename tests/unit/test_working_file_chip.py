"""The header's working-file chip and its drop-down menu.

Which file is writable was visible only as a filename in the window title and
as a lock on rows you could not edit — readable, but not actionable. These
tests pin the control that makes it actionable: what it says, when it offers a
switch, and that opening the menu never commits to one.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ster import store
from ster.tui.app import OntologyApp
from ster.tui.working_file_chip import WorkingFileChip, WorkingFileMenu, truncate_name

pytestmark = pytest.mark.tui

NS = "https://example.org/t#"

GEAR = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <{NS}> .
ex:Scheme a skos:ConceptScheme .
ex:Tent a skos:Concept ; skos:prefLabel "Tent"@en ; skos:inScheme ex:Scheme .
"""

PLACES = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <{NS}> .
ex:PlaceScheme a skos:ConceptScheme .
ex:Alps a skos:Concept ; skos:prefLabel "Alps"@en ; skos:inScheme ex:PlaceScheme .
"""


def _files(tmp_path: Path) -> tuple[Path, Path]:
    gear = tmp_path / "gear.ttl"
    places = tmp_path / "places.ttl"
    gear.write_text(GEAR, encoding="utf-8")
    places.write_text(PLACES, encoding="utf-8")
    return gear, places


async def _settle(pilot, app) -> None:
    """Wait for the switch worker, which re-parses off the UI thread."""
    await app.workers.wait_for_complete()
    await pilot.pause()


def _app(tmp_path: Path, *, with_context: bool = True) -> OntologyApp:
    gear, places = _files(tmp_path)
    context = [places] if with_context else []
    return OntologyApp(
        store.load(gear, context=context),
        source=gear.name,
        path=gear,
        context=context,
    )


# ── truncation ────────────────────────────────────────────────────────────────


def test_truncate_keeps_short_names_whole():
    assert truncate_name("gear.ttl", 20) == "gear.ttl"


def test_truncate_keeps_the_extension():
    """``adeo.ttl`` beside ``adeo.rdf`` is the same ontology exported twice — a
    plain right-truncation renders both as the same string."""
    out = truncate_name("adeo-digital-taxonomy-skos.ttl", 16)
    assert out.endswith(".ttl")
    assert len(out) <= 16


def test_truncate_keeps_the_start_of_the_name():
    out = truncate_name("leboncoin-2026-08-20.ttl", 16)
    assert out.startswith("leboncoin")


def test_truncate_survives_a_name_without_an_extension():
    assert truncate_name("averyveryverylongname", 8) == "averyve…"


# ── what the chip says ────────────────────────────────────────────────────────


def test_chip_shows_the_working_file_name(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            chip = app.query_one("#working-file", WorkingFileChip)
            assert "gear.ttl" in chip.render_text()

    asyncio.run(scenario())


def test_chip_shows_the_context_count(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            chip = app.query_one("#working-file", WorkingFileChip)
            assert "+1 context" in chip.render_text()

    asyncio.run(scenario())


def test_chip_offers_no_caret_when_only_one_file_is_open(tmp_path):
    """A caret onto a menu whose only row is the one you are on is an
    affordance that does nothing."""

    async def scenario() -> None:
        app = _app(tmp_path, with_context=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            chip = app.query_one("#working-file", WorkingFileChip)
            assert chip.switchable is False
            assert "▾" not in chip.render_text()

    asyncio.run(scenario())


def test_chip_says_nothing_in_a_session_with_no_file(tmp_path):
    """A taxonomy opened without a path has no working file to name, and an
    empty chip is the honest rendering of that — not "Working file None"."""

    async def scenario() -> None:
        app = OntologyApp(store.load(_files(tmp_path)[0]), source="gear.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            chip = app.query_one("#working-file", WorkingFileChip)
            assert chip.render_text() == ""

    asyncio.run(scenario())


def test_title_no_longer_repeats_the_filename(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert "gear.ttl" not in app.title

    asyncio.run(scenario())


# ── the menu ──────────────────────────────────────────────────────────────────


def test_f_binding_opens_the_menu(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_working_file()
            await pilot.pause()
            assert app.query_one("#working-file-menu", WorkingFileMenu).has_class("open")

    asyncio.run(scenario())


def test_menu_lists_every_open_file(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_working_file()
            await pilot.pause()
            menu = app.query_one("#working-file-menu", WorkingFileMenu)
            assert menu.option_count == 2

    asyncio.run(scenario())


def test_menu_marks_which_file_is_writable(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            menu = app.query_one("#working-file-menu", WorkingFileMenu)
            gear, places = app.loaded_files()

            assert "writable" in menu._row(gear, gear)
            assert "context" in menu._row(places, gear)

    asyncio.run(scenario())


def test_menu_opens_on_the_current_file(tmp_path):
    """The cursor starts where you are, so ⏎ without moving is a no-op rather
    than a switch you did not ask for."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_working_file()
            await pilot.pause()
            assert app.query_one("#working-file-menu", WorkingFileMenu).highlighted == 0

    asyncio.run(scenario())


def test_escape_dismisses_without_switching(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            before = app._path
            app.action_working_file()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            menu = app.query_one("#working-file-menu", WorkingFileMenu)
            assert not menu.has_class("open")
            assert app._path == before

    asyncio.run(scenario())


def test_single_file_session_explains_instead_of_opening(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path, with_context=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_working_file()
            await pilot.pause()
            assert not app.query_one("#working-file-menu", WorkingFileMenu).has_class("open")

    asyncio.run(scenario())


# ── switching, end to end in the app ──────────────────────────────────────────


def test_switching_makes_the_chosen_file_writable(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            _gear, places = app.loaded_files()
            app.switch_working_file(places)
            await _settle(pilot, app)

            assert app._path == places
            assert store.is_editable(app.tax, NS + "Alps")
            assert not store.is_editable(app.tax, NS + "Tent")

    asyncio.run(scenario())


def test_switching_updates_the_chip(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            _gear, places = app.loaded_files()
            app.switch_working_file(places)
            await _settle(pilot, app)

            chip = app.query_one("#working-file", WorkingFileChip)
            assert "places.ttl" in chip.render_text()

    asyncio.run(scenario())


def test_switching_keeps_the_whole_graph_loaded(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            _gear, places = app.loaded_files()
            app.switch_working_file(places)
            await _settle(pilot, app)

            assert NS + "Tent" in app.tax.concepts
            assert NS + "Alps" in app.tax.concepts

    asyncio.run(scenario())


def test_switching_to_a_deleted_file_is_refused(tmp_path):
    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            gear, places = app.loaded_files()
            places.unlink()

            app.switch_working_file(places)
            await _settle(pilot, app)

            assert app._path == gear  # the session is untouched

    asyncio.run(scenario())


@pytest.mark.parametrize("glyph", ["🔒"])
def test_the_locks_move_with_the_roles(tmp_path, glyph):
    """The clearest confirmation a switch worked: the rows you cannot edit are
    now the other file's."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert glyph in app._row_text(NS + "Alps", "concept", "Alps")
            assert glyph not in app._row_text(NS + "Tent", "concept", "Tent")

            _gear, places = app.loaded_files()
            app.switch_working_file(places)
            await _settle(pilot, app)

            assert glyph in app._row_text(NS + "Tent", "concept", "Tent")
            assert glyph not in app._row_text(NS + "Alps", "concept", "Alps")

    asyncio.run(scenario())


def test_chip_renders_before_it_is_mounted():
    """``Widget.screen`` raises ``NoScreen`` off-screen rather than returning
    None, and the chip renders once from ``on_mount`` — so asking for the
    terminal width must not be a truth test."""
    chip = WorkingFileChip()
    chip.update_files(Path("gear.ttl"), 2)

    assert "gear.ttl" in chip.render_text()


def test_a_broken_chip_never_stops_the_app_starting(tmp_path, monkeypatch):
    """Regression: painting the chip happened outside the guard, so an
    unmounted-widget error escaped ``on_mount`` and aborted startup — a header
    decoration taking the whole editor down with it."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("no screen yet")

    monkeypatch.setattr(WorkingFileChip, "update_files", boom)

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.is_running  # started despite the chip failing to paint

    asyncio.run(scenario())


# ── the whole journey, through real events ────────────────────────────────────


def test_clicking_the_chip_opens_the_menu(tmp_path):
    """Everything above drives the app by calling methods; this drives it the
    way a user does, so the click → message → menu wiring is covered too."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click(WorkingFileChip)
            await pilot.pause()

            assert app.query_one("#working-file-menu", WorkingFileMenu).has_class("open")

    asyncio.run(scenario())


def test_choosing_a_row_switches_the_working_file(tmp_path):
    """Menu selection → Chosen message → switch, with no direct call."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            _gear, places = app.loaded_files()
            app.action_working_file()
            await pilot.pause()

            menu = app.query_one("#working-file-menu", WorkingFileMenu)
            menu.highlighted = 1  # the context file
            await pilot.press("enter")
            await _settle(pilot, app)

            assert app._path == places

    asyncio.run(scenario())


def test_choosing_the_current_row_closes_without_reloading(tmp_path):
    """Picking the row you are already on must not re-parse the ontology."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            before = app.tax
            app.action_working_file()
            await pilot.pause()
            await pilot.press("enter")  # opens highlighted on the current file
            await _settle(pilot, app)

            assert app.tax is before  # same model object: nothing was re-read

    asyncio.run(scenario())


def test_an_unreadable_choice_is_reported_and_keeps_the_session(tmp_path):
    """A parse failure mid-switch must leave the previous model in place rather
    than a half-switched session."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            gear, places = app.loaded_files()
            before = app.tax
            places.write_text("this is not turtle {{{", encoding="utf-8")

            app.switch_working_file(places)
            await _settle(pilot, app)

            assert app._path == gear
            assert app.tax is before

    asyncio.run(scenario())


def test_the_chip_does_nothing_in_a_session_with_no_file(tmp_path):
    async def scenario() -> None:
        app = OntologyApp(store.load(_files(tmp_path)[0]), source="gear.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_working_file()
            await pilot.pause()

            assert app.loaded_files() == []
            assert not app.query_one("#working-file-menu", WorkingFileMenu).has_class("open")

    asyncio.run(scenario())
