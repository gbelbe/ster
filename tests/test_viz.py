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
    assert detail["comments"] == [{"lang": "en", "value": "A cat class"}]
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
    assert detail["comments"] == [{"lang": "en", "value": "A dog named Fido"}]
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


# ── _local parametrized ───────────────────────────────────────────────────────


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
