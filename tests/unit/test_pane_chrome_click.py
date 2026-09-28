"""Clicking a pane's chrome should fold it, not only its header row.

The three left panes accordion when clicked, but `on_click` only acted when the
click landed on the pane's *header row*. A click on the purple border, on the
border title, or on empty space below the last row finds no tree node, so it did
nothing — the one part of the box that most looks like a title bar was the one
part that was not clickable.
"""

from __future__ import annotations

import asyncio
import types
from pathlib import Path

import pytest
from textual.widgets import Tree

from ster import store
from ster.tui.app import OntologyApp

pytestmark = pytest.mark.tui

TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/x#> .

ex:Scheme a skos:ConceptScheme ; rdfs:label "S"@en .
ex:A a skos:Concept ; skos:prefLabel "A"@en ; skos:inScheme ex:Scheme .
ex:Klass a owl:Class ; rdfs:label "Klass"@en .
ex:rel a owl:ObjectProperty ; rdfs:label "rel"@en .
"""

PANES = ("tree", "ont-tree", "prop-tree")


def _app(tmp_path: Path) -> OntologyApp:
    src = tmp_path / "o.ttl"
    src.write_text(TTL, encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src)


def _click_line(app, pid: str, line: int) -> None:
    """A left-click on *line* of the pane, however that line maps to a node."""
    tree = app.query_one(f"#{pid}", Tree)
    tree.hover_line = line
    tree.on_click(types.SimpleNamespace(button=1, style=None, prevent_default=lambda: None))


def _folded(app) -> set[str]:
    return {p for p in PANES if app.query_one(f"#{p}", Tree).has_class("folded")}


@pytest.mark.parametrize("pid", PANES)
def test_clicking_empty_space_in_a_pane_folds_it(tmp_path, pid) -> None:
    """Below the last row there is no node — the click must still reach the pane."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            before = _folded(app)
            _click_line(app, pid, 9999)  # far below any row: get_node_at_line → None
            await pilot.pause()

            assert _folded(app) != before, "clicking blank space changed nothing"

    asyncio.run(scenario())


@pytest.mark.parametrize("pid", PANES)
def test_a_pane_chrome_click_shows_that_panes_overview(tmp_path, pid) -> None:
    """Folding by chrome must select the pane too, as the header row does."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            _click_line(app, pid, 9999)
            await pilot.pause()

            assert app._detail_uri == app._PANEL_OVERVIEW[pid]

    asyncio.run(scenario())


def test_clicking_a_content_row_still_selects_it_rather_than_folding(tmp_path) -> None:
    """The fix must not turn every click into an accordion toggle."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            row = next(
                line
                for line in range(1, 12)
                if (n := tree.get_node_at_line(line)) is not None
                and n.data not in (None, app._PANEL_OVERVIEW["tree"])
            )
            before = _folded(app)
            _click_line(app, "tree", row)
            await pilot.pause()

            assert _folded(app) == before, "a content row must not accordion the pane"

    asyncio.run(scenario())
