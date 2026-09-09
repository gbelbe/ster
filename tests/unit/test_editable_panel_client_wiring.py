"""Phase 3: the side panel's label/description become editable, submitting
through /api/entity-label and /api/entity-description rather than only
rendering read-only detail.

See docs/architecture/graph-editor.md, Phase 3. Structural assertions on
graph_app.js's source, the project's established pattern for JS behaviour it
can't drive through a browser (see test_graph_asset_separation.py and
test_graph_init_completes_js.py).
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def test_label_edits_post_to_the_entity_label_endpoint():
    js = _app_js()
    assert "/api/entity-label" in js


def test_description_edits_post_to_the_entity_description_endpoint():
    js = _app_js()
    assert "/api/entity-description" in js


def test_read_only_nodes_never_get_the_edit_affordance():
    """A node from a context file (readOnly=1) has nowhere for TaxonomyService
    to persist a change — _canEdit must gate on it."""
    js = _app_js()
    start = js.index("function _canEdit(d){")
    end = js.index("\n}", start)
    body = js[start:end]
    assert "d.readOnly" in body
    assert "API_TOKEN" in body


def test_editing_requires_an_explicit_save_not_blur_or_enter():
    """An accidental click-away or Enter keypress must never submit an edit —
    only the Save button's own click handler may call onSave."""
    js = _app_js()
    start = js.index("function _editableRow(")
    end = js.index("\nfunction _editableLabelNode", start)
    body = js[start:end]
    assert "onSave(input.value)" in body
    assert "saveBtn.addEventListener('click'" in body
    assert "'blur'" not in body
    assert "'keydown'" not in body


def test_saving_a_label_updates_the_on_canvas_node_too():
    """The panel and the canvas must not disagree about a node's label after
    an edit — the cy node's own data has to be updated, not just the panel."""
    js = _app_js()
    start = js.index("function _editableLabelNode(d){")
    end = js.index("\n}", start)
    body = js[start:end]
    assert "n.data('label',value)" in body


def test_saving_invalidates_the_cached_detail_so_a_reopen_refetches():
    js = _app_js()
    for fn_start in (
        "function _editableLabelNode(d){",
        "function detailDescriptionOrEditNodes(d,description){",
    ):
        start = js.index(fn_start)
        end = js.index("\nfunction ", start + 1)
        body = js[start:end]
        assert "_detailCache.delete(d.id)" in body


def test_the_detail_panel_still_shows_a_read_only_view_without_a_token():
    """Offline export / no-server case: no edit affordance is even attempted,
    the plain read-only description rendering must still work."""
    js = _app_js()
    start = js.index("function detailDescriptionOrEditNodes(d,description){")
    end = js.index("\n}", start)
    body = js[start:end]
    assert "_canEdit(d)" in body
    assert "linkifyNodes(description)" in body
