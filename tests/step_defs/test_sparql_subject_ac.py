"""BDD step definitions for tests/features/sparql/sparql_subject_ac.feature."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.operations import add_subclass_of
from ster.sparql_query import build_uri_index, qname_level_candidates

scenarios("../features/sparql/sparql_subject_ac.feature")

BASE = "https://example.org/onto/"


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {"taxonomy": Taxonomy(), "idx": {}, "results": []}


def _setup_ns(t: Taxonomy) -> None:
    t.namespace_bindings["kai"] = BASE


@given('a taxonomy with class "Animal" and individual "Fido" typed as "Animal"')
def tax_animal_fido(ctx: dict[str, Any]) -> None:
    t = Taxonomy()
    _setup_ns(t)
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    t.owl_individuals[BASE + "Fido"] = OWLIndividual(
        uri=BASE + "Fido", types=[BASE + "Animal"]
    )
    ctx["taxonomy"] = t


@given('a taxonomy with class "Animal" and property "hasAge"')
def tax_animal_hasage(ctx: dict[str, Any]) -> None:
    t = Taxonomy()
    _setup_ns(t)
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    t.owl_properties[BASE + "hasAge"] = OWLProperty(uri=BASE + "hasAge")
    ctx["taxonomy"] = t


@given('a taxonomy where "Dog" is a subclass of "Animal"')
def tax_dog_subclass(ctx: dict[str, Any]) -> None:
    t = Taxonomy()
    _setup_ns(t)
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    t.owl_classes[BASE + "Dog"] = RDFClass(uri=BASE + "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    ctx["taxonomy"] = t


@given('a taxonomy with an individual "Unnamed" with no class')
def tax_untyped_individual(ctx: dict[str, Any]) -> None:
    t = Taxonomy()
    _setup_ns(t)
    t.owl_individuals[BASE + "Unnamed"] = OWLIndividual(uri=BASE + "Unnamed", types=[])
    ctx["taxonomy"] = t


@when("build_uri_index is called")
def call_build_uri_index(ctx: dict[str, Any]) -> None:
    ctx["idx"] = build_uri_index(ctx["taxonomy"])


@when("qname_level_candidates is called with any context at root level")
def call_level_cands_root(ctx: dict[str, Any]) -> None:
    ctx["idx"] = build_uri_index(ctx["taxonomy"])
    ctx["results"] = qname_level_candidates(ctx["idx"], "kai", "", "", "any")


@when('qname_level_candidates is called with any context drilling into "Animal"')
def call_level_cands_drill(ctx: dict[str, Any]) -> None:
    ctx["idx"] = build_uri_index(ctx["taxonomy"])
    ctx["results"] = qname_level_candidates(ctx["idx"], "kai", "Animal", "", "any")


@then('"individuals_by_class" maps "Animal" to "Fido"')
def ibc_maps_animal_fido(ctx: dict[str, Any]) -> None:
    ibc = ctx["idx"].get("kai", {}).get("individuals_by_class", {})
    assert "Fido" in ibc.get("Animal", []), f"individuals_by_class[Animal] = {ibc.get('Animal')}"


@then(parsers.parse('the results include "{name}"'))
def results_include(name: str, ctx: dict[str, Any]) -> None:
    names = [n for n, _ in ctx["results"]]
    assert name in names, f"Expected {name!r} in {names}"


@then(parsers.parse('the results do not include "{name}"'))
def results_exclude(name: str, ctx: dict[str, Any]) -> None:
    names = [n for n, _ in ctx["results"]]
    assert name not in names, f"Expected {name!r} NOT in {names}"
