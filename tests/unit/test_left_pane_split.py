"""The left column is a three-pane accordion — Mixed SKOS/OWL (#tree), Ontology
(#ont-tree), Properties (#prop-tree) — with a two-layer navigation model.

Panel layer (cursor on a pane header, its row highlight removed so nothing looks
selected): ↑/↓ and Tab/Shift-Tab/←/→ move between panes; Space folds/unfolds the pane;
Enter opens the pane — folding the others — and drops onto its first item.

Item layer (an item selected): ↑/↓ navigate the tree; Tab/←/→ cross to the detail pane
(Tab there toggles back to the item); Escape pops up to the panel layer. Clicking a pane's
header row folds/unfolds it."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Tree

from ster import store
from ster.tui import data, detail
from ster.tui.app import OntologyApp

PURE_TAX = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <https://example.org/> .
ex:Scheme a skos:ConceptScheme ; skos:prefLabel "S"@en ; skos:hasTopConcept ex:Fruit .
ex:Fruit a skos:Concept ; skos:inScheme ex:Scheme ; skos:prefLabel "Fruit"@en .
"""

PURE_ONT = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/> .
ex:O a owl:Ontology .
ex:Animal a owl:Class ; rdfs:label "Animal"@en .
"""

MIXED = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <https://example.org/> .
ex:Scheme a skos:ConceptScheme ; skos:prefLabel "S"@en ; skos:hasTopConcept ex:Fruit .
ex:Fruit a skos:Concept ; skos:inScheme ex:Scheme ; skos:prefLabel "Fruit"@en .
ex:Animal a owl:Class ; rdfs:label "Animal"@en .
"""

_PANES = ("tree", "ont-tree", "prop-tree")


def _load(tmp_path: Path, ttl: str):  # noqa: ANN202
    src = tmp_path / "o.ttl"
    src.write_text(ttl, encoding="utf-8")
    return store.load(src)


# ── content helper (initial-expanded choice) ──────────────────────────────────


def test_has_taxonomy_content(tmp_path) -> None:
    assert data.has_taxonomy_content(_load(tmp_path, PURE_TAX))
    assert data.has_taxonomy_content(_load(tmp_path, MIXED))
    assert not data.has_taxonomy_content(_load(tmp_path, PURE_ONT))


# ── structure: three named panes, two with clickable header rows ──────────────


def _folded(app) -> set[str]:
    return {p for p in _PANES if app.query_one(f"#{p}", Tree).has_class("folded")}


def test_panes_are_named_by_border_title(tmp_path) -> None:
    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)):
            assert app.query_one("#tree", Tree).border_title == "Mixed SKOS/OWL"
            assert app.query_one("#ont-tree", Tree).border_title == "Ontology"
            assert app.query_one("#prop-tree", Tree).border_title == "Properties"

    asyncio.run(scenario())


def test_main_panes_keep_their_clickable_overview_header_rows(tmp_path) -> None:
    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)):
            uni = app.query_one("#tree", Tree).root.children[0]
            ont = app.query_one("#ont-tree", Tree).root.children[0]
            assert uni.data == detail.TAXONOMY_URI and ont.data == detail.OVERVIEW_URI

    asyncio.run(scenario())


def test_pane_header_shows_no_expand_arrow_but_keeps_its_children(tmp_path) -> None:
    """Each pane's header (main entity) drives the accordion, not a tree fold — so it must
    not show an expand/collapse arrow (which reads as foldable) while still displaying its
    subtree."""

    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)):
            for pid in ("tree", "ont-tree", "prop-tree"):
                header = app._panel_main_node(pid)
                assert header.allow_expand is False, pid  # no arrow on the header
                assert header.children, pid  # but its content is still there

    asyncio.run(scenario())


# ── two-layer pane navigation ─────────────────────────────────────────────────

import types  # noqa: E402


def _header_click(app, pid: str) -> None:
    """Simulate a left-click on the pane's header row (its main entity) — accordions it."""
    tree = app.query_one(f"#{pid}", Tree)
    node = app._panel_main_node(pid)
    tree.hover_line = node.line  # the header's tree line (read by OntologyTree._clicked_line)
    tree.on_click(types.SimpleNamespace(button=1, style=None, prevent_default=lambda: None))


def test_opens_balanced_with_all_three_panes_at_one_third(tmp_path) -> None:
    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)):
            assert app._folded_panels == set() and _folded(app) == set()  # all 1/3

    asyncio.run(scenario())


