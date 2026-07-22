"""Step defs for the concept↔class foaf:focus link (tests/features/skos/concept_class_link.feature)."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store
from ster.operations import link_concept_to_class, unlink_concept_from_class

scenarios("../features/skos/concept_class_link.feature")

E = "https://ex.org/"

_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://ex.org/> .
ex:scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Mammal .
ex:Mammal a skos:Concept ; skos:prefLabel "Mammal"@en ;
          skos:topConceptOf ex:scheme ; skos:inScheme ex:scheme .
ex:Dog a owl:Class ; rdfs:label "Dog"@en .
"""


@pytest.fixture
def ctx(tmp_path) -> dict:
    src = tmp_path / "o.ttl"
    src.write_text(_TTL, encoding="utf-8")
    return {"src": src, "tax": store.load(src)}


@given(parsers.parse('a taxonomy with a concept "{c}" and an OWL class "{k}"'))
def _given_tax(ctx, c, k):
    assert E + c in ctx["tax"].concepts and E + k in ctx["tax"].owl_classes


@given(parsers.parse('a taxonomy with a concept "{c}" linked to the class "{k}"'))
def _given_linked(ctx, c, k):
    link_concept_to_class(ctx["tax"], E + c, E + k)


@when(parsers.parse('I link the concept "{c}" to the class "{k}"'))
def _when_link(ctx, c, k):
    link_concept_to_class(ctx["tax"], E + c, E + k)


@when(parsers.parse('I unlink the concept "{c}"'))
def _when_unlink(ctx, c):
    unlink_concept_from_class(ctx["tax"], E + c)


@when("I save and reload the taxonomy")
def _when_reload(ctx):
    store.save(ctx["tax"], ctx["src"])
    ctx["tax"] = store.load(ctx["src"])


@then(parsers.parse('the concept "{c}" has a foaf:focus link to the class "{k}"'))
def _then_linked(ctx, c, k):
    assert ctx["tax"].concepts[E + c].focus == E + k


@then(parsers.parse('the concept "{c}" has no foaf:focus link'))
def _then_unlinked(ctx, c):
    assert ctx["tax"].concepts[E + c].focus is None


@then(parsers.parse('"{c}" is a linked concept, not a pun'))
def _then_is_linked(ctx, c):
    assert ctx["tax"].node_type(E + c) == "linked"
    assert E + c not in ctx["tax"].owl_classes


@then(parsers.parse('the class "{k}" still exists'))
def _then_class_exists(ctx, k):
    assert E + k in ctx["tax"].owl_classes
