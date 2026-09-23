"""GET /api/has-relations — whether "explore relations" would show anything.

The hover overlay offered "explore relations" on every node, including ones
with nothing to explore, which opened an empty view. The answer comes from the
same builder the explore action uses, so the button and the action can never
disagree. It is asked per node on hover, not for every node up front: running
the builders over a 22k-node ontology took 145 s, one node takes milliseconds.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import (
    Concept,
    ConceptScheme,
    Label,
    LabelType,
    OWLIndividual,
    OWLProperty,
    RDFClass,
    Taxonomy,
)
from ster.viz_vowl import _app_js

NS = "https://example.org/onto#"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def uri(name: str) -> str:
    return NS + name


def make_taxonomy() -> Taxonomy:
    t = Taxonomy()
    t.owl_classes[uri("Agent")] = RDFClass(uri=uri("Agent"), labels=[Label("en", "Agent")])
    t.owl_classes[uri("Person")] = RDFClass(
        uri=uri("Person"), labels=[Label("en", "Person")], sub_class_of=[uri("Agent")]
    )
    t.owl_classes[uri("Lonely")] = RDFClass(uri=uri("Lonely"), labels=[Label("en", "Lonely")])
    t.owl_properties[uri("knows")] = OWLProperty(
        uri=uri("knows"), prop_type="ObjectProperty", labels=[Label("en", "knows")]
    )
    t.owl_individuals[uri("ann")] = OWLIndividual(
        uri=uri("ann"),
        types=[uri("Person")],
        labels=[Label("en", "Ann")],
        property_values=[(uri("knows"), uri("bob"))],
    )
    t.owl_individuals[uri("bob")] = OWLIndividual(uri=uri("bob"), types=[uri("Person")])
    t.owl_individuals[uri("hermit")] = OWLIndividual(uri=uri("hermit"))
    t.schemes[uri("S")] = ConceptScheme(uri=uri("S"), labels=[Label("en", "S")])
    t.concepts[uri("Parent")] = Concept(
        uri=uri("Parent"), labels=[Label("en", "Parent", LabelType.PREF)], narrower=[uri("Child")]
    )
    t.concepts[uri("Child")] = Concept(
        uri=uri("Child"), labels=[Label("en", "Child", LabelType.PREF)], broader=[uri("Parent")]
    )
    t.concepts[uri("Alone")] = Concept(
        uri=uri("Alone"), labels=[Label("en", "Alone", LabelType.PREF)]
    )
    return t


@pytest.fixture
def client():
    return TestClient(create_app(make_taxonomy(), TOKEN, SSEBroadcaster(), lambda t: None))


def _ask(client, name: str, kind: str):
    return client.get("/api/has-relations", params={"uri": uri(name), "type": kind}, headers=AUTH)


def test_it_requires_auth(client) -> None:
    response = client.get("/api/has-relations", params={"uri": uri("Person"), "type": "class"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("name", "kind", "expected"),
    [
        ("Person", "class", True),  # subClassOf Agent
        ("Lonely", "class", False),
        ("ann", "individual", True),  # knows bob
        ("hermit", "individual", False),
        ("Parent", "concept", True),  # narrower Child
        ("Alone", "concept", False),
        ("Parent", "topconcept", True),
    ],
)
def test_it_says_whether_explore_would_show_anything(client, name, kind, expected) -> None:
    response = _ask(client, name, kind)
    assert response.status_code == 200
    assert response.json() == {"relations": expected}


def test_it_agrees_with_the_explore_action(client) -> None:
    """Same builder, so a "no" means the explore view really would be empty."""
    explore = client.get("/api/class-links", params={"uri": uri("Lonely")}, headers=AUTH).json()
    assert explore["edges"] == []
    assert _ask(client, "Lonely", "class").json() == {"relations": False}


def test_a_type_explore_does_not_handle_is_refused(client) -> None:
    assert _ask(client, "knows", "property").status_code == 422


# ── the page: ask on hover, remember the answer ─────────────────────────────


def test_the_overlay_asks_before_offering_explore() -> None:
    js = _app_js()
    assert "/api/has-relations" in js
    assert "_relationsKnown" in js, "answers are cached per node"


def test_explore_stays_hidden_until_the_answer_is_yes() -> None:
    js = _app_js().replace(" ", "")
    assert "exploreBtn.style.display='none'" in js
    assert "if(has)exploreBtn.style.display='block'" in js
