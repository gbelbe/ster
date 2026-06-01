"""The graph app must persist layout state only AFTER the (async) cose layout
settles, and must not restore stale/cross-graph positions — otherwise the graph
loads cluttered until the user clicks 'recenter'."""

from __future__ import annotations

from ster.viz_vowl import _app_js


def test_state_is_saved_after_layout_settles():
    js = _app_js()
    # cose is asynchronous; saving must hang off the layoutstop event, never
    # synchronously on the line after .run().
    assert "layoutstop" in js


def test_layout_is_run_via_the_settle_aware_helper():
    js = _app_js()
    assert "runLayout" in js


def test_saved_state_is_versioned():
    js = _app_js()
    # A version prefix lets a fix invalidate previously-corrupted saved state.
    assert "ster_state_v" in js


def test_saved_state_is_guarded_by_a_graph_signature():
    js = _app_js()
    # Restore only when the saved positions belong to the current graph.
    assert "_graphSig" in js


def test_no_synchronous_save_immediately_after_layout_run():
    js = _app_js()
    # Regression guard for the original bug: `cy.layout(makeLayout()).run();_saveState();`
    assert ".run();_saveState();" not in js.replace(" ", "")
