"""The right pane's source face: reading the file as code instead of through the UI.

Two properties matter beyond "it shows text". The graph behind the pane is
expensive, so a reader who never opens it must never pay for it — and once an
edit lands, the text on screen is a lie until it is rebuilt.
"""

from __future__ import annotations

import asyncio

from textual.widgets import ContentSwitcher, Tree

from ster import store
from ster.tui.app import OntologyApp
from ster.tui.source_view import PLACEHOLDER, SourceView

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


def _app(tmp_path):
    source = tmp_path / "demo.ttl"
    source.write_text(DEMO, encoding="utf-8")
    return OntologyApp(store.load(source), source=str(source))


def test_the_pane_opens_on_the_detail_face(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.query_one("#right", ContentSwitcher).current == "detail"

    _run(scenario)


def test_r_toggles_between_the_two_faces(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            switcher = app.query_one("#right", ContentSwitcher)
            await pilot.press("r")
            await pilot.pause()
            assert switcher.current == "source"
            await pilot.press("r")
            await pilot.pause()
            assert switcher.current == "detail"

    _run(scenario)


def test_the_graph_is_not_built_until_the_pane_is_opened(tmp_path) -> None:
    """Navigating the tree must not cost a model→graph pass on every keypress."""
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(THING)
            await pilot.pause()
            assert app._source_graph_cache is None
            await pilot.press("r")
            await pilot.pause()
            assert app._source_graph_cache is not None

    _run(scenario)


def test_the_pane_shows_the_selected_entity(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(THING)
            await pilot.press("r")
            await pilot.pause()
            text = app.query_one("#source", SourceView).text
            assert "ex:Thing" in text
            assert "owl:Class" in text

    _run(scenario)


def test_following_the_selection_while_the_source_face_is_open(tmp_path) -> None:
    """The point of the feature: navigate on the left, read the RDF on the right."""
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(THING)
            await pilot.press("r")
            await pilot.pause()
            app._show("https://ex.org/s#Other")
            await pilot.pause()
            assert "ex:Other" in app.query_one("#source", SourceView).text

    _run(scenario)


def test_nothing_selected_reads_as_a_prompt_not_an_empty_box(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = app.query_one("#source", SourceView)
            view.show(None, None)
            await pilot.pause()
            assert view.text == ""
            assert PLACEHOLDER

    _run(scenario)


def test_an_edit_drops_the_cached_graph(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(THING)
            await pilot.press("r")
            await pilot.pause()
            assert app._source_graph_cache is not None
            app._invalidate_source()
            await pilot.pause()
            assert app._source_graph_cache is None or app._source_showing

    _run(scenario)


def test_an_edit_forgets_where_other_entities_were_scrolled(tmp_path) -> None:
    """Their offsets are line numbers, and the lines moved. The entity on screen
    keeps its place: the refresh re-remembers it, so an edit does not throw the
    reader back to the top of the file."""
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(THING)
            await pilot.press("r")
            await pilot.pause()
            view = app.query_one("#source", SourceView)
            view._scroll_memory["https://ex.org/s#Elsewhere"] = 12.0
            app._invalidate_source()
            await pilot.pause()
            assert "https://ex.org/s#Elsewhere" not in view._scroll_memory

    _run(scenario)


def test_the_inbound_count_is_in_the_pane_title(tmp_path) -> None:
    """The one fact the text alone does not give you at a glance."""
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(THING)  # ex:Other subclasses it
            await pilot.press("r")
            await pilot.pause()
            assert "inbound" in str(app.query_one("#source", SourceView).border_title)

    _run(scenario)


def test_copy_from_the_source_pane_yields_the_whole_entity(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(THING)
            await pilot.press("r")
            await pilot.pause()
            app.query_one("#source", SourceView).focus()
            await pilot.pause()
            assert "ex:Thing" in (app._focused_copy_value() or "")

    _run(scenario)


def test_toggling_back_leaves_the_selection_exactly_where_it_was(tmp_path) -> None:
    """`r` swaps how the right pane draws the selection. It is not a navigation.

    The first version called ``_back_to_panel_selection`` on the way out, which
    is what Escape means: it leaves the item layer and shows the pane overview.
    Pressing `r` twice therefore threw the reader off their entity and onto
    ``__ster:taxonomy__`` — the exact opposite of a pane you keep open while
    walking the tree.
    """
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#ont-tree", Tree)
            app._select_panel("ont-tree")
            await pilot.press("enter")  # into the item layer, off the panel header
            await pilot.press("down")
            await pilot.pause()
            before = (tree.cursor_line, app._entered_pid, app._detail_uri)
            assert app._entered_pid == "ont-tree", "must start inside the item layer"

            await pilot.press("r")
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()

            assert (tree.cursor_line, app._entered_pid, app._detail_uri) == before

    _run(scenario)


def test_the_source_face_does_not_steal_focus_from_the_tree(tmp_path) -> None:
    """The loop is: arrow down the left, read the RDF on the right. That only
    works while the arrows still reach the tree."""
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            focused = app.focused
            await pilot.press("r")
            await pilot.pause()
            assert app.focused is focused

    _run(scenario)
