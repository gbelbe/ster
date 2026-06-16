"""Interaction + snapshot tests for the New-TUI app (``ster.tui.app``).

Textual is a core dependency, so these always run in CI (covering ``app.py``).
The Pilot tests drive the UI with key presses via ``App.run_test()``; the
visual snapshot test is gated to local runs (renderer output can vary across
CI machines) and is refreshed with ``pytest --snapshot-update``.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

import pytest

from ster import store
from ster.tui.app import EntitySearch, OntologyApp

from .test_tui_data import DEMO, ZOO


def _run(scenario: Callable[..., Awaitable[None]]) -> None:
    """Run an async Pilot scenario in a fresh loop (no pytest-asyncio needed)."""
    asyncio.run(scenario())


def _app() -> OntologyApp:
    return OntologyApp(store.load(DEMO), source="demo.ttl")


def test_editing_a_class_label_commits_and_saves(tmp_path) -> None:
    """End-to-end mutation pipeline: focus a label row → modal → command → save."""

    async def scenario() -> None:
        from textual.widgets import Input

        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")  # populate the detail pane (no tree-focus race)
            await pilot.pause()
            label_row = next(
                r for r in app.query(DetailRow) if r.field.meta.get("type") == "rdf_label"
            )
            label_row.focus()
            await pilot.pause()
            assert app.focused is label_row
            await pilot.press("enter")  # row binding → open the edit modal
            await pilot.pause()
            assert app.screen.__class__.__name__ == "EditModal"
            app.screen.query_one("#edit-input", Input).value = "Human"
            await pilot.press("enter")  # submit the modal
            for _ in range(3):
                await pilot.pause()
            # committed in memory …
            labels = {lbl.lang: lbl.value for lbl in app.tax.owl_classes[ZOO + "Person"].labels}
            assert labels.get("en") == "Human"
            # … and persisted to disk
            assert "Human" in src.read_text(encoding="utf-8")

    _run(scenario)


def test_arrow_keys_navigate_panes_and_rows() -> None:
    """Right enters the detail pane, up/down move between rows, left returns to the tree."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.tui.detail_view import DetailRow

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")  # populate the detail pane
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            tree.focus()
            await pilot.pause()

            await pilot.press("right")  # tree → first detail row
            await pilot.pause()
            assert isinstance(app.focused, DetailRow)
            first = app.focused

            await pilot.press("down")  # → next row
            await pilot.pause()
            assert isinstance(app.focused, DetailRow) and app.focused is not first

            await pilot.press("up")  # → back to the first row
            await pilot.pause()
            assert app.focused is first

            await pilot.press("left")  # detail → tree
            await pilot.pause()
            assert app.focused is tree

    _run(scenario)


def test_detail_rows_wrap_around() -> None:
    """Up from the first row jumps to the last; down from the last back to the first."""

    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")
            await pilot.pause()
            rows = list(app.query("#detail DetailRow"))
            rows[0].focus()
            await pilot.pause()
            await pilot.press("up")  # wrap to the last row
            await pilot.pause()
            assert app.focused is rows[-1]
            await pilot.press("down")  # wrap back to the first row
            await pilot.pause()
            assert app.focused is rows[0]

    _run(scenario)


def test_tree_cursor_wraps_around() -> None:
    """Up at the top of the tree jumps to the last node; down there wraps to the top."""

    async def scenario() -> None:
        from textual.widgets import Tree

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            tree.focus()
            tree.cursor_line = 0
            await pilot.pause()
            await pilot.press("up")  # wrap to the last visible line
            await pilot.pause()
            assert tree.cursor_line == len(tree._tree_lines) - 1 > 0
            await pilot.press("down")  # wrap back to the top
            await pilot.pause()
            assert tree.cursor_line == 0

    _run(scenario)


