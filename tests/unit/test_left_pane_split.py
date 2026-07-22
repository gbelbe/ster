"""The left column is a three-pane accordion — Mixed SKOS/OWL (#tree), Ontology
(#ont-tree), Properties (#prop-tree) — with a two-layer navigation model. It opens
balanced (1/3 each). Tab/Shift-Tab *select* a pane (cursor on its main entity, overview
shown); Enter/Space on a selected pane toggle its size (full ⇄ 1/3) and dive into its
content; Escape pops from content back up to the selected pane. Clicking a pane's header
row folds/unfolds it. Space on a content node still folds/unfolds that node, not the pane."""

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


def test_enter_on_a_selected_pane_expands_it_and_enters_the_content(tmp_path) -> None:
    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#ont-tree", Tree).focus()
            app._select_panel("ont-tree")  # cursor on main entity (selected)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert _folded(app) == {"tree", "prop-tree"}  # full: the others fold
            ont = app.query_one("#ont-tree", Tree)
            assert ont.cursor_node.data != detail.OVERVIEW_URI  # dived into content

    asyncio.run(scenario())


def test_enter_toggles_full_back_to_one_third(tmp_path) -> None:
    async def scenario() -> None:
        app = OntologyApp(_load(tmp_path, MIXED), source="o.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#ont-tree", Tree).focus()
            app._select_panel("ont-tree")
            await pilot.pause()
            await pilot.press("enter")  # 1/3 → full + enter content
            await pilot.pause()
            assert _folded(app) == {"tree", "prop-tree"}
            await pilot.press("escape")  # pop up to selection (cursor on main)
            await pilot.press("enter")  # full → 1/3
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
            await pilot.press("enter")  # into content
            await pilot.pause()
            ont = app.query_one("#ont-tree", Tree)
            assert ont.cursor_node.data != detail.OVERVIEW_URI
            await pilot.press("escape")  # back up to selection
            await pilot.pause()
            assert ont.cursor_node.data == detail.OVERVIEW_URI  # cursor on main entity again

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
