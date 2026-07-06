"""Unit tests for ster.nav.logic.suggested_properties — the applicable-property
list (direct + inherited) that seeds the add-individual modal."""

from __future__ import annotations

from ster.model import Label, OWLProperty, RDFClass, Taxonomy
from ster.nav.logic import SuggestedProperty, suggested_properties

ANIMAL = "http://ex/Animal"
MAMMAL = "http://ex/Mammal"
DOG = "http://ex/Dog"
PERSON = "http://ex/Person"


def _tax() -> Taxonomy:
    tax = Taxonomy()
    tax.owl_classes[ANIMAL] = RDFClass(uri=ANIMAL)
    tax.owl_classes[MAMMAL] = RDFClass(uri=MAMMAL, sub_class_of=[ANIMAL])
    tax.owl_classes[DOG] = RDFClass(uri=DOG, sub_class_of=[MAMMAL])
    tax.owl_classes[PERSON] = RDFClass(uri=PERSON)
    # object property on the ancestor Animal → inherited by Dog
    tax.owl_properties["http://ex/hasOwner"] = OWLProperty(
        uri="http://ex/hasOwner",
        prop_type="ObjectProperty",
        labels=[Label(lang="en", value="has owner")],
        domains=[ANIMAL],
        ranges=[PERSON],
    )
    # datatype property directly on Dog
    tax.owl_properties["http://ex/breed"] = OWLProperty(
        uri="http://ex/breed",
        prop_type="DatatypeProperty",
        labels=[Label(lang="en", value="breed")],
        domains=[DOG],
        ranges=["http://www.w3.org/2001/XMLSchema#string"],
    )
    # unrelated property (domain Person) → must NOT be suggested for Dog
    tax.owl_properties["http://ex/email"] = OWLProperty(
        uri="http://ex/email", prop_type="DatatypeProperty", domains=[PERSON]
    )
    return tax


def test_includes_direct_property_marked_not_inherited():
    props = suggested_properties(_tax(), DOG, "en")
    breed = next(p for p in props if p.prop_uri == "http://ex/breed")
    assert breed.inherited_from is None
    assert breed.kind == "datatype"
    assert breed.range_uri == "http://www.w3.org/2001/XMLSchema#string"
    assert breed.label == "breed"


def test_includes_inherited_property_tagged_with_source_class():
    props = suggested_properties(_tax(), DOG, "en")
    owner = next(p for p in props if p.prop_uri == "http://ex/hasOwner")
    assert owner.inherited_from == ANIMAL
    assert owner.kind == "object"
    assert owner.range_uri == PERSON


def test_excludes_properties_of_unrelated_classes():
    uris = {p.prop_uri for p in suggested_properties(_tax(), DOG, "en")}
    assert "http://ex/email" not in uris


def test_returns_suggested_property_instances():
    props = suggested_properties(_tax(), DOG, "en")
    assert props and all(isinstance(p, SuggestedProperty) for p in props)


def test_unknown_class_yields_no_suggestions():
    assert suggested_properties(_tax(), "http://ex/Nope", "en") == []