def test_tab_selects_the_next_pane_and_prints_its_overview(tmp_path) -> None:
    """Tab moves the selection to the next pane: its cursor lands on the main entity and
    the detail view prints that pane's overview. No fold change."""

    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#tree", Tree).focus()
            await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()
            ont = app.query_one("#ont-tree", Tree)
            assert app.focused is ont
            assert ont.cursor_node.data == detail.OVERVIEW_URI  # selected = cursor on main
            assert app._detail_uri == detail.OVERVIEW_URI
            assert _folded(app) == set()  # selecting does not fold

    asyncio.run(scenario())


def test_enter_opens_the_pane_full_and_selects_the_head(tmp_path) -> None:
    """Enter in the panel layer opens the pane: it folds the *other* panes (this one unfolds
    to full) and selects the pane's *head* as the first item — no longer dimmed — so the
    head's own overview shows and it can be navigated to the detail like any item."""

    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#ont-tree", Tree).focus()
            app._select_panel("ont-tree")  # panel layer (cursor on the dimmed header)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert _folded(app) == {"tree", "prop-tree"}  # the other panes fold
            ont = app.query_one("#ont-tree", Tree)
            assert ont.cursor_node.data == detail.OVERVIEW_URI  # the head is the selected item
            assert not ont.has_class("panel-layer")  # selected, not dimmed
            assert app._entered_pid == "ont-tree"
            assert app._detail_uri == detail.OVERVIEW_URI  # its overview shows in the detail

    asyncio.run(scenario())


def test_entered_head_navigates_to_its_overview_detail(tmp_path) -> None:
    """The head is a selected item once entered: → crosses to the detail (its overview) and
    Tab there toggles back to the head — exactly like any other tree item."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            ont = app.query_one("#ont-tree", Tree)
            app._select_panel("ont-tree")
            await pilot.pause()
            await pilot.press("enter")  # select the head
            await pilot.pause()
            await pilot.press("right")  # head → its overview detail
            await pilot.pause()
            assert isinstance(app.focused, DetailRow)
            assert app._detail_uri == detail.OVERVIEW_URI
            await pilot.press("tab")  # → back to the head
            await pilot.pause()
            assert app.focused is ont and ont.cursor_node.data == detail.OVERVIEW_URI

    asyncio.run(scenario())


def test_space_on_a_selected_pane_folds_and_unfolds_it(tmp_path) -> None:
    """Space on the header toggles the pane full ⇄ 1/3 (fold the others / restore), staying
    on the header — Space is now the fold key, not Enter."""

    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#ont-tree", Tree).focus()
            app._select_panel("ont-tree")
            await pilot.pause()
            await pilot.press("space")  # 1/3 → full (others fold)
            await pilot.pause()
            assert _folded(app) == {"tree", "prop-tree"}
            ont = app.query_one("#ont-tree", Tree)
            assert ont.cursor_node.data == detail.OVERVIEW_URI  # stayed on the header
            await pilot.press("space")  # full → 1/3
            await pilot.pause()
            assert _folded(app) == set()

    asyncio.run(scenario())


def test_tab_from_content_crosses_to_the_detail_pane(tmp_path) -> None:
    """Tab while down in a tree's content jumps to the detail (right) pane, landing on its
    first actionable row — rather than cycling panels (which Tab does from the header)."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#ont-tree", Tree).focus()
            app._select_panel("ont-tree")
            await pilot.press("enter")  # dive into content
            await pilot.pause()
            await pilot.press("tab")  # content → detail pane
            await pilot.pause()
            assert isinstance(app.focused, DetailRow)

    asyncio.run(scenario())


def test_nav_hint_strings_match_the_layer() -> None:
    """The contextual hint names the keys that matter in each layer."""
    from ster.tui.app import _nav_hint

    assert "switch" in _nav_hint("panel") and "open" in _nav_hint("panel")
    assert "detail" in _nav_hint("item") and "panels" in _nav_hint("item")
    assert "edit" in _nav_hint("detail") and "panels" in _nav_hint("detail")
    # the copy shortcut is surfaced where there's a value to copy (item + detail, not panel)
    assert "copy" in _nav_hint("item") and "copy" in _nav_hint("detail")
    assert "copy" not in _nav_hint("panel")
    assert _nav_hint(None) == "" and _nav_hint("nope") == ""


