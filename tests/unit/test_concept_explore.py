"""Digging through a SKOS hierarchy: click to select, explore to walk a level.

Concepts had no explore endpoint, so on a thesaurus the hover overlay could not
expand anything — the only expandable kinds were OWL individuals and classes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Concept, ConceptScheme, Label, LabelType, Taxonomy
from ster.viz_vowl import _app_js, build_concept_relations_graph

NS = "https://example.org/gear#"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _lbl(value: str) -> Label:
    return Label(lang="en", value=value, type=LabelType.PREF)


@pytest.fixture
def tree() -> Taxonomy:
    """Scheme → Gear → {Tent, Pack} → DomeTent, i.e. three levels below a root."""
    tax = Taxonomy()
    tax.schemes[NS + "Scheme"] = ConceptScheme(uri=NS + "Scheme", labels=[_lbl("Gear Scheme")])
    tax.concepts[NS + "Gear"] = Concept(
        uri=NS + "Gear",
        labels=[_lbl("Gear")],
        top_concept_of=NS + "Scheme",
        narrower=[NS + "Tent", NS + "Pack"],
    )
    tax.concepts[NS + "Tent"] = Concept(
        uri=NS + "Tent", labels=[_lbl("Tent")], broader=[NS + "Gear"], narrower=[NS + "DomeTent"]
    )
    tax.concepts[NS + "Pack"] = Concept(
        uri=NS + "Pack", labels=[_lbl("Pack")], broader=[NS + "Gear"]
    )
    tax.concepts[NS + "DomeTent"] = Concept(
        uri=NS + "DomeTent", labels=[_lbl("Dome Tent")], broader=[NS + "Tent"]
    )
    return tax


def _labels(graph: dict) -> set[str]:
    return {n["label"] for n in graph["nodes"]}


def test_explore_includes_focus_broader_chain_and_direct_narrower(tree):
    graph = build_concept_relations_graph(tree, NS + "Tent")

    assert _labels(graph) == {"Tent", "Gear", "Dome Tent"}


def test_explore_stops_at_direct_narrower(tree):
    """One level per step, or exploring a root returns most of the thesaurus."""
    tree.concepts[NS + "Micro"] = Concept(
        uri=NS + "Micro", labels=[_lbl("Micro")], broader=[NS + "DomeTent"]
    )

    graph = build_concept_relations_graph(tree, NS + "Tent")

    assert "Micro" not in _labels(graph)


def test_explore_marks_a_top_concept(tree):
    graph = build_concept_relations_graph(tree, NS + "Tent")

    kinds = {n["label"]: n["type"] for n in graph["nodes"]}
    assert kinds["Gear"] == "topconcept"
    assert kinds["Tent"] == "concept"


def test_explore_emits_broader_edges_child_to_parent(tree):
    graph = build_concept_relations_graph(tree, NS + "Tent")

    pairs = {(e["source"], e["target"]) for e in graph["edges"]}
    assert (NS + "Tent", NS + "Gear") in pairs
    assert (NS + "DomeTent", NS + "Tent") in pairs
    assert all(e["type"] == "broader" for e in graph["edges"])


def test_explore_finds_children_that_only_declare_broader(tree):
    """A file may assert one side of the relation; both must dig down."""
    tree.concepts[NS + "Tarp"] = Concept(
        uri=NS + "Tarp", labels=[_lbl("Tarp")], broader=[NS + "Tent"]
    )

    assert "Tarp" in _labels(build_concept_relations_graph(tree, NS + "Tent"))


def test_explore_survives_a_broader_cycle(tree):
    """A malformed thesaurus must not hang the server."""
    tree.concepts[NS + "Gear"].broader = [NS + "Tent"]

    graph = build_concept_relations_graph(tree, NS + "Tent")

    assert "Tent" in _labels(graph)


def test_explore_of_an_unknown_uri_is_empty(tree):
    assert build_concept_relations_graph(tree, NS + "Nope")["nodes"] == []


# ── API ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(tree):
    return TestClient(create_app(tree, TOKEN, SSEBroadcaster(), lambda t: None))


def test_concept_relations_requires_auth(client):
    assert client.get("/api/concept-relations", params={"uri": NS + "Tent"}).status_code == 401


def test_concept_relations_returns_the_subgraph(client, tree):
    resp = client.get("/api/concept-relations", params={"uri": NS + "Tent"}, headers=AUTH)

    assert resp.status_code == 200
    assert _labels(resp.json()) == {"Tent", "Gear", "Dome Tent"}


# ── client wiring ─────────────────────────────────────────────────────────────


def test_app_js_routes_concepts_to_the_explore_endpoint():
    js = _app_js()

    assert "/api/concept-relations" in js
    assert "concept:'/api/concept-relations'" in js
    assert "topconcept:'/api/concept-relations'" in js


def _tap_handler(js: str) -> str:
    """The tap-on-node handler alone, so an assertion cannot match elsewhere."""
    start = js.index("cy.on('tap','node'")
    return js[start : js.index("\n});", start)]


def test_app_js_taps_select_rather_than_explore():
    """A stray click must not change the shape of the graph; that stays on the overlay.

    Tapping used to open a collapsed class's individuals as well as selecting it.
    That moved to the overlay's own button, so the handler now does one thing:
    select. Asserted as behaviour rather than as a literal handler, which is what
    it always meant.
    """
    js = _app_js().replace(" ", "")

    assert "cy.on('tap','node',e=>{" in js
    assert "selectNode(" in js
    assert "toggleClassIndividuals" not in _tap_handler(js)
    assert "function selectNode(" in js.replace("functionselectNode(", "function selectNode(")
    # the swap-the-graph paths must stay off the tap handler
    assert "cy.on('tap','node',e=>activateNode(" not in js
    assert "cy.on('tap','node',e=>exploreOrExtend(" not in js


def test_app_js_select_dims_all_but_the_neighbourhood():
    js = _app_js()

    assert "cy.elements().addClass('dimmed');" in js
    assert "n.neighborhood().add(n).removeClass('dimmed');" in js


def test_a_dimmed_node_is_still_a_click_target():
    """Dimming recedes a node; it does not take it out of play.

    Nodes once carried events:'no' while dimmed, because at 8% opacity an
    invisible node overlapping a bright one stole the click. The cost was worse
    than the fix: a click on a dimmed node fell through to the canvas and cleared
    the selection, so reaching a neighbour meant starting over. Hover highlighting
    solves the original problem properly — you always see what is under the
    cursor before you commit to it.
    """
    js = _app_js().replace(" ", "")

    assert "'events':'no'" not in js.split("edge.dimmed")[0], "nodes must stay clickable"


def test_dimmed_edges_still_ignore_pointer_events():
    """Edges are not click targets here, and a dimmed one only steals from nodes."""
    assert "{selector:'edge.dimmed',style:{'opacity':.04,'events':'no'}}" in _app_js().replace(
        " ", ""
    )


def test_a_dimmed_node_stays_visible_enough_to_aim_at():
    """8% opacity read as "hidden" — you cannot deliberately click what you cannot see."""
    js = _app_js().replace(" ", "")

    assert "{selector:'node.dimmed',style:{'opacity':.15}}" in js


def test_hovering_a_node_highlights_it():
    js = _app_js().replace(" ", "")

    assert "addClass('hovered')" in js
    assert "removeClass('hovered')" in js


def test_a_hovered_node_is_fully_opaque_whatever_its_state():
    """The point of the highlight: a dimmed node under the cursor becomes readable."""
    js = _app_js().replace(" ", "")

    assert "selector:'node.hovered'" in js
    assert "'opacity':1" in js.split("node.hovered")[1][:200]


def test_the_cursor_says_a_node_can_be_clicked():
    assert "cursor='pointer'" in _app_js().replace(" ", "")