def test_picker_list_wraps_around(tmp_path) -> None:
    """The entity picker's up/down wrap around the ends of a long candidate list."""

    async def scenario() -> None:
        from textual.widgets import OptionList

        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Cat")
            await pilot.pause()
            row = next(
                r for r in app.query(DetailRow) if r.field.meta.get("action") == "link_superclass"
            )
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # opens the picker modal
            await pilot.pause()
            options = app.screen.query_one(OptionList)
            options.highlighted = 0
            await pilot.pause()
            await pilot.press("up")  # wrap to the last candidate
            await pilot.pause()
            assert options.highlighted == options.option_count - 1
            await pilot.press("down")  # wrap back to the first
            await pilot.pause()
            assert options.highlighted == 0

    _run(scenario)


def _tree_uris(tree) -> set:  # noqa: ANN001
    """Every node URI (``.data``) in a tree, recursively."""
    out: set = set()

    def walk(node) -> None:  # noqa: ANN001
        if node.data:
            out.add(node.data)
        for child in node.children:
            walk(child)

    walk(tree.root)
    return out


def test_properties_live_in_their_own_pane() -> None:
    """Properties sit in #prop-tree; classes/individuals stay in the main #tree."""

    async def scenario() -> None:
        from textual.widgets import Tree

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            main = _tree_uris(app.query_one("#tree", Tree))
            props = _tree_uris(app.query_one("#prop-tree", Tree))
            # properties only in the dedicated pane
            assert {ZOO + "hasOwner", ZOO + "hasAge"} <= props
            assert ZOO + "hasOwner" not in main
            # the class hierarchy only in the main tree
            assert ZOO + "Animal" in main and ZOO + "Animal" not in props

    _run(scenario)


def test_themes_registered_default_solarized_and_cycles() -> None:
    """Default is solarized-light; the branded `ster` theme is available; `d` cycles."""

    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.theme == "solarized-light"
            assert "ster" in app.available_themes  # branded theme registered
            assert "solarized-light" in app.available_themes  # built-ins kept
            await pilot.press("d")  # cycle to the next shortlist theme
            await pilot.pause()
            assert app.theme != "solarized-light"

    _run(scenario)


