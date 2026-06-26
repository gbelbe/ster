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


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    """Keep the app independent of the developer's real prefs (theme, language) so
    snapshots and theme-default assertions are deterministic."""
    from ster import api_server
    from ster.nav import prefs

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(prefs, "_lang_prefs_path", lambda: tmp_path / "lang.json")
    monkeypatch.setattr(prefs, "_configured_langs_path", lambda: tmp_path / "clangs.json")
    monkeypatch.setattr(api_server, "_SERVER_CONFIG_FILE", tmp_path / "server_config.json")
    monkeypatch.setattr(api_server, "_TOKEN_FILE", tmp_path / "api_token")


def _run(scenario: Callable[..., Awaitable[None]]) -> None:
    """Run an async Pilot scenario in a fresh loop (no pytest-asyncio needed)."""
    asyncio.run(scenario())


def _app() -> OntologyApp:
    return OntologyApp(store.load(DEMO), source="demo.ttl")


def test_is_actionable_distinguishes_info_rows_from_actionable_rows() -> None:
    """Only editable / action / menu rows are actionable; plain info rows aren't."""
    from ster.nav.logic import DetailField
    from ster.tui.detail_view import _is_actionable

    info = DetailField("st:classes", "total", "4", editable=False, meta={"type": "stat"})
    editable = DetailField("k", "label", "v", editable=True, meta={"type": "rdf_label"})
    action = DetailField("a", "＋ Add", "", editable=False, meta={"action": "add_ont_annotation"})

    assert not _is_actionable(info, None)
    assert _is_actionable(editable, None)
    assert _is_actionable(action, None)
    # A value row with a paired delete sibling opens an Edit/Delete menu → actionable.
    assert _is_actionable(info, editable)


def test_clickable_rows_get_an_affordance_icon() -> None:
    """Clickable value rows show a leading icon (✎ editable, ▸ other); info rows
    and already-glyphed action rows don't get an extra one."""
    from ster.nav.logic import DetailField
    from ster.tui.detail_view import _row_content

    info = DetailField("st:classes", "total", "4", editable=False, meta={"type": "stat"})
    editable = DetailField("k", "label", "v", editable=True, meta={"type": "rdf_label"})
    lint = DetailField(
        "st:lint_warning",
        "Warnings",
        "3",
        editable=False,
        meta={"action": "view_lint", "lint_severity": "warning"},
    )
    action = DetailField(
        "a", "＋ Add", "", editable=False, meta={"type": "action_add", "action": "x"}
    )

    assert "✎" not in _row_content(info, actionable=False)  # info row — no affordance
    assert _row_content(editable, actionable=True).startswith("✎")  # editable → pencil
    assert _row_content(lint, actionable=True).startswith("▸")  # clickable non-edit → marker
    assert "▸" not in _row_content(action, actionable=True)  # already has its own ＋ glyph


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
            rows = [r for r in app.query("#detail DetailRow") if r.can_focus]
            rows[0].focus()
            await pilot.pause()
            await pilot.press("up")  # wrap to the last actionable row
            await pilot.pause()
            assert app.focused is rows[-1]
            await pilot.press("down")  # wrap back to the first actionable row
            await pilot.pause()
            assert app.focused is rows[0]

    _run(scenario)


def test_arrows_skip_information_only_rows_on_overview() -> None:
    """On the ontology overview the arrows step over pure stat / info rows and
    only land on actionable rows (edit, ＋ add, view actions)."""

    async def scenario() -> None:
        from ster.tui import detail
        from ster.tui.detail_view import DetailRow

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(detail.OVERVIEW_URI)
            await pilot.pause()
            all_rows = list(app.query(DetailRow))
            info_rows = [r for r in all_rows if not r.can_focus]
            assert info_rows, "the overview has information-only rows (stats)"
            assert all(not r.field.editable and not r.field.meta.get("action") for r in info_rows)
            # Stepping with the arrows only ever lands on focusable rows.
            focusable = [r for r in all_rows if r.can_focus]
            focusable[0].focus()
            await pilot.pause()
            seen = set()
            for _ in range(len(focusable) + 2):
                await pilot.press("down")
                await pilot.pause()
                assert isinstance(app.focused, DetailRow) and app.focused.can_focus
                seen.add(app.focused)
            assert seen == set(focusable)  # every actionable row is reachable, no info rows

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
            # A class has a context menu → its title carries the ⋯ affordance hint.
            assert app.query_one("#detail", DetailView).border_title == "Cat  ⋯"

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


