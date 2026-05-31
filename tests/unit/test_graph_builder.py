"""Unit tests for build_vowl_graph / build_focused_vowl_graph / build_query_result_graph
in Cytoscape.js format: {nodes, edges, layout}."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.viz_vowl import build_focused_vowl_graph, build_query_result_graph, build_vowl_graph

NS = "https://example.org/onto#"
OWL_THING = "http://www.w3.org/2002/07/owl#Thing"


def _uri(name: str) -> str:
    return NS + name


def _cls(name: str, **kwargs) -> RDFClass:
    return RDFClass(uri=_uri(name), labels=[Label("en", name)], **kwargs)


def _ind(name: str, *types: str) -> OWLIndividual:
    return OWLIndividual(uri=_uri(name), labels=[Label("en", name)], types=[_uri(t) for t in types])


def _node_ids(result: dict) -> set[str]:
    return {n["id"] for n in result["nodes"]}


def _edge_types(result: dict) -> list[str]:
    return [e["type"] for e in result["edges"]]


# ── empty ─────────────────────────────────────────────────────────────────────


def test_empty_graph_has_no_nodes():
    assert build_vowl_graph(Taxonomy())["nodes"] == []


def test_empty_graph_has_no_edges():
    assert build_vowl_graph(Taxonomy())["edges"] == []


def test_empty_graph_uses_cose_layout():
    assert build_vowl_graph(Taxonomy())["layout"] == "cose"


# ── node types ────────────────────────────────────────────────────────────────


def test_class_node_has_correct_type():
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = _cls("Animal")
    nodes = build_vowl_graph(tax)["nodes"]
    n = next(n for n in nodes if n["id"] == _uri("Animal"))
    assert n["type"] == "class"


def test_individual_node_has_correct_type():
    tax = Taxonomy()
    tax.owl_classes[_uri("Dog")] = _cls("Dog")
    tax.owl_individuals[_uri("Rex")] = _ind("Rex", "Dog")
    nodes = build_vowl_graph(tax)["nodes"]
    n = next(n for n in nodes if n["id"] == _uri("Rex"))
    assert n["type"] == "individual"


def test_class_node_carries_label():
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = _cls("Animal")
    nodes = build_vowl_graph(tax)["nodes"]
    n = next(n for n in nodes if n["id"] == _uri("Animal"))
    assert n["label"] == "Animal"


# ── edges ─────────────────────────────────────────────────────────────────────


def test_subclassof_edge_produced():
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = _cls("Animal")
    tax.owl_classes[_uri("Dog")] = _cls("Dog", sub_class_of=[_uri("Animal")])
    result = build_vowl_graph(tax)
    found = [e for e in result["edges"] if e["type"] == "subClassOf"]
    assert any(e["source"] == _uri("Dog") and e["target"] == _uri("Animal") for e in found)


def test_instanceof_edge_produced():
    tax = Taxonomy()
    tax.owl_classes[_uri("Dog")] = _cls("Dog")
    tax.owl_individuals[_uri("Rex")] = _ind("Rex", "Dog")
    result = build_vowl_graph(tax)
    found = [e for e in result["edges"] if e["type"] == "instanceOf"]
    assert any(e["source"] == _uri("Rex") and e["target"] == _uri("Dog") for e in found)


def test_objectproperty_edge_produced_with_label():
    tax = Taxonomy()
    tax.owl_classes[_uri("Dog")] = _cls("Dog")
    tax.owl_classes[_uri("Person")] = _cls("Person")
    tax.owl_properties[_uri("hasMaster")] = OWLProperty(
        uri=_uri("hasMaster"),
        labels=[Label("en", "hasMaster")],
        prop_type="ObjectProperty",
        domains=[_uri("Dog")],
        ranges=[_uri("Person")],
    )
    result = build_vowl_graph(tax)
    found = [e for e in result["edges"] if e["type"] == "objectProperty"]
    assert len(found) == 1
    assert found[0]["label"] == "hasMaster"
    assert found[0]["source"] == _uri("Dog")
    assert found[0]["target"] == _uri("Person")


def test_datatypeproperty_edge_produced():
    tax = Taxonomy()
    tax.owl_classes[_uri("Person")] = _cls("Person")
    xsd_string = "http://www.w3.org/2001/XMLSchema#string"
    tax.owl_properties[_uri("name")] = OWLProperty(
        uri=_uri("name"),
        labels=[Label("en", "name")],
        prop_type="DatatypeProperty",
        domains=[_uri("Person")],
        ranges=[xsd_string],
    )
    result = build_vowl_graph(tax)
    found = [e for e in result["edges"] if e["type"] == "datatypeProperty"]
    assert any(e["source"] == _uri("Person") for e in found)


def test_builtin_subclassof_excluded():
    tax = Taxonomy()
    tax.owl_classes[_uri("Dog")] = _cls("Dog", sub_class_of=[OWL_THING])
    result = build_vowl_graph(tax)
    assert not any(e["target"] == OWL_THING for e in result["edges"])


def test_edges_have_id_field():
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = _cls("Animal")
    tax.owl_classes[_uri("Dog")] = _cls("Dog", sub_class_of=[_uri("Animal")])
    result = build_vowl_graph(tax)
    for e in result["edges"]:
        assert "id" in e and e["id"]


# ── layout ────────────────────────────────────────────────────────────────────


def test_owl_only_taxonomy_uses_cose_layout():
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = _cls("Animal")
    assert build_vowl_graph(tax)["layout"] == "cose"


def test_skos_taxonomy_uses_cose_layout():
    from ster.model import Concept, ConceptScheme

    tax = Taxonomy()
    tax.schemes["https://ex.org/s"] = ConceptScheme(uri="https://ex.org/s")
    tax.concepts["https://ex.org/a"] = Concept(uri="https://ex.org/a")
    assert build_vowl_graph(tax)["layout"] == "cose"


# ── focused graph ─────────────────────────────────────────────────────────────


def test_focused_graph_includes_root():
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = _cls("Animal")
    tax.owl_classes[_uri("Dog")] = _cls("Dog", sub_class_of=[_uri("Animal")])
    tax.owl_classes[_uri("Bird")] = _cls("Bird")
    result = build_focused_vowl_graph(tax, _uri("Animal"))
    assert _uri("Animal") in _node_ids(result)


def test_focused_graph_includes_direct_subclass():
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = _cls("Animal")
    tax.owl_classes[_uri("Dog")] = _cls("Dog", sub_class_of=[_uri("Animal")])
    result = build_focused_vowl_graph(tax, _uri("Animal"))
    assert _uri("Dog") in _node_ids(result)


def test_focused_graph_includes_transitive_subclass():
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = _cls("Animal")
    tax.owl_classes[_uri("Dog")] = _cls("Dog", sub_class_of=[_uri("Animal")])
    tax.owl_classes[_uri("Puppy")] = _cls("Puppy", sub_class_of=[_uri("Dog")])
    result = build_focused_vowl_graph(tax, _uri("Animal"))
    assert _uri("Puppy") in _node_ids(result)


def test_focused_graph_excludes_sibling():
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = _cls("Animal")
    tax.owl_classes[_uri("Dog")] = _cls("Dog", sub_class_of=[_uri("Animal")])
    tax.owl_classes[_uri("Cat")] = _cls("Cat", sub_class_of=[_uri("Animal")])
    result = build_focused_vowl_graph(tax, _uri("Dog"))
    assert _uri("Cat") not in _node_ids(result)


def test_focused_graph_excludes_unrelated_root():
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = _cls("Animal")
    tax.owl_classes[_uri("Dog")] = _cls("Dog", sub_class_of=[_uri("Animal")])
    tax.owl_classes[_uri("Bird")] = _cls("Bird")
    result = build_focused_vowl_graph(tax, _uri("Animal"))
    assert _uri("Bird") not in _node_ids(result)


def test_focused_graph_includes_individual_of_included_class():
    tax = Taxonomy()
    tax.owl_classes[_uri("Dog")] = _cls("Dog")
    tax.owl_individuals[_uri("Rex")] = _ind("Rex", "Dog")
    result = build_focused_vowl_graph(tax, _uri("Dog"))
    assert _uri("Rex") in _node_ids(result)


def test_focused_graph_uses_cose_layout():
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = _cls("Animal")
    result = build_focused_vowl_graph(tax, _uri("Animal"))
    assert result["layout"] == "cose"


# ── query result graph ────────────────────────────────────────────────────────


def test_query_result_matched_uri_present():
    tax = Taxonomy()
    tax.owl_classes[_uri("Dog")] = _cls("Dog")
    tax.owl_classes[_uri("Cat")] = _cls("Cat")
    result = build_query_result_graph(tax, {_uri("Dog")})
    assert _uri("Dog") in _node_ids(result)


def test_query_result_unmatched_uri_absent():
    tax = Taxonomy()
    tax.owl_classes[_uri("Dog")] = _cls("Dog")
    tax.owl_classes[_uri("Cat")] = _cls("Cat")
    result = build_query_result_graph(tax, {_uri("Dog")})
    assert _uri("Cat") not in _node_ids(result)


def test_query_result_uses_cose_layout():
    tax = Taxonomy()
    tax.owl_classes[_uri("Dog")] = _cls("Dog")
    result = build_query_result_graph(tax, {_uri("Dog")})
    assert result["layout"] == "cose"