def test_panels_have_border_titles() -> None:
    """Each pane is titled; the detail pane's title tracks the shown entity."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.tui.detail_view import DetailView

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.query_one("#tree", Tree).border_title == "Ontology"
            assert app.query_one("#prop-tree", Tree).border_title == "Properties"
            app._show(ZOO + "Cat")
            await pilot.pause()
            assert app.query_one("#detail", DetailView).border_title == "Cat"

    _run(scenario)


def test_modal_chrome_titles_and_danger_accent() -> None:
    """Modals carry the prompt as a border title; delete confirms get the danger class."""

    async def scenario() -> None:
        from ster.tui.choice_modal import ChoiceModal
        from ster.tui.edit_modal import EditModal
        from ster.tui.picker_modal import PickerModal

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.push_screen(EditModal("New subclass URI", "x"))
            await pilot.pause()
            assert app.screen.query_one("#edit-box").border_title == "New subclass URI"
            app.pop_screen()
            await pilot.pause()

            app.push_screen(PickerModal("Pick a class", [("Animal", "a")]))
            await pilot.pause()
            assert app.screen.query_one("#picker-box").border_title == "Pick a class"
            app.pop_screen()
            await pilot.pause()

            app.push_screen(ChoiceModal("Delete «Cat»?", [("Keep", "keep")], danger=True))
            await pilot.pause()
            box = app.screen.query_one("#choice-box")
            assert box.border_title == "Delete «Cat»?"
            assert box.has_class("-danger")

    _run(scenario)


def test_help_overlay_opens_and_closes() -> None:
    """`?` opens the titled help overlay; Esc closes it."""

    async def scenario() -> None:
        from ster.tui.help_screen import HelpScreen

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            assert app.screen.query_one("#help-box").border_title.startswith("ster")
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)

    _run(scenario)


def test_picker_filters_as_you_type(tmp_path) -> None:
    """Typing in the picker narrows the candidate list."""

    async def scenario() -> None:
        from textual.widgets import OptionList

        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Cat")
            await pilot.pause()
            row = next(
                r for r in app.query(DetailRow) if r.field.meta.get("action") == "link_superclass"
            )
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # open the picker (filter box is focused)
            await pilot.pause()
            options = app.screen.query_one(OptionList)
            full = options.option_count
            await pilot.press("m", "a", "m")  # filter toward "Mammal"
            await pilot.pause()
            assert 0 < options.option_count < full

    _run(scenario)


def test_focus_restored_after_modal_edit(tmp_path) -> None:
    """Regression: after a modal mutation the keyboard stays alive (focus lands on a row).

    The edit rebuilds the detail rows, destroying the row that had focus; without
    restoration, focus becomes None and the UI feels frozen to keyboard input.
    """

    async def scenario() -> None:
        from textual.widgets import Input

        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")
            await pilot.pause()
            row = next(r for r in app.query(DetailRow) if r.field.meta.get("type") == "rdf_label")
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # open the edit modal
            await pilot.pause()
            app.screen.query_one("#edit-input", Input).value = "Human"
            await pilot.press("enter")  # submit → mutation rebuilds the detail rows
            for _ in range(4):
                await pilot.pause()
            assert isinstance(app.focused, DetailRow)  # keyboard still works

    _run(scenario)


def test_detail_row_tooltips() -> None:
    """Editable rows hint 'Enter to edit'; action rows describe the action; stats none."""
    from ster.nav.logic import DetailField
    from ster.tui.detail_view import DetailRow

    editable = DetailRow(DetailField("k", "label", "v", editable=True, meta={"type": "rdf_label"}))
    assert editable.tooltip == "Enter to edit"
    action = DetailRow(
        DetailField(
            "k", "⊘ Delete", "", editable=False, meta={"type": "action", "action": "delete_class"}
        )
    )
    assert action.tooltip and "Delete" in action.tooltip
    stat = DetailRow(DetailField("k", "x", "y", editable=False, meta={"type": "stat"}))
    assert stat.tooltip is None


def test_clicking_blank_pane_space_selects_the_window() -> None:
    """Clicking blank space in a pane selects it: detail → a row; tree → the tree."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.tui.detail_view import DetailRow, DetailView

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            tree.focus()
            await pilot.pause()
            # real click on blank space at the bottom of the detail pane → focuses a row
            view = app.query_one("#detail", DetailView)
            await pilot.click("#detail", offset=(4, view.region.height - 2))
            await pilot.pause()
            assert isinstance(app.focused, DetailRow)
            # real click on blank space at the bottom of the tree pane → focuses the tree
            await pilot.click("#tree", offset=(2, tree.region.height - 2))
            await pilot.pause()
            assert app.focused is tree

    _run(scenario)


def test_clicking_empty_detail_pane_selects_it() -> None:
    """With no entity shown (placeholder), clicking the detail pane focuses the pane."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.tui.detail_view import DetailView

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(None)  # placeholder, no rows
            await pilot.pause()
            app.query_one("#tree", Tree).focus()
            await pilot.pause()
            view = app.query_one("#detail", DetailView)
            await pilot.click("#detail", offset=(4, view.region.height - 2))
            await pilot.pause()
            assert app.focused is view

    _run(scenario)


def test_view_graph_action_opens_browser(monkeypatch) -> None:
    """Activating the overview's graph action calls viz_vowl.open_in_browser (read-only OK)."""

    async def scenario() -> None:
        from ster import viz_vowl
        from ster.tui import detail
        from ster.tui.detail_view import DetailRow

        calls: list = []
        monkeypatch.setattr(
            viz_vowl,
            "open_in_browser",
            lambda tax, path=None, on_change_fn=None: calls.append(tax) or "http://x",
        )
        app = _app()  # no path → read-only; the graph view still works
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(detail.OVERVIEW_URI)
            await pilot.pause()
            row = next(
                r
                for r in app.query(DetailRow)
                if r.field.meta.get("action") == "view_ontology_graph"
            )
            row.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert calls  # open_in_browser was invoked

    _run(scenario)


