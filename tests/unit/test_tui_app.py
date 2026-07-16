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


async def _settle(pilot, predicate: Callable[[], bool], *, tries: int = 60) -> None:
    """Pump the event loop until ``predicate`` holds (or give up after ``tries``).

    Robust replacement for the fixed ``for _ in range(n): await pilot.pause()``
    idiom, which can under-wait when the suite is under scheduling load and a
    modal submit / command dispatch needs a few extra event-loop turns to land.
    Deterministic waits (condition met) return immediately; the cap only bites
    when the state genuinely never arrives, letting the following assertion fail
    against the freshest state instead of on a stale, half-processed frame.
    """
    for _ in range(tries):
        if predicate():
            return
        await pilot.pause()
    await pilot.pause()  # one more so a failing assert sees the latest state


@pytest.fixture
def semanticlint_enabled(tmp_path, monkeypatch):
    """Enable the semanticlint plugin against isolated prefs + quality.json so lint UI
    is active (semanticlint is installed in the test env)."""
    from ster import plugins
    from ster.nav import prefs
    from ster.plugins.semanticlint import config

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(config, "_config_path", lambda: tmp_path / "quality.json")
    plugins.set_enabled("semanticlint", True)


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
            await _settle(
                pilot,
                lambda: any(
                    lbl.lang == "en" and lbl.value == "Human"
                    for lbl in app.tax.owl_classes[ZOO + "Person"].labels
                ),
            )
            # committed in memory …
            labels = {lbl.lang: lbl.value for lbl in app.tax.owl_classes[ZOO + "Person"].labels}
            assert labels.get("en") == "Human"
            # … and persisted to disk (the save runs on a background worker now)
            await app.workers.wait_for_complete()
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


def test_cursor_on_leaf_lights_parent_branch_column_not_the_leaf() -> None:
    """The guide column at the cursor's level stays lit: Textual's default lights
    the guides descending from the cursor (gone on a leaf); we move that flag to
    the cursor's parent so the branch it shares with its siblings stays lit."""

    async def scenario() -> None:
        from textual.widgets import Tree

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")  # expand all so Rex (a leaf individual) is visible
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            rex = app._uri_nodes[ZOO + "Rex"]  # individual under Dog
            tree.move_cursor(rex)
            await pilot.pause()
            assert rex._selected is False  # the cursor node itself is NOT the lit branch
            assert rex.parent._selected is True  # its parent's column is lit instead

    _run(scenario)


def test_branch_column_persists_when_moving_among_siblings() -> None:
    """Moving the cursor between two children of the same parent keeps that
    parent's guide column lit (the highlight tracks the level, not the node)."""

    async def scenario() -> None:
        from textual.widgets import Tree

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            cat = app._uri_nodes[ZOO + "Cat"]  # Cat and Dog are siblings under Mammal
            dog = app._uri_nodes[ZOO + "Dog"]
            mammal = app._uri_nodes[ZOO + "Mammal"]
            tree.move_cursor(cat)
            await pilot.pause()
            assert mammal._selected is True
            tree.move_cursor(dog)  # slide to the sibling
            await pilot.pause()
            assert mammal._selected is True  # same level → still lit
            assert cat._selected is False and dog._selected is False

    _run(scenario)


def test_moving_across_branches_clears_the_previous_column() -> None:
    """Jumping to a different branch lights the new parent and unlights the old."""

    async def scenario() -> None:
        from textual.widgets import Tree

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            rex = app._uri_nodes[ZOO + "Rex"]  # parent: Dog
            alice = app._uri_nodes[ZOO + "Alice"]  # parent: Person
            tree.move_cursor(rex)
            await pilot.pause()
            assert app._uri_nodes[ZOO + "Dog"]._selected is True
            tree.move_cursor(alice)
            await pilot.pause()
            assert app._uri_nodes[ZOO + "Dog"]._selected is False  # old column cleared
            assert app._uri_nodes[ZOO + "Person"]._selected is True  # new column lit

    _run(scenario)


def test_top_level_cursor_does_not_light_the_hidden_root() -> None:
    """A top-level node's parent is the hidden root, whose guide spans every line —
    lighting it would highlight the whole tree, so it is left untouched."""

    async def scenario() -> None:
        from textual.widgets import Tree

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            tree.cursor_line = 0  # first visible row = the top-level "Ontology" node
            await pilot.pause()
            assert tree.root._selected is False  # the root is never lit

    _run(scenario)


def test_childless_nodes_drop_the_expand_arrow() -> None:
    """A node with no subtree shows no ▶/▼ arrow (it would falsely hint a drill-down);
    a node that does have children keeps it."""

    async def scenario() -> None:
        from textual.widgets import Tree

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            cat = app._uri_nodes[ZOO + "Eagle"]  # leaf class: no subclasses, no individuals
            mammal = app._uri_nodes[ZOO + "Mammal"]  # has subclasses Cat + Dog
            assert cat.allow_expand is False  # arrow removed
            assert mammal.allow_expand is True  # arrow kept
            # Individuals (leaves) and properties never get an arrow either.
            assert app._uri_nodes[ZOO + "Rex"].allow_expand is False
            props = app.query_one("#prop-tree", Tree)
            assert app._uri_nodes[ZOO + "hasOwner"].allow_expand is False
            assert props.root.children[0].allow_expand is True  # the Properties section

    _run(scenario)


def test_childless_node_labels_stay_aligned_with_expandable_siblings() -> None:
    """Removing the arrow must not shift text left: a childless label is padded by
    the arrow's width so its text starts at the same column as a sibling's."""

    async def scenario() -> None:
        from rich.style import Style
        from textual.widgets import Tree

        from ster.tui import data

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            eagle = tree.render_label(app._uri_nodes[ZOO + "Eagle"], Style(), Style())
            mammal = tree.render_label(app._uri_nodes[ZOO + "Mammal"], Style(), Style())
            # The childless label carries no arrow, just padding …
            assert "▶" not in eagle.plain and "▼" not in eagle.plain
            assert eagle.plain.startswith("  ")
            # … the expandable one carries the arrow; both prefixes are 2 cells wide,
            # so the entity text lines up.
            assert mammal.plain[:2] in ("▶ ", "▼ ")
            assert eagle.plain[2:].startswith(data.ICON["class"])
            assert mammal.plain[2:].startswith(data.ICON["class"])

    _run(scenario)


def test_picker_list_wraps_around(tmp_path) -> None:
    """The entity picker's up/down wrap around the ends of a long candidate list."""

    async def scenario() -> None:
        from textual.widgets import OptionList

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Cat")
            await pilot.pause()
            app._run_field_action(_action_field("link_superclass"))  # context-menu action
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


