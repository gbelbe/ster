"""Pressing Enter on a search match activates a node (expanding its relations).
Clicking a node itself does nothing — expansion is driven only by the hover
overlay buttons (explore/extend, hide)."""

from __future__ import annotations

from ster.viz_vowl import _app_js


def test_app_js_defines_activate_node():
    assert "function activateNode" in _app_js()


def test_node_click_selects_without_expanding():
    # Tapping a node selects it — panel plus neighbourhood highlight — but never
    # swaps the graph out. Replacing the whole view stays a deliberate action on
    # the hover overlay, so a stray click cannot lose the reader's place.
    # Empty-canvas taps still clear the selection. Opening a collapsed class is
    # the overlay button's job, not the click's, so a tap never adds nodes either.
    js = _app_js().replace(" ", "")
    assert "cy.on('tap','node',e=>{" in js
    assert "selectNode(" in js
    start = js.index("cy.on('tap','node'")
    assert "toggleClassIndividuals" not in js[start : js.index("\n});", start)]
    assert "cy.on('tap',function(e){if(e.target===cy)" in js


def test_node_click_never_reaches_explore():
    """The tap handler must not route through activateNode, which can expand."""
    js = _app_js().replace(" ", "")
    assert "cy.on('tap','node',e=>activateNode(" not in js


def test_search_enter_activates_first_match():
    js = _app_js()
    # A keydown handler on the search box that triggers node activation on Enter.
    assert "keydown" in js
    assert "e.key!=='Enter'" in js.replace(" ", "")
    assert "activateNode(matched.first" in js.replace(" ", "")


def test_activate_expands_explorable_nodes_by_default():
    js = _app_js().replace(" ", "")
    # Inside activateNode, explorable node types go through the mode-aware
    # dispatcher: explore (replace) on the full graph, extend (merge) in a subgraph.
    assert "_EXPLORE_ENDPOINT[n.data('type')]){exploreOrExtend(" in js
