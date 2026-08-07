"""Phase A: the vendored Cytoscape library is cleanly separated from ster's
own graph application code.

Contract guaranteed by these tests:
  * ster's graph interaction/update code lives in a versioned repo asset
    (``ster/assets/graph_app.js``), not glued into the library blob.
  * The rendered page emits three distinct <script> layers: vendored library,
    per-render data injection, and the ster app code.
  * Swapping the library (a Cytoscape upgrade) leaves the ster app block
    byte-for-byte unchanged.
  * Taxonomy data is injected separately; the app asset itself carries no
    per-ontology data.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from ster import viz_vowl
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


_LIB_MARKER = "/*__STUB_CYTOSCAPE_LIB__*/"


@pytest.fixture
def stub_lib(monkeypatch):
    """Replace the real (network/cache) library tag with a controllable stub."""

    def _make(version: str):
        return f"<script>{_LIB_MARKER} window.cytoscape=function(){{return{{}};}}; // {version}</script>"

    monkeypatch.setattr(viz_vowl, "_cytoscape_script_tag", lambda: _make("3.29.2"))
    return _make


def _app_block(html: str) -> str:
    """Extract the ster app <script> block (the one carrying the asset)."""
    needle = _app_js().strip()
    assert needle in html, "app asset content not found in rendered HTML"
    return needle


# ── asset existence ────────────────────────────────────────────────────────────


def test_app_js_asset_is_a_nonempty_repo_file():
    js = _app_js()
    assert isinstance(js, str)
    assert len(js.strip()) > 0
    # It is the application layer: it wires up Cytoscape, so it must reference it.
    assert "cytoscape(" in js


def test_rendered_html_inlines_app_asset_verbatim(stub_lib):
    html = render_vowl_html(_tax(), file_path=None)
    assert _app_js().strip() in html


# ── three distinct layers ───────────────────────────────────────────────────────


def test_three_distinct_script_layers(stub_lib):
    html = render_vowl_html(_tax(), file_path=None)
    assert _LIB_MARKER in html  # vendored library
    assert "window.__STER_GRAPH__" in html  # data injection
    assert _app_js().strip() in html  # app code


def test_app_code_is_outside_the_library_script(stub_lib):
    html = render_vowl_html(_tax(), file_path=None)
    lib_start = html.index(_LIB_MARKER)
    lib_end = html.index("</script>", lib_start)
    app_pos = html.index(_app_js().strip())
    assert app_pos > lib_end, "app code must not live inside the library <script>"


def test_data_injection_is_outside_the_library_script(stub_lib):
    html = render_vowl_html(_tax(), file_path=None)
    lib_start = html.index(_LIB_MARKER)
    lib_end = html.index("</script>", lib_start)
    assert html.index("window.__STER_GRAPH__") > lib_end


# ── data / code separation ──────────────────────────────────────────────────────


def test_taxonomy_data_injected_not_baked_into_app_asset(stub_lib):
    html = render_vowl_html(_tax(), file_path=None)
    # The ontology data must reach the page via the injection block …
    assert NS + "Rex" in html
    # … but the reusable app asset must contain no per-ontology data.
    assert NS + "Rex" not in _app_js()
    assert NS + "Animal" not in _app_js()


def test_app_asset_reads_data_from_injected_global():
    js = _app_js()
    assert "globalThis.__STER_GRAPH__" in js
    # The old inline placeholder tokens must be gone from the app layer.
    assert "__GRAPH_DATA__" not in js
    assert "__API_TOKEN__" not in js


# ── library upgrade isolation (the core requirement) ────────────────────────────


def test_library_upgrade_leaves_app_block_unchanged(monkeypatch):
    t = _tax()
    monkeypatch.setattr(
        viz_vowl,
        "_cytoscape_script_tag",
        lambda: "<script>/* cytoscape 3.29.2 — old */ window.cytoscape=function(){};</script>",
    )
    html_old = render_vowl_html(t, file_path=None)
    monkeypatch.setattr(
        viz_vowl,
        "_cytoscape_script_tag",
        lambda: (
            "<script>/* cytoscape 9.9.9 — NEW, totally different bytes */ "
            "window.cytoscape=function(){return 42;};</script>"
        ),
    )
    html_new = render_vowl_html(t, file_path=None)
    assert _app_block(html_old) == _app_block(html_new) == _app_js().strip()


# ── public-API discipline ───────────────────────────────────────────────────────


def test_app_asset_uses_only_public_cytoscape_entrypoint():
    js = _app_js()
    assert "cytoscape(" in js  # documented factory
    # Guard against reaching into private/internal Cytoscape internals.
    for forbidden in ("._private", "cytoscape.__", ".__proto__"):
        assert forbidden not in js, f"app asset reaches into internals: {forbidden}"


def test_app_asset_is_valid_javascript_when_node_available():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available to syntax-check the asset")
    from importlib.resources import files

    asset = files("ster") / "assets" / "graph_app.js"
    proc = subprocess.run(
        [node, "--check", str(asset)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
