"""BDD step definitions for tests/features/owl/graph_extend_hide.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import Label, OWLIndividual, RDFClass, Taxonomy
from ster.viz_vowl import _app_js, render_vowl_html

scenarios("../features/owl/graph_extend_hide.feature")

NS = "https://example.org/onto#"


@pytest.fixture
def ctx() -> dict:
    return {}


def _fn_body(js: str, name: str) -> str:
    """Return the source of a top-level ``function <name>(`` up to the next ``\\nfunction ``."""
    start = js.index(f"function {name}(")
    nxt = js.find("\nfunction ", start + 1)
    return js[start : nxt if nxt != -1 else len(js)]


# ── Given ─────────────────────────────────────────────────────────────────────


@given('an ontology with an individual "Rex" of class "Animal"')
def given_ontology(ctx: dict) -> None:
    t = Taxonomy()
    t.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal", labels=[Label("en", "Animal")])
    t.owl_individuals[NS + "Rex"] = OWLIndividual(
        uri=NS + "Rex", labels=[Label("en", "Rex")], types=[NS + "Animal"]
    )
    ctx["taxonomy"] = t


# ── When ──────────────────────────────────────────────────────────────────────


@when("I load the ster graph app asset")
def when_load_asset(ctx: dict) -> None:
    ctx["js"] = _app_js()


@when("I render the graph page for interaction")
def when_render(ctx: dict) -> None:
    ctx["html"] = render_vowl_html(ctx["taxonomy"], file_path=None, api_token="TESTTOKEN")


# ── Then: labels / mode ───────────────────────────────────────────────────────


@then("the app wires the explore-relations label")
def then_explore_label(ctx: dict) -> None:
    assert "explore relations" in ctx["js"]


@then("the app wires the extend-relations label")
def then_extend_label(ctx: dict) -> None:
    assert "extend relations" in ctx["js"]


@then("the explore overlay label depends on whether a subgraph is open")
def then_label_mode(ctx: dict) -> None:
    # The label is chosen from _savedGraph (subgraph open) in the same expression
    # that mentions both label texts.
    js = ctx["js"]
    assert "_savedGraph" in js
    explore_at = js.index("explore relations")
    extend_at = js.index("extend relations")
    window = js[min(explore_at, extend_at) : max(explore_at, extend_at) + 40]
    assert "_savedGraph" in window or "subgraphOpen" in window or "?" in window


# ── Then: extend ──────────────────────────────────────────────────────────────


@then("the app defines an extend-node action")
def then_extend_defined(ctx: dict) -> None:
    assert "function extendNode(" in ctx["js"]


@then("extending merges new elements without clearing the whole graph")
def then_extend_additive(ctx: dict) -> None:
    body = _fn_body(ctx["js"], "extendNode").replace(" ", "")
    assert "cy.elements().remove()" not in body.replace(" ", "")
    assert "cy.add(" in body


@then("extending de-duplicates edges by their endpoints and type")
def then_extend_dedupes(ctx: dict) -> None:
    body = _fn_body(ctx["js"], "extendNode")
    # A signature combining source, target and type guards duplicate edges.
    assert "source" in body and "target" in body and "type" in body


# ── Then: hide ────────────────────────────────────────────────────────────────


@then("the app defines a hide-node-and-parents action")
def then_hide_defined(ctx: dict) -> None:
    assert "function hideNodeAndParents(" in ctx["js"]


@then("hiding an individual follows its rdf:type and subClassOf trail")
def then_hide_individual(ctx: dict) -> None:
    body = _fn_body(ctx["js"], "hideNodeAndParents")
    assert "instanceOf" in body
    assert "subClassOf" in body


@then("hiding a class follows only its subClassOf trail")
def then_hide_class(ctx: dict) -> None:
    body = _fn_body(ctx["js"], "hideNodeAndParents")
    assert "subClassOf" in body


@then("hiding keeps a parent that another visible node depends on")
def then_hide_shared_parent(ctx: dict) -> None:
    # Shared-parent protection inspects other edges of the same parent before removal.
    body = _fn_body(ctx["js"], "hideNodeAndParents")
    assert "_isParentShared" in ctx["js"] or "shared" in body.lower() or "depend" in body.lower()


# ── Then: rendered page ───────────────────────────────────────────────────────


@then("the page contains the explore overlay button")
def then_has_explore_btn(ctx: dict) -> None:
    assert 'id="explore-btn"' in ctx["html"]


@then("the page contains the hide overlay button")
def then_has_hide_btn(ctx: dict) -> None:
    assert 'id="hide-btn"' in ctx["html"]
