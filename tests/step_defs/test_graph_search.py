"""BDD step definitions for tests/features/owl/graph_search.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import Label, RDFClass, Taxonomy
from ster.viz_vowl import _build_query_result_html, render_vowl_html

scenarios("../features/owl/graph_search.feature")

NS = "https://example.org/onto#"


def _uri(name: str) -> str:
    return NS + name


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given('a taxonomy with OWL classes "Animal" and "Dog"')
def given_animal_dog(ctx: dict) -> None:
    tax = Taxonomy()
    for name in ("Animal", "Dog"):
        tax.owl_classes[_uri(name)] = RDFClass(uri=_uri(name), labels=[Label("en", name)])
    ctx["taxonomy"] = tax


# ── When ──────────────────────────────────────────────────────────────────────


@when("I render the full VOWL graph HTML")
def when_render_full(ctx: dict) -> None:
    ctx["html"] = render_vowl_html(ctx["taxonomy"], file_path=None)


@when('I render a focused VOWL graph HTML rooted at "Animal"')
def when_render_focused(ctx: dict) -> None:
    ctx["html"] = render_vowl_html(ctx["taxonomy"], file_path=None, root_uri=_uri("Animal"))


@when('I render the query result VOWL graph HTML for "Animal"')
def when_render_query_result(ctx: dict) -> None:
    _, ctx["html"] = _build_query_result_html(ctx["taxonomy"], {_uri("Animal")})


# ── Then ──────────────────────────────────────────────────────────────────────


@then("the HTML contains a search input element")
def then_search_input_present(ctx: dict) -> None:
    assert 'id="search-box"' in ctx["html"]


@then("the HTML contains the searchNodes JavaScript function")
def then_search_fn_present(ctx: dict) -> None:
    assert "searchNodes" in ctx["html"]


@then("the HTML contains clearSearch called on the Escape key")
def then_clear_search_on_escape(ctx: dict) -> None:
    assert "clearSearch" in ctx["html"]
    assert "Escape" in ctx["html"]
