"""Unit tests for ster/viz_vowl.py — build_vowl_graph() data builder."""

from __future__ import annotations

from ster.model import (
    Concept,
    ConceptScheme,
    Label,
    OWLIndividual,
    OWLProperty,
    RDFClass,
    Taxonomy,
)
from ster.viz_vowl import build_vowl_graph

NS = "https://example.org/onto#"


# ── empty ─────────────────────────────────────────────────────────────────────


def test_build_vowl_graph_empty():
    tax = Taxonomy()
    result = build_vowl_graph(tax)
    assert result["nodes"] == []
    assert result["links"] == []
    assert result["layout"] == "force"


# ── class nodes ───────────────────────────────────────────────────────────────


def test_build_vowl_graph_class_node():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(
        uri=NS + "Animal", labels=[Label(lang="en", value="Animal")]
    )
    result = build_vowl_graph(tax)
    assert len(result["nodes"]) == 1
    n = result["nodes"][0]
    assert n["type"] == "class"
    assert n["label"] == "Animal"
    assert n["id"] == NS + "Animal"


def test_build_vowl_graph_label_passed_through_full():
    # Python no longer pre-truncates; the JS renderLabel handles wrapping/clipping.
    tax = Taxonomy()
    long_name = "A" * 25
    tax.owl_classes[NS + long_name] = RDFClass(
        uri=NS + long_name, labels=[Label(lang="en", value=long_name)]
    )
    result = build_vowl_graph(tax)
    assert result["nodes"][0]["label"] == long_name
    assert result["nodes"][0]["fullLabel"] == long_name


def test_build_vowl_graph_no_duplicate_nodes():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    result = build_vowl_graph(tax)
    ids = [n["id"] for n in result["nodes"]]
    assert len(ids) == len(set(ids))


# ── individual nodes ──────────────────────────────────────────────────────────


def test_build_vowl_graph_individual_node():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    tax.owl_individuals[NS + "Fido"] = OWLIndividual(uri=NS + "Fido", types=[NS + "Animal"])
    result = build_vowl_graph(tax)
    ind_nodes = [n for n in result["nodes"] if n["type"] == "individual"]
    assert len(ind_nodes) == 1
    assert ind_nodes[0]["id"] == NS + "Fido"


# ── subClassOf links ──────────────────────────────────────────────────────────


def test_build_vowl_graph_subclass_link():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    tax.owl_classes[NS + "Dog"] = RDFClass(uri=NS + "Dog", sub_class_of=[NS + "Animal"])
    result = build_vowl_graph(tax)
    links = [lnk for lnk in result["links"] if lnk["type"] == "subClassOf"]
    assert len(links) == 1
    assert links[0]["source"] == NS + "Dog"
    assert links[0]["target"] == NS + "Animal"


def test_build_vowl_graph_builtin_subclass_skipped():
    tax = Taxonomy()
    tax.owl_classes[NS + "Thing"] = RDFClass(
        uri=NS + "Thing", sub_class_of=["http://www.w3.org/2002/07/owl#Thing"]
    )
    result = build_vowl_graph(tax)
    assert result["links"] == []


# ── object property edges ─────────────────────────────────────────────────────


def test_build_vowl_graph_object_property_edge():
    tax = Taxonomy()
    tax.owl_classes[NS + "Person"] = RDFClass(uri=NS + "Person")
    tax.owl_classes[NS + "Document"] = RDFClass(uri=NS + "Document")
    tax.owl_properties[NS + "hasDoc"] = OWLProperty(
        uri=NS + "hasDoc",
        prop_type="ObjectProperty",
        labels=[Label(lang="en", value="has document")],
        domains=[NS + "Person"],
        ranges=[NS + "Document"],
    )
    result = build_vowl_graph(tax)
    op = [lnk for lnk in result["links"] if lnk["type"] == "objectProperty"]
    assert len(op) == 1
    assert op[0]["source"] == NS + "Person"
    assert op[0]["target"] == NS + "Document"
    assert op[0]["label"] == "has document"


def test_build_vowl_graph_datatype_property_skipped():
    tax = Taxonomy()
    tax.owl_classes[NS + "Person"] = RDFClass(uri=NS + "Person")
    tax.owl_classes[NS + "Lit"] = RDFClass(uri=NS + "Lit")
    tax.owl_properties[NS + "hasAge"] = OWLProperty(
        uri=NS + "hasAge",
        prop_type="DatatypeProperty",
        domains=[NS + "Person"],
        ranges=[NS + "Lit"],
    )
    result = build_vowl_graph(tax)
    op = [lnk for lnk in result["links"] if lnk["type"] == "objectProperty"]
    assert op == []


