"""Pilot tests for the Textual SparqlEditor autocomplete popup (ster/tui/sparql_editor.py)."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from ster.tui.sparql_complete import Completion, EntityIndex, replace_start, suggest
from ster.tui.sparql_editor import SparqlEditor

KEYWORDS = ["SELECT", "WHERE", "FILTER", "OPTIONAL", "PREFIX"]

INDEX = EntityIndex(
    prefixes={"": "https://ex/"},
    classes={"": ["Animal", "Dog"]},
    individuals={"": ["rex"]},
    properties={"": ["hasOwner"]},
)


def _suggest_fn(text: str, cursor: int) -> tuple[list[Completion], int]:
    return suggest(text, cursor, INDEX, KEYWORDS), replace_start(text, cursor, {""})


class _Host(App):
    CSS = "Screen { layers: base popup; }"

    def compose(self) -> ComposeResult:
        yield SparqlEditor("", suggest_fn=_suggest_fn, id="ed")


def _run(coro_factory) -> None:  # noqa: ANN001
    asyncio.run(coro_factory())


def _set(ed: SparqlEditor, text: str) -> None:
    ed.text = text
    lines = text.split("\n")
    ed.move_cursor((len(lines) - 1, len(lines[-1])))


def test_typing_a_qname_opens_the_entity_popup() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test(size=(80, 24)) as pilot:
            ed = app.query_one("#ed", SparqlEditor)
            _set(ed, "SELECT * WHERE { ?s a :")
            ed._refresh()
            await pilot.pause()
            popup = ed._popup
            assert popup is not None and popup.display
            assert ed._completions[0].kind == "class"  # object of 'a' → classes first

    _run(scenario)


def test_accept_inserts_local_name_keeping_prefix() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test(size=(80, 24)) as pilot:
            ed = app.query_one("#ed", SparqlEditor)
            _set(ed, "SELECT * WHERE { ?s a :An")
            ed._refresh()
            await pilot.pause()
            ed._popup.highlighted = 0  # 'Animal'
            ed._accept()
            await pilot.pause()
            assert ed.text == "SELECT * WHERE { ?s a :Animal"
            assert not ed._popup.display

    _run(scenario)


def test_keyword_completion_expands_block_with_caret_inside() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test(size=(80, 24)) as pilot:
            ed = app.query_one("#ed", SparqlEditor)
            _set(ed, "WHERE")
            ed._refresh()
            await pilot.pause()
            ed._popup.highlighted = 0  # 'WHERE'
            ed._accept()
            await pilot.pause()
            assert ed.text == "WHERE {\n  \n}"
            # caret sits on the inner indented line, not at the very end
            assert ed.text[ed._cursor_index() :] == "\n}"

    _run(scenario)


def test_escape_closes_the_popup() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test(size=(80, 24)) as pilot:
            ed = app.query_one("#ed", SparqlEditor)
            _set(ed, "SELECT * WHERE { ?s a :")
            ed._refresh()
            await pilot.pause()
            assert ed._popup.display
            await pilot.press("escape")  # routed through _on_key while popup open
            await pilot.pause()
            assert not ed._popup.display

    _run(scenario)


def test_no_suggestions_keeps_popup_hidden() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test(size=(80, 24)) as pilot:
            ed = app.query_one("#ed", SparqlEditor)
            _set(ed, "SELECT ?s ")  # trailing space, nothing to complete
            ed._refresh()
            await pilot.pause()
            assert not ed._popup.display

    _run(scenario)


def test_enter_accepts_via_key_when_popup_open() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test(size=(80, 24)) as pilot:
            ed = app.query_one("#ed", SparqlEditor)
            ed.focus()
            _set(ed, "SELECT * WHERE { ?s a :Do")
            ed._refresh()
            await pilot.pause()
            assert ed._popup.display and ed._completions[0].insert == "Dog"
            await pilot.press("enter")  # accept the highlighted completion
            await pilot.pause()
            assert ed.text == "SELECT * WHERE { ?s a :Dog"
            assert isinstance(ed._popup, OptionList) and not ed._popup.display

    _run(scenario)
