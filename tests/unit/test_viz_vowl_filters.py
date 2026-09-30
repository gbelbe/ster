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


# ── blunt toolbar switches: hide edges / individuals / datatypes ──────────────
# Unlike the per-type filters above (rdf:type, superclasses, inScheme,
# datatype, in the legacy #ft-legacy bar the JS never shows), these three
# live in the main hint bar and each clears one whole category of clutter
# regardless of how its elements arrived on screen.


def test_hide_edges_btn_and_fn_present() -> None:
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    assert 'id="ft-hide-edges"' in html
    assert "function toggleAllEdges(){" in html


def test_hide_individuals_btn_and_fn_present() -> None:
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    assert 'id="ft-hide-individuals"' in html
    assert "function toggleIndividualNodes(){" in html


def test_hide_individuals_reads_every_individual_on_screen_not_a_load_time_map() -> None:
    """toggleAllIndividuals (the legacy, never-shown button) only knows about
    classIndMap, built once at load — normally empty, since individuals
    usually arrive later through "show individuals". toggleIndividualNodes
    must instead select by type at click time, so it also catches individuals
    added afterwards by toggleClassIndividuals."""
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    assert "cy.nodes('[type=\"individual\"]')" in html.replace(" ", "")


def test_hide_datatypes_btn_and_fn_present() -> None:
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    assert 'id="ft-hide-datatypes"' in html
    assert "function toggleDatatypeNodes(){" in html


def test_hide_datatypes_btn_hides_itself_when_there_are_no_datatype_nodes() -> None:
    """Datatype value nodes, unlike individuals, are present from the initial
    render if they exist at all — so, like the per-type edge filters, the
    button can safely be hidden at wiring time when there is nothing to hide."""
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    js = html.replace(" ", "")
    assert (
        "if(cy.nodes('[type=\"datatype\"]').length===0){btn.style.display='none';return;}".replace(
            " ", ""
        )
        in js
    )


def test_hide_datatypes_wiring_is_its_own_function() -> None:
    """Split out of initSterRelationsGraph, the same reason
    wireEdgeTypeFilters is: an unrelated branch inline in that function's body
    is what pushed its cognitive complexity over the ratchet."""
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    js = html.replace(" ", "")
    assert "functionwireHideDatatypesBtn(){" in js
    assert "wireHideDatatypesBtn();" in js


def test_hiding_edges_and_datatypes_do_not_fight_each_other() -> None:
    """Turning one blunt switch back off must only restore what no other
    active filter — the other blunt switch, or a per-type filter — still
    wants hidden, the same way the per-class individual toggles already
    check before un-hiding a shared edge."""
    html = render_vowl_html(_make_hierarchy(), file_path=None)
    js = html.replace(" ", "")
    assert "!(datatypeNodesHidden&&e.data('type')==='datatypeProperty')" in js
    assert "!allEdgesHidden&&!hiddenEdgeTypes.has('datatypeProperty')" in js
    assert "!allEdgesHidden&&!hiddenEdgeTypes.has('instanceOf')" in js
