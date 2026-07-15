"""Unit tests for the New-TUI SPARQL query adapter + screen."""

from __future__ import annotations

import asyncio

from textual.app import App
from textual.widgets import DataTable, TextArea

from ster.model import Label, RDFClass, Taxonomy
from ster.tui import query
from ster.tui.query_screen import QueryScreen

BASE = "https://example.org/onto/"


def _tax() -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = BASE.rstrip("/")
    t.owl_classes[BASE + "Person"] = RDFClass(uri=BASE + "Person", labels=[Label("en", "Person")])
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal", labels=[Label("en", "Animal")])
    return t


# ── adapter ─────────────────────────────────────────────────────────────────


def test_run_select_returns_columns_and_rows() -> None:
    res = query.run(_tax(), "SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }")
    assert res.error == ""
    assert res.columns == ["c"]
    values = {r[0] for r in res.rows}
    assert BASE + "Person" in values and BASE + "Animal" in values


def test_run_ask_returns_true_false() -> None:
    res = query.run(_tax(), "ASK { ?c a <http://www.w3.org/2002/07/owl#Class> }")
    assert res.query_type == "ASK"
    assert res.rows == [["true"]]


def test_run_syntax_error_is_captured_not_raised() -> None:
    res = query.run(_tax(), "SELECT ?s WHERE { this is not sparql")
    assert res.error  # an error message, no exception
    assert res.rows == []


def test_run_reflects_in_memory_edits() -> None:
    """A class added in memory (not on disk) is visible to the query."""
    t = _tax()
    t.owl_classes[BASE + "Robot"] = RDFClass(uri=BASE + "Robot", labels=[Label("en", "Robot")])
    res = query.run(t, "SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }")
    assert BASE + "Robot" in {r[0] for r in res.rows}


def test_presets_are_exposed() -> None:
    ps = query.presets()
    assert ps and all(p.label and p.sparql for p in ps)


# ── screen ──────────────────────────────────────────────────────────────────


class _Host(App):
    def compose(self):  # type: ignore[no-untyped-def]
        return iter(())


def _run(coro_factory) -> None:  # noqa: ANN001
    asyncio.run(coro_factory())


def test_screen_prefills_editor_with_a_starter_query() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(QueryScreen(_tax()))
            await pilot.pause()
            editor = app.screen.query_one("#query-editor", TextArea)
            assert "SELECT" in editor.text
            assert app.screen.query_one("#query-results", DataTable) is not None

    _run(scenario)


def test_running_a_select_populates_the_results_table() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(QueryScreen(_tax()))
            await pilot.pause()
            app.screen.query_one(
                "#query-editor", TextArea
            ).text = "SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }"
            app.screen.action_run()
            await pilot.pause()
            table = app.screen.query_one("#query-results", DataTable)
            assert len(table.columns) == 1
            assert len(table.rows) == 2  # Person + Animal
            assert app.screen._last_result.error == ""

    _run(scenario)


def test_running_a_bad_query_shows_the_error_without_crashing() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(QueryScreen(_tax()))
            await pilot.pause()
            app.screen.query_one("#query-editor", TextArea).text = "SELECT ?s WHERE { bad"
            app.screen.action_run()
            await pilot.pause()
            assert app.screen._last_result.error  # the error was captured
            assert len(app.screen.query_one("#query-results", DataTable).rows) == 0

    _run(scenario)


def test_loading_a_preset_sets_the_editor_text() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(QueryScreen(_tax()))
            await pilot.pause()
            preset = query.presets()[0]
            app.screen._apply_preset(preset.sparql)  # what the picker callback does
            await pilot.pause()
            assert app.screen.query_one("#query-editor", TextArea).text == preset.sparql

    _run(scenario)


def test_presets_action_opens_a_picker_that_applies_the_choice() -> None:
    async def scenario() -> None:
        from ster.tui.picker_modal import PickerModal

        app = _Host()
        async with app.run_test() as pilot:
            screen = QueryScreen(_tax())
            app.push_screen(screen)
            await pilot.pause()
            screen.action_presets()  # opens the preset picker
            await pilot.pause()
            assert isinstance(app.screen, PickerModal)
            app.screen.dismiss("0")  # pick the first preset
            await pilot.pause()
            assert screen.query_one("#query-editor", TextArea).text == query.presets()[0].sparql

    _run(scenario)


def test_app_action_open_query_pushes_the_screen() -> None:
    async def scenario() -> None:
        from ster.tui.app import OntologyApp

        app = OntologyApp(_tax(), source="t")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_open_query()
            await pilot.pause()
            assert isinstance(app.screen, QueryScreen)

    _run(scenario)


def test_app_opens_query_on_start_when_requested() -> None:
    async def scenario() -> None:
        from ster.tui.app import OntologyApp

        app = OntologyApp(_tax(), source="t", open_query=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, QueryScreen)

    _run(scenario)