def test_right_click_opens_context_menu_left_click_does_not() -> None:
    """Right-click a node opens its context menu; left-click is left to the tree."""

    async def scenario() -> None:
        import types

        from textual.widgets import Tree

        from ster.tui.context_menu import ContextMenu

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.jump_to(ZOO + "Cat")
            for _ in range(3):
                await pilot.pause()
            tree = app.query_one("#tree", Tree)
            menu = app.query_one("#ctx-menu", ContextMenu)
            tree.hover_line = tree.cursor_line  # cursor is on Cat after jump_to
            tree.on_click(types.SimpleNamespace(button=1))  # left → no menu
            await pilot.pause()
            assert not menu.has_class("open")
            # right → menu opens as an overlay (the TUI stays visible — not a screen swap)
            tree.on_click(types.SimpleNamespace(button=3, screen_x=5, screen_y=3))
            await pilot.pause()
            assert menu.has_class("open")
            actions = [a for _, a in menu._items]
            assert {"move_class", "class_to_individual", "rename", "delete_class"} <= set(actions)

    _run(scenario)


def test_context_menu_dispatches_rename_and_delete(tmp_path) -> None:
    """Choosing a context-menu action runs the matching flow (rename → edit; delete → choice)."""

    async def scenario() -> None:
        from ster.tui.choice_modal import ChoiceModal
        from ster.tui.context_menu import ContextMenu
        from ster.tui.edit_modal import EditModal

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.open_context_menu(ZOO + "Cat")
            await pilot.pause()
            assert app.query_one("#ctx-menu", ContextMenu).has_class("open")

            app.on_context_menu_chosen(ContextMenu.Chosen("rename"))  # → rename modal
            await pilot.pause()
            assert isinstance(app.screen, EditModal)
            app.screen.dismiss(None)
            await pilot.pause()

            app.open_context_menu(ZOO + "Cat")
            await pilot.pause()
            app.on_context_menu_chosen(ContextMenu.Chosen("delete_class"))  # → danger choice
            await pilot.pause()
            assert isinstance(app.screen, ChoiceModal)
            assert app.screen.query_one("#choice-box").has_class("-danger")

    _run(scenario)


def test_tree_populates_and_focuses() -> None:
    async def scenario() -> None:
        from textual.widgets import Tree

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert len(app._uri_nodes) == 12  # every class/individual/property indexed
            assert isinstance(app.focused, Tree)  # tree gets focus on mount

    _run(scenario)


def test_arrow_keys_drive_the_detail_panel() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("down", "down", "down")  # Ontology → Classes → Animal → Person
            await pilot.pause()
            assert "Person" in app._detail_text  # detail panel followed the cursor

    _run(scenario)


def test_action_row_creates_a_subclass_and_saves(tmp_path) -> None:
    """An action row (Enter) → modal → constructive command → reload + save."""

    async def scenario() -> None:
        from textual.widgets import Input

        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")
            await pilot.pause()
            row = next(
                r for r in app.query(DetailRow) if r.field.meta.get("action") == "new_subclass"
            )
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # action row → modal
            await pilot.pause()
            assert app.screen.__class__.__name__ == "EditModal"
            app.screen.query_one("#edit-input", Input).value = ZOO + "Worker"
            await pilot.press("enter")  # submit
            for _ in range(3):
                await pilot.pause()
            assert ZOO + "Worker" in app.tax.owl_classes  # created in memory
            assert "Worker" in src.read_text(encoding="utf-8")  # persisted

    _run(scenario)


