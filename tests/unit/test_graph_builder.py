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


def test_functional_objectproperty_edge_has_cardinality():
    tax = Taxonomy()
    tax.owl_classes[_uri("Dog")] = _cls("Dog")
    tax.owl_classes[_uri("Person")] = _cls("Person")
    tax.owl_properties[_uri("hasMaster")] = OWLProperty(
        uri=_uri("hasMaster"),
        labels=[Label("en", "hasMaster")],
        prop_type="ObjectProperty",
        domains=[_uri("Dog")],
        ranges=[_uri("Person")],
        is_functional=True,
    )
    result = build_vowl_graph(tax)
    found = [e for e in result["edges"] if e["type"] == "objectProperty"][0]
    assert found["cardinality"] == "0..1"


def test_objectproperty_edge_skipped_when_domain_class_undeclared():
    """A property whose domain isn't itself a declared class produces no edge
    (the domain node was never added, so it's not in seen_nodes)."""
    tax = Taxonomy()
    tax.owl_classes[_uri("Person")] = _cls("Person")
    tax.owl_properties[_uri("hasMaster")] = OWLProperty(
        uri=_uri("hasMaster"),
        labels=[Label("en", "hasMaster")],
        prop_type="ObjectProperty",
        domains=[_uri("Dog")],  # never declared as a class
        ranges=[_uri("Person")],
    )
    result = build_vowl_graph(tax)
    assert result["edges"] == []


def test_datatypeproperty_edge_skipped_when_domain_class_undeclared():
    tax = Taxonomy()
    tax.owl_properties[_uri("name")] = OWLProperty(
        uri=_uri("name"),
        labels=[Label("en", "name")],
        prop_type="DatatypeProperty",
        domains=[_uri("Person")],  # never declared as a class
        ranges=["http://www.w3.org/2001/XMLSchema#string"],
    )
    result = build_vowl_graph(tax)
    assert result["nodes"] == []
    assert result["edges"] == []


def test_datatypeproperty_edge_skipped_when_range_already_a_node():
    """When the datatype-range URI coincides with an already-added node, the
    duplicate node/edge is skipped rather than clobbering the existing node."""
    tax = Taxonomy()
    tax.owl_classes[_uri("Person")] = _cls("Person")
    weird_range = _uri("Person")  # coincides with an existing class node's URI
    tax.owl_properties[_uri("selfDescribes")] = OWLProperty(
        uri=_uri("selfDescribes"),
        labels=[Label("en", "selfDescribes")],
        prop_type="DatatypeProperty",
        domains=[_uri("Person")],
        ranges=[weird_range],
    )
    result = build_vowl_graph(tax)
    assert [n for n in result["nodes"] if n["id"] == weird_range] == [
        n for n in result["nodes"] if n["id"] == _uri("Person")
    ]
    assert not any(e["type"] == "datatypeProperty" for e in result["edges"])


def test_individual_builtin_type_is_skipped():
    tax = Taxonomy()
    ind = _ind("Rex")
    ind.types.append(OWL_THING)
    tax.owl_individuals[_uri("Rex")] = ind
    result = build_vowl_graph(tax)
    assert OWL_THING not in _node_ids(result)


def test_individual_type_not_predeclared_class_gets_created_on_the_fly():
    """An individual's rdf:type that has no matching owl:Class entry still
    gets a class node created for it (so the instanceOf edge has an endpoint)."""
    tax = Taxonomy()
    tax.owl_individuals[_uri("Rex")] = _ind("Rex", "Dog")  # "Dog" is never declared as a class
    result = build_vowl_graph(tax)
    assert _uri("Dog") in _node_ids(result)
    assert any(
        e["source"] == _uri("Rex") and e["target"] == _uri("Dog") and e["type"] == "instanceOf"
        for e in result["edges"]
    )


def test_skos_broader_edge_produced():
    from ster.model import Concept

    tax = Taxonomy()
    tax.concepts[_uri("Animal")] = Concept(uri=_uri("Animal"), labels=[Label("en", "Animal")])
    tax.concepts[_uri("Dog")] = Concept(
        uri=_uri("Dog"), labels=[Label("en", "Dog")], broader=[_uri("Animal")]
    )
    result = build_vowl_graph(tax)
    assert any(
        e["source"] == _uri("Dog") and e["target"] == _uri("Animal") and e["type"] == "broader"
        for e in result["edges"]
    )


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


