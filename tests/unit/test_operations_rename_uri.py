"""Unit tests for rename_owl_uri() and count_owl_uri_references()."""

from __future__ import annotations

import pytest

from ster.exceptions import URIAlreadyExistsError
from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.operations import count_owl_uri_references, rename_owl_uri

NS = "https://example.org/onto#"


def uri(name: str) -> str:
    return NS + name


def _cls(name: str, *parents: str) -> RDFClass:
    return RDFClass(
        uri=uri(name),
        labels=[Label("en", name)],
        sub_class_of=[uri(p) for p in parents],
    )


def _ind(name: str, *types: str) -> OWLIndividual:
    return OWLIndividual(
        uri=uri(name),
        labels=[Label("en", name)],
        types=[uri(t) for t in types],
    )


def _prop(
    name: str, domains: list[str] | None = None, ranges: list[str] | None = None
) -> OWLProperty:
    return OWLProperty(
        uri=uri(name),
        labels=[Label("en", name)],
        domains=[uri(d) for d in (domains or [])],
        ranges=[uri(r) for r in (ranges or [])],
    )


# ── rename class ──────────────────────────────────────────────────────────────


def test_rename_class_renames_key_and_uri():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    rename_owl_uri(t, uri("Dog"), uri("Canine"))
    assert uri("Canine") in t.owl_classes
    assert uri("Dog") not in t.owl_classes
    assert t.owl_classes[uri("Canine")].uri == uri("Canine")


def test_rename_class_updates_subclass_of_references():
    t = Taxonomy()
    t.owl_classes[uri("Animal")] = _cls("Animal")
    t.owl_classes[uri("Dog")] = _cls("Dog", "Animal")
    rename_owl_uri(t, uri("Animal"), uri("LivingThing"))
    assert uri("LivingThing") in t.owl_classes[uri("Dog")].sub_class_of
    assert uri("Animal") not in t.owl_classes[uri("Dog")].sub_class_of


def test_rename_class_updates_equivalent_and_disjoint():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    t.owl_classes[uri("Cat")] = _cls("Cat")
    t.owl_classes[uri("Dog")].equivalent_class.append(uri("Cat"))
    t.owl_classes[uri("Dog")].disjoint_with.append(uri("Cat"))
    rename_owl_uri(t, uri("Cat"), uri("Feline"))
    assert uri("Feline") in t.owl_classes[uri("Dog")].equivalent_class
    assert uri("Cat") not in t.owl_classes[uri("Dog")].equivalent_class
    assert uri("Feline") in t.owl_classes[uri("Dog")].disjoint_with
    assert uri("Cat") not in t.owl_classes[uri("Dog")].disjoint_with


def test_rename_class_updates_individual_types():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    t.owl_individuals[uri("Rex")] = _ind("Rex", "Dog")
    rename_owl_uri(t, uri("Dog"), uri("Canine"))
    assert uri("Canine") in t.owl_individuals[uri("Rex")].types
    assert uri("Dog") not in t.owl_individuals[uri("Rex")].types


def test_rename_class_updates_property_domains_and_ranges():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    t.owl_properties[uri("hasMaster")] = _prop("hasMaster", domains=["Dog"], ranges=["Dog"])
    rename_owl_uri(t, uri("Dog"), uri("Canine"))
    assert uri("Canine") in t.owl_properties[uri("hasMaster")].domains
    assert uri("Dog") not in t.owl_properties[uri("hasMaster")].domains
    assert uri("Canine") in t.owl_properties[uri("hasMaster")].ranges
    assert uri("Dog") not in t.owl_properties[uri("hasMaster")].ranges


# ── rename individual ─────────────────────────────────────────────────────────


def test_rename_individual_renames_key_and_uri():
    t = Taxonomy()
    t.owl_individuals[uri("Rex")] = _ind("Rex", "Dog")
    rename_owl_uri(t, uri("Rex"), uri("Max"))
    assert uri("Max") in t.owl_individuals
    assert uri("Rex") not in t.owl_individuals
    assert t.owl_individuals[uri("Max")].uri == uri("Max")


def test_rename_individual_updates_property_value_objects():
    t = Taxonomy()
    t.owl_individuals[uri("Rex")] = _ind("Rex")
    t.owl_individuals[uri("Bob")] = _ind("Bob")
    t.owl_individuals[uri("Rex")].property_values.append((uri("knows"), uri("Bob")))
    rename_owl_uri(t, uri("Bob"), uri("Alice"))
    pv = t.owl_individuals[uri("Rex")].property_values
    assert (uri("knows"), uri("Alice")) in pv
    assert (uri("knows"), uri("Bob")) not in pv


# ── rename property ───────────────────────────────────────────────────────────


