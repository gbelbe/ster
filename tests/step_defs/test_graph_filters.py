"""BDD step definitions for tests/features/owl/graph_filters.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import Concept, ConceptScheme, Label, RDFClass, Taxonomy
from ster.viz_vowl import render_vowl_html

scenarios("../features/owl/graph_filters.feature")

NS = "https://example.org/onto#"


def _uri(name: str) -> str:
    return NS + name


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given('a taxonomy with root class "Animal" and subclass "Dog" under it')
def given_owl_hierarchy(ctx: dict) -> None:
    tax = Taxonomy()
    tax.owl_classes[_uri("Animal")] = RDFClass(uri=_uri("Animal"), labels=[Label("en", "Animal")])
    tax.owl_classes[_uri("Dog")] = RDFClass(
        uri=_uri("Dog"),
        labels=[Label("en", "Dog")],
        sub_class_of=[_uri("Animal")],
    )
    ctx["taxonomy"] = tax


@given("a SKOS-only taxonomy with a concept")
def given_skos_only(ctx: dict) -> None:
    tax = Taxonomy()
    tax.schemes[_uri("Scheme")] = ConceptScheme(uri=_uri("Scheme"), labels=[Label("en", "Scheme")])
    tax.concepts[_uri("Dog")] = Concept(
        uri=_uri("Dog"),
        labels=[Label("en", "Dog")],
        top_concept_of=_uri("Scheme"),
    )
    ctx["taxonomy"] = tax


# ── When ──────────────────────────────────────────────────────────────────────


@when("I render the filter VOWL graph HTML")
def when_render_filter(ctx: dict) -> None:
    ctx["html"] = render_vowl_html(ctx["taxonomy"], file_path=None)


# ── Then ──────────────────────────────────────────────────────────────────────


@then('the filter HTML contains button id "ft-first-order"')
def then_first_order_btn(ctx: dict) -> None:
    assert 'id="ft-first-order"' in ctx["html"]


@then('the filter HTML contains button id "ft-second-order"')
def then_second_order_btn(ctx: dict) -> None:
    assert 'id="ft-second-order"' in ctx["html"]


@then("the filter HTML contains the toggleFirstOrderClasses function")
def then_first_order_fn(ctx: dict) -> None:
    assert "toggleFirstOrderClasses" in ctx["html"]


@then("the filter HTML contains the toggleSecondOrderClasses function")
def then_second_order_fn(ctx: dict) -> None:
    assert "toggleSecondOrderClasses" in ctx["html"]


@then("the filter HTML contains code to hide ft-first-order when empty")
def then_hide_first_order_when_empty(ctx: dict) -> None:
    assert "ft-first-order" in ctx["html"]
    assert "firstOrderIds" in ctx["html"]


@then("the filter HTML contains code to hide ft-second-order when empty")
def then_hide_second_order_when_empty(ctx: dict) -> None:
    assert "ft-second-order" in ctx["html"]
    assert "secondOrderIds" in ctx["html"]