def test_prop_tree_groups_properties_by_kind() -> None:
    """The three OWL group headers always show, in order; within a group the local
    properties are listed first, then used-but-undeclared header predicates flagged
    with a small '(ext)'. An orange 'Untyped Properties' group appears for bare
    rdf:Property entries."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.model import Label, OWLProperty

        app = _app()
        app.tax.owl_properties[ZOO + "relatedTo"] = OWLProperty(
            uri=ZOO + "relatedTo", prop_type="Property", labels=[Label("en", "related to")]
        )

        def leaves(group):  # [(uri, has_ext_tag), …] in display order
            return [(n.data, "(ext)" in n.label.plain) for n in group.children]

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            root = app.query_one("#prop-tree", Tree).root
            groups = {node.label.plain: node for node in root.children}
            assert [n.label.plain for n in root.children][:3] == [
                "Object Properties",
                "Datatype Properties",
                "Annotation Properties",
            ]
            # local properties: flat leaves, no (ext) tag
            assert leaves(groups["Object Properties"]) == [(ZOO + "hasOwner", False)]
            assert leaves(groups["Datatype Properties"]) == [(ZOO + "hasAge", False)]
            # demo's used-but-undeclared header predicates → Annotation, each (ext)-tagged
            ann = leaves(groups["Annotation Properties"])
            assert ann == [
                ("http://purl.org/dc/terms/description", True),
                ("http://www.w3.org/2000/01/rdf-schema#label", True),
                ("http://purl.org/dc/terms/title", True),
            ]
            # the untyped group is orange and holds relatedTo (local, no tag)
            untyped = root.children[-1]
            assert untyped.label.plain == "Untyped Properties"
            assert any("orange1" in str(span.style) for span in untyped.label.spans)
            assert leaves(untyped) == [(ZOO + "relatedTo", False)]

    _run(scenario)


def test_prop_tree_leaf_shows_local_name_not_label() -> None:
    """Property leaves are labelled by local name (hasOwner), not rdfs:label (has owner)."""

    async def scenario() -> None:
        from textual.widgets import Tree

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            leaf = app._uri_nodes[ZOO + "hasOwner"]
            assert leaf in app.query_one("#prop-tree", Tree).root.children[0].children
            assert "hasOwner" in leaf.label.plain
            assert "has owner" not in leaf.label.plain

    _run(scenario)


def test_prop_tree_hover_shows_property_comment_tooltip() -> None:
    """Hovering a property leaf sets the tree tooltip to its rdfs:comment; hovering
    nothing (or a non-property) clears it."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.model import Definition

        app = _app()
        app.tax.owl_properties[ZOO + "hasOwner"].comments = [
            Definition("en", "Who owns the animal.")
        ]
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            prop_tree = app.query_one("#prop-tree", Tree)
            prop_tree.root.expand_all()
            await pilot.pause()
            node = app._uri_nodes[ZOO + "hasOwner"]
            prop_tree.hover_line = node.line
            await pilot.pause()
            assert prop_tree.tooltip == "Who owns the animal."
            prop_tree.hover_line = -1
            await pilot.pause()
            assert prop_tree.tooltip is None

    _run(scenario)


def test_prop_tree_lists_local_before_external_within_a_group() -> None:
    """When a group has both declared and used-but-undeclared predicates, the local
    one comes first and only the external one carries the (ext) flag."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.model import Label, OWLProperty

        app = _app()
        # a locally-declared annotation property, alongside the demo's external ones
        app.tax.owl_properties[ZOO + "note"] = OWLProperty(
            uri=ZOO + "note", prop_type="AnnotationProperty", labels=[Label("en", "note")]
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            root = app.query_one("#prop-tree", Tree).root
            ann = {n.label.plain: n for n in root.children}["Annotation Properties"]
            ordered = [(n.data, "(ext)" in n.label.plain) for n in ann.children]
            assert ordered[0] == (ZOO + "note", False)  # local first, no tag
            assert all(is_ext for _, is_ext in ordered[1:])  # the rest are external

    _run(scenario)


def test_expand_collapse_target_the_focused_tree() -> None:
    """The 'e'/'c' expand/collapse actions act on whichever tree pane has focus —
    the properties tree when it's selected, otherwise the main ontology tree."""

    async def scenario() -> None:
        from textual.widgets import Tree

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            main = app.query_one("#tree", Tree)
            props = app.query_one("#prop-tree", Tree)
            # focus the properties pane → collapse acts on it, leaving the main tree be
            props.focus()
            await pilot.pause()
            app.action_collapse_all()
            await pilot.pause()
            assert all(not c.is_expanded for c in props.root.children)  # prop groups closed
            assert any(c.is_expanded for c in main.root.children)  # main tree untouched
            app.action_expand_all()  # re-open the properties groups
            await pilot.pause()
            assert all(c.is_expanded for c in props.root.children)
            # focus back on the main tree → collapse now targets it, not properties
            main.focus()
            await pilot.pause()
            app.action_collapse_all()
            await pilot.pause()
            assert all(not c.is_expanded for c in main.root.children)  # main collapsed
            assert all(c.is_expanded for c in props.root.children)  # properties untouched

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
            # The title notes the resource type and (class → context menu) the ⋯ hint.
            assert app.query_one("#detail", DetailView).border_title == "Cat (Class)  ⋯"

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

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Cat")
            await pilot.pause()
            app._run_field_action(_action_field("link_superclass"))  # context-menu action
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
    """Editable rows carry no hint (the ✎ icon signals it); action rows describe the
    action; stats none."""
    from ster.nav.logic import DetailField
    from ster.tui.detail_view import DetailRow

    editable = DetailRow(DetailField("k", "label", "v", editable=True, meta={"type": "rdf_label"}))
    assert editable.tooltip is None  # "Enter to edit" removed — redundant with the ✎ affordance
    action = DetailRow(
        DetailField(
            "k", "⊘ Delete", "", editable=False, meta={"type": "action", "action": "delete_class"}
        )
    )
    assert action.tooltip and "Delete" in action.tooltip
    stat = DetailRow(DetailField("k", "x", "y", editable=False, meta={"type": "stat"}))
    assert stat.tooltip is None


def test_detail_row_tooltip_prefers_explicit_comment() -> None:
    """A property row carries its rdfs:comment as an explicit tooltip, shown ahead of any
    edit/action hint."""
    from ster.nav.logic import DetailField
    from ster.tui.detail_view import DetailRow

    row = DetailRow(
        DetailField(
            "classprop:x",
            "hasName",
            "(Object Prop.)",
            editable=False,
            meta={"type": "class_prop_nav", "action": "edit_property", "tooltip": "The name."},
        )
    )
    assert row.tooltip == "The name."


def test_clicking_a_link_row_opens_the_url_in_the_browser() -> None:
    """A click landing on a rendered hyperlink opens it via App.open_url; a click on
    plain text keeps the normal edit/run activate path."""

    async def scenario() -> None:
        import types

        from rich.style import Style

        from ster.tui.detail_view import DetailRow

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")  # populate the detail pane
            await pilot.pause()
            row = next(iter(app.query(DetailRow)))

            opened: list[str] = []
            activated: list[bool] = []
            app.open_url = lambda url, **_: opened.append(url)  # type: ignore[method-assign]
            row.action_activate = lambda: activated.append(True)  # type: ignore[method-assign]

            # click on a hyperlink → open it, do not activate the row
            row.on_click(types.SimpleNamespace(style=Style(link="https://example.org")))
            assert opened == ["https://example.org"]
            assert activated == []

            # click on plain text (no link) → normal activate, no URL opened
            row.on_click(types.SimpleNamespace(style=Style()))
            assert activated == [True]
            assert opened == ["https://example.org"]  # unchanged

    _run(scenario)


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