def test_delete_class_via_choice_modal_and_saves(tmp_path) -> None:
    """Destructive path: Enter on delete row → mode choice → OwlDeleteClass → save."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Cat")
            await pilot.pause()
            row = next(
                r for r in app.query(DetailRow) if r.field.meta.get("action") == "delete_class"
            )
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # → mode-choice modal
            await pilot.pause()
            assert app.screen.__class__.__name__ == "ChoiceModal"
            await pilot.click("#opt-delete_all")  # pick a mode
            for _ in range(3):
                await pilot.pause()
            assert ZOO + "Cat" not in app.tax.owl_classes  # gone in memory
            assert ZOO + "Cat" not in store.load(src).owl_classes  # gone on disk

    _run(scenario)


def test_add_superclass_via_picker_and_saves(tmp_path) -> None:
    """Relation path: Enter on "Add superclass" → picker → OwlMoveClass → save."""

    async def scenario() -> None:
        from textual.widgets import OptionList

        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Cat")
            await pilot.pause()
            row = next(
                r for r in app.query(DetailRow) if r.field.meta.get("action") == "link_superclass"
            )
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # → picker
            await pilot.pause()
            modal = app.screen
            assert modal.__class__.__name__ == "PickerModal"
            idx = next(i for i, (_, uri) in enumerate(modal._options) if uri == ZOO + "Person")
            modal.query_one(OptionList).highlighted = idx
            await pilot.press("enter")  # select Person as an additional superclass
            for _ in range(3):
                await pilot.pause()
            assert ZOO + "Person" in app.tax.owl_classes[ZOO + "Cat"].sub_class_of  # in memory
            assert ZOO + "Person" in store.load(src).owl_classes[ZOO + "Cat"].sub_class_of  # disk

    _run(scenario)


def test_command_palette_search_jumps_end_to_end() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("slash")  # open the fuzzy search palette
            await pilot.pause()
            assert app.screen.__class__.__name__ == "CommandPalette"
            await pilot.press(*"rex")  # type a query
            for _ in range(3):
                await pilot.pause()  # let the async provider search settle
            await pilot.press("enter")  # pick the top hit
            for _ in range(3):
                await pilot.pause()
            assert app.screen.__class__.__name__ == "Screen"  # palette closed
            assert "Rex" in app._detail_text and "Alice" in app._detail_text  # jumped + detail

    _run(scenario)


def test_expand_collapse_keys_and_jump_to_deep_node() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")  # expand all
            await pilot.pause()
            assert app._uri_nodes[ZOO + "Dog"].line >= 0  # a deep node is now visible
            await pilot.press("c")  # collapse
            await pilot.pause()
            app.jump_to(ZOO + "Rex")  # re-expands ancestors + selects
            await pilot.pause()
            assert "Rex" in app._detail_text

    _run(scenario)


def test_detail_view_composes_focusable_rows() -> None:
    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow, SectionHeader

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.jump_to(ZOO + "Dog")
            await pilot.pause()
            rows = list(app.query(DetailRow))
            headers = list(app.query(SectionHeader))
            assert rows, "detail view should compose one focusable row per field"
            assert all(r.can_focus for r in rows)
            assert any(h.title_text == "Identity" for h in headers)

    _run(scenario)


def test_search_provider_fuzzy_matches() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)):
            provider = EntitySearch(app.screen)
            await provider.startup()
            hits = [hit async for hit in provider.search("eag")]
            assert any("Eagle" in hit.text for hit in hits)

    _run(scenario)


def test_launch_constructs_and_runs_the_app() -> None:
    from unittest.mock import patch

    import ster.tui as tui

    with patch.object(OntologyApp, "run", autospec=True) as run:
        tui.launch(store.load(DEMO), source="demo.ttl")
    run.assert_called_once()


def test_dunder_main_launches(monkeypatch) -> None:
    from unittest.mock import patch

    with patch("ster.tui.launch") as launch:
        import ster.tui.__main__ as entry

        entry.main([str(DEMO)])
    launch.assert_called_once()


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="visual snapshot is renderer-sensitive; run locally with --snapshot-update",
)
def test_browser_snapshot(snap_compare) -> None:
    """Render the app (after jumping to Rex) and diff against the committed SVG."""

    async def jump(pilot) -> None:
        await pilot.pause()
        pilot.app.jump_to(ZOO + "Rex")
        await pilot.pause()

    assert snap_compare(_app(), terminal_size=(120, 40), run_before=jump)
