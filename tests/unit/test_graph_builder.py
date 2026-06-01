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


# ── build_individual_relations_graph ───────────────────────────────────────────


def _rel_tax():
    """Alice (Person) ← owns ← Fido (Dog); Alice → livesIn → Paris (City).

    Bob (Person) is unrelated to Alice.
    """
    from ster.model import OWLProperty as _P

    t = Taxonomy()
    for c in ("Person", "Dog", "City"):
        t.owl_classes[_uri(c)] = _cls(c)
    t.owl_properties[_uri("owns")] = _P(uri=_uri("owns"), labels=[Label("en", "owns")])
    t.owl_properties[_uri("livesIn")] = _P(uri=_uri("livesIn"), labels=[Label("en", "livesIn")])
    t.owl_individuals[_uri("Alice")] = _ind("Alice", "Person")
    t.owl_individuals[_uri("Fido")] = _ind("Fido", "Dog")
    t.owl_individuals[_uri("Paris")] = _ind("Paris", "City")
    t.owl_individuals[_uri("Bob")] = _ind("Bob", "Person")
    # Fido owns Alice (incoming to Alice); Alice livesIn Paris (outgoing from Alice)
    t.owl_individuals[_uri("Fido")].property_values.append((_uri("owns"), _uri("Alice")))
    t.owl_individuals[_uri("Alice")].property_values.append((_uri("livesIn"), _uri("Paris")))
    return t


def test_individual_relations_includes_focus():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax(), _uri("Alice"))
    assert _uri("Alice") in _node_ids(g)


def test_individual_relations_includes_incoming_neighbour():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax(), _uri("Alice"))
    assert _uri("Fido") in _node_ids(g)
    assert any(
        e["source"] == _uri("Fido") and e["target"] == _uri("Alice") and e["type"] == "objectProperty"
        for e in g["edges"]
    )


def test_individual_relations_includes_outgoing_neighbour():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax(), _uri("Alice"))
    assert _uri("Paris") in _node_ids(g)
    assert any(
        e["source"] == _uri("Alice") and e["target"] == _uri("Paris") and e["type"] == "objectProperty"
        for e in g["edges"]
    )


def test_individual_relations_object_property_edge_carries_label():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax(), _uri("Alice"))
    incoming = next(
        e for e in g["edges"] if e["source"] == _uri("Fido") and e["target"] == _uri("Alice")
    )
    assert incoming["label"] == "owns"


def test_individual_relations_includes_focus_classes():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax(), _uri("Alice"))
    assert _uri("Person") in _node_ids(g)
    assert any(
        e["source"] == _uri("Alice") and e["target"] == _uri("Person") and e["type"] == "instanceOf"
        for e in g["edges"]
    )


def test_individual_relations_includes_related_individual_classes():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax(), _uri("Alice"))
    # Dog (Fido's class) and City (Paris's class) must appear
    assert _uri("Dog") in _node_ids(g)
    assert _uri("City") in _node_ids(g)


def test_individual_relations_excludes_unrelated_individual():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax(), _uri("Alice"))
    assert _uri("Bob") not in _node_ids(g)


def test_individual_relations_ignores_literal_values():
    from ster.viz_vowl import build_individual_relations_graph

    t = _rel_tax()
    t.owl_individuals[_uri("Alice")].literal_values.append((_uri("age"), "30", ""))
    g = build_individual_relations_graph(t, _uri("Alice"))
    assert _uri("age") not in _node_ids(g)
    assert "datatypeProperty" not in _edge_types(g)


def test_individual_relations_missing_uri_returns_empty():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax(), _uri("Ghost"))
    assert g["nodes"] == []
    assert g["edges"] == []


def test_individual_relations_layout_is_cose():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax(), _uri("Alice"))
    assert g["layout"] == "cose"


# ── build_individual_relations_graph: superclass trail ─────────────────────────


def _rel_tax_with_hierarchy():
    """Alice:Person ⊑ Agent ⊑ Thing; Fido:Dog ⊑ Animal ⊑ Thing; Fido owns Alice."""
    t = Taxonomy()
    t.owl_classes[_uri("Thing")] = _cls("Thing")
    t.owl_classes[_uri("Agent")] = _cls("Agent", sub_class_of=[_uri("Thing")])
    t.owl_classes[_uri("Animal")] = _cls("Animal", sub_class_of=[_uri("Thing")])
    t.owl_classes[_uri("Person")] = _cls("Person", sub_class_of=[_uri("Agent")])
    t.owl_classes[_uri("Dog")] = _cls("Dog", sub_class_of=[_uri("Animal")])
    t.owl_properties[_uri("owns")] = OWLProperty(uri=_uri("owns"), labels=[Label("en", "owns")])
    t.owl_individuals[_uri("Alice")] = _ind("Alice", "Person")
    t.owl_individuals[_uri("Fido")] = _ind("Fido", "Dog")
    t.owl_individuals[_uri("Fido")].property_values.append((_uri("owns"), _uri("Alice")))
    return t


def test_individual_relations_includes_direct_superclass_of_focus_class():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax_with_hierarchy(), _uri("Alice"))
    assert _uri("Agent") in _node_ids(g)


def test_individual_relations_includes_transitive_superclasses():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax_with_hierarchy(), _uri("Alice"))
    # Person ⊑ Agent ⊑ Thing — the whole trail above Alice's class
    assert {_uri("Person"), _uri("Agent"), _uri("Thing")} <= _node_ids(g)


def test_individual_relations_superclass_edge_is_subclassof_type():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax_with_hierarchy(), _uri("Alice"))
    assert any(
        e["source"] == _uri("Person") and e["target"] == _uri("Agent") and e["type"] == "subClassOf"
        for e in g["edges"]
    )
    assert any(
        e["source"] == _uri("Agent") and e["target"] == _uri("Thing") and e["type"] == "subClassOf"
        for e in g["edges"]
    )


