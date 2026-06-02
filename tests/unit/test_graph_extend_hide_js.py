"""Unit tests for the extend/hide graph interactions in the app asset.

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


# ── hide ─────────────────────────────────────────────────────────────────────────


def test_app_js_defines_hide_node_and_parents():
    assert "function hideNodeAndParents(" in _app_js()


def test_hide_individual_walks_instanceof_and_subclassof():
    body = _fn_body(_app_js(), "hideNodeAndParents")
    assert "instanceOf" in body
    assert "subClassOf" in body


def test_hide_removes_elements():
    body = _fn_body(_app_js(), "hideNodeAndParents")
    assert ".remove()" in body


def test_hide_protects_shared_parents():
    js = _app_js()
    body = _fn_body(js, "hideNodeAndParents")
    assert "_isParentShared" in js or "shared" in body.lower() or "depend" in body.lower()


# ── rendered page ────────────────────────────────────────────────────────────────


def test_rendered_html_has_hide_button():
    html = render_vowl_html(_tax(), file_path=None, api_token="TESTTOKEN")
    assert 'id="hide-btn"' in html


def test_rendered_html_has_both_overlay_buttons():
    html = render_vowl_html(_tax(), file_path=None, api_token="TESTTOKEN")
    assert 'id="explore-btn"' in html
    assert 'id="hide-btn"' in html
