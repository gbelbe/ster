"""Unit tests for first/second-order class filter buttons in the VOWL renderer."""

from __future__ import annotations

from ster.model import Concept, ConceptScheme, Label, RDFClass, Taxonomy
from ster.viz_vowl import render_vowl_html

NS = "https://example.org/onto#"


def _uri(name: str) -> str:
    return NS + name


def _make_hierarchy() -> Taxonomy:
    """Animal (root) → Dog (1st-order child) → Puppy (2nd-order child)."""
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = RDFClass(uri=_uri("Animal"), labels=[Label("en", "Animal")])
    tax.owl_classes[_uri("Dog")] = RDFClass(
        uri=_uri("Dog"), labels=[Label("en", "Dog")], sub_class_of=[_uri("Animal")]
    )
    tax.owl_classes[_uri("Puppy")] = RDFClass(
        uri=_uri("Puppy"), labels=[Label("en", "Puppy")], sub_class_of=[_uri("Dog")]
    )
    return tax


def _make_skos_only() -> Taxonomy:
    tax = Taxonomy()
    tax.schemes[_uri("Scheme")] = ConceptScheme(uri=_uri("Scheme"), labels=[Label("en", "Scheme")])
    tax.concepts[_uri("Concept")] = Concept(
        uri=_uri("Concept"),
        labels=[Label("en", "Concept")],
        top_concept_of=_uri("Scheme"),
    )
    return tax


# ── button presence ────────────────────────────────────────────────────────────


def test_first_order_btn_present() -> None:
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    assert 'id="ft-first-order"' in html


def test_second_order_btn_present() -> None:
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    assert 'id="ft-second-order"' in html


def test_first_order_btn_present_in_focused_graph() -> None:
    html = render_vowl_html(_make_hierarchy(), file_path=None, root_uri=_uri("Animal"))
    assert 'id="ft-first-order"' in html


def test_second_order_btn_present_in_focused_graph() -> None:
    html = render_vowl_html(_make_hierarchy(), file_path=None, root_uri=_uri("Animal"))
    assert 'id="ft-second-order"' in html


# ── JavaScript functions ───────────────────────────────────────────────────────


def test_toggle_first_order_fn_present() -> None:
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    assert "toggleFirstOrderClasses" in html


def test_toggle_second_order_fn_present() -> None:
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    assert "toggleSecondOrderClasses" in html


# ── auto-hide logic ────────────────────────────────────────────────────────────


def test_first_order_ids_computed_in_js() -> None:
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    assert "firstOrderIds" in html


def test_second_order_ids_computed_in_js() -> None:
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    assert "secondOrderIds" in html


def test_auto_hide_first_order_btn_when_empty() -> None:
    html = render_vowl_html(_make_skos_only(), file_path=None)
    assert "ft-first-order" in html
    assert "firstOrderIds" in html


def test_auto_hide_second_order_btn_when_empty() -> None:
    html = render_vowl_html(_make_skos_only(), file_path=None)
    assert "ft-second-order" in html
    assert "secondOrderIds" in html
