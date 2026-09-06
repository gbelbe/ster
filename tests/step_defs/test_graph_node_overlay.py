"""BDD step definitions for tests/features/owl/graph_node_overlay.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import Label, OWLIndividual, RDFClass, Taxonomy
from ster.viz_vowl import _app_js, render_vowl_html

scenarios("../features/owl/graph_node_overlay.feature")

NS = "https://example.org/onto#"


@pytest.fixture
def ctx() -> dict:
    return {}


def _fn_body(js: str, name: str) -> str:
    """Return the source of a top-level ``function <name>(`` up to the next ``\\nfunction ``."""
    start = js.index(f"function {name}(")
    nxt = js.find("\nfunction ", start + 1)
    return js[start : nxt if nxt != -1 else len(js)]


def _listener_body(js: str, var: str) -> str:
    """The source of ``<var>.addEventListener(...)`` up to the end of that statement."""
    start = js.index(f"{var}.addEventListener(")
    return js[start : js.index("\n", start)]


def _expression_around(js: str, *needles: str) -> str:
    """The source spanning both labels, plus the condition that precedes them.

    A ternary states its condition before either branch, so a window starting at
    the first label would miss the variable that chooses between them.
    """
    hits = [js.index(n) for n in needles]
    return js[max(0, min(hits) - 160) : max(hits) + 60]


def _tap_handler(js: str) -> str:
    """The source of the ``cy.on('tap','node',...)`` handler."""
    start = js.index("cy.on('tap','node'")
    return js[start : js.index("\n});", start)]


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
    assert "_savedGraph" in _expression_around(js, "explore relations", "extend relations")


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


# ── Then: the individuals button ──────────────────────────────────────────────


@then("the app wires the show-individuals label")
def then_show_label(ctx: dict) -> None:
    assert "show individuals" in ctx["js"]


@then("the app wires the hide-individuals label")
def then_hide_label(ctx: dict) -> None:
    assert "hide individuals" in ctx["js"]


@then("the individuals label depends on whether the class is already open")
def then_label_from_expanded(ctx: dict) -> None:
    """Both labels are chosen in one expression driven by the open-class set."""
    js = ctx["js"]
    assert "_expanded" in _expression_around(js, "show individuals", "hide individuals")


@then("the individuals button opens the class through the class-individuals fetch")
def then_button_toggles(ctx: dict) -> None:
    body = _listener_body(ctx["js"], "individualsBtn")
    assert "toggleClassIndividuals" in body
    assert "class-individuals" in _fn_body(ctx["js"], "toggleClassIndividuals")


@then("the individuals button is shown only when the node holds individuals")
def then_button_conditional(ctx: dict) -> None:
    body = _fn_body(ctx["js"], "_showOverlay")
    assert "individualCount" in body


@then("the individuals button is withheld when there is no api token")
def then_button_offline(ctx: dict) -> None:
    """Nothing to fetch offline, so the button would do nothing if offered."""
    assert "API_TOKEN" in _fn_body(ctx["js"], "_showOverlay")


# ── Then: clicking a node ─────────────────────────────────────────────────────


@then("the app defines a parent-chain walk")
def then_parent_chain_defined(ctx: dict) -> None:
    assert "function parentChain(" in ctx["js"]


@then("the highlight keeps the node and everything one step away")
def then_highlight_neighbourhood(ctx: dict) -> None:
    assert "neighborhood()" in _fn_body(ctx["js"], "applyHighlight")


@then("the highlight keeps the whole subClassOf chain above the node")
def then_highlight_parent_chain(ctx: dict) -> None:
    assert "parentChain(" in _fn_body(ctx["js"], "applyHighlight")


@then("the parent chain of an individual starts at the classes it instantiates")
def then_chain_seeds_from_type(ctx: dict) -> None:
    body = _fn_body(ctx["js"], "_highlightSeeds")
    assert "instanceOf" in body
    assert "subClassOf" in _fn_body(ctx["js"], "parentChain")


@then("tapping a node does not open its individuals")
def then_tap_does_not_open(ctx: dict) -> None:
    assert "toggleClassIndividuals" not in _tap_handler(ctx["js"])


@then("the app defines no hide-node-and-parents action")
def then_no_hide_action(ctx: dict) -> None:
    assert "hideNodeAndParents" not in ctx["js"]
    assert "releaseSharedParents" not in ctx["js"]


# ── Then: rendered page ───────────────────────────────────────────────────────


@then("the page contains the explore overlay button")
def then_has_explore_btn(ctx: dict) -> None:
    assert 'id="explore-btn"' in ctx["html"]


@then("the page contains the individuals overlay button")
def then_has_individuals_btn(ctx: dict) -> None:
    assert 'id="individuals-btn"' in ctx["html"]


@then("the page contains no hide overlay button")
def then_no_hide_btn(ctx: dict) -> None:
    assert 'id="hide-btn"' not in ctx["html"]