def test_lint_is_gated_off_when_the_plugin_is_disabled(tmp_path) -> None:
    """With the semanticlint plugin off (default), no lint runs — _ontology_lint is None."""

    async def scenario() -> None:
        src = tmp_path / "o.ttl"
        src.write_text(_SKOS_DUP, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app._ontology_lint() is None  # plugin disabled ⇒ no lint data

    _run(scenario)


def test_lint_runs_when_the_plugin_is_enabled(tmp_path, semanticlint_enabled) -> None:
    """Enabling the plugin activates lint: _ontology_lint returns counts + issues."""

    async def scenario() -> None:
        src = tmp_path / "o.ttl"
        src.write_text(_SKOS_DUP, encoding="utf-8")  # duplicate prefLabel ⇒ SKO001 error
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            result = app._ontology_lint()
            assert result is not None
            counts, issues = result
            assert counts.get("error", 0) >= 1 and any(i["check_id"] == "SKO001" for i in issues)

    _run(scenario)


def test_tree_icon_plain_when_the_plugin_is_disabled(tmp_path) -> None:
    """With the plugin off, node icons carry no severity colour."""

    async def scenario() -> None:
        src = tmp_path / "o.ttl"
        src.write_text(_SKOS_DUP, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            label = app._uri_nodes["http://example.org/C1"].label
            styles = " ".join(str(s.style) for s in label.spans)
            assert not any(c in styles for c in ("red", "orange", "green"))

    _run(scenario)


def test_tree_icon_coloured_by_worst_severity_when_plugin_on(
    tmp_path, semanticlint_enabled
) -> None:
    """A concept with a duplicate prefLabel (SKO001 error) gets a red icon."""

    async def scenario() -> None:
        src = tmp_path / "o.ttl"
        src.write_text(_SKOS_DUP, encoding="utf-8")  # ex:C1 → SKO001 error
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(4):
                await pilot.pause()  # let initial lint + recolour settle
            label = app._uri_nodes["http://example.org/C1"].label
            assert any("red" in str(s.style) for s in label.spans)  # error → red

    _run(scenario)


def test_deactivating_plugin_clears_tree_icon_colours(tmp_path, semanticlint_enabled) -> None:
    """Regression: disabling the plugin via the config modal must repaint the tree with
    plain icons — the colours must not linger. Root cause: _apply_config re-showed the
    detail but never rebuilt the tree on a plugin-only toggle, so _lint_icons_on and the
    coloured glyphs stayed. The config modal removes the Semantic Lint tab on toggle-off,
    so the applied result carries no 'semanticlint' key (only plugins)."""

    async def scenario() -> None:
        src = tmp_path / "o.ttl"
        src.write_text(_SKOS_DUP, encoding="utf-8")  # ex:C1 → SKO001 error
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(4):
                await pilot.pause()  # initial lint + recolour
            label = app._uri_nodes["http://example.org/C1"].label
            assert any("red" in str(s.style) for s in label.spans)  # coloured while on

            # Disable the plugin exactly as the modal submits it (tab already removed).
            app._apply_config(
                {"display": "en", "configured": ["en"], "plugins": {"semanticlint": False}}
            )
            for _ in range(4):
                await pilot.pause()
            assert app._lint_icons_on is False
            label = app._uri_nodes["http://example.org/C1"].label
            styles = " ".join(str(s.style) for s in label.spans)
            assert not any(c in styles for c in ("red", "orange", "green"))

    _run(scenario)


def test_toggling_quality_block_feature_hides_overview_block(
    tmp_path, semanticlint_enabled
) -> None:
    """Regression: unchecking 'Show the Quality & Coverage block' must remove the
    overview's Quality & Coverage group. Root cause: the overview presenter always
    rendered it — the feature only gated the per-entity subtree block."""
    from ster.tui import detail as det
    from ster.tui.detail_view import DetailRow

    def _has_group(app) -> bool:  # noqa: ANN001
        # The 'Errors' row is produced by health(), inside the Quality & Coverage group.
        return any(str(r.field.display) == "Errors" for r in app.query(DetailRow))

    async def scenario() -> None:
        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(4):
                await pilot.pause()
            app._show(det.OVERVIEW_URI)
            await pilot.pause()
            assert app._overview_quality_on is True
            assert _has_group(app)  # shown while the feature is on

            # Turn the feature off exactly as the modal submits it.
            app._apply_config(
                {
                    "display": "en",
                    "configured": ["en"],
                    "semanticlint": {
                        "features": {"icons": True, "detail": True, "quality_block": False}
                    },
                }
            )
            for _ in range(4):
                await pilot.pause()
            assert app._overview_quality_on is False
            assert not _has_group(app)  # the whole group is gone

    _run(scenario)


def test_detail_shows_a_quality_issues_row_for_the_entity(tmp_path, semanticlint_enabled) -> None:
    """Viewing an entity with a lint issue shows a 'Quality issues' row (keyed lint:*)."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(_SKOS_DUP, encoding="utf-8")  # ex:C1 → SKO001 error
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(4):
                await pilot.pause()
            app._show("http://example.org/C1")
            await pilot.pause()
            keys = [r.field.key for r in app.query(DetailRow)]
            assert any(k.startswith("lint:SKO001") for k in keys)  # the issue is annotated

    _run(scenario)


def test_detail_has_no_quality_issues_when_plugin_disabled(tmp_path) -> None:
    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(_SKOS_DUP, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show("http://example.org/C1")
            await pilot.pause()
            assert not any(r.field.key.startswith("lint:") for r in app.query(DetailRow))

    _run(scenario)


def test_detail_shows_subtree_quality_block_for_a_class_or_concept(
    tmp_path, semanticlint_enabled
) -> None:
    """A parent concept's Quality (subtree) block counts an issue on its child."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        ttl = (
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "@prefix ex:   <http://example.org/> .\n\n"
            "ex:Scheme a skos:ConceptScheme ; skos:hasTopConcept ex:P .\n"
            "ex:P a skos:Concept ; skos:inScheme ex:Scheme ; skos:topConceptOf ex:Scheme ;"
            ' skos:prefLabel "P"@en .\n'
            "ex:C a skos:Concept ; skos:inScheme ex:Scheme ; skos:broader ex:P ;"
            ' skos:prefLabel "C"@en ; skos:prefLabel "C2"@en .\n'  # dup prefLabel → SKO001
        )
        src = tmp_path / "o.ttl"
        src.write_text(ttl, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(4):
                await pilot.pause()
            app._show("http://example.org/P")  # the parent
            await pilot.pause()
            rows = {r.field.key: r.field.value for r in app.query(DetailRow)}
            assert rows.get("stq:error") == "1"  # child C's error counted in P's subtree

    _run(scenario)


_OWL_SUBCLASS = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix ex:   <http://example.org/> .\n\n"
    "ex:Ont a owl:Ontology .\n"
    'ex:Animal a owl:Class ; rdfs:label "Animal"@en .\n'
    'ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:label "Dog"@en .\n'
    'ex:hasAge a owl:DatatypeProperty ; rdfs:label "has age"@en ; rdfs:domain ex:Animal .\n'
    'ex:Rex a owl:NamedIndividual, ex:Dog ; rdfs:label "Rex"@en .\n'  # gives Property Fill a row
)


def test_class_quality_summary_is_titled_issues_under_property_fill(
    tmp_path, semanticlint_enabled
) -> None:
    """On a class with subclasses the subtree quality summary drops the old 'Quality
    (subtree)' header, becomes an 'Issues' section, and sits right after 'Property Fill'
    inside the Quality & Coverage box."""

    async def scenario() -> None:
        from ster.tui.detail_view import SectionHeader

        src = tmp_path / "o.ttl"
        src.write_text(_OWL_SUBCLASS, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(4):
                await pilot.pause()
            app._show("http://example.org/Animal")  # has subclass Dog → the box shows
            await pilot.pause()
            titles = [h.title_text for h in app.query(SectionHeader)]
            assert "Quality (subtree)" not in titles  # old header gone
            assert "Property Fill" in titles and "Issues" in titles
            assert titles.index("Issues") == titles.index("Property Fill") + 1  # directly under

    _run(scenario)


def _lint_row(app, severity: str):  # noqa: ANN001 - test helper
    """The overview's 'Errors'/'Warnings' count row for *severity*."""
    from ster.tui.detail_view import DetailRow

    return next(
        r
        for r in app.query(DetailRow)
        if r.field.meta.get("action") == "view_lint"
        and r.field.meta.get("lint_severity") == severity
    )


def test_warnings_row_opens_a_warnings_only_modal(tmp_path, semanticlint_enabled) -> None:
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


def test_selecting_a_lint_issue_jumps_to_its_entity(tmp_path, semanticlint_enabled) -> None:
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
        monkeypatch.setattr(viz_vowl, "port_holder", lambda host=None, port=None: None)  # port free
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


def test_footer_swaps_theme_hint_for_graphview() -> None:
    """The bottom bar drops the 'd Theme' hint (theme cycling still works, just hidden)
    and gains a visible 'g GraphView' shortcut."""
    binds = {b.key: b for b in OntologyApp.BINDINGS}
    assert binds["d"].action == "cycle_theme" and binds["d"].show is False  # hidden, still works
    assert binds["g"].action == "open_graph"
    assert binds["g"].description == "GraphView" and binds["g"].show is True


def _patch_graph(monkeypatch) -> list:
    """Record which graph entry point fired: the focus URI for a focused graph, or the
    sentinel ``"GLOBAL"`` for the whole-ontology graph."""
    from ster import viz_vowl

    calls: list = []
    monkeypatch.setattr(viz_vowl, "port_holder", lambda host=None, port=None: None)  # port free
    monkeypatch.setattr(
        viz_vowl,
        "open_focused_in_browser",
        lambda tax, root, path=None: calls.append(root) or "http://x",
    )
    monkeypatch.setattr(
        viz_vowl,
        "open_in_browser",
        lambda tax, path=None, on_change_fn=None: calls.append("GLOBAL") or "http://g",
    )
    return calls


def test_g_focuses_the_graph_on_the_selected_class(monkeypatch) -> None:
    """Pressing 'g' with a class selected in the tree opens a graph focused on it."""

    async def scenario() -> None:
        from textual.widgets import Tree

        calls = _patch_graph(monkeypatch)
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            tree.move_cursor(app._uri_nodes[ZOO + "Dog"])
            tree.focus()
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert calls == [ZOO + "Dog"]  # focused on the selected class

    _run(scenario)


def test_g_focuses_the_graph_on_the_selected_individual(monkeypatch) -> None:
    """Pressing 'g' with an individual selected opens a graph focused on that individual."""

    async def scenario() -> None:
        from textual.widgets import Tree

        calls = _patch_graph(monkeypatch)
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            tree.move_cursor(app._uri_nodes[ZOO + "Rex"])  # individual under Dog
            tree.focus()
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert calls == [ZOO + "Rex"]

    _run(scenario)


def test_g_opens_the_global_graph_when_nothing_focusable_is_selected(monkeypatch) -> None:
    """With the overview shown (no focusable entity), 'g' opens the whole-ontology graph."""

    async def scenario() -> None:
        from ster.tui import detail

        calls = _patch_graph(monkeypatch)
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(detail.OVERVIEW_URI)  # overview is not a focusable entity
            await pilot.pause()
            app.action_open_graph()  # what the 'g' binding invokes
            await pilot.pause()
            assert calls == ["GLOBAL"]  # fell back to the global graph

    _run(scenario)


def test_detail_title_includes_the_resource_type() -> None:
    """The detail pane title annotates the entity's kind, e.g. 'Dog (Class)'."""
    from ster.tui import detail

    app = _app()
    assert app._detail_title(ZOO + "Dog").startswith("Dog (Class)")
    assert app._detail_title(ZOO + "Rex").startswith("Rex (Individual)")
    assert app._detail_title(ZOO + "hasOwner").startswith("has owner (Property)")
    # Pseudo-entities (the overviews) keep their plain titles — no type suffix.
    assert app._detail_title(detail.OVERVIEW_URI) == "Ontology overview"


def _graph_row(app):  # type: ignore[no-untyped-def]
    """The detail pane's '» Open Graph View' action row (focused or whole-ontology), or None."""
    from ster.tui.detail_view import DetailRow

    return next(
        (
            r
            for r in app.query(DetailRow)
            if r.field.meta.get("action") in ("view_focused_graph", "view_ontology_graph")
        ),
        None,
    )


def test_class_detail_leads_with_a_highlighted_graph_action_row() -> None:
    """A class detail opens with a highlighted, focusable '» Open Graph View' row as
    its first row."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Dog")
            await pilot.pause()
            first = next(iter(app.query(DetailRow)))  # the very first row in the pane
            assert first.field.meta.get("action") == "view_focused_graph"
            assert first.field.meta.get("uri") == ZOO + "Dog"
            assert "Open Graph View" in first.field.display
            assert first.can_focus  # keyboard-navigable
            assert first.has_class("graph-action")  # highlighted

    _run(scenario)


def test_graph_action_row_opens_the_focused_graph(monkeypatch) -> None:
    """Activating the detail pane's graph row opens a graph focused on that entity."""

    async def scenario() -> None:
        calls = _patch_graph(monkeypatch)
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Dog")
            await pilot.pause()
            row = _graph_row(app)
            assert row is not None
            row.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert calls == [ZOO + "Dog"]  # focused on the class

    _run(scenario)


def test_individual_detail_has_a_graph_action_row() -> None:
    """Individuals get the same '» Open Graph View' row (scope: classes & individuals)."""

    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Rex")
            await pilot.pause()
            assert _graph_row(app) is not None

    _run(scenario)


def test_property_detail_has_no_graph_action_row() -> None:
    """A property is not focusable in the graph, so its detail gets no graph row."""

    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "hasOwner")
            await pilot.pause()
            assert _graph_row(app) is None

    _run(scenario)


def test_overview_and_taxonomy_lead_with_the_same_highlighted_graph_row() -> None:
    """The ontology + taxonomy overviews get the same highlighted '» Open Graph View'
    header row as classes — the whole-ontology graph (view_ontology_graph)."""

    async def scenario() -> None:
        from ster.tui import detail
        from ster.tui.detail_view import DetailRow

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for uri in (detail.OVERVIEW_URI, detail.TAXONOMY_URI):
                app._show(uri)
                await pilot.pause()
                first = next(iter(app.query(DetailRow)))  # leads the pane, like classes
                assert first.field.meta.get("action") == "view_ontology_graph", uri
                assert "Open Graph View" in first.field.display
                assert first.has_class("graph-action")  # same highlighted formatting

    _run(scenario)


def test_concept_scheme_detail_leads_with_the_graph_row() -> None:
    """A concept scheme gets the same highlighted graph row (whole-ontology graph)."""

    async def scenario() -> None:
        from ster.model import ConceptScheme, Label, Taxonomy

        t = Taxonomy()
        s = ConceptScheme(uri="https://ex.org/skos/Sch", labels=[Label("en", "Sch")])
        t.schemes[s.uri] = s
        app = OntologyApp(t, source="skos")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(s.uri)
            await pilot.pause()
            row = _graph_row(app)
            assert row is not None and row.field.meta.get("action") == "view_ontology_graph"
            assert row.has_class("graph-action")

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
            assert {"move_class", "class_to_individual", "delete_class"} <= set(actions)
            assert "rename" not in actions  # URI edits go through "Edit class…"
            assert "link_superclass" not in actions  # Cat is non-top-level (under Mammal)

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
            # 7 classes + 3 individuals + 2 local properties + 3 used-but-undeclared
            # ontology header predicates (rdfs:label, dcterms:title, dcterms:description).
            entity_nodes = [u for u in app._uri_nodes if "://" in u]
            assert len(entity_nodes) == 15  # every class/individual/property node indexed
            # plus the focusable section nodes: Ontology, Taxonomy + 3 property sections.
            assert {"__ster:overview__", "__ster:taxonomy__"} <= set(app._uri_nodes)
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
            await app.workers.wait_for_complete()  # let the background save land
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
            app.screen.dismiss(None)  # discard (✕ / click-away) — Esc now auto-saves
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


def test_object_properties_header_is_right_clickable_to_add_one(tmp_path) -> None:
    """The Object Properties section header carries an add-sentinel; right-clicking it
    opens the full modal, whose submission creates the object property (labels + domain)."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.tui.app import _add_prop_uri
        from ster.tui.object_property_modal import ObjectPropertyModal

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            sentinel = _add_prop_uri("ObjectProperty")
            prop_tree = app.query_one("#prop-tree", Tree)
            assert sentinel in [n.data for n in prop_tree.root.children]  # header is wired
            app.open_context_menu(sentinel)  # simulate the right-click
            await pilot.pause()
            assert isinstance(app.screen, ObjectPropertyModal)
            modal = app.screen
            modal._uri.value = ZOO + "livesIn"
            modal._label_inputs[app.lang].value = "lives in"
            modal._domain.value = ZOO + "Animal"  # a valid class option
            modal._submit()
            for _ in range(3):
                await pilot.pause()
            prop = app.tax.owl_properties.get(ZOO + "livesIn")
            assert prop is not None and prop.prop_type == "ObjectProperty"
            assert {lbl.value for lbl in prop.labels} == {"lives in"}
            assert prop.domains == [ZOO + "Animal"]
            await app.workers.wait_for_complete()
            assert "livesIn" in src.read_text(encoding="utf-8")  # persisted

    _run(scenario)


def test_renaming_a_property_keeps_the_highlight_on_it_regression(tmp_path) -> None:
    """Regression: renaming a property (URI change) must keep the tree highlight + detail
    on that same property — not leave the detail on the gone old URI (which cascades to
    the highlight jumping to the main tree). _rename_entity must pass select=new URI."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.tui.uri_modal import FragmentInput

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            prop_tree = app.query_one("#prop-tree", Tree)
            prop_tree.move_cursor(app._uri_nodes[ZOO + "hasOwner"])
            app._show(ZOO + "hasOwner")
            await pilot.pause()
            app._rename_entity(ZOO + "hasOwner")  # opens the rename UriModal
            await pilot.pause()
            app.screen.query_one("#uri-input", FragmentInput).value = ZOO + "hasKeeper"
            await pilot.press("enter")  # submit the rename
            for _ in range(4):
                await pilot.pause()
            assert ZOO + "hasKeeper" in app.tax.owl_properties  # renamed
            assert app._detail_uri == ZOO + "hasKeeper"  # detail follows the property
            assert prop_tree.cursor_node is app._uri_nodes[ZOO + "hasKeeper"]  # highlight follows

    _run(scenario)


def test_editing_a_class_property_renames_it_and_keeps_domain(tmp_path) -> None:
    """Activating a property's ✎ row opens the edit modal; saving renames the property
    (URI + label) while preserving its domain/range."""

    async def scenario() -> None:
        from ster.nav.logic import DetailField
        from ster.tui.property_edit_modal import PropertyEditModal

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Animal")  # its Properties list has hasOwner (domain Animal)
            await pilot.pause()
            # what the ✎ property row dispatches (carries the property uri in its meta)
            app._run_field_action(
                DetailField(
                    "classprop",
                    "",
                    "",
                    editable=False,
                    meta={"action": "edit_property", "uri": ZOO + "hasOwner"},
                )
            )
            await pilot.pause()
            assert isinstance(app.screen, PropertyEditModal)
            app.screen._uri.value = ZOO + "hasKeeper"
            app.screen._label_inputs[app.lang].value = "has keeper"
            app.screen._submit()
            for _ in range(4):
                await pilot.pause()
            assert ZOO + "hasKeeper" in app.tax.owl_properties  # renamed
            assert ZOO + "hasOwner" not in app.tax.owl_properties
            prop = app.tax.owl_properties[ZOO + "hasKeeper"]
            assert {lbl.value for lbl in prop.labels} == {"has keeper"}
            assert prop.domains == [ZOO + "Animal"]  # domain preserved

    _run(scenario)


def test_action_row_creates_a_subclass_and_saves(tmp_path) -> None:
    """An action row (Enter) → modal → constructive command → reload + save."""

    async def scenario() -> None:
        from ster.tui.class_modal import ClassModal

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")
            await pilot.pause()
            app._run_field_action(_action_field("new_subclass"))  # context-menu action
            await pilot.pause()
            assert isinstance(app.screen, ClassModal)
            modal = app.screen
            assert modal._uri.value == ZOO  # base locked to the ontology namespace
            modal._uri.value = ZOO + "Worker"  # the new fragment
            modal._label_inputs[app.lang].value = "Worker"  # also set a label in one go
            modal._submit()
            await _settle(pilot, lambda: ZOO + "Worker" in app.tax.owl_classes)
            cls = app.tax.owl_classes.get(ZOO + "Worker")
            assert cls is not None and ZOO + "Person" in cls.sub_class_of  # created under Person
            assert {lbl.value for lbl in cls.labels} == {"Worker"}  # label set at creation
            await app.workers.wait_for_complete()
            assert "Worker" in src.read_text(encoding="utf-8")  # persisted

    _run(scenario)


def test_delete_class_via_choice_modal_and_saves(tmp_path) -> None:
    """Destructive path: the delete action (right-click context menu) → mode choice →
    OwlDeleteClass → save. (Delete moved off the detail panel to the context menu.)"""

    async def scenario() -> None:
        from ster.nav.logic import DetailField

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Cat")
            await pilot.pause()
            # what the right-click "⊘ Delete…" menu item dispatches
            app._run_field_action(
                DetailField(
                    "ctx", "", "", editable=False, meta={"type": "action", "action": "delete_class"}
                )
            )
            await pilot.pause()
            assert app.screen.__class__.__name__ == "ChoiceModal"
            await pilot.click("#opt-delete_all")  # pick a mode
            await _settle(pilot, lambda: ZOO + "Cat" not in app.tax.owl_classes)
            assert ZOO + "Cat" not in app.tax.owl_classes  # gone in memory
            await app.workers.wait_for_complete()  # let the background save flush
            assert ZOO + "Cat" not in store.load(src).owl_classes  # gone on disk

    _run(scenario)


def test_add_superclass_via_picker_and_saves(tmp_path) -> None:
    """Relation path: Enter on "Add superclass" → picker → OwlMoveClass → save."""

    async def scenario() -> None:
        from textual.widgets import OptionList

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Cat")
            await pilot.pause()
            app._run_field_action(_action_field("link_superclass"))  # context-menu action
            await pilot.pause()
            modal = app.screen
            assert modal.__class__.__name__ == "PickerModal"
            idx = next(i for i, (_, uri) in enumerate(modal._options) if uri == ZOO + "Person")
            modal.query_one(OptionList).highlighted = idx
            await pilot.press("enter")  # select Person as an additional superclass
            await _settle(
                pilot, lambda: ZOO + "Person" in app.tax.owl_classes[ZOO + "Cat"].sub_class_of
            )
            assert ZOO + "Person" in app.tax.owl_classes[ZOO + "Cat"].sub_class_of  # in memory
            await app.workers.wait_for_complete()  # let the background save flush
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
            await _settle(pilot, lambda: "Rex" in app._detail_text)
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

    from ster import tui

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


def test_overview_quality_sections_render_in_a_bordered_group_box() -> None:
    """The overview's Health/Completeness/Metadata-coverage/Languages sections are
    enclosed in one bordered '.detail-group' box; Structure sits outside it."""

    async def scenario() -> None:
        from ster.tui import detail
        from ster.tui.detail_view import SectionHeader

        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.jump_to(detail.OVERVIEW_URI)
            await pilot.pause()
            boxes = list(app.query(".detail-group"))
            assert len(boxes) == 1
            box = boxes[0]
            assert str(box.border_title) == "Quality & Coverage"
            inside = {h.title_text for h in box.query(SectionHeader)}
            assert {"Health & Issues", "Completeness", "Metadata coverage", "Languages"} <= inside
            assert "Structure" not in inside  # Structure is a sibling, outside the box

    _run(scenario)


def test_editing_keeps_tree_highlight_put_regression(tmp_path) -> None:
    """Regression: after a plain edit (no new entity), the tree highlight must stay on
    the entity the user was on — not reset to the top of the tree when the rebuild
    wipes and re-adds the nodes. Root cause: the ``select is None`` branch of
    ``_apply_command`` never restored the cursor the ``_rebuild_tree`` reset."""

    async def scenario() -> None:
        from textual.widgets import Input, Tree

        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")  # expand so Dog is a visible node
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            tree.move_cursor(app._uri_nodes[ZOO + "Dog"])
            app._show(ZOO + "Dog")  # detail pane on Dog
            await pilot.pause()
            label_row = next(
                r
                for r in app.query(DetailRow)
                if r.field.meta.get("type") == "rdf_label" and r.field.editable
            )
            label_row.focus()
            await pilot.press("enter")  # open the edit modal
            await pilot.pause()
            app.screen.query_one("#edit-input", Input).value = "Canine"
            await pilot.press("enter")  # submit → command → rebuild
            for _ in range(4):
                await pilot.pause()
            # The highlight stayed on Dog (did not jump to the top of the tree) …
            assert tree.cursor_node is app._uri_nodes[ZOO + "Dog"]
            # … and focus stayed in the detail pane, never stolen to the tree.
            assert app.focused is not tree

    _run(scenario)


def test_renaming_a_class_follows_the_entity_regression(tmp_path) -> None:
    """Regression: renaming a class's URI must keep the highlight on that same (renamed)
    entity, not jump to the top. Root cause: ``_open_class_edit`` passed no ``select``,
    so the rebuild reset the cursor and ``_detail_uri`` was left pointing at the gone
    old URI."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.nav.logic import DetailField
        from ster.tui.class_modal import ClassModal

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            tree.move_cursor(app._uri_nodes[ZOO + "Dog"])
            app._show(ZOO + "Dog")
            await pilot.pause()
            # "Edit class…" is a context-menu action, dispatched via _run_field_action.
            app._run_field_action(
                DetailField("k", "Edit class", "", editable=False, meta={"action": "edit_class"})
            )
            await pilot.pause()
            assert isinstance(app.screen, ClassModal)
            app.screen._uri.value = ZOO + "Canine"  # rename the URI fragment
            app.screen._submit()
            for _ in range(4):
                await pilot.pause()
            renamed = ZOO + "Canine"
            assert renamed in app.tax.owl_classes  # the rename happened
            # The highlight followed the entity to its new URI …
            assert tree.cursor_node is app._uri_nodes[renamed]
            # … and the detail pane tracks the new URI, not the stale old one.
            assert app._detail_uri == renamed

    _run(scenario)


def test_creating_an_individual_reveals_without_stealing_focus_regression(tmp_path) -> None:
    """Regression: creating an individual reveals it in the tree (highlight moves to the
    new entity) but must NOT steal keyboard focus away to the tree. Root cause: creates
    went through ``jump_to`` which focuses the tree."""

    async def scenario() -> None:
        from textual.widgets import Tree

        from ster.tui.individual_modal import IndividualModal

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Dog")  # its context menu offers "+ Add individual"
            await pilot.pause()
            app._run_field_action(_action_field("add_individual"))  # context-menu action → modal
            await pilot.pause()
            assert isinstance(app.screen, IndividualModal)
            app.screen._uri.value = ZOO + "Fido"
            app.screen._submit()
            for _ in range(4):
                await pilot.pause()
            created = ZOO + "Fido"
            assert created in app.tax.owl_individuals  # created
            tree = app.query_one("#tree", Tree)
            # The new individual is revealed (highlight moved to it) …
            assert tree.cursor_node is app._uri_nodes[created]
            # … but focus stayed in the detail pane, not stolen to the tree.
            assert app.focused is not tree

    _run(scenario)


def _action_field(action: str):  # type: ignore[no-untyped-def]
    """A synthetic action field standing in for a property context-menu choice."""
    from ster.nav.logic import DetailField

    return DetailField("ctx", "", "", editable=False, meta={"type": "action", "action": action})


def _enforce_field():  # type: ignore[no-untyped-def]
    return _action_field("enforce_shacl")


def test_add_superclass_only_offered_on_top_level_classes() -> None:
    """The class context menu offers '↑ Add superclass' only on a top-level (root) class;
    a class that already has a superclass doesn't get it."""
    from ster.tui import edits

    app = _app()  # demo zoo: Animal is a root; Dog is under Mammal
    class_items = edits.context_actions("class")
    top = [a for _, a in app._filter_class_actions(ZOO + "Animal", class_items)]
    child = [a for _, a in app._filter_class_actions(ZOO + "Dog", class_items)]
    assert "link_superclass" in top  # root class → can add a superclass
    assert "link_superclass" not in child  # already has one → hidden


def test_context_menu_hides_shacl_actions_when_enforce_feature_off() -> None:
    """The property context menu's Enforce/Remove SHACL items are gated on semanticlint's
    opt-in 'enforce' feature — filtered out when it's off (the default)."""
    app = _app()  # plugin/feature off (prefs isolated)
    items = [
        ("◆ Enforce with SHACL rule", "enforce_shacl"),
        ("◇ Remove SHACL rule", "unenforce_shacl"),
        ("✎ Rename URI…", "rename"),
    ]
    filtered = app._filter_plugin_actions(items)
    assert [a for _, a in filtered] == ["rename"]  # SHACL actions dropped, others kept


def test_enforce_shacl_writes_a_mandatory_rule_to_the_sibling_shapes_file(tmp_path) -> None:
    """The property context action writes a mandatory SHACL rule (targeting the domain)
    to <stem>.shapes.ttl, with a dated comment."""

    async def scenario() -> None:
        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "hasOwner")  # domain: Animal, range: Person
            await pilot.pause()
            app._run_field_action(_enforce_field())
            await pilot.pause()
            shapes = src.with_name("o.shapes.ttl")
            assert shapes.exists()
            text = shapes.read_text(encoding="utf-8")
            assert "# ster " in text  # dated comment
            assert f"sh:targetClass <{ZOO}Animal>" in text  # required on its domain
            assert f"sh:path <{ZOO}hasOwner>" in text and "sh:minCount 1" in text

    _run(scenario)