def test_rename_property_renames_key_and_uri():
    t = Taxonomy()
    t.owl_properties[uri("hasMaster")] = _prop("hasMaster")
    rename_owl_uri(t, uri("hasMaster"), uri("ownedBy"))
    assert uri("ownedBy") in t.owl_properties
    assert uri("hasMaster") not in t.owl_properties
    assert t.owl_properties[uri("ownedBy")].uri == uri("ownedBy")


def test_rename_property_updates_individual_property_value_predicates():
    t = Taxonomy()
    t.owl_properties[uri("hasMaster")] = _prop("hasMaster")
    t.owl_individuals[uri("Rex")] = _ind("Rex")
    t.owl_individuals[uri("Rex")].property_values.append((uri("hasMaster"), uri("Rex")))
    rename_owl_uri(t, uri("hasMaster"), uri("ownedBy"))
    pv = t.owl_individuals[uri("Rex")].property_values
    assert (uri("ownedBy"), uri("Rex")) in pv
    assert (uri("hasMaster"), uri("Rex")) not in pv


# ── error case ────────────────────────────────────────────────────────────────


def test_rename_raises_when_new_uri_already_exists():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    t.owl_classes[uri("Canine")] = _cls("Canine")
    with pytest.raises(URIAlreadyExistsError):
        rename_owl_uri(t, uri("Dog"), uri("Canine"))


# ── count references ──────────────────────────────────────────────────────────


def test_count_references_isolated_class():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    count = count_owl_uri_references(t, uri("Dog"))
    # Appears as subject only: rdf:type + 1 label = 2
    assert count >= 1


def test_count_references_class_with_subclass_and_individual():
    t = Taxonomy()
    t.owl_classes[uri("Animal")] = _cls("Animal")
    t.owl_classes[uri("Dog")] = _cls("Dog", "Animal")
    t.owl_individuals[uri("Rex")] = _ind("Rex", "Animal")
    base = count_owl_uri_references(t, uri("Dog"))
    # Animal has extra references: 1 subClassOf from Dog + 1 type from Rex
    animal_count = count_owl_uri_references(t, uri("Animal"))
    assert animal_count > base


def test_count_references_property_with_domain_and_values():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    t.owl_properties[uri("hasMaster")] = _prop("hasMaster", domains=["Dog"])
    t.owl_individuals[uri("Rex")] = _ind("Rex")
    t.owl_individuals[uri("Rex")].property_values.append((uri("hasMaster"), uri("Rex")))
    count = count_owl_uri_references(t, uri("hasMaster"))
    # hasMaster appears: as subject (own triples) + 1 pv predicate
    assert count >= 2


def test_count_references_individual_referenced_as_value():
    t = Taxonomy()
    # "Popular" is referenced by two individuals as a value; "Loner" is not referenced at all
    t.owl_individuals[uri("Popular")] = _ind("Popular")
    t.owl_individuals[uri("Loner")] = _ind("Loner")
    t.owl_individuals[uri("A")] = _ind("A")
    t.owl_individuals[uri("B")] = _ind("B")
    t.owl_individuals[uri("A")].property_values.append((uri("knows"), uri("Popular")))
    t.owl_individuals[uri("B")].property_values.append((uri("knows"), uri("Popular")))
    popular_count = count_owl_uri_references(t, uri("Popular"))
    loner_count = count_owl_uri_references(t, uri("Loner"))
    # Popular gains 2 extra cross-reference triples that Loner does not have
    assert popular_count > loner_count


# ── literal_values — rename property ─────────────────────────────────────────


def test_rename_property_updates_literal_value_predicates():
    t = Taxonomy()
    t.owl_properties[uri("hasMaster")] = _prop("hasMaster")
    t.owl_individuals[uri("Rex")] = _ind("Rex")
    t.owl_individuals[uri("Rex")].literal_values.append((uri("hasMaster"), "John", ""))
    rename_owl_uri(t, uri("hasMaster"), uri("ownedBy"))
    lv = t.owl_individuals[uri("Rex")].literal_values
    assert (uri("ownedBy"), "John", "") in lv
    assert (uri("hasMaster"), "John", "") not in lv


# ── literal_values — rename individual ───────────────────────────────────────


def test_rename_individual_updates_own_literal_value_predicates():
    t = Taxonomy()
    t.owl_individuals[uri("Rex")] = _ind("Rex")
    t.owl_individuals[uri("Rex")].literal_values.append((uri("Rex"), "meta", ""))
    rename_owl_uri(t, uri("Rex"), uri("Max"))
    lv = t.owl_individuals[uri("Max")].literal_values
    assert (uri("Max"), "meta", "") in lv
    assert (uri("Rex"), "meta", "") not in lv


# ── literal_values — count references ────────────────────────────────────────


