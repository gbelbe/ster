"""Step definitions for sparql_pfx_ac.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.sparql_query import _sparql_pfx_candidates

scenarios("../features/ui/sparql_pfx_ac.feature")


@pytest.fixture
def ctx() -> dict:
    return {}


@given('a known prefix set containing "kai", "skos", "owl", "rdf"')
def given_standard_prefixes(ctx: dict) -> None:
    ctx["known"] = {"kai", "skos", "owl", "rdf"}


@given('a known prefix set containing "rdf", "rdfs", "rdfa"')
def given_rdf_prefixes(ctx: dict) -> None:
    ctx["known"] = {"rdf", "rdfs", "rdfa"}


@when('prefix candidates are requested with filter ""')
def when_filter_empty(ctx: dict) -> None:
    ctx["result"] = _sparql_pfx_candidates(ctx["known"], "")


@when('prefix candidates are requested with filter "s"')
def when_filter_s(ctx: dict) -> None:
    ctx["result"] = _sparql_pfx_candidates(ctx["known"], "s")


@when('prefix candidates are requested with filter "SK"')
def when_filter_sk(ctx: dict) -> None:
    ctx["result"] = _sparql_pfx_candidates(ctx["known"], "SK")


@when('prefix candidates are requested with filter "xyz"')
def when_filter_xyz(ctx: dict) -> None:
    ctx["result"] = _sparql_pfx_candidates(ctx["known"], "xyz")


@when('prefix candidates are requested with filter "rdf"')
def when_filter_rdf(ctx: dict) -> None:
    ctx["result"] = _sparql_pfx_candidates(ctx["known"], "rdf")


@when('prefix candidates are requested with filter "owl"')
def when_filter_owl(ctx: dict) -> None:
    ctx["result"] = _sparql_pfx_candidates(ctx["known"], "owl")


@then('the result is ["kai", "owl", "rdf", "skos"]')
def then_all_sorted(ctx: dict) -> None:
    assert ctx["result"] == ["kai", "owl", "rdf", "skos"]


@then('the result is ["skos"]')
def then_skos(ctx: dict) -> None:
    assert ctx["result"] == ["skos"]


@then("the result is []")
def then_empty(ctx: dict) -> None:
    assert ctx["result"] == []


@then('the result is ["rdf", "rdfa", "rdfs"]')
def then_rdf_variants(ctx: dict) -> None:
    assert ctx["result"] == ["rdf", "rdfa", "rdfs"]


@then('the result is ["owl"]')
def then_owl(ctx: dict) -> None:
    assert ctx["result"] == ["owl"]