def test_focused_pane_shows_its_layer_hint_on_the_border(tmp_path) -> None:
    """The contextual key hint rides the *focused* pane's bottom border and tracks the layer:
    panel-layer hint on the header, item-layer hint once inside; other panes stay clear."""
    from ster.tui.app import _nav_hint

    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            ont = app.query_one("#ont-tree", Tree)
            app._select_panel("ont-tree")
            await pilot.pause()
            assert str(ont.border_subtitle) == _nav_hint("panel")
            assert str(app.query_one("#tree", Tree).border_subtitle) == ""  # only the focused one
            await pilot.press("enter")  # into the item layer
            await pilot.pause()
            assert str(ont.border_subtitle) == _nav_hint("item")

    asyncio.run(scenario())


def test_detail_pane_shows_the_detail_hint(tmp_path) -> None:
    from ster.tui.app import _nav_hint

    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            ont = app.query_one("#ont-tree", Tree)
            app._select_panel("ont-tree")
            ont.move_cursor(app._uri_nodes["https://example.org/Animal"])
            await pilot.pause()
            await pilot.press("right")  # cross to the detail pane
            await pilot.pause()
            detail_pane = app.query_one("#detail")
            assert str(detail_pane.border_subtitle) == _nav_hint("detail")
            assert str(ont.border_subtitle) == ""  # the tree hint cleared

    asyncio.run(scenario())


def test_panel_layer_removes_the_header_highlight(tmp_path) -> None:
    """Panel layer: the cursor rests on the pane header, tagged 'panel-layer' so its row
    highlight is removed entirely (no item selected) — only the pane border reads as active."""

    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            ont = app.query_one("#ont-tree", Tree)
            app._select_panel("ont-tree")
            await pilot.pause()
            assert ont.has_class("panel-layer")  # header highlight suppressed
            assert ont.cursor_node.data == detail.OVERVIEW_URI

    asyncio.run(scenario())


def test_arrows_move_between_panels_in_the_panel_layer(tmp_path) -> None:
    """In the panel layer, ↑/↓ (not just Tab) move between panels; once you Enter a pane the
    same arrows navigate the tree instead."""

    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._select_panel("tree")
            await pilot.pause()
            await pilot.press("down")  # ↓ → next panel
            await pilot.pause()
            assert app.focused is app.query_one("#ont-tree", Tree)
            await pilot.press("up")  # ↑ → previous panel
            await pilot.pause()
            assert app.focused is app.query_one("#tree", Tree)

    asyncio.run(scenario())