def test_focused_graph_diamond_hierarchy_does_not_duplicate_class():
    """A class reachable through two subclass paths from the root is only
    included once (the BFS closure's own visited/seen dedup)."""
    tax = Taxonomy()
    tax.owl_classes[_uri("Root")] = _cls("Root")
    tax.owl_classes[_uri("Left")] = _cls("Left", sub_class_of=[_uri("Root")])
    tax.owl_classes[_uri("Right")] = _cls("Right", sub_class_of=[_uri("Root")])
    tax.owl_classes[_uri("Diamond")] = _cls("Diamond", sub_class_of=[_uri("Left"), _uri("Right")])
    result = build_focused_vowl_graph(tax, _uri("Root"))
    diamond_nodes = [n for n in result["nodes"] if n["id"] == _uri("Diamond")]
    assert len(diamond_nodes) == 1


def test_focused_graph_includes_object_property_edge_within_scope():
    tax = Taxonomy()
    tax.owl_classes[_uri("Root")] = _cls("Root")
    tax.owl_classes[_uri("Person")] = _cls("Person", sub_class_of=[_uri("Root")])
    tax.owl_classes[_uri("Pet")] = _cls("Pet", sub_class_of=[_uri("Root")])
    tax.owl_properties[_uri("owns")] = OWLProperty(
        uri=_uri("owns"),
        labels=[Label("en", "owns")],
        prop_type="ObjectProperty",
        domains=[_uri("Person")],
        ranges=[_uri("Pet")],
    )
    result = build_focused_vowl_graph(tax, _uri("Root"))
    assert any(
        e["source"] == _uri("Person")
        and e["target"] == _uri("Pet")
        and e["type"] == "objectProperty"
        for e in result["edges"]
    )


def test_focused_graph_excludes_object_property_edge_outside_scope():
    """A property whose domain is outside the focused subtree contributes no edge."""
    tax = Taxonomy()
    tax.owl_classes[_uri("Root")] = _cls("Root")
    tax.owl_classes[_uri("Pet")] = _cls("Pet", sub_class_of=[_uri("Root")])
    tax.owl_classes[_uri("Outsider")] = _cls("Outsider")  # not under Root
    tax.owl_properties[_uri("owns")] = OWLProperty(
        uri=_uri("owns"),
        labels=[Label("en", "owns")],
        prop_type="ObjectProperty",
        domains=[_uri("Outsider")],
        ranges=[_uri("Pet")],
    )
    result = build_focused_vowl_graph(tax, _uri("Root"))
    assert result["edges"] == [] or all(e["type"] != "objectProperty" for e in result["edges"])


def test_focused_graph_includes_datatype_property_node_and_edge():
    tax = Taxonomy()
    tax.owl_classes[_uri("Root")] = _cls("Root")
    tax.owl_classes[_uri("Person")] = _cls("Person", sub_class_of=[_uri("Root")])
    xsd_string = "http://www.w3.org/2001/XMLSchema#string"
    tax.owl_properties[_uri("name")] = OWLProperty(
        uri=_uri("name"),
        labels=[Label("en", "name")],
        prop_type="DatatypeProperty",
        domains=[_uri("Person")],
        ranges=[xsd_string],
    )
    result = build_focused_vowl_graph(tax, _uri("Root"))
    assert xsd_string in _node_ids(result)
    assert any(
        e["source"] == _uri("Person")
        and e["target"] == xsd_string
        and e["type"] == "datatypeProperty"
        for e in result["edges"]
    )


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


def test_query_result_includes_matched_scheme_node():
    from ster.model import ConceptScheme

    tax = Taxonomy()
    tax.schemes[_uri("Scheme")] = ConceptScheme(uri=_uri("Scheme"), labels=[Label("en", "Scheme")])
    result = build_query_result_graph(tax, {_uri("Scheme")})
    node = next(n for n in result["nodes"] if n["id"] == _uri("Scheme"))
    assert node["type"] == "scheme"


def test_query_result_includes_instance_of_edge_when_type_matched():
    tax = Taxonomy()
    tax.owl_classes[_uri("Dog")] = _cls("Dog")
    tax.owl_individuals[_uri("Fido")] = _ind("Fido", "Dog")
    result = build_query_result_graph(tax, {_uri("Dog"), _uri("Fido")})
    assert any(
        e["source"] == _uri("Fido") and e["target"] == _uri("Dog") and e["type"] == "instanceOf"
        for e in result["edges"]
    )