def test_individual_relations_includes_superclasses_of_related_individual_classes():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax_with_hierarchy(), _uri("Alice"))
    # Fido (related) is a Dog ⊑ Animal ⊑ Thing
    assert {_uri("Dog"), _uri("Animal")} <= _node_ids(g)


def test_individual_relations_shared_ancestor_not_duplicated():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax_with_hierarchy(), _uri("Alice"))
    thing_nodes = [n for n in g["nodes"] if n["id"] == _uri("Thing")]
    assert len(thing_nodes) == 1


def test_individual_relations_subclass_cycle_terminates():
    from ster.viz_vowl import build_individual_relations_graph

    t = Taxonomy()
    # A ⊑ B ⊑ A (pathological cycle) — must not loop forever
    t.owl_classes[_uri("A")] = _cls("A", sub_class_of=[_uri("B")])
    t.owl_classes[_uri("B")] = _cls("B", sub_class_of=[_uri("A")])
    t.owl_individuals[_uri("X")] = _ind("X", "A")
    g = build_individual_relations_graph(t, _uri("X"))
    assert {_uri("A"), _uri("B")} <= _node_ids(g)


# ── build_class_links_graph ────────────────────────────────────────────────────


def _node_by_id(result, uri):
    return next(n for n in result["nodes"] if n["id"] == uri)


def _class_links_tax():
    """Person ⊑ Agent ⊑ Thing; Person --owns--> Pet; Company --employs--> Person."""
    t = Taxonomy()
    t.owl_classes[_uri("Thing")] = _cls("Thing")
    t.owl_classes[_uri("Agent")] = _cls("Agent", sub_class_of=[_uri("Thing")])
    t.owl_classes[_uri("Person")] = _cls("Person", sub_class_of=[_uri("Agent")])
    t.owl_classes[_uri("Pet")] = _cls("Pet")
    t.owl_classes[_uri("Company")] = _cls("Company")
    t.owl_classes[_uri("Unrelated")] = _cls("Unrelated")
    t.owl_properties[_uri("owns")] = OWLProperty(
        uri=_uri("owns"), prop_type="ObjectProperty", labels=[Label("en", "owns")],
        domains=[_uri("Person")], ranges=[_uri("Pet")],
    )
    t.owl_properties[_uri("employs")] = OWLProperty(
        uri=_uri("employs"), prop_type="ObjectProperty", labels=[Label("en", "employs")],
        domains=[_uri("Company")], ranges=[_uri("Person")],
    )
    return t


def test_class_links_includes_focus_class():
    from ster.viz_vowl import build_class_links_graph

    g = build_class_links_graph(_class_links_tax(), _uri("Person"))
    assert _uri("Person") in _node_ids(g)


def test_class_links_includes_superclasses_with_edges():
    from ster.viz_vowl import build_class_links_graph

    g = build_class_links_graph(_class_links_tax(), _uri("Person"))
    assert {_uri("Agent"), _uri("Thing")} <= _node_ids(g)
    assert any(
        e["source"] == _uri("Person") and e["target"] == _uri("Agent") and e["type"] == "subClassOf"
        for e in g["edges"]
    )


def test_class_links_includes_object_property_range_class():
    from ster.viz_vowl import build_class_links_graph

    g = build_class_links_graph(_class_links_tax(), _uri("Person"))
    assert _uri("Pet") in _node_ids(g)
    assert any(
        e["source"] == _uri("Person") and e["target"] == _uri("Pet")
        and e["type"] == "objectProperty" and e["label"] == "owns"
        for e in g["edges"]
    )


def test_class_links_includes_object_property_domain_class():
    from ster.viz_vowl import build_class_links_graph

    g = build_class_links_graph(_class_links_tax(), _uri("Person"))
    assert _uri("Company") in _node_ids(g)
    assert any(
        e["source"] == _uri("Company") and e["target"] == _uri("Person")
        and e["type"] == "objectProperty" and e["label"] == "employs"
        for e in g["edges"]
    )


def test_class_links_excludes_unrelated_class():
    from ster.viz_vowl import build_class_links_graph

    g = build_class_links_graph(_class_links_tax(), _uri("Person"))
    assert _uri("Unrelated") not in _node_ids(g)


def test_class_links_missing_uri_returns_empty():
    from ster.viz_vowl import build_class_links_graph

    g = build_class_links_graph(_class_links_tax(), _uri("Ghost"))
    assert g["nodes"] == []
    assert g["edges"] == []


def test_class_links_layout_is_cose():
    from ster.viz_vowl import build_class_links_graph

    assert build_class_links_graph(_class_links_tax(), _uri("Person"))["layout"] == "cose"


def test_class_links_marks_superclass_nodes():
    from ster.viz_vowl import build_class_links_graph

    g = build_class_links_graph(_class_links_tax(), _uri("Person"))
    assert _node_by_id(g, _uri("Agent"))["superclass"] == 1
    assert _node_by_id(g, _uri("Thing"))["superclass"] == 1
    assert _node_by_id(g, _uri("Person"))["superclass"] == 0
    assert _node_by_id(g, _uri("Pet"))["superclass"] == 0


def test_individual_relations_marks_superclass_nodes():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax_with_hierarchy(), _uri("Alice"))
    assert _node_by_id(g, _uri("Agent"))["superclass"] == 1
    assert _node_by_id(g, _uri("Thing"))["superclass"] == 1
    # Direct rdf:type classes and the focus individual are not superclasses
    assert _node_by_id(g, _uri("Person"))["superclass"] == 0
    assert _node_by_id(g, _uri("Alice"))["superclass"] == 0
