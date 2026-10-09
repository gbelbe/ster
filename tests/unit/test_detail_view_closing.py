"""The detail pane must not crash a closing app.

A late timer or click can ask for a draw after an exit was requested. Textual then
reports every widget as detached even though it is still in the DOM, and mounting
into it raises ``MountError`` — which took the whole TUI down on a busy machine.
"""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App

from ster.model import Taxonomy
from ster.tui.detail_view import DetailView

pytestmark = pytest.mark.tui


class _Host(App):
    def compose(self):  # type: ignore[no-untyped-def]
        yield DetailView(id="detail")


def test_drawing_into_the_pane_of_a_closing_app_does_nothing():
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            view = app.query_one("#detail", DetailView)
            app._exit = True  # what requesting an exit sets

            view.update_entity(Taxonomy(), None)  # raised MountError before the guard
            await pilot.pause()

    asyncio.run(scenario())


def test_drawing_into_a_live_pane_still_works():
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            view = app.query_one("#detail", DetailView)

            view.update_entity(Taxonomy(), None)
            await pilot.pause()

            assert "Select a class" in str(view.query_one("Static").render())

    asyncio.run(scenario())


def test_a_tree_highlight_that_arrives_after_quitting_does_not_crash_the_app():
    """The reported crash: a click's highlight event was still queued when the app quit
    (busy machine, large ontology), so ``on_tree_node_highlighted`` drew into a pane that
    Textual already called detached and the quit ended in a MountError traceback."""

    async def scenario() -> None:
        from pathlib import Path

        from textual.widgets import Tree

        from ster import store
        from ster.tui.app import OntologyApp

        demo = Path(__file__).parents[2] / "ster" / "tui" / "demo.ttl"
        app = OntologyApp(store.load(demo), source="demo.ttl", path=demo)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._exit = True  # a quit is under way
            app._last_highlight = 0.0  # not a held-down key: the draw is immediate
            node = next(n for n in app.query_one("#tree", Tree).root.children if n.data)

            app.on_tree_node_highlighted(Tree.NodeHighlighted(node))  # raised MountError

    asyncio.run(scenario())
