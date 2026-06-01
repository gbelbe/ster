"""Unit tests for rename_uri() propagation across SKOS mapping properties.

rename_uri must update the five SKOS mapping fields (broad_match, narrow_match,
related_match, exact_match, close_match) on every other concept, while leaving
mapping targets that are not being renamed untouched.
"""

from __future__ import annotations

from ster.model import Concept, ConceptScheme, Label, LabelType, Taxonomy
from ster.operations import count_concept_uri_references, rename_uri

NS = "https://example.org/onto#"


def uri(name: str) -> str:
    return NS + name


def _concept(name: str) -> Concept:
    return Concept(uri=uri(name), labels=[Label("en", name, LabelType.PREF)])


def _taxonomy(*names: str) -> Taxonomy:
    t = Taxonomy()
    for name in names:
        t.concepts[uri(name)] = _concept(name)
    return t


# ── mapping-property propagation ───────────────────────────────────────────────


def test_rename_concept_updates_broad_match():
    t = _taxonomy("Animal", "Dog")
    t.concepts[uri("Dog")].broad_match.append(uri("Animal"))
    rename_uri(t, uri("Animal"), uri("LivingThing"))
    bm = t.concepts[uri("Dog")].broad_match
    assert uri("LivingThing") in bm
    assert uri("Animal") not in bm


def test_rename_concept_updates_narrow_match():
    t = _taxonomy("Animal", "Dog")
    t.concepts[uri("Animal")].narrow_match.append(uri("Dog"))
    rename_uri(t, uri("Dog"), uri("Canine"))
    nm = t.concepts[uri("Animal")].narrow_match
    assert uri("Canine") in nm
    assert uri("Dog") not in nm


def test_rename_concept_updates_related_match():
    t = _taxonomy("Cat", "Dog")
    t.concepts[uri("Dog")].related_match.append(uri("Cat"))
    rename_uri(t, uri("Cat"), uri("Feline"))
    rm = t.concepts[uri("Dog")].related_match
    assert uri("Feline") in rm
    assert uri("Cat") not in rm


def test_rename_concept_updates_exact_match():
    t = _taxonomy("Cat", "Dog")
    t.concepts[uri("Dog")].exact_match.append(uri("Cat"))
    rename_uri(t, uri("Cat"), uri("Feline"))
    em = t.concepts[uri("Dog")].exact_match
    assert uri("Feline") in em
    assert uri("Cat") not in em


def test_rename_concept_updates_close_match():
    t = _taxonomy("Cat", "Dog")
    t.concepts[uri("Dog")].close_match.append(uri("Cat"))
    rename_uri(t, uri("Cat"), uri("Feline"))
    cm = t.concepts[uri("Dog")].close_match
    assert uri("Feline") in cm
    assert uri("Cat") not in cm


def test_rename_concept_leaves_external_matches_untouched():
    external = "https://other.org/vocab#Wolf"
    t = _taxonomy("Cat", "Dog")
    t.concepts[uri("Dog")].exact_match.append(uri("Cat"))
    t.concepts[uri("Dog")].exact_match.append(external)
    rename_uri(t, uri("Cat"), uri("Feline"))
    em = t.concepts[uri("Dog")].exact_match
    assert external in em
    assert uri("Feline") in em


# ── count_concept_uri_references ───────────────────────────────────────────────


def test_count_concept_references_isolated():
    t = _taxonomy("Dog")
    # Own subject triples: rdf:type + 1 prefLabel = at least 1
    assert count_concept_uri_references(t, uri("Dog")) >= 1


def test_count_concept_references_includes_broader_narrower_related():
    t = _taxonomy("Animal", "Dog")
    t.concepts[uri("Dog")].broader.append(uri("Animal"))
    t.concepts[uri("Animal")].narrower.append(uri("Dog"))
    isolated = count_concept_uri_references(_taxonomy("Lonely"), uri("Lonely"))
    referenced = count_concept_uri_references(t, uri("Animal"))
    # Animal gains a broader (from Dog) plus its own narrower entry
    assert referenced > isolated


def test_count_concept_references_includes_match_fields():
    t = _taxonomy("Cat", "Dog")
    t.concepts[uri("Dog")].exact_match.append(uri("Cat"))
    t.concepts[uri("Dog")].close_match.append(uri("Cat"))
    base = count_concept_uri_references(_taxonomy("Cat"), uri("Cat"))
    with_matches = count_concept_uri_references(t, uri("Cat"))
    # Two extra cross-reference statements (exactMatch + closeMatch) point at Cat
    assert with_matches >= base + 2


def test_count_concept_references_includes_scheme_top_concepts():
    t = _taxonomy("Top")
    scheme = ConceptScheme(uri=uri("Scheme"), top_concepts=[uri("Top")])
    t.schemes[uri("Scheme")] = scheme
    base = count_concept_uri_references(_taxonomy("Top"), uri("Top"))
    assert count_concept_uri_references(t, uri("Top")) > base


def test_count_concept_references_referenced_higher_than_isolated():
    t = _taxonomy("Animal", "Dog", "Cat")
    t.concepts[uri("Dog")].broader.append(uri("Animal"))
    t.concepts[uri("Cat")].related.append(uri("Animal"))
    animal = count_concept_uri_references(t, uri("Animal"))
    dog = count_concept_uri_references(t, uri("Dog"))
    assert animal > dog