def test_count_references_includes_literal_value_predicate():
    t = Taxonomy()
    t.owl_individuals[uri("Rex")] = _ind("Rex")
    t.owl_individuals[uri("Rex")].literal_values.append((uri("hasMaster"), "John", ""))
    count = count_owl_uri_references(t, uri("hasMaster"))
    assert count >= 1


# ── literal_values — rename_ontology_uri ─────────────────────────────────────


def test_rename_ontology_uri_updates_literal_value_predicates():
    from ster.operations import rename_ontology_uri

    old_ns = "https://example.org/onto#"
    t = Taxonomy()
    t.ontology_uri = "https://example.org/onto"
    prop_uri = old_ns + "hasMaster"
    rex_uri_old = old_ns + "Rex"
    t.owl_properties[prop_uri] = OWLProperty(uri=prop_uri, labels=[Label("en", "hasMaster")])
    t.owl_individuals[rex_uri_old] = OWLIndividual(uri=rex_uri_old, labels=[Label("en", "Rex")])
    t.owl_individuals[rex_uri_old].literal_values.append((prop_uri, "John", ""))
    rename_ontology_uri(t, "https://new.org/onto", "#")
    new_pred = "https://new.org/onto#hasMaster"
    rex_uri_new = "https://new.org/onto#Rex"
    lv = t.owl_individuals[rex_uri_new].literal_values
    assert (new_pred, "John", "") in lv
    assert (prop_uri, "John", "") not in lv


# ── subPropertyOf / inverseOf — rename property ──────────────────────────────


def test_rename_property_updates_other_subproperty_of():
    t = Taxonomy()
    t.owl_properties[uri("hasMaster")] = _prop("hasMaster")
    t.owl_properties[uri("hasOwner")] = _prop("hasOwner")
    t.owl_properties[uri("hasOwner")].sub_property_of.append(uri("hasMaster"))
    rename_owl_uri(t, uri("hasMaster"), uri("ownedBy"))
    spo = t.owl_properties[uri("hasOwner")].sub_property_of
    assert uri("ownedBy") in spo
    assert uri("hasMaster") not in spo


def test_rename_property_updates_other_inverse_of():
    t = Taxonomy()
    t.owl_properties[uri("hasMaster")] = _prop("hasMaster")
    t.owl_properties[uri("isMasterOf")] = _prop("isMasterOf")
    t.owl_properties[uri("isMasterOf")].inverse_of.append(uri("hasMaster"))
    rename_owl_uri(t, uri("hasMaster"), uri("ownedBy"))
    inv = t.owl_properties[uri("isMasterOf")].inverse_of
    assert uri("ownedBy") in inv
    assert uri("hasMaster") not in inv


# ── subPropertyOf / inverseOf — rename_ontology_uri ──────────────────────────


def test_rename_ontology_uri_updates_subproperty_of_and_inverse_of():
    from ster.operations import rename_ontology_uri

    old_ns = "https://example.org/onto#"
    t = Taxonomy()
    t.ontology_uri = "https://example.org/onto"
    master = old_ns + "hasMaster"
    owner = old_ns + "hasOwner"
    inverse = old_ns + "isMasterOf"
    t.owl_properties[master] = OWLProperty(uri=master, labels=[Label("en", "hasMaster")])
    t.owl_properties[owner] = OWLProperty(
        uri=owner, labels=[Label("en", "hasOwner")], sub_property_of=[master]
    )
    t.owl_properties[inverse] = OWLProperty(
        uri=inverse, labels=[Label("en", "isMasterOf")], inverse_of=[master]
    )
    rename_ontology_uri(t, "https://new.org/onto", "#")
    new_master = "https://new.org/onto#hasMaster"
    assert new_master in t.owl_properties["https://new.org/onto#hasOwner"].sub_property_of
    assert master not in t.owl_properties["https://new.org/onto#hasOwner"].sub_property_of
    assert new_master in t.owl_properties["https://new.org/onto#isMasterOf"].inverse_of
    assert master not in t.owl_properties["https://new.org/onto#isMasterOf"].inverse_of


# ── subPropertyOf / inverseOf — count references ─────────────────────────────


def test_count_references_includes_subproperty_of_and_inverse_of():
    t = Taxonomy()
    t.owl_properties[uri("hasMaster")] = _prop("hasMaster")
    t.owl_properties[uri("hasOwner")] = _prop("hasOwner")
    t.owl_properties[uri("isMasterOf")] = _prop("isMasterOf")
    t.owl_properties[uri("hasOwner")].sub_property_of.append(uri("hasMaster"))
    t.owl_properties[uri("isMasterOf")].inverse_of.append(uri("hasMaster"))
    count = count_owl_uri_references(t, uri("hasMaster"))
    # 1 subPropertyOf + 1 inverseOf cross-reference, plus the entity's own triples
    assert count >= 2
