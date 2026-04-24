"""Tests for ster/viz.py — Python helper functions (no browser, no file I/O)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ster.model import (
    Concept,
    ConceptScheme,
    Definition,
    Label,
    LabelType,
    OWLIndividual,
    OWLProperty,
    RDFClass,
    Taxonomy,
)
from ster.viz import (
    _detail_class,
    _detail_concept,
    _detail_individual,
    _detail_scheme,
    _label,
    _label_for,
    _local,
    _ontology_title,
    build_graph,
)

NS = "https://example.org/onto#"


# ── _local ────────────────────────────────────────────────────────────────────


def test_local_hash():
    assert _local("https://example.org/onto#Foo") == "Foo"


def test_local_slash():
    assert _local("https://example.org/onto/Bar") == "Bar"


def test_local_no_sep():
    assert _local("urn:simple") == "urn:simple"


def test_local_multiple_hash():
    # rsplit from right — returns last fragment
    assert _local("https://example.org#a#b") == "b"


# ── _label ────────────────────────────────────────────────────────────────────


def test_label_short():
    assert _label("Hello") == "Hello"


def test_label_exact_max():
    text = "A" * 18
    assert _label(text) == text


def test_label_truncated():
    text = "A" * 19
    result = _label(text)
    assert result.endswith("…")
    assert len(result) == 18


def test_label_custom_max():
    assert _label("Hello World", max_len=5) == "Hell…"


# ── _ontology_title ───────────────────────────────────────────────────────────


def test_ontology_title_label():
    tax = Taxonomy(ontology_label="My Ontology", ontology_uri="https://example.org/onto")
    assert _ontology_title(tax, None) == "My Ontology"


def test_ontology_title_uri_hash():
    tax = Taxonomy(ontology_uri="https://example.org/onto#MyOntology")
    assert _ontology_title(tax, None) == "MyOntology"


def test_ontology_title_uri_slash():
    tax = Taxonomy(ontology_uri="https://example.org/onto/")
    assert _ontology_title(tax, None) == "onto"


def test_ontology_title_uri_no_separator():
    tax = Taxonomy(ontology_uri="urn:myontology")
    assert _ontology_title(tax, None) == "urn:myontology"


def test_ontology_title_file_path():
    tax = Taxonomy()
    assert _ontology_title(tax, Path("/data/my-schema.ttl")) == "my-schema"


def test_ontology_title_fallback():
    tax = Taxonomy()
    assert _ontology_title(tax, None) == "Ontology"


# ── _label_for ────────────────────────────────────────────────────────────────


def _make_taxonomy() -> Taxonomy:
    tax = Taxonomy()
    tax.concepts[NS + "Cat"] = Concept(
        uri=NS + "Cat",
        labels=[Label(lang="en", value="Cat", type=LabelType.PREF)],
    )
    tax.owl_classes[NS + "Animal"] = RDFClass(
        uri=NS + "Animal",
        labels=[Label(lang="en", value="Animal")],
    )
    tax.owl_individuals[NS + "Fido"] = OWLIndividual(
        uri=NS + "Fido",
        labels=[Label(lang="en", value="Fido")],
    )
    tax.owl_properties[NS + "hasName"] = OWLProperty(
        uri=NS + "hasName",
        labels=[Label(lang="en", value="has name")],
    )
    return tax


def test_label_for_concept():
    tax = _make_taxonomy()
    assert _label_for(NS + "Cat", tax) == "Cat"


def test_label_for_class():
    tax = _make_taxonomy()
    assert _label_for(NS + "Animal", tax) == "Animal"


def test_label_for_individual():
    tax = _make_taxonomy()
    assert _label_for(NS + "Fido", tax) == "Fido"


def test_label_for_property():
    tax = _make_taxonomy()
    assert _label_for(NS + "hasName", tax) == "has name"


def test_label_for_unknown():
    tax = _make_taxonomy()
    assert _label_for(NS + "Unknown", tax) == "Unknown"


# ── _detail_concept ───────────────────────────────────────────────────────────


def test_detail_concept_empty():
    tax = Taxonomy()
    concept = Concept(uri=NS + "Foo")
    detail = _detail_concept(concept, tax)
    assert detail["labels"] == []
    assert detail["description"] == ""
    assert detail["scopeNote"] == ""
    assert detail["relations"] == []


def test_detail_concept_labels_and_description():
    tax = Taxonomy()
    concept = Concept(
        uri=NS + "Foo",
        labels=[
            Label(lang="en", value="Foo", type=LabelType.PREF),
            Label(lang="en", value="Foo alt", type=LabelType.ALT),
        ],
        definitions=[Definition(lang="en", value="A foo thing")],
        scope_notes=[Definition(lang="en", value="Used for testing")],
    )
    detail = _detail_concept(concept, tax)
    assert len(detail["labels"]) == 2
    assert detail["labels"][0] == {"lang": "en", "kind": "pref", "value": "Foo"}
    assert detail["labels"][1] == {"lang": "en", "kind": "alt", "value": "Foo alt"}
    assert detail["description"] == "A foo thing"
    assert detail["scopeNote"] == "Used for testing"


def test_detail_concept_broader_relation():
    tax = _make_taxonomy()
    concept = Concept(uri=NS + "Cat", broader=[NS + "Animal"])
    tax.concepts[NS + "Cat"] = concept
    detail = _detail_concept(concept, tax)
    broader = [r for r in detail["relations"] if r["rel"] == "broader"]
    assert len(broader) == 1
    assert broader[0]["uri"] == NS + "Animal"
    assert broader[0]["label"] == "Animal"


def test_detail_concept_exact_match():
    tax = _make_taxonomy()
    concept = Concept(uri=NS + "Cat", exact_match=[NS + "Animal"])
    detail = _detail_concept(concept, tax)
    exact = [r for r in detail["relations"] if r["rel"] == "exactMatch"]
    assert len(exact) == 1
    assert exact[0]["uri"] == NS + "Animal"


def test_detail_concept_narrower_relation():
    tax = _make_taxonomy()
    concept = Concept(uri=NS + "Animal", narrower=[NS + "Cat"])
    detail = _detail_concept(concept, tax)
    narrower = [r for r in detail["relations"] if r["rel"] == "narrower"]
    assert len(narrower) == 1
    assert narrower[0]["uri"] == NS + "Cat"
    assert narrower[0]["label"] == "Cat"


def test_detail_concept_close_match():
    tax = _make_taxonomy()
    concept = Concept(uri=NS + "Cat", close_match=[NS + "Animal"])
    detail = _detail_concept(concept, tax)
    close = [r for r in detail["relations"] if r["rel"] == "closeMatch"]
    assert len(close) == 1


def test_detail_concept_broad_match():
    tax = _make_taxonomy()
    concept = Concept(uri=NS + "Cat", broad_match=[NS + "Animal"])
    detail = _detail_concept(concept, tax)
    broad = [r for r in detail["relations"] if r["rel"] == "broadMatch"]
    assert len(broad) == 1


def test_detail_concept_narrow_match():
    tax = _make_taxonomy()
    concept = Concept(uri=NS + "Animal", narrow_match=[NS + "Cat"])
    detail = _detail_concept(concept, tax)
    narrow = [r for r in detail["relations"] if r["rel"] == "narrowMatch"]
    assert len(narrow) == 1


def test_detail_concept_related_match():
    tax = _make_taxonomy()
    concept = Concept(uri=NS + "Cat", related_match=[NS + "Animal"])
    detail = _detail_concept(concept, tax)
    related = [r for r in detail["relations"] if r["rel"] == "relatedMatch"]
    assert len(related) == 1


# ── _detail_class ─────────────────────────────────────────────────────────────


def test_detail_class_empty():
    tax = Taxonomy()
    cls = RDFClass(uri=NS + "Thing")
    detail = _detail_class(cls, tax)
    assert detail["labels"] == []
    assert detail["description"] == ""
    assert detail["relations"] == []


def test_detail_class_comment_and_subclass():
    tax = _make_taxonomy()
    cls = RDFClass(
        uri=NS + "Cat",
        labels=[Label(lang="en", value="Cat")],
        comments=[Definition(lang="en", value="A cat class")],
        sub_class_of=[NS + "Animal"],
    )
    detail = _detail_class(cls, tax)
    assert detail["description"] == "A cat class"
    sub = [r for r in detail["relations"] if r["rel"] == "subClassOf"]
    assert len(sub) == 1
    assert sub[0]["uri"] == NS + "Animal"
    assert sub[0]["label"] == "Animal"


def test_detail_class_builtin_filtered():
    tax = Taxonomy()
    cls = RDFClass(
        uri=NS + "Thing",
        sub_class_of=["http://www.w3.org/2002/07/owl#Thing"],
    )
    detail = _detail_class(cls, tax)
    assert detail["relations"] == []


def test_detail_class_labels():
    tax = Taxonomy()
    cls = RDFClass(
        uri=NS + "Cat",
        labels=[Label(lang="en", value="Cat"), Label(lang="fr", value="Chat")],
    )
    detail = _detail_class(cls, tax)
    assert len(detail["labels"]) == 2
    assert all(lbl["kind"] == "label" for lbl in detail["labels"])


# ── _detail_individual ────────────────────────────────────────────────────────


def test_detail_individual_empty():
    tax = Taxonomy()
    ind = OWLIndividual(uri=NS + "Fido")
    detail = _detail_individual(ind, tax)
    assert detail["labels"] == []
    assert detail["description"] == ""
    assert detail["relations"] == []


def test_detail_individual_type_relation():
    tax = _make_taxonomy()
    ind = OWLIndividual(
        uri=NS + "Fido",
        labels=[Label(lang="en", value="Fido")],
        comments=[Definition(lang="en", value="A dog named Fido")],
        types=[NS + "Animal"],
    )
    detail = _detail_individual(ind, tax)
    assert detail["description"] == "A dog named Fido"
    types = [r for r in detail["relations"] if r["rel"] == "type"]
    assert len(types) == 1
    assert types[0]["label"] == "Animal"


def test_detail_individual_property_values():
    tax = _make_taxonomy()
    ind = OWLIndividual(
        uri=NS + "Fido",
        property_values=[(NS + "hasName", NS + "Fido")],
    )
    detail = _detail_individual(ind, tax)
    prop_rels = [r for r in detail["relations"] if r["rel"] == "has name"]
    assert len(prop_rels) == 1


# ── _detail_scheme ────────────────────────────────────────────────────────────


def test_detail_scheme_empty():
    tax = Taxonomy()
    scheme = ConceptScheme(uri=NS + "TestScheme")
    detail = _detail_scheme(scheme, tax)
    assert detail["labels"] == []
    assert detail["description"] == ""
    assert detail["relations"] == []


def test_detail_scheme_with_label_and_description():
    tax = Taxonomy()
    scheme = ConceptScheme(
        uri=NS + "TestScheme",
        labels=[Label(lang="en", value="Test Scheme", type=LabelType.PREF)],
        descriptions=[Definition(lang="en", value="A test scheme")],
    )
    detail = _detail_scheme(scheme, tax)
    assert detail["labels"][0] == {"lang": "en", "kind": "pref", "value": "Test Scheme"}
    assert detail["description"] == "A test scheme"


# ── build_graph ───────────────────────────────────────────────────────────────


def test_build_graph_empty():
    tax = Taxonomy()
    result = build_graph(tax)
    assert result["nodes"] == []
    assert result["links"] == []


def test_build_graph_class_node():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(
        uri=NS + "Animal",
        labels=[Label(lang="en", value="Animal")],
    )
    result = build_graph(tax)
    nodes = result["nodes"]
    assert len(nodes) == 1
    assert nodes[0]["id"] == NS + "Animal"
    assert nodes[0]["type"] == "class"
    assert nodes[0]["label"] == "Animal"


def test_build_graph_subclass_link():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    tax.owl_classes[NS + "Cat"] = RDFClass(
        uri=NS + "Cat",
        sub_class_of=[NS + "Animal"],
    )
    result = build_graph(tax)
    links = [lnk for lnk in result["links"] if lnk["type"] == "subClassOf"]
    assert len(links) == 1
    assert links[0]["source"] == NS + "Cat"
    assert links[0]["target"] == NS + "Animal"


def test_build_graph_individual_node():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    tax.owl_individuals[NS + "Fido"] = OWLIndividual(
        uri=NS + "Fido",
        types=[NS + "Animal"],
    )
    result = build_graph(tax)
    ind_nodes = [n for n in result["nodes"] if n["type"] == "individual"]
    assert len(ind_nodes) == 1
    links = [lnk for lnk in result["links"] if lnk["type"] == "instanceOf"]
    assert len(links) == 1


def test_build_graph_no_duplicate_nodes():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    result = build_graph(tax)
    ids = [n["id"] for n in result["nodes"]]
    assert len(ids) == len(set(ids))


def test_build_graph_concept_node():
    tax = Taxonomy()
    scheme_uri = NS + "Scheme"
    tax.schemes[scheme_uri] = ConceptScheme(uri=scheme_uri)
    concept_uri = NS + "Cat"
    tax.concepts[concept_uri] = Concept(
        uri=concept_uri,
        labels=[Label(lang="en", value="Cat", type=LabelType.PREF)],
        top_concept_of=scheme_uri,
    )
    result = build_graph(tax)
    concept_nodes = [n for n in result["nodes"] if n["type"] == "topconcept"]
    assert len(concept_nodes) == 1
    assert concept_nodes[0]["label"] == "Cat"


def test_build_graph_equivalent_class_no_duplicates():
    tax = Taxonomy()
    tax.owl_classes[NS + "A"] = RDFClass(uri=NS + "A", equivalent_class=[NS + "B"])
    tax.owl_classes[NS + "B"] = RDFClass(uri=NS + "B", equivalent_class=[NS + "A"])
    result = build_graph(tax)
    equiv_links = [lnk for lnk in result["links"] if lnk["type"] == "equivalentClass"]
    assert len(equiv_links) == 1


def test_build_graph_label_truncated():
    tax = Taxonomy()
    long_name = "A" * 30
    tax.owl_classes[NS + long_name] = RDFClass(
        uri=NS + long_name,
        labels=[Label(lang="en", value=long_name)],
    )
    result = build_graph(tax)
    assert len(result["nodes"][0]["label"]) == 18
    assert result["nodes"][0]["fullLabel"] == long_name


@pytest.mark.parametrize(
    "uri,expected",
    [
        ("https://example.org/onto#Foo", "Foo"),
        ("https://example.org/onto/Bar", "Bar"),
        ("urn:simple", "urn:simple"),
    ],
)
def test_local_parametrized(uri: str, expected: str) -> None:
    assert _local(uri) == expected


# ── build_graph — additional link types ───────────────────────────────────────


def test_build_graph_disjoint_with_link():
    tax = Taxonomy()
    tax.owl_classes[NS + "A"] = RDFClass(uri=NS + "A", disjoint_with=[NS + "B"])
    tax.owl_classes[NS + "B"] = RDFClass(uri=NS + "B")
    result = build_graph(tax)
    disj = [lnk for lnk in result["links"] if lnk["type"] == "disjointWith"]
    assert len(disj) == 1
    assert disj[0]["source"] == NS + "A"
    assert disj[0]["target"] == NS + "B"


def test_build_graph_disjoint_no_duplicates():
    tax = Taxonomy()
    tax.owl_classes[NS + "A"] = RDFClass(uri=NS + "A", disjoint_with=[NS + "B"])
    tax.owl_classes[NS + "B"] = RDFClass(uri=NS + "B", disjoint_with=[NS + "A"])
    result = build_graph(tax)
    disj = [lnk for lnk in result["links"] if lnk["type"] == "disjointWith"]
    assert len(disj) == 1


def test_build_graph_skos_broader_link():
    tax = Taxonomy()
    scheme_uri = NS + "Scheme"
    tax.schemes[scheme_uri] = ConceptScheme(uri=scheme_uri)
    tax.concepts[NS + "Animal"] = Concept(uri=NS + "Animal")
    tax.concepts[NS + "Dog"] = Concept(uri=NS + "Dog", broader=[NS + "Animal"])
    result = build_graph(tax)
    broader = [lnk for lnk in result["links"] if lnk["type"] == "broader"]
    assert len(broader) == 1
    assert broader[0]["source"] == NS + "Dog"
    assert broader[0]["target"] == NS + "Animal"


def test_build_graph_skos_related_link():
    tax = Taxonomy()
    tax.schemes[NS + "S"] = ConceptScheme(uri=NS + "S")
    tax.concepts[NS + "A"] = Concept(uri=NS + "A", related=[NS + "B"])
    tax.concepts[NS + "B"] = Concept(uri=NS + "B", related=[NS + "A"])
    result = build_graph(tax)
    related = [lnk for lnk in result["links"] if lnk["type"] == "related"]
    assert len(related) == 1


def test_build_graph_in_scheme_link():
    tax = Taxonomy()
    scheme_uri = NS + "Scheme"
    tax.schemes[scheme_uri] = ConceptScheme(uri=scheme_uri)
    tax.concepts[NS + "Cat"] = Concept(
        uri=NS + "Cat",
        top_concept_of=scheme_uri,
    )
    result = build_graph(tax)
    in_scheme = [lnk for lnk in result["links"] if lnk["type"] == "inScheme"]
    assert len(in_scheme) == 1
    assert in_scheme[0]["source"] == NS + "Cat"
    assert in_scheme[0]["target"] == scheme_uri


def test_build_graph_property_assertion_link():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    tax.owl_individuals[NS + "Fido"] = OWLIndividual(
        uri=NS + "Fido",
        property_values=[(NS + "hasOwner", NS + "Alice")],
    )
    tax.owl_individuals[NS + "Alice"] = OWLIndividual(uri=NS + "Alice")
    result = build_graph(tax)
    prop_links = [lnk for lnk in result["links"] if lnk["type"] == "property"]
    assert len(prop_links) == 1
    assert prop_links[0]["source"] == NS + "Fido"
    assert prop_links[0]["target"] == NS + "Alice"


def test_build_graph_property_assertion_label_from_property():
    tax = Taxonomy()
    tax.owl_individuals[NS + "Fido"] = OWLIndividual(
        uri=NS + "Fido",
        property_values=[(NS + "hasOwner", NS + "Alice")],
    )
    tax.owl_individuals[NS + "Alice"] = OWLIndividual(uri=NS + "Alice")
    tax.owl_properties[NS + "hasOwner"] = OWLProperty(
        uri=NS + "hasOwner",
        labels=[Label(lang="en", value="has owner")],
    )
    result = build_graph(tax)
    prop_links = [lnk for lnk in result["links"] if lnk["type"] == "property"]
    assert prop_links[0]["label"] == "has owner"


def test_build_graph_property_assertion_label_fallback():
    tax = Taxonomy()
    tax.owl_individuals[NS + "Fido"] = OWLIndividual(
        uri=NS + "Fido",
        property_values=[(NS + "hasOwner", NS + "Alice")],
    )
    tax.owl_individuals[NS + "Alice"] = OWLIndividual(uri=NS + "Alice")
    # No property in taxonomy — fallback to local name
    result = build_graph(tax)
    prop_links = [lnk for lnk in result["links"] if lnk["type"] == "property"]
    assert prop_links[0]["label"] == "hasOwner"


# ── build_graph — tier assignment ─────────────────────────────────────────────


def test_build_graph_class_root_tier():
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    result = build_graph(tax)
    node = next(n for n in result["nodes"] if n["id"] == NS + "Animal")
    assert node["tier"] == 0


def test_build_graph_class_with_children_tier():
    # Animal has children (Dog subclasses it) → tier=1 (parent)
    # Dog is a leaf → tier=0
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    tax.owl_classes[NS + "Dog"] = RDFClass(uri=NS + "Dog", sub_class_of=[NS + "Animal"])
    result = build_graph(tax)
    animal = next(n for n in result["nodes"] if n["id"] == NS + "Animal")
    dog = next(n for n in result["nodes"] if n["id"] == NS + "Dog")
    assert animal["tier"] == 1  # is a parent (has subclasses)
    assert dog["tier"] == 0  # is a leaf (no subclasses)


def test_build_graph_individual_tier():
    tax = Taxonomy()
    tax.owl_individuals[NS + "Fido"] = OWLIndividual(uri=NS + "Fido")
    result = build_graph(tax)
    node = next(n for n in result["nodes"] if n["id"] == NS + "Fido")
    assert node["tier"] == 2


def test_build_graph_scheme_tier():
    tax = Taxonomy()
    tax.schemes[NS + "S"] = ConceptScheme(uri=NS + "S")
    result = build_graph(tax)
    node = next(n for n in result["nodes"] if n["id"] == NS + "S")
    assert node["tier"] == 0


def test_build_graph_concept_tier():
    tax = Taxonomy()
    tax.schemes[NS + "S"] = ConceptScheme(uri=NS + "S")
    tax.concepts[NS + "Cat"] = Concept(uri=NS + "Cat")
    result = build_graph(tax)
    cat = next(n for n in result["nodes"] if n["id"] == NS + "Cat")
    assert cat["tier"] == 2


def test_build_graph_topconcept_tier():
    tax = Taxonomy()
    scheme_uri = NS + "S"
    tax.schemes[scheme_uri] = ConceptScheme(uri=scheme_uri)
    tax.concepts[NS + "Cat"] = Concept(uri=NS + "Cat", top_concept_of=scheme_uri)
    result = build_graph(tax)
    cat = next(n for n in result["nodes"] if n["id"] == NS + "Cat")
    assert cat["tier"] == 1


# ── build_graph — builtin URIs filtered ───────────────────────────────────────


def test_build_graph_builtin_subclass_not_linked():
    tax = Taxonomy()
    tax.owl_classes[NS + "Thing"] = RDFClass(
        uri=NS + "Thing",
        sub_class_of=["http://www.w3.org/2002/07/owl#Thing"],
    )
    result = build_graph(tax)
    assert result["links"] == []


def test_build_graph_detail_has_images_field():
    tax = Taxonomy()
    tax.owl_classes[NS + "Dog"] = RDFClass(
        uri=NS + "Dog",
        schema_images=["https://example.org/dog.jpg"],
    )
    result = build_graph(tax)
    node = result["nodes"][0]
    assert node["img"] == "https://example.org/dog.jpg"
    assert node["detail"]["images"] == ["https://example.org/dog.jpg"]
