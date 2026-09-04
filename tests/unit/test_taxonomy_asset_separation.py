"""The vendored d3-hierarchy library is cleanly separated from ster's own
treemap application code — mirrors test_graph_asset_separation.py's contract
for the Cytoscape/graph_app.js pair.

Contract guaranteed by these tests:
  * ster's treemap render/zoom/search/filter/detail code lives in a versioned
    repo asset (``ster/assets/taxonomy_app.js``), not glued into the library blob.
  * The rendered page emits distinct <script> layers: vendored d3-hierarchy,
    per-render data injection, and the ster treemap app code.
  * Swapping the library (a d3-hierarchy upgrade) leaves the ster app block
    byte-for-byte unchanged.
  * Taxonomy data is injected separately; the app asset itself carries no
    per-ontology data.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from ster import viz_vowl
from ster.model import Concept, ConceptScheme, Label, LabelType, Taxonomy
from ster.viz_vowl import _treemap_js, render_vowl_html

NS = "https://example.org/onto#"


def _tax() -> Taxonomy:
    t = Taxonomy()
    scheme_uri = NS + "Scheme"
    root_uri = NS + "Root"
    t.concepts[root_uri] = Concept(uri=root_uri, labels=[Label("en", "Root", LabelType.PREF)])
    t.schemes[scheme_uri] = ConceptScheme(
        uri=scheme_uri, labels=[Label("en", "Scheme", LabelType.PREF)], top_concepts=[root_uri]
    )
    return t


_LIB_MARKER = "/*__STUB_D3_HIERARCHY_LIB__*/"


@pytest.fixture
def stub_lib(monkeypatch):
    """Replace the real (network/cache) library tag with a controllable stub."""

    def _make(version: str):
        return f"<script>{_LIB_MARKER} globalThis.d3={{hierarchy(){{}},treemap(){{}}}}; // {version}</script>"

    monkeypatch.setattr(viz_vowl, "_d3_hierarchy_script_tag", lambda: _make("3.1.2"))
    return _make


def _app_block(html: str) -> str:
    """Extract the ster treemap app <script> block (the one carrying the asset)."""
    needle = _treemap_js().strip()
    assert needle in html, "treemap asset content not found in rendered HTML"
    return needle


# ── asset existence ────────────────────────────────────────────────────────────


def test_treemap_js_asset_is_a_nonempty_repo_file():
    js = _treemap_js()
    assert isinstance(js, str)
    assert len(js.strip()) > 0
    # It is the application layer: it wires up d3-hierarchy, so it must reference it.
    assert "d3.hierarchy(" in js


def test_rendered_html_inlines_treemap_asset_verbatim(stub_lib):
    html = render_vowl_html(_tax(), file_path=None)
    assert _treemap_js().strip() in html


# ── distinct script layers ──────────────────────────────────────────────────────


def test_treemap_layers_present(stub_lib):
    html = render_vowl_html(_tax(), file_path=None)
    assert _LIB_MARKER in html  # vendored library
    assert '"taxonomy":' in html  # data injection carries the treemap payload
    assert _treemap_js().strip() in html  # app code


def test_treemap_app_code_is_outside_the_library_script(stub_lib):
    html = render_vowl_html(_tax(), file_path=None)
    lib_start = html.index(_LIB_MARKER)
    lib_end = html.index("</script>", lib_start)
    app_pos = html.index(_treemap_js().strip())
    assert app_pos > lib_end, "app code must not live inside the library <script>"


# ── data / code separation ──────────────────────────────────────────────────────


def test_taxonomy_data_injected_not_baked_into_treemap_asset(stub_lib):
    html = render_vowl_html(_tax(), file_path=None)
    # The taxonomy data must reach the page via the injection block …
    assert NS + "Root" in html
    # … but the reusable app asset must contain no per-ontology data.
    assert NS + "Root" not in _treemap_js()


def test_treemap_asset_reads_data_from_injected_global():
    js = _treemap_js()
    assert "globalThis.__STER_GRAPH__" in js


def test_owl_only_taxonomy_omits_taxonomy_payload():
    from ster.model import RDFClass

    t = Taxonomy()
    t.owl_classes[NS + "Cls"] = RDFClass(uri=NS + "Cls", labels=[Label("en", "Cls")])
    html = render_vowl_html(t, file_path=None)
    assert '"taxonomy":' not in html


# ── library upgrade isolation ────────────────────────────────────────────────────


def test_library_upgrade_leaves_treemap_app_block_unchanged(monkeypatch):
    t = _tax()
    monkeypatch.setattr(
        viz_vowl,
        "_d3_hierarchy_script_tag",
        lambda: "<script>/* d3-hierarchy 3.1.2 — old */ globalThis.d3={};</script>",
    )
    html_old = render_vowl_html(t, file_path=None)
    monkeypatch.setattr(
        viz_vowl,
        "_d3_hierarchy_script_tag",
        lambda: (
            "<script>/* d3-hierarchy 9.9.9 — NEW, totally different bytes */ globalThis.d3={};</script>"
        ),
    )
    html_new = render_vowl_html(t, file_path=None)
    assert _app_block(html_old) == _app_block(html_new) == _treemap_js().strip()


# ── syntax validity ──────────────────────────────────────────────────────────────


def test_treemap_asset_is_valid_javascript_when_node_available():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available to syntax-check the asset")
    from importlib.resources import files

    asset = files("ster") / "assets" / "taxonomy_app.js"
    proc = subprocess.run(
        [node, "--check", str(asset)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
