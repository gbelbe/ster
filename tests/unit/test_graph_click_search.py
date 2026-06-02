"""Pressing Enter on a search match activates a node (expanding its relations).
Clicking a node itself does nothing — expansion is driven only by the hover
overlay buttons (explore/extend, hide)."""

from __future__ import annotations

from ster.viz_vowl import _app_js


def test_app_js_defines_activate_node():
    assert "function activateNode" in _app_js()


def test_node_click_does_not_activate():
    # Tapping a node must NOT trigger activate/explore/extend; only empty-canvas
    # taps remain wired (to clear the selection).
    js = _app_js().replace(" ", "")
    assert "cy.on('tap','node'" not in js
    assert "cy.on('tap',function(e){if(e.target===cy)" in js


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
