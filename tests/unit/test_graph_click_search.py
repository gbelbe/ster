"""Clicking a node — or pressing Enter on a search match — activates it the same
way, expanding its relations by default (individuals and classes)."""

from __future__ import annotations

from ster.viz_vowl import _app_js


def test_app_js_defines_activate_node():
    assert "function activateNode" in _app_js()


def test_node_click_goes_through_activate_node():
    js = _app_js()
    assert "cy.on('tap','node',function(e){activateNode(" in js.replace(" ", "")


def test_search_enter_activates_first_match():
    js = _app_js()
    # A keydown handler on the search box that triggers node activation on Enter.
    assert "keydown" in js
    assert "e.key!=='Enter'" in js.replace(" ", "")
    assert "activateNode(matched.first" in js.replace(" ", "")


def test_activate_expands_explorable_nodes_by_default():
    js = _app_js().replace(" ", "")
    # Inside activateNode, explorable node types call exploreNode.
    assert "_EXPLORE_ENDPOINT[n.data('type')]){exploreNode(" in js
