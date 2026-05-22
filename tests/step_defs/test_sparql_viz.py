"""BDD step definitions for SPARQL → graph viz integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import Concept, Taxonomy

scenarios("../features/ui/sparql_viz.feature")

_NS = "http://ex.org/"


@pytest.fixture
def ctx():
    return {"taxonomy": None, "rows": [], "opened_url": None, "error": None}


# ── Given ──────────────────────────────────────────────────────────────────────


@given("a taxonomy containing concepts A and B")
def given_two_concepts(ctx):
    tax = Taxonomy()
    tax.concepts[_NS + "A"] = Concept(uri=_NS + "A")
    tax.concepts[_NS + "B"] = Concept(uri=_NS + "B")
    ctx["taxonomy"] = tax


@given("a taxonomy containing concept A")
def given_one_concept(ctx):
    tax = Taxonomy()
    tax.concepts[_NS + "A"] = Concept(uri=_NS + "A")
    ctx["taxonomy"] = tax


@given("a query result whose rows contain the URIs of A and B")
def given_rows_with_uris(ctx):
    ctx["rows"] = [[_NS + "A"], [_NS + "B"]]


@given("a query result containing only literal values")
def given_rows_literals(ctx):
    ctx["rows"] = [["Cat"], ["Dog"]]


@given("a query result with no rows")
def given_rows_empty(ctx):
    ctx["rows"] = []


# ── When ───────────────────────────────────────────────────────────────────────


@when("I open query result viz")
def when_open_viz(ctx):
    from ster import sparql_query as _sq
    from ster import viz_vowl as _viz

    uris = _sq.extract_result_uris(ctx["rows"])

    def _capture(url: str) -> None:
        ctx["opened_url"] = url

    with (
        patch("ster.viz_vowl.webbrowser.open", side_effect=_capture),
        patch("ster.viz_vowl._ensure_server", return_value=8080),
        patch("pathlib.Path.mkdir"),
        patch("pathlib.Path.write_text"),
    ):
        try:
            _viz.open_query_result_in_browser(ctx["taxonomy"], uris)
        except ValueError as exc:
            ctx["error"] = exc


# ── Then ───────────────────────────────────────────────────────────────────────


@then("the browser is opened")
def then_browser_opened(ctx):
    assert ctx["error"] is None
    assert ctx["opened_url"] is not None


@then("the opened URL is non-empty")
def then_url_non_empty(ctx):
    assert ctx["opened_url"]


@then("a ValueError is raised indicating no matching nodes")
def then_value_error(ctx):
    assert isinstance(ctx["error"], ValueError)
    assert "No taxonomy nodes" in str(ctx["error"])
