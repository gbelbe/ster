"""The graph view can be drawn from a query, not only from the model.

The model walk answers "what does ster understand about this ontology". It
reaches only what the typed model holds, so anything the model has no field for
— a relation between context files, a reasoner's output, an arbitrary predicate
— is invisible to it however plainly it sits in the graph.

A CONSTRUCT reaches all of it, and returns triples, which already *are* nodes
and edges. The map takes SELECT because it needs ?lat and ?long by name; a
graph wants a subgraph. Each view asks in the shape of its answer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ster import store
from ster.api import SSEBroadcaster, create_app
from ster.viz_vowl import graph_from_query

E = "https://example.org/#"
AUTH = {"Authorization": "Bearer t"}

MAIN = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/#> .
ex:O a owl:Ontology .
ex:Shop  a owl:Class ; rdfs:label "Shop"@en .
ex:Paint a owl:Class ; rdfs:label "Paint"@en ; rdfs:subClassOf ex:Shop .
ex:alpha a owl:NamedIndividual, ex:Shop ; rdfs:label "Alpha"@en .
"""

CTX = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/#> .
ex:V a owl:Ontology .
ex:Rival a owl:Class ; rdfs:label "Rival"@en .
ex:alpha ex:competesWith ex:Rival .
"""

CLASSES = (
    "PREFIX owl: <http://www.w3.org/2002/07/owl#> "
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
    "CONSTRUCT { ?s a owl:Class ; rdfs:label ?l } "
    "WHERE { ?s a owl:Class OPTIONAL { ?s rdfs:label ?l } }"
)
COMPETITORS = ("alpha", "Rival")  # the two ends of the one competesWith in the fixtures
COMPETES = (
    "PREFIX ex: <https://example.org/#> "
    "CONSTRUCT { ?a ex:competesWith ?b } WHERE { ?a ex:competesWith ?b }"
)


@pytest.fixture
def tax(tmp_path):
    main, ctx = tmp_path / "main.ttl", tmp_path / "ctx.ttl"
    main.write_text(MAIN, encoding="utf-8")
    ctx.write_text(CTX, encoding="utf-8")
    return store.load(main, context=[ctx]), main, ctx


@pytest.fixture
def client(tax):
    loaded, main, _ctx = tax
    return TestClient(create_app(loaded, "t", SSEBroadcaster(), lambda t: None, file_path=main))


# ── what a query can draw that the model walk cannot ────────────────────────


def test_a_relation_the_model_does_not_type_is_drawn(tax):
    """ex:competesWith has no field on any dataclass. The model walk cannot
    show it; the graph plainly contains it."""
    loaded, _m, _c = tax

    g = graph_from_query(loaded, COMPETES)

    assert {n["label"] for n in g["nodes"]} == {"Alpha", "Rival"}
    assert [e["type"] for e in g["edges"]] == ["competesWith"]


def test_a_context_entity_is_marked_read_only(tax):
    """Dimmed for the same reason the model builder dims it: a node you cannot
    edit must not look like one you can, whichever path drew it."""
    loaded, _m, _c = tax

    g = graph_from_query(loaded, CLASSES)
    rival = next(n for n in g["nodes"] if n["label"] == "Rival")

    assert rival["readOnly"] == 1
    assert next(n for n in g["nodes"] if n["label"] == "Shop")["readOnly"] == 0


def test_a_label_is_shown_as_a_name_not_a_literal(tax):
    """CONSTRUCT output is stringified N-Triples, so a label arrives as
    '"Shop"@en'. The quoting and tag are serialisation, not the name."""
    loaded, _m, _c = tax

    labels = {n["label"] for n in graph_from_query(loaded, CLASSES)["nodes"]}

    assert "Shop" in labels
    assert not any(lbl.startswith('"') for lbl in labels)


def test_a_node_with_no_label_falls_back_to_its_local_name(tax):
    loaded, _m, _c = tax

    g = graph_from_query(
        loaded,
        "PREFIX ex: <https://example.org/#> CONSTRUCT { ?a ex:competesWith ?b } "
        "WHERE { ?a ex:competesWith ?b }",
    )

    assert all(n["label"] and not n["label"].startswith("http") for n in g["nodes"])


def test_an_edge_target_becomes_a_node_even_if_unmentioned(tax):
    """Cytoscape silently discards an edge whose endpoint is missing, so the
    answer would look smaller than it is."""
    loaded, _m, _c = tax

    g = graph_from_query(loaded, COMPETES)
    ids = {n["id"] for n in g["nodes"]}

    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])


# ── through the endpoint ────────────────────────────────────────────────────


def test_without_a_query_the_model_walk_still_answers(client):
    """Additive: the default view is untouched."""
    body = client.get("/api/graph", headers=AUTH).json()

    assert body["nodes"]
    assert "error" not in body


def test_a_query_replaces_the_model_walk(client):
    from_model = client.get("/api/graph", headers=AUTH).json()
    from_query = client.get("/api/graph", params={"q": COMPETES}, headers=AUTH).json()

    assert len(from_query["nodes"]) == len(COMPETITORS)
    assert len(from_query["nodes"]) != len(from_model["nodes"])


def test_a_broken_query_returns_an_empty_graph_and_the_reason(client):
    """Not a 500 and not a blank page: the page needs something to show."""
    body = client.get("/api/graph", params={"q": "CONSTRUCT {{{"}, headers=AUTH).json()

    assert body["nodes"] == []
    assert "error" in body


def test_a_write_query_is_refused_here_too(client):
    """The graph endpoint reaches the same executor, so the read-only guard
    covers it without being remembered a second time."""
    body = client.get("/api/graph", params={"q": "DELETE WHERE { ?s ?p ?o }"}, headers=AUTH).json()

    assert body["nodes"] == []
    assert "error" in body


# ── naming what the model does not hold ─────────────────────────────────────

CTX_PEOPLE = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/#> .
ex:Team rdfs:label "Team"@en .
ex:red a ex:Team ; rdfs:label "Red team"@en .
ex:red ex:runs ex:alpha .
"""
RUNS = "PREFIX ex: <https://example.org/#> CONSTRUCT { ?t ex:runs ?s } WHERE { ?t ex:runs ?s }"


@pytest.fixture
def with_people(tmp_path):
    main, ctx = tmp_path / "main.ttl", tmp_path / "people.ttl"
    main.write_text(MAIN, encoding="utf-8")
    ctx.write_text(CTX_PEOPLE, encoding="utf-8")
    return store.load(main, context=[ctx])


def test_a_context_individual_is_named_from_the_graph(with_people):
    """The model holds only the main file's entities; a node from reference data
    loaded beside it would otherwise read as an identifier."""
    labels = {n["label"] for n in graph_from_query(with_people, RUNS)["nodes"]}

    assert labels == {"Red team", "Alpha"}


def test_an_individual_says_what_kind_of_thing_it_is(with_people):
    """So the page can tell a team from a shop without opening each node."""
    nodes = {n["label"]: n for n in graph_from_query(with_people, RUNS)["nodes"]}

    assert nodes["Red team"]["kind"] == "Team"


def test_an_edge_is_labelled_with_its_relation(tax):
    loaded, _m, _c = tax

    g = graph_from_query(loaded, COMPETES)

    assert [e["label"] for e in g["edges"]] == ["competesWith"]