def test_item_layer_tab_toggles_to_the_detail_and_back(tmp_path) -> None:
    """Item layer: with an item selected, Tab (and Shift-Tab) cross to the detail pane; Tab
    there toggles back to that exact item. Escape pops up to the panel layer (header)."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            ont = app.query_one("#ont-tree", Tree)
            app._select_panel("ont-tree")
            ont.move_cursor(app._uri_nodes["https://example.org/Animal"])  # item layer
            await pilot.pause()
            await pilot.press("shift+tab")  # mirrors Tab: item → detail
            await pilot.pause()
            assert isinstance(app.focused, DetailRow)
            await pilot.press("tab")  # detail → back to that same item
            await pilot.pause()
            assert app.focused is ont
            assert ont.cursor_node.data == "https://example.org/Animal"  # the very item
            await pilot.press("escape")  # item → panel layer (header, dimmed)
            await pilot.pause()
            assert ont.cursor_node.data == detail.OVERVIEW_URI
            assert ont.has_class("panel-layer")

    asyncio.run(scenario())


def test_left_right_arrows_move_between_panels_like_tab(tmp_path) -> None:
    """The ←/→ arrows are aliases for Shift-Tab / Tab: from a pane header, → selects the next
    pane and ← the previous one."""

    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._select_panel("tree")
            await pilot.pause()
            await pilot.press("right")  # → next pane (like Tab)
            await pilot.pause()
            assert app.focused is app.query_one("#ont-tree", Tree)
            await pilot.press("left")  # ← previous pane (like Shift-Tab)
            await pilot.pause()
            assert app.focused is app.query_one("#tree", Tree)

    asyncio.run(scenario())


def test_detail_escape_returns_to_the_panel_layer(tmp_path) -> None:
    """Escape in the detail pane pops up to the panel layer of the pane it came from — its
    header, dimmed — rather than back to the source item (that's Tab's job)."""

    async def scenario() -> None:
        from ster.tui.detail_view import DetailRow

        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            ont = app.query_one("#ont-tree", Tree)
            app._select_panel("ont-tree")
            ont.move_cursor(app._uri_nodes["https://example.org/Animal"])
            await pilot.pause()
            await pilot.press("right")  # item → detail
            await pilot.pause()
            assert isinstance(app.focused, DetailRow)
            await pilot.press("escape")  # detail → panel layer (header)
            await pilot.pause()
            assert app.focused is ont
            assert ont.cursor_node.data == detail.OVERVIEW_URI
            assert ont.has_class("panel-layer")

    asyncio.run(scenario())


def test_space_toggles_full_back_to_one_third(tmp_path) -> None:
    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#ont-tree", Tree).focus()
            app._select_panel("ont-tree")
            await pilot.pause()
            await pilot.press("space")  # 1/3 → full
            await pilot.pause()
            assert _folded(app) == {"tree", "prop-tree"}
            await pilot.press("space")  # full → 1/3 (stayed on the header)
            await pilot.pause()
            assert app._folded_panels == set() and _folded(app) == set()

    asyncio.run(scenario())


def test_escape_from_content_pops_up_to_pane_selection(tmp_path) -> None:
    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#ont-tree", Tree).focus()
            app._select_panel("ont-tree")
            await pilot.pause()
            await pilot.press("enter")  # open the pane (head selected)
            await pilot.press("down")  # move into the content
            await pilot.pause()
            ont = app.query_one("#ont-tree", Tree)
            assert ont.cursor_node.data != detail.OVERVIEW_URI  # on a content item
            await pilot.press("escape")  # back up to the panel layer
            await pilot.pause()
            assert ont.cursor_node.data == detail.OVERVIEW_URI  # cursor on the head again
            assert app._entered_pid is None  # deselected → panel layer

    asyncio.run(scenario())


def test_clicking_the_header_folds_and_unfolds_the_pane(tmp_path) -> None:
    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            _header_click(app, "tree")  # → Mixed full, the other two fold (accordion)
            await pilot.pause()
            assert _folded(app) == {"ont-tree", "prop-tree"}
            _header_click(app, "tree")  # full → back to 1/3 each
            await pilot.pause()
            assert _folded(app) == set()

    asyncio.run(scenario())


def test_ontology_pane_offers_the_add_class_cta_when_empty(tmp_path) -> None:
    """A pure taxonomy: the Ontology pane still holds its header + '＋ Add class'."""

    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, PURE_TAX), source="o.ttl")
        async with app.run_test(size=(120, 40)):
            ont_header = app.query_one("#ont-tree", Tree).root.children[0]
            assert any("Add class" in c.label.plain for c in ont_header.children)

    asyncio.run(scenario())


# ── content-driven opening layout ─────────────────────────────────────────────


def test_pure_taxonomy_opens_with_ontology_and_properties_folded(tmp_path) -> None:
    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, PURE_TAX), source="o.ttl")
        async with app.run_test(size=(120, 40)):
            assert _folded(app) == {"ont-tree", "prop-tree"}  # only the taxonomy is open

    asyncio.run(scenario())


def test_pure_ontology_opens_with_the_taxonomy_folded(tmp_path) -> None:
    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, PURE_ONT), source="o.ttl")
        async with app.run_test(size=(120, 40)):
            assert _folded(app) == {"tree"}  # ontology + properties open

    asyncio.run(scenario())


# ── Properties pane: main entity + overview + accordion parity ────────────────


def test_properties_pane_has_a_main_entity_and_takes_part_in_the_accordion(tmp_path) -> None:
    """Selecting the Properties pane focuses its 'Properties' main entity and prints the
    properties overview; clicking that header folds/unfolds it like the other panes."""

    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            prop = app.query_one("#prop-tree", Tree)
            assert prop.root.children[0].data == detail.PROPERTIES_URI  # main entity node
            app._select_panel("prop-tree")
            await pilot.pause()
            assert app._detail_uri == detail.PROPERTIES_URI  # overview shown on select
            _header_click(app, "prop-tree")
            await pilot.pause()
            assert _folded(app) == {"tree", "ont-tree"}  # Properties full, the others fold

    asyncio.run(scenario())


def test_properties_overview_shows_stats_and_quality(tmp_path) -> None:
    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, PURE_ONT), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(detail.PROPERTIES_URI)
            await pilot.pause()
            text = app._detail_text
            assert "Structure" in text and "object properties" in text  # stats
            assert "Quality & Coverage" in text and "Completeness" in text  # quality section

    asyncio.run(scenario())
