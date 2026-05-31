"""Unit tests for delete_owl_class() — OWL class deletion with subclass/individual handling."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.operations import delete_owl_class

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


# ── keep_all ──────────────────────────────────────────────────────────────────


def test_delete_class_no_dependents_removes_cleanly():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    delete_owl_class(t, uri("Dog"), mode="keep_all")
    assert uri("Dog") not in t.owl_classes


def test_delete_class_keep_all_reparents_direct_subclass():
    t = Taxonomy()
    t.owl_classes[uri("GrandParent")] = _cls("GrandParent")
    t.owl_classes[uri("Parent")] = _cls("Parent", "GrandParent")
    t.owl_classes[uri("Child")] = _cls("Child", "Parent")
    delete_owl_class(t, uri("Parent"), mode="keep_all")
    assert uri("Parent") not in t.owl_classes
    assert uri("GrandParent") in t.owl_classes[uri("Child")].sub_class_of


def test_delete_class_keep_all_reparents_multiple_subclasses():
    t = Taxonomy()
    t.owl_classes[uri("Root")] = _cls("Root")
    t.owl_classes[uri("Mid")] = _cls("Mid", "Root")
    t.owl_classes[uri("A")] = _cls("A", "Mid")
    t.owl_classes[uri("B")] = _cls("B", "Mid")
    delete_owl_class(t, uri("Mid"), mode="keep_all")
    assert uri("Root") in t.owl_classes[uri("A")].sub_class_of
    assert uri("Root") in t.owl_classes[uri("B")].sub_class_of


def test_delete_class_keep_all_preserves_individuals_and_retypes_to_parent():
    t = Taxonomy()
    t.owl_classes[uri("Animal")] = _cls("Animal")
    t.owl_classes[uri("Dog")] = _cls("Dog", "Animal")
    t.owl_individuals[uri("Rex")] = _ind("Rex", "Dog")
    delete_owl_class(t, uri("Dog"), mode="keep_all")
    assert uri("Dog") not in t.owl_classes
    assert uri("Rex") in t.owl_individuals
    assert uri("Animal") in t.owl_individuals[uri("Rex")].types
    assert uri("Dog") not in t.owl_individuals[uri("Rex")].types


def test_delete_class_keep_all_orphans_individuals_when_no_parent():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    t.owl_individuals[uri("Rex")] = _ind("Rex", "Dog")
    delete_owl_class(t, uri("Dog"), mode="keep_all")
    assert uri("Rex") in t.owl_individuals
    assert t.owl_individuals[uri("Rex")].types == []


# ── cascade_subclasses ────────────────────────────────────────────────────────


def test_delete_class_cascade_subclasses_removes_direct_children():
    t = Taxonomy()
    t.owl_classes[uri("Root")] = _cls("Root")
    t.owl_classes[uri("Mid")] = _cls("Mid", "Root")
    t.owl_classes[uri("Leaf")] = _cls("Leaf", "Mid")
    delete_owl_class(t, uri("Mid"), mode="cascade_subclasses")
    assert uri("Mid") not in t.owl_classes
    assert uri("Leaf") not in t.owl_classes
    assert uri("Root") in t.owl_classes


def test_delete_class_cascade_subclasses_removes_transitive_descendants():
    t = Taxonomy()
    t.owl_classes[uri("A")] = _cls("A")
    t.owl_classes[uri("B")] = _cls("B", "A")
    t.owl_classes[uri("C")] = _cls("C", "B")
    t.owl_classes[uri("D")] = _cls("D", "C")
    delete_owl_class(t, uri("B"), mode="cascade_subclasses")
    assert uri("B") not in t.owl_classes
    assert uri("C") not in t.owl_classes
    assert uri("D") not in t.owl_classes
    assert uri("A") in t.owl_classes


def test_delete_class_cascade_subclasses_retypes_individuals_to_parent():
    t = Taxonomy()
    t.owl_classes[uri("Animal")] = _cls("Animal")
    t.owl_classes[uri("Dog")] = _cls("Dog", "Animal")
    t.owl_classes[uri("Poodle")] = _cls("Poodle", "Dog")
    t.owl_individuals[uri("Rex")] = _ind("Rex", "Dog")
    t.owl_individuals[uri("Tiny")] = _ind("Tiny", "Poodle")
    delete_owl_class(t, uri("Dog"), mode="cascade_subclasses")
    assert uri("Rex") in t.owl_individuals
    assert uri("Animal") in t.owl_individuals[uri("Rex")].types
    assert uri("Tiny") in t.owl_individuals
    assert uri("Animal") in t.owl_individuals[uri("Tiny")].types


def test_delete_class_cascade_subclasses_orphans_individuals_when_no_parent():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    t.owl_classes[uri("Poodle")] = _cls("Poodle", "Dog")
    t.owl_individuals[uri("Tiny")] = _ind("Tiny", "Poodle")
    delete_owl_class(t, uri("Dog"), mode="cascade_subclasses")
    assert uri("Tiny") in t.owl_individuals
    assert t.owl_individuals[uri("Tiny")].types == []


# ── delete_all ────────────────────────────────────────────────────────────────


def test_delete_class_delete_all_removes_individuals():
    t = Taxonomy()
    t.owl_classes[uri("Animal")] = _cls("Animal")
    t.owl_classes[uri("Dog")] = _cls("Dog", "Animal")
    t.owl_individuals[uri("Rex")] = _ind("Rex", "Dog")
    delete_owl_class(t, uri("Dog"), mode="delete_all")
    assert uri("Dog") not in t.owl_classes
    assert uri("Rex") not in t.owl_individuals
    assert uri("Animal") in t.owl_classes


def test_delete_class_delete_all_removes_descendants_and_their_individuals():
    t = Taxonomy()
    t.owl_classes[uri("Animal")] = _cls("Animal")
    t.owl_classes[uri("Dog")] = _cls("Dog", "Animal")
    t.owl_classes[uri("Poodle")] = _cls("Poodle", "Dog")
    t.owl_individuals[uri("Rex")] = _ind("Rex", "Dog")
    t.owl_individuals[uri("Tiny")] = _ind("Tiny", "Poodle")
    delete_owl_class(t, uri("Dog"), mode="delete_all")
    assert uri("Dog") not in t.owl_classes
    assert uri("Poodle") not in t.owl_classes
    assert uri("Rex") not in t.owl_individuals
    assert uri("Tiny") not in t.owl_individuals
    assert uri("Animal") in t.owl_classes


# ── property domain/range cleanup ─────────────────────────────────────────────


def test_delete_class_removes_domain_reference():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    t.owl_properties[uri("hasMaster")] = _prop("hasMaster", domains=["Dog"])
    delete_owl_class(t, uri("Dog"), mode="keep_all")
    assert uri("Dog") not in t.owl_properties[uri("hasMaster")].domains


def test_delete_class_removes_range_reference():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = _cls("Dog")
    t.owl_properties[uri("hasPet")] = _prop("hasPet", ranges=["Dog"])
    delete_owl_class(t, uri("Dog"), mode="keep_all")
    assert uri("Dog") not in t.owl_properties[uri("hasPet")].ranges


def test_delete_class_cascade_removes_domain_for_deleted_subclass():
    t = Taxonomy()
    t.owl_classes[uri("Animal")] = _cls("Animal")
    t.owl_classes[uri("Dog")] = _cls("Dog", "Animal")
    t.owl_properties[uri("hasMaster")] = _prop("hasMaster", domains=["Dog"])
    delete_owl_class(t, uri("Animal"), mode="cascade_subclasses")
    assert uri("Dog") not in t.owl_properties[uri("hasMaster")].domains
