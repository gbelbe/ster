"""Phase 1: fcose (+ layout-base/cose-base) and cytoscape-expand-collapse are
vendored and wired into the rendered page, and the app layer's force layout
uses fcose instead of the non-linear-cost cose layout it replaced.

See docs/architecture/graph-editor.md, Phase 1 (layout & scale).
"""

from __future__ import annotations

import pytest

from ster import viz_vowl
from ster.model import Label, OWLIndividual, RDFClass, Taxonomy
from ster.viz_vowl import _app_js, _build_query_result_html, render_vowl_html

NS = "https://example.org/onto#"


def _tax() -> Taxonomy:
    t = Taxonomy()
    t.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal", labels=[Label("en", "Animal")])
    t.owl_individuals[NS + "Rex"] = OWLIndividual(
        uri=NS + "Rex", labels=[Label("en", "Rex")], types=[NS + "Animal"]
    )
    return t


_MARKERS = {
    "_layout_base_script_tag": "/*__STUB_LAYOUT_BASE__*/",
    "_cose_base_script_tag": "/*__STUB_COSE_BASE__*/",
    "_fcose_script_tag": "/*__STUB_FCOSE__*/",
    "_expand_collapse_script_tag": "/*__STUB_EXPAND_COLLAPSE__*/",
}


@pytest.fixture
def stub_libs(monkeypatch):
    """Replace every vendored-library tag with a small, distinct, controllable
    stub so tests can assert on presence/placement without hitting the network."""
    for name, marker in _MARKERS.items():
        monkeypatch.setattr(viz_vowl._js_assets, name, lambda m=marker: f"<script>{m}</script>")
    monkeypatch.setattr(
        viz_vowl._js_assets,
        "_cytoscape_script_tag",
        lambda: "<script>/*__STUB_CY__*/</script>",
    )
    return _MARKERS


def test_all_four_new_libraries_are_inlined_in_the_default_render(stub_libs):
    html = render_vowl_html(_tax(), file_path=None)
    for marker in stub_libs.values():
        assert marker in html


def test_all_four_new_libraries_are_inlined_in_the_query_result_render(stub_libs):
    _, html = _build_query_result_html(_tax(), {NS + "Animal"})
    for marker in stub_libs.values():
        assert marker in html


def test_no_leftover_placeholder_tokens_in_rendered_html(stub_libs):
    """Regression guard: a forgotten .replace() leaves the raw __TOKEN__ text
    sitting in the page instead of a <script> tag (as happened for __SHOW_ALL_BTN__
    during Phase 0)."""
    html = render_vowl_html(_tax(), file_path=None)
    for token in (
        "__LAYOUT_BASE_SCRIPT__",
        "__COSE_BASE_SCRIPT__",
        "__FCOSE_SCRIPT__",
        "__EXPAND_COLLAPSE_SCRIPT__",
    ):
        assert token not in html


def test_load_order_puts_cytoscape_before_the_layout_extensions(stub_libs):
    """fcose registers itself against the global cytoscape object at load time,
    so cytoscape (and layout-base/cose-base, which fcose itself depends on) must
    already be on the page before the fcose <script> runs."""
    html = render_vowl_html(_tax(), file_path=None)
    cy_pos = html.index("__STUB_CY__")
    layout_base_pos = html.index("__STUB_LAYOUT_BASE__")
    cose_base_pos = html.index("__STUB_COSE_BASE__")
    fcose_pos = html.index("__STUB_FCOSE__")
    assert cy_pos < layout_base_pos < cose_base_pos < fcose_pos


# ── app layer uses fcose, not cose ──────────────────────────────────────────


def test_app_asset_uses_fcose_as_the_force_layout():
    js = _app_js()
    assert "name:'fcose'" in js
    assert "name:'cose'" not in js, "the non-linear-cost cose layout must be fully replaced"


def test_app_asset_still_registers_only_the_public_cytoscape_entrypoint():
    js = _app_js()
    for forbidden in ("._private", "cytoscape.__", ".__proto__"):
        assert forbidden not in js