def test_unenforce_shacl_removes_the_rule(tmp_path) -> None:
    """The 'Remove SHACL rule' action deletes the property's rule from the shapes file."""

    async def scenario() -> None:
        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "hasOwner")
            await pilot.pause()
            app._run_field_action(_enforce_field())  # enforce first
            await pilot.pause()
            shapes = src.with_name("o.shapes.ttl")
            assert f"sh:path <{ZOO}hasOwner>" in shapes.read_text(encoding="utf-8")
            app._run_field_action(_action_field("unenforce_shacl"))  # then remove
            await pilot.pause()
            assert f"sh:path <{ZOO}hasOwner>" not in shapes.read_text(encoding="utf-8")

    _run(scenario)


def test_config_enforce_entity_scope_writes_class_and_concept_rules(tmp_path) -> None:
    """Enforcing an entity-metadata property (config tab) writes rules requiring it on
    every owl:Class and skos:Concept, and un-enforcing removes them."""

    async def scenario() -> None:
        from ster.tui.config_modal import EnforceShaclRequested

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        shapes = src.with_name("o.shapes.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            pred = "http://purl.org/dc/terms/description"
            app.on_enforce_shacl_requested(
                EnforceShaclRequested(pred, "description", True, "entity")
            )
            await pilot.pause()
            text = shapes.read_text(encoding="utf-8")
            assert "sh:targetClass <http://www.w3.org/2002/07/owl#Class>" in text
            assert "sh:targetClass <http://www.w3.org/2004/02/skos/core#Concept>" in text
            assert f"sh:path <{pred}>" in text
            app.on_enforce_shacl_requested(
                EnforceShaclRequested(pred, "description", False, "entity")
            )
            await pilot.pause()
            assert pred not in shapes.read_text(encoding="utf-8")  # both rules removed

    _run(scenario)


def test_config_enforce_ontology_scope_targets_the_ontology_node(tmp_path) -> None:
    """Enforcing an ontology-metadata property requires it on the ontology node."""

    async def scenario() -> None:
        from ster.tui.config_modal import EnforceShaclRequested

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            ont = app.tax.ontology_uri
            assert ont  # the demo declares an owl:Ontology
            pred = "http://purl.org/dc/terms/creator"
            app.on_enforce_shacl_requested(EnforceShaclRequested(pred, "creator", True, "ontology"))
            await pilot.pause()
            text = src.with_name("o.shapes.ttl").read_text(encoding="utf-8")
            assert f"sh:targetNode <{ont}>" in text and f"sh:path <{pred}>" in text

    _run(scenario)


def test_config_enforce_ontology_scope_without_ontology_node_writes_nothing(tmp_path) -> None:
    """Ontology-scope enforcement needs an owl:Ontology node; without one it warns and
    writes no rule."""

    async def scenario() -> None:
        from ster.tui.config_modal import EnforceShaclRequested

        ttl = (
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix ex: <http://example.org/> .\n\n"
            "ex:Animal a owl:Class .\n"  # no owl:Ontology declaration
        )
        src = tmp_path / "o.ttl"
        src.write_text(ttl, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert not app.tax.ontology_uri
            app.on_enforce_shacl_requested(
                EnforceShaclRequested("http://x/creator", "creator", True, "ontology")
            )
            await pilot.pause()
            assert not src.with_name("o.shapes.ttl").exists()

    _run(scenario)


def test_enforce_shacl_without_a_domain_writes_nothing(tmp_path) -> None:
    """A property with no rdfs:domain has nothing to attach 'required' to — no file."""

    async def scenario() -> None:
        ttl = (
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "@prefix ex:   <http://example.org/> .\n\n"
            "ex:Ont a owl:Ontology .\n"
            'ex:orphan a owl:ObjectProperty ; rdfs:label "orphan"@en .\n'  # no domain
        )
        src = tmp_path / "o.ttl"
        src.write_text(ttl, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show("http://example.org/orphan")
            await pilot.pause()
            app._run_field_action(_enforce_field())
            await pilot.pause()
            assert not src.with_name("o.shapes.ttl").exists()

    _run(scenario)


def test_bottom_bar_shows_the_selected_language() -> None:
    """The bottom-right status overlay reports the current display language."""

    async def scenario() -> None:
        from textual.widgets import Static

        app = OntologyApp(store.load(DEMO), source="demo.ttl", lang="fr")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            ind = app.query_one("#lang-indicator", Static)
            assert "selected language: fr" in str(ind.render())
            # sits at the bottom-right corner
            assert ind.region.right == 120 and ind.region.bottom == 40

    _run(scenario)


# ── graph web view: port-conflict warning + offer to close the holder ───────────


def test_show_graph_warns_when_the_live_server_port_is_held() -> None:
    """When the port is taken by another process (and our server isn't live), the graph
    action pops a confirmation naming the holder instead of silently going offline."""
    from unittest.mock import patch

    from ster import viz_vowl
    from ster.tui.choice_modal import ChoiceModal

    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            with (
                patch.object(viz_vowl, "is_live_server", return_value=False),
                patch.object(viz_vowl, "port_holder", return_value=(999, "python ster show x.ttl")),
            ):
                app._show_graph(None)
                await pilot.pause()
            assert isinstance(app.screen, ChoiceModal)
            assert "999" in app.screen._prompt and "already in use" in app.screen._prompt

    _run(scenario)


def test_show_graph_opens_directly_when_the_port_is_free() -> None:
    from unittest.mock import patch

    from ster import viz_vowl
    from ster.tui.choice_modal import ChoiceModal

    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            opened: list = []
            with (
                patch.object(viz_vowl, "is_live_server", return_value=False),
                patch.object(viz_vowl, "port_holder", return_value=None),
                patch.object(app, "_open_graph_now", lambda t: opened.append(t)),
            ):
                app._show_graph(None)
                await pilot.pause()
            assert opened == [None]
            assert not isinstance(app.screen, ChoiceModal)  # no prompt when the port is free

    _run(scenario)


def test_port_conflict_close_frees_the_port_then_opens() -> None:
    from unittest.mock import patch

    from ster import viz_vowl

    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            freed: list = []
            opened: list = []
            with (
                patch.object(viz_vowl, "free_port", lambda pid: freed.append(pid) or True),
                patch.object(app, "_open_graph_now", lambda t: opened.append(t)),
            ):
                app._on_port_conflict("close", 999, None)
            assert freed == [999] and opened == [None]  # killed then opened the live graph

    _run(scenario)


def test_port_conflict_close_failure_reports_and_does_not_open() -> None:
    from unittest.mock import patch

    from ster import viz_vowl

    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            opened: list = []
            with (
                patch.object(viz_vowl, "free_port", lambda pid: False),
                patch.object(app, "_open_graph_now", lambda t: opened.append(t)),
            ):
                app._on_port_conflict("close", 999, None)
            assert opened == []  # port never freed → don't open (user is notified of the error)

    _run(scenario)


def test_port_conflict_snapshot_opens_without_killing_and_cancel_does_nothing() -> None:
    from unittest.mock import patch

    from ster import viz_vowl

    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            freed: list = []
            opened: list = []
            with (
                patch.object(viz_vowl, "free_port", lambda pid: freed.append(pid) or True),
                patch.object(app, "_open_graph_now", lambda t: opened.append(t)),
            ):
                app._on_port_conflict("snapshot", 999, None)  # offline snapshot, no kill
                app._on_port_conflict("cancel", 999, None)  # nothing
                app._on_port_conflict(None, 999, None)  # dismissed → nothing
            assert opened == [None] and freed == []

    _run(scenario)


def test_editing_a_datatype_literal_value_opens_the_multiline_markdown_editor(tmp_path) -> None:
    """The user's case: editing a datatype/annotation literal opens the larger multi-line
    editor (a TextArea), not the one-line box."""

    async def scenario() -> None:
        from textual.widgets import TextArea

        from ster.model import Label, OWLIndividual, OWLProperty, Taxonomy
        from ster.tui.context_menu import ContextMenu
        from ster.tui.detail_view import DetailRow

        t = Taxonomy()
        t.ontology_uri = ZOO.rstrip("/")
        t.owl_properties[ZOO + "note"] = OWLProperty(
            uri=ZOO + "note", prop_type="DatatypeProperty", labels=[Label("en", "note")]
        )
        t.owl_individuals[ZOO + "Rex"] = OWLIndividual(
            uri=ZOO + "Rex", labels=[Label("en", "Rex")], literal_values=[(ZOO + "note", "hi", "")]
        )
        src = tmp_path / "o.ttl"
        store.save(t, src)
        app = OntologyApp(store.load(src), source="o.ttl", path=src)  # editable (has a path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Rex")
            await pilot.pause()
            row = next(r for r in app.query(DetailRow) if r.field.meta.get("type") == "ind_lit_val")
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # opens the row's Edit/Delete menu
            await pilot.pause()
            app.query_one("#ctx-menu", ContextMenu).highlighted = 0  # Edit
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen.query_one("#edit-area", TextArea), TextArea)  # multi-line

    _run(scenario)


def test_flush_save_persists_a_pending_background_edit(tmp_path) -> None:
    """_flush_save (run on quit / on_unmount) writes an edit whose background save
    hasn't landed yet — so async persistence can never lose data."""

    async def scenario() -> None:
        from ster.model import Label

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.tax.owl_classes[ZOO + "Person"].labels[:] = [Label("en", "FlushMe")]
            app._save_dirty = True  # a pending, not-yet-persisted edit
            app._flush_save()
            assert "FlushMe" in src.read_text(encoding="utf-8")
            assert app._save_dirty is False

    _run(scenario)


def test_an_edit_debounces_the_relint(tmp_path, monkeypatch) -> None:
    """An edit arms a debounce timer for the heavy re-lint instead of linting immediately,
    so a burst of edits triggers one lint pass."""

    async def scenario() -> None:
        from ster.core.commands import OwlSetLabel

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")
            await pilot.pause()
            calls: list = []
            monkeypatch.setattr(app, "_refresh_lint_async", lambda: calls.append(1))
            app._apply_command(OwlSetLabel(src, ZOO + "Person", "en", "Human"))
            await app.workers.wait_for_complete()  # let the background save land
            assert calls == []  # not linted synchronously
            assert app._lint_timer is not None  # a debounce timer is armed instead

    _run(scenario)


def test_editing_a_row_keeps_focus_on_that_row(tmp_path) -> None:
    """After saving an edit, the cursor stays on the edited detail row (not the first
    row / tree) — the mutation rebuilds the pane, so focus is re-found by field key."""

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
            key = row.field.key
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # open the edit modal
            await pilot.pause()
            app.screen.query_one("#edit-input", Input).value = "Human"
            await pilot.press("enter")  # save
            await app.workers.wait_for_complete()
            for _ in range(3):
                await pilot.pause()
            assert isinstance(app.focused, DetailRow) and app.focused.field.key == key

    _run(scenario)


def test_cancelling_an_edit_keeps_focus_on_that_row(tmp_path) -> None:
    """Discarding an edit (✕ / click-away → dismiss None, no save) keeps the cursor on the
    edited row — the pane isn't rebuilt, so focus returns to the origin row. (Esc itself now
    auto-saves — see test_editing_a_row_keeps_focus_on_that_row.)"""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")
            await pilot.pause()
            row = next(r for r in app.query(DetailRow) if r.field.meta.get("type") == "rdf_label")
            key = row.field.key
            row.focus()
            await pilot.pause()
            await pilot.press("enter")  # open the edit modal
            await pilot.pause()
            app.screen.dismiss(None)  # ✕ / click-away discards — no save, no rebuild
            for _ in range(3):
                await pilot.pause()
            assert isinstance(app.focused, DetailRow) and app.focused.field.key == key

    _run(scenario)


def test_async_lint_refresh_keeps_focus_on_the_edited_row_regression(tmp_path) -> None:
    """Regression: the debounced re-lint lands a second or two after an edit and rebuilds
    the detail pane, which dropped focus to the tree. Focus must stay on the edited row."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")
            await pilot.pause()
            row = next(r for r in app.query(DetailRow) if r.field.meta.get("type") == "rdf_label")
            key = row.field.key
            row.focus()
            await pilot.pause()
            assert app.focused is row
            # Simulate the background lint completing (what set_timer → _lint_worker calls).
            app._on_lint_ready(None)
            for _ in range(3):
                await pilot.pause()
            assert isinstance(app.focused, DetailRow) and app.focused.field.key == key

    _run(scenario)


def test_async_lint_refresh_leaves_tree_focus_alone(tmp_path) -> None:
    """When focus is on the tree (not a detail row), the lint refresh must not yank it into
    the detail pane — only a focused row is preserved."""

    async def scenario() -> None:
        from textual.widgets import Tree

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(ZOO + "Person")
            tree = app.query_one("#tree", Tree)
            tree.focus()
            await pilot.pause()
            app._on_lint_ready(None)
            for _ in range(3):
                await pilot.pause()
            assert app.focused is tree

    _run(scenario)


async def _open_value_delete_menu(app, pilot):  # noqa: ANN001
    """Open Rex's 'has owner' value row Edit/Delete submenu and pick Delete → the
    confirm modal. Returns the value DetailRow."""
    from ster.tui.context_menu import ContextMenu
    from ster.tui.detail_view import DetailRow

    app._show(ZOO + "Rex")
    await pilot.pause()
    row = next(r for r in app.query(DetailRow) if r.field.meta.get("type") == "ind_prop_val")
    row.focus()
    await pilot.pause()
    await pilot.press("enter")  # Edit/Delete submenu
    await pilot.pause()
    app.query_one("#ctx-menu", ContextMenu).highlighted = 1  # Delete
    await pilot.press("enter")
    await pilot.pause()
    return row


def test_deleting_a_value_row_asks_to_confirm_then_focuses_the_tree(tmp_path) -> None:
    """Deleting a property value confirms first, then removes it and lands focus on the
    entity's tree node (one Tab/arrow back to the detail pane)."""

    async def scenario() -> None:
        from textual.widgets import Tree

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _open_value_delete_menu(app, pilot)
            assert app.screen.__class__.__name__ == "ChoiceModal"  # confirm first
            await pilot.click("#opt-ok")  # confirm the delete
            await app.workers.wait_for_complete()
            for _ in range(3):
                await pilot.pause()
            # the value is gone …
            assert not app.tax.owl_individuals[ZOO + "Rex"].property_values
            # … and focus landed on Rex's tree node, not a stale detail row
            assert app.focused is app.query_one("#tree", Tree)

    _run(scenario)


def test_cancelling_a_value_delete_keeps_the_value_and_row_focus(tmp_path) -> None:
    """Declining the delete confirm leaves the value intact and the cursor on its row."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        src = tmp_path / "o.ttl"
        src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            row = await _open_value_delete_menu(app, pilot)
            key = row.field.key
            app.screen.dismiss(None)  # decline the confirm
            for _ in range(3):
                await pilot.pause()
            assert app.tax.owl_individuals[ZOO + "Rex"].property_values  # value kept
            assert isinstance(app.focused, DetailRow) and app.focused.field.key == key

    _run(scenario)


# ── delete lands the cursor on the entity's parent (kept unfolded) ─────────────

_SKOS_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix : <https://ex/sk/> .
:Scheme a skos:ConceptScheme ; skos:prefLabel "Scheme"@en ; skos:hasTopConcept :Top .
:Top a skos:Concept ; skos:inScheme :Scheme ; skos:topConceptOf :Scheme ;
    skos:prefLabel "Top"@en ; skos:narrower :Child .
:Child a skos:Concept ; skos:inScheme :Scheme ; skos:prefLabel "Child"@en ; skos:broader :Top .
"""

_SUBPROP_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <https://ex/p/> .
:parentProp a owl:ObjectProperty .
:childProp a owl:ObjectProperty ; rdfs:subPropertyOf :parentProp .
"""


def _app_on(tmp_path, ttl: str):
    src = tmp_path / "o.ttl"
    src.write_text(ttl, encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src)


async def _delete(app, pilot, uri: str, action: str, mode: str) -> None:  # noqa: ANN001
    """Show *uri*, run its delete action, and confirm *mode* in the choice modal."""
    from ster.nav.logic import DetailField

    app._show(uri)
    await pilot.pause()
    app._run_field_action(
        DetailField("ctx", "", "", editable=False, meta={"type": "action", "action": action})
    )
    await pilot.pause()
    await pilot.click(f"#opt-{mode}")
    for _ in range(3):
        await pilot.pause()


def test_delete_subclass_lands_cursor_on_superclass(tmp_path) -> None:
    async def scenario() -> None:
        app = _app_on(tmp_path, DEMO.read_text(encoding="utf-8"))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _delete(app, pilot, ZOO + "Dog", "delete_class", "keep_all")
            assert app._detail_uri == ZOO + "Mammal"  # Dog's super-class

    _run(scenario)


def test_delete_root_class_lands_cursor_on_ontology(tmp_path) -> None:
    async def scenario() -> None:
        from ster.tui import detail

        app = _app_on(tmp_path, DEMO.read_text(encoding="utf-8"))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _delete(app, pilot, ZOO + "Animal", "delete_class", "cascade_subclasses")
            assert app._detail_uri == detail.OVERVIEW_URI  # the "Ontology" node

    _run(scenario)


def test_delete_individual_lands_on_class_and_keeps_it_unfolded(tmp_path) -> None:
    async def scenario() -> None:
        app = _app_on(tmp_path, DEMO.read_text(encoding="utf-8"))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _delete(app, pilot, ZOO + "Rex", "delete_individual", "delete")
            assert app._detail_uri == ZOO + "Dog"  # Rex's class
            assert app._uri_nodes[ZOO + "Dog"].is_expanded  # class stays unfolded

    _run(scenario)


def test_delete_property_lands_on_its_section(tmp_path) -> None:
    async def scenario() -> None:
        from ster.tui.app import _prop_section_key

        app = _app_on(tmp_path, DEMO.read_text(encoding="utf-8"))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _delete(app, pilot, ZOO + "hasOwner", "delete_property", "decl")
            assert app._detail_uri == _prop_section_key("ObjectProperty")  # Object Properties

    _run(scenario)


def test_delete_subproperty_lands_on_parent_property(tmp_path) -> None:
    async def scenario() -> None:
        app = _app_on(tmp_path, _SUBPROP_TTL)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _delete(app, pilot, "https://ex/p/childProp", "delete_property", "decl")
            assert app._detail_uri == "https://ex/p/parentProp"

    _run(scenario)


def test_delete_subconcept_lands_on_broader(tmp_path) -> None:
    async def scenario() -> None:
        app = _app_on(tmp_path, _SKOS_TTL)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _delete(app, pilot, "https://ex/sk/Child", "delete", "keep")
            assert app._detail_uri == "https://ex/sk/Top"  # broader concept

    _run(scenario)


def test_delete_top_concept_lands_on_scheme(tmp_path) -> None:
    async def scenario() -> None:
        app = _app_on(tmp_path, _SKOS_TTL)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _delete(app, pilot, "https://ex/sk/Top", "delete", "cascade")
            assert app._detail_uri == "https://ex/sk/Scheme"

    _run(scenario)


def test_delete_scheme_lands_on_taxonomy(tmp_path) -> None:
    async def scenario() -> None:
        from ster.tui import detail

        app = _app_on(tmp_path, _SKOS_TTL)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _delete(app, pilot, "https://ex/sk/Scheme", "delete_scheme", "scheme_only")
            assert app._detail_uri == detail.TAXONOMY_URI  # the "Taxonomy" node

    _run(scenario)