_SKOS_DUP = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <http://example.org/> .

ex:Scheme a skos:ConceptScheme .
ex:C1 a skos:Concept ;
    skos:inScheme ex:Scheme ;
    skos:prefLabel "One"@en ;
    skos:prefLabel "Uno"@en .
"""


def _lint_row(app, severity: str):  # noqa: ANN001 - test helper
    """The overview's 'Errors'/'Warnings' count row for *severity*."""
    from ster.tui.detail_view import DetailRow

    return next(
        r
        for r in app.query(DetailRow)
        if r.field.meta.get("action") == "view_lint"
        and r.field.meta.get("lint_severity") == severity
    )


def test_warnings_row_opens_a_warnings_only_modal(tmp_path) -> None:
    """Activating the overview's 'Warnings' count row opens a LintModal scoped to
    warnings (errors are excluded)."""

    async def scenario() -> None:
        from ster.tui import detail
        from ster.tui.lint_modal import LintModal

        src = tmp_path / "o.ttl"
        src.write_text(_SKOS_DUP, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(detail.OVERVIEW_URI)
            await pilot.pause()
            _lint_row(app, "warning").focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, LintModal)
            assert all(i["severity"] == "warning" for i in app.screen._issues)

    _run(scenario)


def test_selecting_a_lint_issue_jumps_to_its_entity(tmp_path) -> None:
    """Pressing enter on a missing-label warning navigates to that concept."""

    async def scenario() -> None:
        from textual.widgets import OptionList

        from ster.tui import detail

        # ex:C1 has no prefLabel → a navigable SKOS warning pointing at ex:C1.
        ttl = (
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "@prefix ex:   <http://example.org/> .\n\n"
            "ex:Scheme a skos:ConceptScheme ; skos:hasTopConcept ex:C1 .\n"
            "ex:C1 a skos:Concept ; skos:inScheme ex:Scheme ; skos:topConceptOf ex:Scheme .\n"
        )
        src = tmp_path / "o.ttl"
        src.write_text(ttl, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(detail.OVERVIEW_URI)
            await pilot.pause()
            _lint_row(app, "warning").focus()
            await pilot.pause()
            await pilot.press("enter")  # open the warnings modal
            await pilot.pause()
            ol = app.screen.query_one(OptionList)
            assert ol.highlighted is not None  # a selectable (navigable) issue is highlighted
            await pilot.press("enter")  # activate it → jump to the concept
            for _ in range(3):
                await pilot.pause()
            assert app._detail_uri == "http://example.org/C1"

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
        from ster.tui.uri_modal import UriModal

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.open_context_menu(ZOO + "Cat")
            await pilot.pause()
            assert app.query_one("#ctx-menu", ContextMenu).has_class("open")

            app.on_context_menu_chosen(ContextMenu.Chosen("rename"))  # → fragment rename modal
            await pilot.pause()
            assert isinstance(app.screen, UriModal)
            app.screen.dismiss(None)
            await pilot.pause()

            app.open_context_menu(ZOO + "Cat")
            await pilot.pause()
            app.on_context_menu_chosen(ContextMenu.Chosen("delete_class"))  # → danger choice
            await pilot.pause()
            assert isinstance(app.screen, ChoiceModal)
            assert app.screen.query_one("#choice-box").has_class("-danger")

    _run(scenario)


def test_dot_opens_context_menu_with_nothing_preselected() -> None:
    """Pressing '.' opens the selected entity's context menu, and no item is
    highlighted until the user navigates."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.tui.context_menu import ContextMenu

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.jump_to(ZOO + "Cat")  # select a class
            for _ in range(3):
                await pilot.pause()
            app.query_one("#tree", Tree).focus()
            await pilot.pause()
            await pilot.press("full_stop")  # "."
            await pilot.pause()
            menu = app.query_one("#ctx-menu", ContextMenu)
            assert menu.has_class("open")
            assert menu.highlighted is None  # nothing pre-selected
            await pilot.press("down")  # first arrow moves into the list
            await pilot.pause()
            assert menu.highlighted == 0

    _run(scenario)


def test_detail_title_hints_context_menu_only_for_entities() -> None:
    """The ⋯ menu hint appears for entities with actions, not for the overview."""

    async def scenario() -> None:
        from ster.tui import detail

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app._detail_title(ZOO + "Cat").endswith("⋯")  # class → has a menu
            assert app._detail_title(detail.OVERVIEW_URI) == "Ontology overview"  # no hint

    _run(scenario)


def test_delete_scheme_from_context_menu_removes_it(tmp_path) -> None:
    """The scheme context menu offers Delete; confirming 'scheme only' drops the
    scheme but keeps its concepts."""

    async def scenario() -> None:
        from ster.tui.choice_modal import ChoiceModal
        from ster.tui.context_menu import ContextMenu
        from ster.tui.edits import context_actions

        ttl = (
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "@prefix ex:   <http://example.org/> .\n\n"
            "ex:Scheme a skos:ConceptScheme ; skos:prefLabel 'S'@en ; skos:hasTopConcept ex:C1 .\n"
            "ex:C1 a skos:Concept ; skos:inScheme ex:Scheme ; skos:topConceptOf ex:Scheme ;\n"
            "    skos:prefLabel 'C1'@en .\n"
        )
        src = tmp_path / "o.ttl"
        src.write_text(ttl, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            scheme_uri = "http://example.org/Scheme"
            assert scheme_uri in app.tax.schemes
            app.open_context_menu(scheme_uri)
            await pilot.pause()
            assert "delete_scheme" in [a for _, a in context_actions("scheme")]
            app.on_context_menu_chosen(ContextMenu.Chosen("delete_scheme"))
            await pilot.pause()
            assert isinstance(app.screen, ChoiceModal)
            app.screen.dismiss("scheme_only")  # keep concepts, drop the scheme
            for _ in range(3):
                await pilot.pause()
            assert scheme_uri not in app.tax.schemes
            assert "http://example.org/C1" in app.tax.concepts  # concept survived

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


def test_initial_detail_shows_overview() -> None:
    """On open, the detail pane shows the ontology overview (no Overview leaf).

    Regression: both trees emit a spurious initial NodeHighlighted on mount; the
    prop-tree's data-less header used to clobber the detail back to the placeholder.
    """

    async def scenario() -> None:
        from ster.tui import detail

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            assert app._detail_uri == detail.OVERVIEW_URI

    _run(scenario)


def test_editable_deletable_row_opens_edit_delete_submenu() -> None:
    """A row that is both editable and deletable (an annotation) opens an
    Edit/Delete submenu on Enter; its standalone "✕ remove" row is folded in."""

    async def scenario() -> None:
        from ster.tui.context_menu import ContextMenu
        from ster.tui.detail_view import DetailRow

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()  # overview is shown
            row = next(
                r for r in app.query(DetailRow) if r.field.meta.get("type") == "ont_annotation"
            )
            assert row.delete_field is not None  # paired with its remove sibling
            # The standalone "✕ remove" action row is no longer rendered.
            assert not any(
                r.field.meta.get("action") == "remove_ont_annotation" for r in app.query(DetailRow)
            )
            row.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            menu = app.query_one("#ctx-menu", ContextMenu)
            assert menu.has_class("open")
            assert [label for label, _ in menu._items] == ["✎ Edit", "⊘ Delete"]

    _run(scenario)


def test_identity_modal_decomposes_the_uri_into_fields(tmp_path) -> None:
    """Activating an Identity row opens the modal with the URI split into
    domain / path / separator fields (demo URI: https://example.org/zoo/)."""

    async def scenario() -> None:
        from textual.widgets import Input, RadioSet

        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()  # overview shown
            row = next(r for r in app.query(DetailRow) if r.field.meta.get("type") == "uri")
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # opens the identity modal (no delete → no submenu)
            await pilot.pause()
            modal = app.screen
            assert modal.query_one("#oi-domain", Input).value == "example.org"
            assert modal.query_one("#oi-path", Input).value == "zoo"
            assert modal.query_one(RadioSet).pressed_index == 1  # "/" detected

    _run(scenario)


def test_identity_modal_saves_domain_and_prefix_together(tmp_path) -> None:
    """Changing the domain and the prefix in one save persists both to the file."""

    async def scenario() -> None:
        from textual.widgets import Input

        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()  # overview shown
            row = next(r for r in app.query(DetailRow) if r.field.meta.get("type") == "uri")
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # open identity modal
            await pilot.pause()
            modal = app.screen
            modal.query_one("#oi-domain", Input).value = "garden.org"
            modal.query_one("#oi-prefix", Input).value = "zoo"
            modal._submit()
            await pilot.pause()
            await pilot.press("enter")  # confirm the rename cascade
            await pilot.pause()
            await pilot.pause()
            saved = src.read_text(encoding="utf-8")
            assert "garden.org" in saved  # domain rename cascaded + saved
            assert "@prefix zoo:" in saved  # prefix saved too

    _run(scenario)


def test_cancel_edit_keeps_focus_in_detail_pane(tmp_path) -> None:
    """Regression: Esc-ing the edit modal kept focus in the detail pane, not the tree.

    The submenu grabbed focus before the modal, so Textual restored focus to the
    hidden menu on cancel → it fell back to the tree. We now refocus the row.
    """

    async def scenario() -> None:
        from ster.tui.context_menu import ContextMenu
        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()  # overview shown
            row = next(
                r for r in app.query(DetailRow) if r.field.meta.get("type") == "ont_annotation"
            )
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # open Edit/Delete submenu
            await pilot.pause()
            app.query_one("#ctx-menu", ContextMenu).highlighted = 0  # Edit
            await pilot.press("enter")  # open edit modal
            await pilot.pause()
            await pilot.press("escape")  # cancel
            await pilot.pause()
            assert isinstance(app.focused, DetailRow)  # stayed in the detail pane

    _run(scenario)


def test_arrow_keys_drive_the_detail_panel() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Navigate past the Ontology section header and ＋Add class into the first class.
            await pilot.press("down", "down", "down")
            await pilot.pause()
            # Detail panel must be showing some OWL class (action nodes show placeholder).
            assert "owl:Class" in app._detail_text

    _run(scenario)


def test_action_row_creates_a_subclass_and_saves(tmp_path) -> None:
    """An action row (Enter) → modal → constructive command → reload + save."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow
        from ster.tui.uri_modal import FragmentInput, UriModal

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
            await pilot.press("enter")  # action row → fragment URI modal
            await pilot.pause()
            assert isinstance(app.screen, UriModal)
            inp = app.screen.query_one(FragmentInput)
            assert inp.value == ZOO  # base locked to the ontology namespace, fragment empty
            await pilot.press("W", "o", "r", "k", "e", "r")  # type only the fragment
            await pilot.press("enter")  # submit
            for _ in range(3):
                await pilot.pause()
            assert ZOO + "Worker" in app.tax.owl_classes  # created under the locked base
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


def test_detail_view_composes_rows_only_actionable_focusable() -> None:
    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow, SectionHeader, _is_actionable

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.jump_to(ZOO + "Dog")
            await pilot.pause()
            rows = list(app.query(DetailRow))
            headers = list(app.query(SectionHeader))
            assert rows, "detail view should compose one row per field"
            # A row is focusable iff it is actionable (editable / action / has a menu);
            # pure information rows are skipped by keyboard + click navigation.
            for r in rows:
                assert r.can_focus == _is_actionable(r.field, r.delete_field)
            assert any(r.can_focus for r in rows), "some rows must be reachable"
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
