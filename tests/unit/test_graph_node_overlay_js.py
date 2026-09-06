"""Unit tests for the node-overlay graph interactions in the app asset.

These assert structurally on the ``graph_app.js`` source and the rendered page,
matching the string-based style of ``test_graph_expand_relations_js.py``. The
runtime merge/hide behaviour is verified live in the browser.
"""

from __future__ import annotations

from ster.model import Label, OWLIndividual, RDFClass, Taxonomy
from ster.viz_vowl import _app_js, render_vowl_html

NS = "https://example.org/onto#"


def _tax() -> Taxonomy:
    t = Taxonomy()
    t.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal", labels=[Label("en", "Animal")])
    t.owl_individuals[NS + "Rex"] = OWLIndividual(
        uri=NS + "Rex", labels=[Label("en", "Rex")], types=[NS + "Animal"]
    )
    return t


def _fn_body(js: str, name: str) -> str:
    start = js.index(f"function {name}(")
    nxt = js.find("\nfunction ", start + 1)
    return js[start : nxt if nxt != -1 else len(js)]


# ── extend ──────────────────────────────────────────────────────────────────────


def test_app_js_defines_extend_node():
    assert "function extendNode(" in _app_js()


def test_explore_button_label_is_mode_dependent():
    js = _app_js()
    assert "explore relations" in js
    assert "extend relations" in js
    # The choice is driven by whether a subgraph is currently open.
    assert "_savedGraph" in js


def test_extend_is_additive_not_replace():
    body = _fn_body(_app_js(), "extendNode")
    # Must NOT wipe the graph — it merges onto the existing elements.
    assert "cy.elements().remove()" not in body
    assert "cy.add(" in body


def test_extend_dedupes_nodes_by_id():
    body = _fn_body(_app_js(), "extendNode")
    # Only nodes whose URI id is not already present get added.
    assert "existingIds" in body
    assert "newNodes" in body


def test_extend_dedupes_edges_by_signature():
    body = _fn_body(_app_js(), "extendNode")
    assert "source" in body and "target" in body and "type" in body


# ── individual-rooted sessions keep class extensions subClassOf-only ────────────


def test_explore_records_session_root_type():
    js = _app_js()
    assert "_rootType" in js
    body = _fn_body(js, "exploreNode")
    assert "_rootType=node.data('type')" in body.replace(" ", "")


def test_class_fetch_is_subclass_only_when_rooted_on_individual():
    body = _fn_body(_app_js(), "_fetchRel").replace(" ", "")
    assert "type==='class'&&_rootType==='individual'" in body
    assert "subclass_only=1" in body


# ── the individuals button ─────────────────────────────────────────────────────


def _listener_body(js: str, var: str) -> str:
    start = js.index(f"{var}.addEventListener(")
    return js[start : js.index("\n", start)]


def _tap_handler(js: str) -> str:
    start = js.index("cy.on('tap','node'")
    return js[start : js.index("\n});", start)]


def test_individuals_button_label_is_state_dependent():
    js = _app_js()
    assert "show individuals" in js
    assert "hide individuals" in js
    # A ternary states its condition before either branch, so the window has to
    # reach back past the first label to find the variable that chooses.
    show_at, hide_at = js.index("show individuals"), js.index("hide individuals")
    window = js[max(0, min(show_at, hide_at) - 160) : max(show_at, hide_at) + 60]
    assert "_expanded" in window


def test_individuals_button_click_toggles_class_individuals():
    assert "toggleClassIndividuals" in _listener_body(_app_js(), "individualsBtn")


def test_individuals_button_shown_only_when_the_node_holds_individuals():
    assert "individualCount" in _fn_body(_app_js(), "_showOverlay")


def test_individuals_button_absent_without_an_api_token():
    """Offline there is no endpoint to fetch from, so the button is withheld."""
    assert "API_TOKEN" in _fn_body(_app_js(), "_showOverlay")


def test_toggle_still_reaches_the_class_individuals_endpoint():
    assert "class-individuals" in _fn_body(_app_js(), "toggleClassIndividuals")


# ── clicking a node ────────────────────────────────────────────────────────────


def test_app_js_defines_parent_chain():
    assert "function parentChain(" in _app_js()


def test_parent_chain_walks_sub_class_of_transitively():
    body = _fn_body(_app_js(), "parentChain")
    assert "subClassOf" in body
    # A stack-driven walk rather than a single hop.
    assert "while" in body


def test_parent_chain_seeds_from_rdf_type_for_an_individual():
    assert "instanceOf" in _fn_body(_app_js(), "_highlightSeeds")


def test_apply_highlight_keeps_the_one_hop_neighbourhood():
    assert "neighborhood()" in _fn_body(_app_js(), "applyHighlight")


def test_apply_highlight_includes_the_parent_chain():
    assert "parentChain(" in _fn_body(_app_js(), "applyHighlight")


def test_tap_no_longer_opens_individuals():
    assert "toggleClassIndividuals" not in _tap_handler(_app_js())


# ── the removed hide action ────────────────────────────────────────────────────


def test_hide_node_and_parents_is_gone():
    js = _app_js()
    assert "hideNodeAndParents" not in js
    assert "releaseSharedParents" not in js
    assert "hasVisibleDependency" not in js


# ── rendered page ──────────────────────────────────────────────────────────────


def test_rendered_html_has_the_explore_and_individuals_buttons():
    html = render_vowl_html(_tax(), file_path=None, api_token="TESTTOKEN")
    assert 'id="explore-btn"' in html
    assert 'id="individuals-btn"' in html


def test_hide_button_markup_is_gone():
    html = render_vowl_html(_tax(), file_path=None, api_token="TESTTOKEN")
    assert 'id="hide-btn"' not in html
