"""Phase 4: adding/removing relations from the panel — /api/relation,
/api/relation/remove, /api/class-parent, /api/class-parent/remove — and the
search-backed picker that feeds them.

See docs/architecture/graph-editor.md, Phase 4. Structural assertions on
graph_app.js's source, per the project's established pattern for JS behaviour
it can't drive through a browser.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def test_add_relation_posts_to_the_relation_endpoint():
    js = _app_js()
    assert "/api/relation'" in js.replace('"', "'")


def test_remove_relation_posts_to_the_relation_remove_endpoint():
    js = _app_js()
    assert "/api/relation/remove" in js


def test_add_class_parent_posts_to_the_class_parent_endpoint():
    js = _app_js()
    assert "/api/class-parent'" in js.replace('"', "'")


def test_remove_class_parent_posts_to_the_class_parent_remove_endpoint():
    js = _app_js()
    assert "/api/class-parent/remove" in js


def test_the_picker_searches_via_the_types_filter():
    """The relation picker must restrict candidates by type (property/
    individual/class) so, e.g., picking a relation target never offers a
    concept as a candidate object-property value."""
    js = _app_js()
    start = js.index("function _searchPicker(")
    end = js.index("\nfunction ", start + 1)
    body = js[start:end]
    assert "/api/search?q=" in body
    assert "&types=" in body


def test_only_property_and_subclassof_relations_get_a_remove_button():
    """rdf:type, broader, equivalentClass etc. have no matching command in
    this slice, so they must stay display-only rather than offering a button
    that would silently do nothing (or error) if clicked."""
    js = _app_js()
    start = js.index("function detailRelationsNodes(")
    end = js.index("\nfunction ", start + 1)
    body = js[start:end]
    assert "r.propUri" in body
    assert "r.rel==='subClassOf'" in body


def test_relation_editing_is_gated_on_canEdit():
    js = _app_js()
    start = js.index("function detailRelationsNodes(")
    end = js.index("\nfunction ", start + 1)
    body = js[start:end]
    assert "_canEdit(d)" in body


def test_individual_gets_an_add_relation_form_class_gets_add_superclass():
    js = _app_js()
    start = js.index("function detailRelationsNodes(")
    end = js.index("\nfunction ", start + 1)
    body = js[start:end]
    assert "_individualRelationAddForm(d)" in body
    assert "_classParentAddForm(d)" in body