def test_build_vowl_graph_object_property_skips_unknown_endpoint():
    tax = Taxonomy()
    tax.owl_classes[NS + "Person"] = RDFClass(uri=NS + "Person")
    tax.owl_properties[NS + "hasDoc"] = OWLProperty(
        uri=NS + "hasDoc",
        prop_type="ObjectProperty",
        domains=[NS + "Person"],
        ranges=[NS + "MissingClass"],
    )
    result = build_vowl_graph(tax)
    op = [lnk for lnk in result["links"] if lnk["type"] == "objectProperty"]
    assert op == []


# ── instanceOf links ──────────────────────────────────────────────────────────


def test_build_vowl_graph_instance_of_link():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    tax.owl_individuals[NS + "Fido"] = OWLIndividual(uri=NS + "Fido", types=[NS + "Animal"])
    result = build_vowl_graph(tax)
    links = [lnk for lnk in result["links"] if lnk["type"] == "instanceOf"]
    assert len(links) == 1
    assert links[0]["source"] == NS + "Fido"
    assert links[0]["target"] == NS + "Animal"


# ── SKOS nodes & links ────────────────────────────────────────────────────────


def test_build_vowl_graph_skos_top_concept():
    tax = Taxonomy()
    scheme_uri = NS + "Scheme"
    tax.schemes[scheme_uri] = ConceptScheme(uri=scheme_uri)
    tax.concepts[NS + "Cat"] = Concept(uri=NS + "Cat", top_concept_of=scheme_uri)
    result = build_vowl_graph(tax)
    top = [n for n in result["nodes"] if n["type"] == "topconcept"]
    assert len(top) == 1


def test_build_vowl_graph_skos_broader_link():
    tax = Taxonomy()
    tax.concepts[NS + "Animal"] = Concept(uri=NS + "Animal")
    tax.concepts[NS + "Dog"] = Concept(uri=NS + "Dog", broader=[NS + "Animal"])
    result = build_vowl_graph(tax)
    links = [lnk for lnk in result["links"] if lnk["type"] == "broader"]
    assert len(links) == 1


# ── datatype property nodes & edges ──────────────────────────────────────────

XSD = "http://www.w3.org/2001/XMLSchema#"


def test_build_vowl_graph_datatype_node_created():
    tax = Taxonomy()
    tax.owl_classes[NS + "Person"] = RDFClass(uri=NS + "Person")
    tax.owl_properties[NS + "hasAge"] = OWLProperty(
        uri=NS + "hasAge",
        prop_type="DatatypeProperty",
        domains=[NS + "Person"],
        ranges=[XSD + "integer"],
    )
    result = build_vowl_graph(tax)
    dt = [n for n in result["nodes"] if n["type"] == "datatype"]
    assert len(dt) == 1
    assert dt[0]["id"] == XSD + "integer"


def test_build_vowl_graph_datatype_link_created():
    tax = Taxonomy()
    tax.owl_classes[NS + "Person"] = RDFClass(uri=NS + "Person")
    tax.owl_properties[NS + "hasAge"] = OWLProperty(
        uri=NS + "hasAge",
        prop_type="DatatypeProperty",
        domains=[NS + "Person"],
        ranges=[XSD + "integer"],
    )
    result = build_vowl_graph(tax)
    dp = [lnk for lnk in result["links"] if lnk["type"] == "datatypeProperty"]
    assert len(dp) == 1
    assert dp[0]["source"] == NS + "Person"
    assert dp[0]["target"] == XSD + "integer"


def test_build_vowl_graph_datatype_link_label():
    tax = Taxonomy()
    tax.owl_classes[NS + "Person"] = RDFClass(uri=NS + "Person")
    tax.owl_properties[NS + "hasAge"] = OWLProperty(
        uri=NS + "hasAge",
        prop_type="DatatypeProperty",
        labels=[Label(lang="en", value="has age")],
        domains=[NS + "Person"],
        ranges=[XSD + "integer"],
    )
    result = build_vowl_graph(tax)
    dp = [lnk for lnk in result["links"] if lnk["type"] == "datatypeProperty"]
    assert dp[0]["label"] == "has age"


def test_build_vowl_graph_datatype_skips_unknown_domain():
    tax = Taxonomy()
    tax.owl_properties[NS + "hasAge"] = OWLProperty(
        uri=NS + "hasAge",
        prop_type="DatatypeProperty",
        domains=[NS + "MissingClass"],
        ranges=[XSD + "integer"],
    )
    result = build_vowl_graph(tax)
    assert [n for n in result["nodes"] if n["type"] == "datatype"] == []
    assert [lnk for lnk in result["links"] if lnk["type"] == "datatypeProperty"] == []


