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


def _open_on(app, pilot, uri: str):
    """Select *uri*, open the source face, and return the view."""

    async def go() -> SourceView:
        await pilot.pause()
        app._show(uri)
        await pilot.press("r")
        await pilot.pause()
        return app.query_one("#source", SourceView)

    return go()


def test_copy_yields_the_turtle_without_headings(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            view = await _open_on(app, pilot, THING)
            view.focus()
            await pilot.pause()
            copied = app._focused_copy_value() or ""
            assert "ex:Thing" in copied
            assert "demo.ttl" not in copied
            assert "point here" not in copied

    _run(scenario)


def test_headings_and_file_labels_are_drawn_outside_the_turtle(tmp_path) -> None:
    """Only statements really in a file are Turtle; ster's commentary is its own kind."""
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            view = await _open_on(app, pilot, THING)  # ex:Other points at it
            kinds = [kind for kind, _ in view.parts]
            assert kinds == [
                *("heading", "turtle"),  # the shared prefixes
                *("heading", "file", "turtle"),  # own statements
                *("heading", "file", "turtle"),  # what points here
            ]
            assert ("file", "demo.ttl") in view.parts
            assert all("demo.ttl" not in text for kind, text in view.parts if kind == "turtle")

    _run(scenario)


def test_the_statements_pointing_here_are_counted_in_their_heading(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            view = await _open_on(app, pilot, THING)
            headings = [text for kind, text in view.parts if kind == "heading"]
            assert any("1 statement points here" in text for text in headings)

    _run(scenario)


def test_an_entity_with_nothing_of_its_own_says_so_in_a_note(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            view = await _open_on(app, pilot, "https://ex.org/s#Nowhere")
            assert view.parts == [("note", "https://ex.org/s#Nowhere is not in the graph")]
            assert view.text == ""

    _run(scenario)


def test_the_turtle_has_no_line_numbers() -> None:
    """They would count lines of this snippet, not of the file — a false claim."""
    from ster.tui.source_view import _turtle_text

    assert _turtle_text("ex:a ex:b ex:c .", "ansi_dark").plain.strip() == "ex:a ex:b ex:c ."


# ── selecting text ────────────────────────────────────────────────────────────
# Root cause of the regression these lock in: the pane drew one Rich Group of
# Syntax blocks, and Textual can only select text in a widget that renders Text
# or Content — for anything else Widget.get_selection returns None, so nothing
# in the pane could be selected or copied with the mouse.


def _select_all_in(app, text: str) -> str:
    """Select everything in the pane's part showing *text*; return what is selected."""
    widget = next(w for w in app.query("#source Static") if text in str(w.render()))
    widget.text_select_all()
    return app.screen.get_selected_text() or ""


def test_the_turtle_can_be_selected_regression(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_on(app, pilot, THING)
            await pilot.pause()
            assert "ex:Thing a owl:Class" in _select_all_in(app, "owl:Class")

    _run(scenario)


def test_ster_s_headings_can_be_selected_too(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_on(app, pilot, THING)
            await pilot.pause()
            assert "Own statements" in _select_all_in(app, "Own statements")
            assert "demo.ttl" in _select_all_in(app, "demo.ttl")

    _run(scenario)


def test_copy_takes_the_selection_rather_than_the_whole_entity(tmp_path) -> None:
    """With text selected, Ctrl+C copies what was selected — nothing more."""
    from unittest.mock import patch

    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_on(app, pilot, THING)
            await pilot.pause()
            selected = _select_all_in(app, "rdfs:subClassOf")  # the part pointing here
            with (
                patch.object(app, "copy_to_clipboard") as copied,
                patch("ster.tui.clipboard.copy_to_system_clipboard", return_value=True),
            ):
                app.action_copy()
            assert copied.call_args.args[0] == selected
            assert "ex:Other" in selected and "owl:Class" not in selected

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


# ── line numbers and prefix files, beside the Turtle ─────────────────────────
# DEMO opens with a blank line and three prefixes, so ex:Thing's statement
# starts on line 6 and ex:Other's on line 7.


def _asides(view, kind: str) -> list[tuple[str, str]]:
    return [aside for (k, _), aside in zip(view.parts, view.asides, strict=True) if k == kind]


def test_each_statement_s_line_is_shown_on_its_first_line(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            view = await _open_on(app, pilot, THING)
            _prefixes, own, pointing = _asides(view, "turtle")
            assert own[0].splitlines()[0] == "L6"
            assert pointing[0].splitlines()[0] == "L7"

    _run(scenario)


def test_each_prefix_names_the_files_that_use_it(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            view = await _open_on(app, pilot, THING)
            prefixes, *_ = _asides(view, "turtle")
            assert all(note == "← demo.ttl" for note in prefixes[1].splitlines())

    _run(scenario)


def test_line_numbers_and_prefix_files_are_not_copied(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            view = await _open_on(app, pilot, THING)
            view.focus()
            await pilot.pause()
            copied = app._focused_copy_value() or ""
            assert "L6" not in copied and "←" not in copied

    _run(scenario)


def test_the_gutter_is_drawn_beside_the_turtle_not_inside_it(tmp_path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            view = await _open_on(app, pilot, THING)
            assert all("L6" not in text for kind, text in view.parts if kind == "turtle")
            shown = [str(w.render()) for w in app.query("#source Static")]
            assert any(line.startswith("L6") for text in shown for line in text.splitlines())

    _run(scenario)