def test_query_result_includes_top_concept_of_edge_when_scheme_matched():
    from ster.model import Concept, ConceptScheme

    tax = Taxonomy()
    tax.schemes[_uri("Scheme")] = ConceptScheme(uri=_uri("Scheme"), top_concepts=[_uri("Root")])
    tax.concepts[_uri("Root")] = Concept(
        uri=_uri("Root"), labels=[Label("en", "Root")], top_concept_of=_uri("Scheme")
    )
    result = build_query_result_graph(tax, {_uri("Scheme"), _uri("Root")})
    assert any(
        e["source"] == _uri("Root") and e["target"] == _uri("Scheme") and e["type"] == "inScheme"
        for e in result["edges"]
    )


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
        e["source"] == _uri("Fido")
        and e["target"] == _uri("Alice")
        and e["type"] == "objectProperty"
        for e in g["edges"]
    )


def test_individual_relations_includes_outgoing_neighbour():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax(), _uri("Alice"))
    assert _uri("Paris") in _node_ids(g)
    assert any(
        e["source"] == _uri("Alice")
        and e["target"] == _uri("Paris")
        and e["type"] == "objectProperty"
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


def test_individual_relations_skips_builtin_rdf_type():
    """A builtin type mixed into an individual's rdf:type list is skipped
    entirely — no node, no instanceOf edge, no crash."""
    from ster.viz_vowl import build_individual_relations_graph

    t = Taxonomy()
    t.owl_classes[_uri("Person")] = _cls("Person")
    alice = _ind("Alice", "Person")
    alice.types.append(OWL_THING)
    t.owl_individuals[_uri("Alice")] = alice

    g = build_individual_relations_graph(t, _uri("Alice"))
    assert OWL_THING not in _node_ids(g)
    assert not any(e["target"] == OWL_THING or e["source"] == OWL_THING for e in g["edges"])


def test_individual_relations_skips_builtin_superclass():
    """A builtin URI in a class's sub_class_of (e.g. owl:Thing declared
    directly) is skipped when walking the superclass trail."""
    from ster.viz_vowl import build_individual_relations_graph

    t = Taxonomy()
    t.owl_classes[_uri("Person")] = _cls("Person", sub_class_of=[OWL_THING])
    t.owl_individuals[_uri("Alice")] = _ind("Alice", "Person")

    g = build_individual_relations_graph(t, _uri("Alice"))
    assert OWL_THING not in _node_ids(g)
    assert not any(e["target"] == OWL_THING or e["source"] == OWL_THING for e in g["edges"])


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
        uri=_uri("owns"),
        prop_type="ObjectProperty",
        labels=[Label("en", "owns")],
        domains=[_uri("Person")],
        ranges=[_uri("Pet")],
    )
    t.owl_properties[_uri("employs")] = OWLProperty(
        uri=_uri("employs"),
        prop_type="ObjectProperty",
        labels=[Label("en", "employs")],
        domains=[_uri("Company")],
        ranges=[_uri("Person")],
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
        e["source"] == _uri("Person")
        and e["target"] == _uri("Pet")
        and e["type"] == "objectProperty"
        and e["label"] == "owns"
        for e in g["edges"]
    )


