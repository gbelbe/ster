"""The graph page remembers where nodes were left, through the project, not the browser.

Positions used to be saved in localStorage: per origin, and ster serves the
graph on a new port each launch, so nothing survived a restart; and all or
nothing, discarded the moment one node was added. They are now read and saved
through /api/layout (ster.graph_layout) and restored node by node.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_nothing_is_kept_in_the_browser_any_more() -> None:
    assert "localStorage.setItem" not in _app_js()
    assert "localStorage.getItem" not in _app_js()


def test_positions_are_read_and_saved_through_the_api() -> None:
    js = _app_js()
    assert "const _LAYOUT_URL='/api/layout';" in js
    assert "method:'PUT'" in js and "method:'DELETE'" in js


def test_only_the_full_file_view_remembers() -> None:
    """The server marks it; a focused graph or a query result lays out fresh.

    The page trusts the flag alone: the server sets it only with a token (see
    test_a_static_page_has_no_server_to_remember_with), and repeating that check
    here was the one branch that pushed the page's setup past SonarQube's
    cognitive-complexity limit (S3776).
    """
    assert "const_REMEMBER=Boolean(taxoMeta.rememberLayout);" in _js()


def test_restore_is_per_node_not_all_or_nothing() -> None:
    js = _js()
    assert "constknown=cy.nodes().filter(n=>Boolean(stored[n.id()]));" in js
    assert "constnewcomers=cy.nodes().difference(known);" in js


def test_newcomers_are_laid_out_around_pinned_remembered_nodes() -> None:
    js = _js()
    assert "fixedNodeConstraint:pinned" in js
    assert "randomize:false" in js


def test_a_layout_is_saved_once_it_settles_never_synchronously() -> None:
    js = _js()
    assert "l.one('layoutstop',()=>{_saveLayout();hideSpinner();});" in js
    assert ".run();_saveLayout();" not in js


def test_a_drop_saves_after_a_pause() -> None:
    js = _js()
    assert "cy.on('dragfree','node',_debouncedSave);" in js
    assert "setTimeout(_saveLayout,400)" in js


def test_the_viewport_is_not_remembered() -> None:
    assert "cy.on('viewport',_debouncedSave)" not in _js()


def test_an_explore_view_never_overwrites_the_layout() -> None:
    assert "if(!_REMEMBER||_savedGraph)return;" in _js()


def test_saved_graph_is_declared_before_anything_saves() -> None:
    """A `let` read before its line has run throws; saving checks _savedGraph."""
    js = _app_js()
    assert js.index("let _savedGraph=null;") < js.index("function _saveLayout(){")


def test_recenter_fits_without_forgetting_the_layout() -> None:
    js = _js()
    assert (
        "document.getElementById('zoom-fit').addEventListener('click',()=>cy.fit(undefined,30));"
        in js
    )
    assert "if(e.key==='f'){cy.fit(undefined,30);}" in js


def test_reset_layout_forgets_then_lays_out_afresh() -> None:
    js = _js()
    assert "document.getElementById('layout-reset')?.addEventListener('click',_resetLayout);" in js
    assert ".finally(runLayout);" in js


def test_the_reset_button_is_on_the_page() -> None:
    from ster.viz_vowl._html_template import _HTML_TEMPLATE

    assert 'id="layout-reset"' in _HTML_TEMPLATE


# ── which pages remember ─────────────────────────────────────────────────────


def _remembers(**kwargs) -> bool:
    import json
    import re

    from ster.model import Label, RDFClass, Taxonomy
    from ster.viz_vowl import render_vowl_html

    tax = Taxonomy()
    tax.owl_classes["https://ex.org/A"] = RDFClass(
        uri="https://ex.org/A", labels=[Label("en", "A")]
    )
    html = render_vowl_html(tax, None, **kwargs)
    payload = re.search(r"window\.__STER_GRAPH__=(\{.*?\});</script>", html, re.S).group(1)
    return json.loads(payload)["meta"]["rememberLayout"]


def test_the_full_file_view_with_a_server_remembers() -> None:
    assert _remembers(api_token="t") is True


def test_a_graph_focused_on_one_entity_does_not() -> None:
    assert _remembers(api_token="t", root_uri="https://ex.org/A") is False


def test_a_query_result_does_not() -> None:
    assert _remembers(api_token="t", sparql="SELECT * WHERE { ?s ?p ?o }") is False


def test_a_static_page_has_no_server_to_remember_with() -> None:
    assert _remembers() is False
