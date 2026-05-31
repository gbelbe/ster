"""BDD step definitions for tests/features/owl/individual_property_range.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Label, OWLIndividual, RDFClass, Taxonomy
from ster.nav.logic import build_individual_candidates_grouped

scenarios("../features/owl/individual_property_range.feature")

NS = "https://example.org/onto#"


def _uri(name: str) -> str:
    return NS + name


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given('a taxonomy with classes "Dog" and "Person"')
def given_dog_person(ctx: dict) -> None:
    tax = Taxonomy()
    for name in ("Dog", "Person"):
        tax.owl_classes[_uri(name)] = RDFClass(uri=_uri(name), labels=[Label("en", name)])
    ctx["taxonomy"] = tax


@given('individuals "Rex" typed as "Dog" and "Alice" typed as "Person"')
def given_rex_alice(ctx: dict) -> None:
    tax: Taxonomy = ctx["taxonomy"]
    tax.owl_individuals[_uri("Rex")] = OWLIndividual(
        uri=_uri("Rex"), labels=[Label("en", "Rex")], types=[_uri("Dog")]
    )
    tax.owl_individuals[_uri("Alice")] = OWLIndividual(
        uri=_uri("Alice"), labels=[Label("en", "Alice")], types=[_uri("Person")]
    )


@given(parsers.parse('a property "{prop}" with range "{cls}"'))
def given_prop_with_range(ctx: dict, prop: str, cls: str) -> None:
    ctx["prop_ranges"] = [_uri(cls)]


@given(parsers.parse('a property "{prop}" with no range'))
def given_prop_no_range(ctx: dict, prop: str) -> None:
    ctx["prop_ranges"] = []


@given(parsers.parse('a class "{child}" that is a subclass of "{parent}"'))
def given_subclass(ctx: dict, child: str, parent: str) -> None:
    tax: Taxonomy = ctx["taxonomy"]
    tax.owl_classes[_uri(child)] = RDFClass(
        uri=_uri(child), labels=[Label("en", child)], sub_class_of=[_uri(parent)]
    )


@given(parsers.parse('individual "{ind}" typed as "{cls}"'))
def given_individual_typed(ctx: dict, ind: str, cls: str) -> None:
    tax: Taxonomy = ctx["taxonomy"]
    tax.owl_individuals[_uri(ind)] = OWLIndividual(
        uri=_uri(ind), labels=[Label("en", ind)], types=[_uri(cls)]
    )


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I build individual candidates for "{prop}" excluding "{exclude}"'))
def when_build_candidates(ctx: dict, prop: str, exclude: str) -> None:
    exclude_uri = _uri(exclude) if exclude else ""
    ctx["candidates"] = build_individual_candidates_grouped(
        ctx["taxonomy"], "en", ctx.get("prop_ranges", []), exclude_uri
    )
    ctx["candidate_uris"] = {uri for uri, _ in ctx["candidates"] if not uri.startswith("__HDR__:")}


@when('I build individual candidates for "hasPet" excluding no one')
def when_build_candidates_no_exclude(ctx: dict) -> None:
    ctx["candidates"] = build_individual_candidates_grouped(
        ctx["taxonomy"], "en", ctx.get("prop_ranges", []), ""
    )
    ctx["candidate_uris"] = {uri for uri, _ in ctx["candidates"] if not uri.startswith("__HDR__:")}


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('"{name}" appears in the candidates'))
def then_in_candidates(ctx: dict, name: str) -> None:
    assert _uri(name) in ctx["candidate_uris"], (
        f"{name!r} not found in candidates {ctx['candidate_uris']}"
    )


@then(parsers.parse('"{name}" does not appear in the candidates'))
def then_not_in_candidates(ctx: dict, name: str) -> None:
    assert _uri(name) not in ctx["candidate_uris"], (
        f"{name!r} unexpectedly found in candidates {ctx['candidate_uris']}"
    )