def test_class_links_includes_object_property_domain_class():
    from ster.viz_vowl import build_class_links_graph

    g = build_class_links_graph(_class_links_tax(), _uri("Person"))
    assert _uri("Company") in _node_ids(g)
    assert any(
        e["source"] == _uri("Company")
        and e["target"] == _uri("Person")
        and e["type"] == "objectProperty"
        and e["label"] == "employs"
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


# ── subclass_only mode (used when exploration started from an individual) ───────


def test_class_links_subclass_only_keeps_superclass_trail():
    from ster.viz_vowl import build_class_links_graph

    g = build_class_links_graph(_class_links_tax(), _uri("Person"), subclass_only=True)
    assert {_uri("Person"), _uri("Agent"), _uri("Thing")} <= _node_ids(g)
    assert any(
        e["source"] == _uri("Person") and e["target"] == _uri("Agent") and e["type"] == "subClassOf"
        for e in g["edges"]
    )


def test_class_links_subclass_only_drops_object_property_links():
    from ster.viz_vowl import build_class_links_graph

    g = build_class_links_graph(_class_links_tax(), _uri("Person"), subclass_only=True)
    # Object-property-linked classes and their edges are omitted.
    assert _uri("Pet") not in _node_ids(g)
    assert _uri("Company") not in _node_ids(g)
    assert all(e["type"] != "objectProperty" for e in g["edges"])


def test_individual_relations_marks_superclass_nodes():
    from ster.viz_vowl import build_individual_relations_graph

    g = build_individual_relations_graph(_rel_tax_with_hierarchy(), _uri("Alice"))
    assert _node_by_id(g, _uri("Agent"))["superclass"] == 1
    assert _node_by_id(g, _uri("Thing"))["superclass"] == 1
    # Direct rdf:type classes and the focus individual are not superclasses
    assert _node_by_id(g, _uri("Person"))["superclass"] == 0
    assert _node_by_id(g, _uri("Alice"))["superclass"] == 0


def test_class_links_includes_superclasses_of_linked_classes():
    """Object-property-linked classes should also carry their superclass trail."""
    from ster.viz_vowl import build_class_links_graph

    t = _class_links_tax()  # Person --owns--> Pet ; Company --employs--> Person
    t.owl_classes[_uri("LivingBeing")] = _cls("LivingBeing")
    t.owl_classes[_uri("Pet")].sub_class_of.append(_uri("LivingBeing"))
    t.owl_classes[_uri("Org")] = _cls("Org")
    t.owl_classes[_uri("Company")].sub_class_of.append(_uri("Org"))
    g = build_class_links_graph(t, _uri("Person"))
    ids = _node_ids(g)
    # Superclass of the range-linked class (Pet ⊑ LivingBeing)
    assert _uri("LivingBeing") in ids
    assert any(
        e["source"] == _uri("Pet")
        and e["target"] == _uri("LivingBeing")
        and e["type"] == "subClassOf"
        for e in g["edges"]
    )
    # Superclass of the domain-linked class (Company ⊑ Org)
    assert _uri("Org") in ids
    assert any(
        e["source"] == _uri("Company") and e["target"] == _uri("Org") and e["type"] == "subClassOf"
        for e in g["edges"]
    )


def test_class_links_marks_linked_class_superclasses_as_superclass():
    from ster.viz_vowl import build_class_links_graph

    t = _class_links_tax()
    t.owl_classes[_uri("LivingBeing")] = _cls("LivingBeing")
    t.owl_classes[_uri("Pet")].sub_class_of.append(_uri("LivingBeing"))
    g = build_class_links_graph(t, _uri("Person"))
    assert _node_by_id(g, _uri("LivingBeing"))["superclass"] == 1
    # The linked class itself stays a direct (non-superclass) node.
    assert _node_by_id(g, _uri("Pet"))["superclass"] == 0


def test_class_links_ignores_non_object_properties():
    """A DatatypeProperty domain/range is not treated as a class link."""
    from ster.model import OWLProperty as _P
    from ster.viz_vowl import build_class_links_graph

    t = _class_links_tax()
    t.owl_properties[_uri("age")] = _P(
        uri=_uri("age"),
        prop_type="DatatypeProperty",
        labels=[Label("en", "age")],
        domains=[_uri("Person")],
        ranges=["http://www.w3.org/2001/XMLSchema#integer"],
    )
    g = build_class_links_graph(t, _uri("Person"))
    assert all(e["label"] != "age" for e in g["edges"])


def test_class_links_skips_builtin_object_property_domain_and_range():
    """A builtin URI (e.g. owl:Thing) as an object property's domain/range is
    never turned into a class-link node or edge."""
    from ster.model import OWLProperty as _P
    from ster.viz_vowl import build_class_links_graph

    t = _class_links_tax()
    t.owl_properties[_uri("relatesToEverything")] = _P(
        uri=_uri("relatesToEverything"),
        prop_type="ObjectProperty",
        labels=[Label("en", "relatesToEverything")],
        domains=[_uri("Person")],
        ranges=[OWL_THING],
    )
    g = build_class_links_graph(t, _uri("Person"))
    assert OWL_THING not in _node_ids(g)


def test_class_links_skips_builtin_superclass():
    from ster.viz_vowl import build_class_links_graph

    t = _class_links_tax()
    t.owl_classes[_uri("Person")].sub_class_of.append(OWL_THING)
    g = build_class_links_graph(t, _uri("Person"))
    assert OWL_THING not in _node_ids(g)


def test_class_links_dedups_class_linked_by_two_properties():
    """The same range class reached via two different object properties is
    added once (add_class's own seen_nodes dedup, not just the caller's)."""
    from ster.model import OWLProperty as _P
    from ster.viz_vowl import build_class_links_graph

    t = _class_links_tax()
    t.owl_properties[_uri("adopts")] = _P(
        uri=_uri("adopts"),
        prop_type="ObjectProperty",
        labels=[Label("en", "adopts")],
        domains=[_uri("Person")],
        ranges=[_uri("Pet")],
    )
    g = build_class_links_graph(t, _uri("Person"))
    pet_nodes = [n for n in g["nodes"] if n["id"] == _uri("Pet")]
    assert len(pet_nodes) == 1


def test_class_links_shared_superclass_via_focus_and_linked_class_dedups():
    """Agent is a superclass of both the focus class (Person) and the
    object-property-linked class (Pet) — it gets pushed onto the walk stack
    twice but processed only once."""
    from ster.viz_vowl import build_class_links_graph

    t = _class_links_tax()
    t.owl_classes[_uri("Pet")].sub_class_of.append(_uri("Agent"))
    g = build_class_links_graph(t, _uri("Person"))
    agent_nodes = [n for n in g["nodes"] if n["id"] == _uri("Agent")]
    assert len(agent_nodes) == 1


def test_focused_graph_excludes_object_property_edge_when_range_not_included():
    """Domain is inside the focused subtree but the range class is outside it
    — no edge is produced (the range never became a seen node)."""
    tax = Taxonomy()
    tax.owl_classes[_uri("Root")] = _cls("Root")
    tax.owl_classes[_uri("Person")] = _cls("Person", sub_class_of=[_uri("Root")])
    tax.owl_classes[_uri("Pet")] = _cls("Pet")  # not under Root
    tax.owl_properties[_uri("owns")] = OWLProperty(
        uri=_uri("owns"),
        labels=[Label("en", "owns")],
        prop_type="ObjectProperty",
        domains=[_uri("Person")],
        ranges=[_uri("Pet")],
    )
    result = build_focused_vowl_graph(tax, _uri("Root"))
    assert all(e["type"] != "objectProperty" for e in result["edges"])


def test_focused_graph_functional_objectproperty_edge_has_cardinality():
    tax = Taxonomy()
    tax.owl_classes[_uri("Root")] = _cls("Root")
    tax.owl_classes[_uri("Person")] = _cls("Person", sub_class_of=[_uri("Root")])
    tax.owl_classes[_uri("Pet")] = _cls("Pet", sub_class_of=[_uri("Root")])
    tax.owl_properties[_uri("owns")] = OWLProperty(
        uri=_uri("owns"),
        labels=[Label("en", "owns")],
        prop_type="ObjectProperty",
        domains=[_uri("Person")],
        ranges=[_uri("Pet")],
        is_functional=True,
    )
    result = build_focused_vowl_graph(tax, _uri("Root"))
    found = [e for e in result["edges"] if e["type"] == "objectProperty"][0]
    assert found["cardinality"] == "0..1"


def test_focused_graph_excludes_datatype_property_when_domain_not_included():
    tax = Taxonomy()
    tax.owl_classes[_uri("Root")] = _cls("Root")
    tax.owl_classes[_uri("Outsider")] = _cls("Outsider")  # not under Root
    tax.owl_properties[_uri("name")] = OWLProperty(
        uri=_uri("name"),
        labels=[Label("en", "name")],
        prop_type="DatatypeProperty",
        domains=[_uri("Outsider")],
        ranges=["http://www.w3.org/2001/XMLSchema#string"],
    )
    result = build_focused_vowl_graph(tax, _uri("Root"))
    assert all(e["type"] != "datatypeProperty" for e in result["edges"])


def test_focused_graph_datatype_property_range_dedup_when_already_seen():
    """A datatype range URI that coincides with an already-included class
    node is skipped rather than duplicated."""
    tax = Taxonomy()
    tax.owl_classes[_uri("Root")] = _cls("Root")
    tax.owl_classes[_uri("Person")] = _cls("Person", sub_class_of=[_uri("Root")])
    weird_range = _uri("Person")
    tax.owl_properties[_uri("selfDescribes")] = OWLProperty(
        uri=_uri("selfDescribes"),
        labels=[Label("en", "selfDescribes")],
        prop_type="DatatypeProperty",
        domains=[_uri("Person")],
        ranges=[weird_range],
    )
    result = build_focused_vowl_graph(tax, _uri("Root"))
    person_nodes = [n for n in result["nodes"] if n["id"] == weird_range]
    assert len(person_nodes) == 1
    assert not any(e["type"] == "datatypeProperty" for e in result["edges"])
