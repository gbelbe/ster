"""Promote / demote domain ops — the concept ↔ pun toggle.

Promote gives a skos:Concept an owl:Class facet (punning); demote removes it,
non-destructively (subclasses re-root, typed individuals drop the type but
survive). Both keep the graph valid and are no-ops on the wrong kind of node.
"""

from __future__ import annotations

from pathlib import Path

from ster import store
from ster.operations import (
    demote_pun_to_concept,
    link_concept_to_class,
    promote_concept_to_class,
    unlink_concept_from_class,
)

E = "https://ex.org/"

_HEADER = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://ex.org/> .
"""

# A pure concept (Mammal) to promote; a pun (Animal) with an OWL subclass (Dog)
# and an individual typed directly as the pun (nero) to demote.
TTL = (
    _HEADER
    + """
ex:scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Animal .
ex:Animal a skos:Concept, owl:Class ; skos:prefLabel "Animal"@en ;
          skos:topConceptOf ex:scheme ; skos:inScheme ex:scheme .
ex:Mammal a skos:Concept ; skos:prefLabel "Mammal"@en ;
          skos:broader ex:Animal ; skos:inScheme ex:scheme .
ex:Dog    a owl:Class ; rdfs:subClassOf ex:Animal .
ex:nero   a owl:NamedIndividual, ex:Animal .
"""
)


def _tax(tmp_path: Path):
    src = tmp_path / "o.ttl"
    src.write_text(TTL, encoding="utf-8")
    return store.load(src)


# ── promote ─────────────────────────────────────────────────────────────────


def test_promote_gives_a_concept_an_owl_class_facet(tmp_path):
    tax = _tax(tmp_path)
    promote_concept_to_class(tax, E + "Mammal")
    assert tax.node_type(E + "Mammal") == "promoted"  # now a pun
    assert E + "Mammal" in tax.concepts  # still a concept — SKOS side intact
    assert tax.concepts[E + "Mammal"].broader == [E + "Animal"]


def test_promote_carries_the_concept_label_so_display_survives(tmp_path):
    tax = _tax(tmp_path)
    promote_concept_to_class(tax, E + "Mammal")
    # label_of reads the class facet first — it must carry the concept's prefLabel.
    assert tax.owl_classes[E + "Mammal"].label("en") == "Mammal"


def test_promote_is_a_noop_on_an_existing_pun_or_a_non_concept(tmp_path):
    tax = _tax(tmp_path)
    before = dict(tax.owl_classes[E + "Animal"].__dict__)
    promote_concept_to_class(tax, E + "Animal")  # already a pun
    assert tax.owl_classes[E + "Animal"].__dict__ == before
    promote_concept_to_class(tax, E + "Dog")  # a pure class, not a concept
    assert E + "Dog" not in tax.concepts


# ── demote ──────────────────────────────────────────────────────────────────


def test_demote_removes_the_class_facet_keeping_the_concept(tmp_path):
    tax = _tax(tmp_path)
    demote_pun_to_concept(tax, E + "Animal")
    assert tax.node_type(E + "Animal") == "concept"
    assert E + "Animal" not in tax.owl_classes
    assert E + "Animal" in tax.concepts


def test_demote_re_roots_subclasses_of_the_pun(tmp_path):
    tax = _tax(tmp_path)
    demote_pun_to_concept(tax, E + "Animal")
    # Dog keeps existing but its dangling superclass link to the (now non-class) pun is dropped.
    assert E + "Dog" in tax.owl_classes
    assert E + "Animal" not in tax.owl_classes[E + "Dog"].sub_class_of


def test_demote_drops_the_type_from_typed_individuals_without_deleting_them(tmp_path):
    tax = _tax(tmp_path)
    demote_pun_to_concept(tax, E + "Animal")
    assert E + "nero" in tax.owl_individuals  # survives
    assert E + "Animal" not in tax.owl_individuals[E + "nero"].types


def test_demote_is_a_noop_on_a_pure_concept_or_a_pure_class(tmp_path):
    tax = _tax(tmp_path)
    demote_pun_to_concept(tax, E + "Mammal")  # pure concept
    assert E + "Mammal" in tax.concepts and E + "Mammal" not in tax.owl_classes
    demote_pun_to_concept(tax, E + "Dog")  # pure class
    assert E + "Dog" in tax.owl_classes


# ── link / unlink (foaf:focus concept ↔ existing class) ───────────────────────


def test_link_concept_to_class_sets_focus(tmp_path):
    tax = _tax(tmp_path)
    link_concept_to_class(tax, E + "Mammal", E + "Dog")  # Mammal → existing class Dog
    assert tax.concepts[E + "Mammal"].focus == E + "Dog"
    assert tax.node_type(E + "Mammal") == "linked"  # a distinct kind from a pun
    assert E + "Mammal" not in tax.owl_classes  # not punned — no owl:Class facet minted


def test_link_is_a_noop_when_the_class_is_unknown(tmp_path):
    tax = _tax(tmp_path)
    link_concept_to_class(tax, E + "Mammal", E + "Nope")
    assert tax.concepts[E + "Mammal"].focus is None


def test_link_is_a_noop_when_the_concept_is_unknown(tmp_path):
    tax = _tax(tmp_path)
    link_concept_to_class(tax, E + "Nope", E + "Dog")  # must not raise / create anything
    assert E + "Nope" not in tax.concepts


def test_unlink_removes_the_focus_keeping_everything_else(tmp_path):
    tax = _tax(tmp_path)
    link_concept_to_class(tax, E + "Mammal", E + "Dog")
    unlink_concept_from_class(tax, E + "Mammal")
    assert tax.concepts[E + "Mammal"].focus is None
    assert tax.node_type(E + "Mammal") == "concept"  # back to a plain concept
    assert E + "Dog" in tax.owl_classes  # non-destructive — the class survives untouched


def test_foaf_focus_survives_save_and_reload(tmp_path):
    tax = _tax(tmp_path)
    link_concept_to_class(tax, E + "Mammal", E + "Dog")
    src = tmp_path / "o.ttl"
    store.save(tax, src)
    reloaded = store.load(src)
    assert reloaded.concepts[E + "Mammal"].focus == E + "Dog"  # foaf:focus round-trips
