"""Phase 2: the client's search box is wired to /api/search, not just the
on-canvas cy.nodes() filter.

See docs/architecture/graph-editor.md, Phase 2. These are structural
assertions on graph_app.js's source (the project's established pattern for
JS behaviour it can't drive through a browser — see test_graph_init_completes_js.py
and test_graph_asset_separation.py), not a browser-level integration test.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def test_search_calls_the_server_search_endpoint():
    js = _app_js()
    assert "/api/search?q=" in js


def test_server_search_is_debounced():
    """A round trip per keystroke would hammer the server on every large
    ontology; the local cy.nodes() filter stays instant, only the server
    call is debounced."""
    js = _app_js()
    start = js.index("function _searchServerWhole")
    end = js.index("\n}", start)
    body = js[start:end]
    assert "setTimeout" in body


def test_server_search_guards_against_out_of_order_responses():
    """A fast typist's earlier, slower response must never overwrite a later
    keystroke's result — guarded by an incrementing request id."""
    js = _app_js()
    start = js.index("function _searchServerWhole")
    end = js.index("\n}", start)
    body = js[start:end]
    assert "reqId" in body and "_searchReqId" in body


def test_enter_falls_back_to_a_whole_ontology_match_not_on_canvas():
    """When nothing on the canvas matches, Enter must still be able to reach
    a match that only /api/search found, by exploring it directly."""
    js = _app_js()
    keydown_start = js.index("document.getElementById('search-box').addEventListener('keydown'")
    keydown_end = js.index("\n});", keydown_start)
    body = js[keydown_start:keydown_end]
    assert "_serverMatches" in body
    assert "exploreNode(hit.id,hit.type)" in body


def test_explore_node_accepts_an_explicit_type_for_off_canvas_nodes():
    """exploreNode must work for a node that only exists server-side (a search
    hit that was never rendered), not only one already sitting in cy.nodes()."""
    js = _app_js()
    assert "function exploreNode(uri,typeOverride)" in js


def test_clearing_search_invalidates_any_in_flight_server_request():
    js = _app_js()
    start = js.index("function clearSearch()")
    end = js.index("\n}", start)
    body = js[start:end]
    assert "_serverMatches=[]" in body
    assert "_searchReqId++" in body