def test_build_vowl_graph_datatype_no_duplicate_nodes():
    tax = Taxonomy()
    tax.owl_classes[NS + "Person"] = RDFClass(uri=NS + "Person")
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    tax.owl_properties[NS + "hasName"] = OWLProperty(
        uri=NS + "hasName",
        prop_type="DatatypeProperty",
        domains=[NS + "Person"],
        ranges=[XSD + "string"],
    )
    tax.owl_properties[NS + "animalName"] = OWLProperty(
        uri=NS + "animalName",
        prop_type="DatatypeProperty",
        domains=[NS + "Animal"],
        ranges=[XSD + "string"],
    )
    result = build_vowl_graph(tax)
    dt = [n for n in result["nodes"] if n["type"] == "datatype"]
    assert len(dt) == 1


# ── functional property cardinality ───────────────────────────────────────────


def test_build_vowl_graph_functional_object_property_cardinality():
    tax = Taxonomy()
    tax.owl_classes[NS + "Person"] = RDFClass(uri=NS + "Person")
    tax.owl_classes[NS + "Document"] = RDFClass(uri=NS + "Document")
    tax.owl_properties[NS + "hasDoc"] = OWLProperty(
        uri=NS + "hasDoc",
        prop_type="ObjectProperty",
        is_functional=True,
        domains=[NS + "Person"],
        ranges=[NS + "Document"],
    )
    result = build_vowl_graph(tax)
    op = [lnk for lnk in result["links"] if lnk["type"] == "objectProperty"]
    assert op[0].get("cardinality") == "0..1"


def test_build_vowl_graph_non_functional_no_cardinality():
    tax = Taxonomy()
    tax.owl_classes[NS + "Person"] = RDFClass(uri=NS + "Person")
    tax.owl_classes[NS + "Document"] = RDFClass(uri=NS + "Document")
    tax.owl_properties[NS + "hasDoc"] = OWLProperty(
        uri=NS + "hasDoc",
        prop_type="ObjectProperty",
        is_functional=False,
        domains=[NS + "Person"],
        ranges=[NS + "Document"],
    )
    result = build_vowl_graph(tax)
    op = [lnk for lnk in result["links"] if lnk["type"] == "objectProperty"]
    assert "cardinality" not in op[0]


# ── layout key ────────────────────────────────────────────────────────────────


def test_build_vowl_graph_layout_owl_only():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    result = build_vowl_graph(tax)
    assert result["layout"] == "hierarchical"


def test_build_vowl_graph_layout_skos_is_force():
    tax = Taxonomy()
    tax.schemes[NS + "S"] = ConceptScheme(uri=NS + "S")
    tax.concepts[NS + "Cat"] = Concept(uri=NS + "Cat")
    result = build_vowl_graph(tax)
    assert result["layout"] == "force"


def test_build_vowl_graph_layout_mixed_is_force():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    tax.schemes[NS + "S"] = ConceptScheme(uri=NS + "S")
    result = build_vowl_graph(tax)
    assert result["layout"] == "force"


# ── render_vowl_html ──────────────────────────────────────────────────────────

from ster.viz_vowl import render_vowl_html  # noqa: E402


def _make_render_taxonomy() -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = "https://example.org/onto"
    for name in ("Animal", "Dog", "Cat"):
        t.owl_classes[NS + name] = RDFClass(uri=NS + name, labels=[Label(lang="en", value=name)])
    t.owl_classes[NS + "Dog"].sub_class_of = [NS + "Animal"]
    t.owl_classes[NS + "Cat"].sub_class_of = [NS + "Animal"]
    t.owl_individuals[NS + "Fido"] = OWLIndividual(uri=NS + "Fido", types=[NS + "Dog"])
    return t


def test_render_vowl_html_injects_api_token():
    html = render_vowl_html(_make_render_taxonomy(), None, api_token="secret-token")
    assert 'const tok="secret-token"' in html


def test_render_vowl_html_empty_token_sse_exits_early():
    html = render_vowl_html(_make_render_taxonomy(), None, api_token="")
    assert 'const tok=""' in html
    assert "if(!tok) return;" in html


def test_render_vowl_html_with_root_uri_changes_title():
    html = render_vowl_html(_make_render_taxonomy(), None, root_uri=NS + "Animal")
    assert "Animal" in html


def test_render_vowl_html_with_root_uri_excludes_unrelated_classes():
    t = _make_render_taxonomy()
    t.owl_classes[NS + "Unrelated"] = RDFClass(
        uri=NS + "Unrelated", labels=[Label(lang="en", value="Unrelated")]
    )
    html = render_vowl_html(t, None, root_uri=NS + "Dog")
    assert NS + "Unrelated" not in html


def test_render_vowl_html_without_root_uri_includes_all_classes():
    t = _make_render_taxonomy()
    html = render_vowl_html(t, None)
    for name in ("Animal", "Dog", "Cat"):
        assert NS + name in html
