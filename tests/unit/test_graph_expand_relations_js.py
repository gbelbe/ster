"""The graph app asset wires up the 'Expand relations' button + escape-restore."""

from __future__ import annotations

from ster.viz_vowl import _app_js


def test_app_js_defines_expand_relations_handler():
    js = _app_js()
    assert "expandRelations" in js


def test_app_js_fetches_individual_relations_endpoint():
    js = _app_js()
    assert "/api/individual-relations" in js


def test_app_js_can_restore_original_graph():
    js = _app_js()
    # A saved-elements slot used to restore the pre-expand graph on Escape.
    assert "restoreGraph" in js


def test_app_js_button_is_guarded_by_server_token():
    """The button is server-only: its rendering is gated on API_TOKEN."""
    js = _app_js()
    assert "expandRelations" in js
    assert "API_TOKEN" in js
