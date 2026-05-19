"""Unit tests for build_focused_vowl_graph() in ster/viz_vowl.py."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.viz_vowl import build_focused_vowl_graph

NS = "https://example.org/onto#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def _uri(name: str) -> str:
    return NS + name


def _base_taxonomy() -> Taxonomy:
    """Animal → Dog, Cat (siblings); Fido: Dog; Simba: Animal; Bird + Tweety unrelated."""
    t = Taxonomy()
    t.owl_classes[_uri("Animal")] = RDFClass(uri=_uri("Animal"), labels=[Label("en", "Animal")])
    t.owl_classes[_uri("Dog")] = RDFClass(
        uri=_uri("Dog"), labels=[Label("en", "Dog")], sub_class_of=[_uri("Animal")]
    )
    t.owl_classes[_uri("Cat")] = RDFClass(
        uri=_uri("Cat"), labels=[Label("en", "Cat")], sub_class_of=[_uri("Animal")]
    )
    t.owl_individuals[_uri("Fido")] = OWLIndividual(uri=_uri("Fido"), types=[_uri("Dog")])
    t.owl_individuals[_uri("Simba")] = OWLIndividual(uri=_uri("Simba"), types=[_uri("Animal")])
    t.owl_classes[_uri("Bird")] = RDFClass(uri=_uri("Bird"), labels=[Label("en", "Bird")])
    t.owl_individuals[_uri("Tweety")] = OWLIndividual(uri=_uri("Tweety"), types=[_uri("Bird")])
    return t


def _node_ids(result: dict) -> set[str]:
    return {n["id"] for n in result["nodes"]}


def _link_types(result: dict) -> list[str]:
    return [lnk["type"] for lnk in result["links"]]


# ── Inclusion ─────────────────────────────────────────────────────────────────


def test_focused_root_node_present():
    result = build_focused_vowl_graph(_base_taxonomy(), _uri("Animal"))
    assert _uri("Animal") in _node_ids(result)


def test_focused_direct_subclass_present():
    result = build_focused_vowl_graph(_base_taxonomy(), _uri("Animal"))
    assert _uri("Dog") in _node_ids(result)


def test_focused_transitive_subclass_present():
    t = _base_taxonomy()
    t.owl_classes[_uri("Puppy")] = RDFClass(uri=_uri("Puppy"), sub_class_of=[_uri("Dog")])
    result = build_focused_vowl_graph(t, _uri("Animal"))
    assert _uri("Puppy") in _node_ids(result)


def test_focused_individual_of_root_present():
    result = build_focused_vowl_graph(_base_taxonomy(), _uri("Animal"))
    assert _uri("Simba") in _node_ids(result)


def test_focused_individual_of_subclass_present():
    result = build_focused_vowl_graph(_base_taxonomy(), _uri("Animal"))
    assert _uri("Fido") in _node_ids(result)


# ── Exclusion ─────────────────────────────────────────────────────────────────


def test_focused_sibling_excluded():
    result = build_focused_vowl_graph(_base_taxonomy(), _uri("Dog"))
    assert _uri("Cat") not in _node_ids(result)


def test_focused_unrelated_class_excluded():
    result = build_focused_vowl_graph(_base_taxonomy(), _uri("Animal"))
    assert _uri("Bird") not in _node_ids(result)


def test_focused_individual_of_unrelated_excluded():
    result = build_focused_vowl_graph(_base_taxonomy(), _uri("Animal"))
    assert _uri("Tweety") not in _node_ids(result)


# ── Empty / edge cases ────────────────────────────────────────────────────────


def test_focused_empty_class_no_crash():
    t = Taxonomy()
    t.owl_classes[_uri("Leaf")] = RDFClass(uri=_uri("Leaf"))
    result = build_focused_vowl_graph(t, _uri("Leaf"))
    assert _uri("Leaf") in _node_ids(result)
    assert result["links"] == []


def test_focused_unknown_root_returns_empty():
    result = build_focused_vowl_graph(_base_taxonomy(), _uri("DoesNotExist"))
    assert result["nodes"] == []
    assert result["links"] == []


# ── Links ────────────────────────────────────────────────────────────────────


def test_focused_subClassOf_links_present():
    result = build_focused_vowl_graph(_base_taxonomy(), _uri("Animal"))
    links = [lnk for lnk in result["links"] if lnk["type"] == "subClassOf"]
    sources = {lnk["source"] for lnk in links}
    assert _uri("Dog") in sources


def test_focused_instanceOf_links_present():
    result = build_focused_vowl_graph(_base_taxonomy(), _uri("Animal"))
    links = [lnk for lnk in result["links"] if lnk["type"] == "instanceOf"]
    assert len(links) >= 1


def test_focused_object_property_edge_between_included_classes():
    t = _base_taxonomy()
    t.owl_properties[_uri("hasPet")] = OWLProperty(
        uri=_uri("hasPet"),
        prop_type="ObjectProperty",
        labels=[Label("en", "has pet")],
        domains=[_uri("Animal")],
        ranges=[_uri("Dog")],
    )
    result = build_focused_vowl_graph(t, _uri("Animal"))
    op = [lnk for lnk in result["links"] if lnk["type"] == "objectProperty"]
    assert len(op) == 1
    assert op[0]["label"] == "has pet"


def test_focused_object_property_outside_subgraph_excluded():
    t = _base_taxonomy()
    t.owl_properties[_uri("related")] = OWLProperty(
        uri=_uri("related"),
        prop_type="ObjectProperty",
        domains=[_uri("Animal")],
        ranges=[_uri("Bird")],  # Bird is outside the focused subgraph
    )
    result = build_focused_vowl_graph(t, _uri("Animal"))
    op = [lnk for lnk in result["links"] if lnk["type"] == "objectProperty"]
    assert op == []


def test_focused_datatype_property_included():
    t = _base_taxonomy()
    t.owl_properties[_uri("hasAge")] = OWLProperty(
        uri=_uri("hasAge"),
        prop_type="DatatypeProperty",
        labels=[Label("en", "has age")],
        domains=[_uri("Animal")],
        ranges=[XSD + "integer"],
    )
    result = build_focused_vowl_graph(t, _uri("Animal"))
    dp = [lnk for lnk in result["links"] if lnk["type"] == "datatypeProperty"]
    assert len(dp) == 1
    dt_nodes = [n for n in result["nodes"] if n["type"] == "datatype"]
    assert len(dt_nodes) == 1


# ── Layout ────────────────────────────────────────────────────────────────────


def test_focused_layout_is_hierarchical():
    result = build_focused_vowl_graph(_base_taxonomy(), _uri("Animal"))
    assert result["layout"] == "hierarchical"
