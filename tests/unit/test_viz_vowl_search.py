"""Unit tests for graph search feature in the VOWL HTML renderer."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, RDFClass, Taxonomy
from ster.viz_vowl import _build_query_result_html, render_vowl_html

NS = "https://example.org/onto#"


def _uri(name: str) -> str:
    return NS + name


def _make_taxonomy() -> Taxonomy:
    tax = Taxonomy()
    for name in ("Animal", "Dog", "Cat"):
        tax.owl_classes[_uri(name)] = RDFClass(uri=_uri(name), labels=[Label("en", name)])
    tax.owl_classes[_uri("Dog")].sub_class_of.append(_uri("Animal"))
    tax.owl_individuals[_uri("Rex")] = OWLIndividual(uri=_uri("Rex"), types=[_uri("Dog")])
    return tax


# ── search input element ───────────────────────────────────────────────────────


def test_search_input_present_full_graph() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    assert 'id="search-box"' in html


def test_search_input_present_focused_graph() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None, root_uri=_uri("Animal"))
    assert 'id="search-box"' in html


def test_search_input_present_query_result() -> None:
    _, html = _build_query_result_html(_make_taxonomy(), {_uri("Animal"), _uri("Dog")})
    assert 'id="search-box"' in html


def test_search_input_has_placeholder() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    assert "placeholder=" in html
    assert "search-box" in html


# ── JavaScript functions ───────────────────────────────────────────────────────


def test_search_nodes_function_present() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    assert "searchNodes" in html


def test_clear_search_function_present() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    assert "clearSearch" in html


# ── autofocus behaviour ────────────────────────────────────────────────────────


def test_search_box_has_autofocus_attribute() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    assert "autofocus" in html


def test_search_box_focused_on_load_via_js() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    assert "search-box" in html
    assert ".focus()" in html


def test_clear_search_on_escape() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    assert "clearSearch" in html
    assert "Escape" in html


# ── search UI elements ────────────────────────────────────────────────────────


def test_search_wrap_element_present() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    assert 'id="search-wrap"' in html


def test_search_clear_button_present() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    assert 'id="search-clear"' in html


def test_search_count_element_present() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    assert 'id="search-count"' in html
