"""Unit tests for auto-update WebVOWL after SPARQL query execution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ster.model import OWLIndividual, RDFClass, Taxonomy
from ster.viz_vowl import (
    _build_query_result_html,
    open_query_result_in_browser,
    render_vowl_html,
)

_NS = "https://ex.org/kai/"
_URI = _NS + "Digital"


def _make_taxonomy() -> Taxonomy:
    tax = Taxonomy()
    tax.namespace_bindings["kai"] = _NS
    tax.owl_classes[_URI] = RDFClass(uri=_URI)
    tax.owl_individuals[_NS + "Dev1"] = OWLIndividual(uri=_NS + "Dev1", types=[_URI])
    return tax


# ── _build_query_result_html ─────────────────────────────────────────────────


def test_query_result_html_has_show_all_btn() -> None:
    tax = _make_taxonomy()
    _, html = _build_query_result_html(tax, {_URI}, full_graph_link="/full.html")
    assert "Show all nodes" in html
    assert "/full.html" in html


def test_query_result_html_no_show_all_without_link() -> None:
    tax = _make_taxonomy()
    _, html = _build_query_result_html(tax, {_URI})
    assert "Show all nodes" not in html


# ── render_vowl_html ─────────────────────────────────────────────────────────


def test_render_vowl_html_no_show_all_btn() -> None:
    tax = _make_taxonomy()
    html = render_vowl_html(tax, file_path=None)
    assert "Show all nodes" not in html


# ── open_query_result_in_browser ─────────────────────────────────────────────


def test_open_query_result_generates_full_graph_file(tmp_path: Path) -> None:
    tax = _make_taxonomy()
    file_path = tmp_path / "ont.ttl"
    file_path.write_text("", encoding="utf-8")

    with (
        patch("ster.viz_vowl._ensure_server", return_value=8000),
        patch("ster.viz_vowl.webbrowser.open"),
        patch("ster.viz_vowl._d3_script_tag", return_value="<script></script>"),
        patch("ster.viz_vowl.Path.home", return_value=tmp_path),
    ):
        _url, out_path = open_query_result_in_browser(tax, {_URI}, file_path)

    full_path = tmp_path / ".cache" / "ster" / f"{file_path.stem}_vowl.html"
    assert full_path.exists(), "Full graph HTML must be written alongside the result file"
    # The query result HTML must contain the Show all nodes button
    result_html = out_path.read_text(encoding="utf-8")
    assert "Show all nodes" in result_html
