"""Unit tests for GET /api/individual-relations — the expand-relations subgraph."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy

NS = "https://example.org/onto#"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def uri(name: str) -> str:
    return NS + name


def make_taxonomy() -> Taxonomy:
    t = Taxonomy()
    for c in ("Person", "Dog", "City"):
        t.owl_classes[uri(c)] = RDFClass(uri=uri(c), labels=[Label("en", c)])
    t.owl_properties[uri("owns")] = OWLProperty(uri=uri("owns"), labels=[Label("en", "owns")])
    t.owl_properties[uri("livesIn")] = OWLProperty(
        uri=uri("livesIn"), labels=[Label("en", "livesIn")]
    )
    for name, cls in (("Alice", "Person"), ("Fido", "Dog"), ("Paris", "City"), ("Bob", "Person")):
        t.owl_individuals[uri(name)] = OWLIndividual(
            uri=uri(name), labels=[Label("en", name)], types=[uri(cls)]
        )
    t.owl_individuals[uri("Fido")].property_values.append((uri("owns"), uri("Alice")))
    t.owl_individuals[uri("Alice")].property_values.append((uri("livesIn"), uri("Paris")))
    return t


@pytest.fixture
def client():
    return TestClient(create_app(make_taxonomy(), TOKEN, SSEBroadcaster(), lambda t: None))


def test_relations_requires_auth(client):
    r = client.get("/api/individual-relations", params={"uri": uri("Alice")})
    assert r.status_code == 401


def test_relations_wrong_token_401(client):
    r = client.get(
        "/api/individual-relations",
        params={"uri": uri("Alice")},
        headers={"Authorization": "Bearer bad"},
    )
    assert r.status_code == 401


def test_relations_returns_subgraph(client):
    r = client.get("/api/individual-relations", params={"uri": uri("Alice")}, headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    ids = {n["id"] for n in data["nodes"]}
    assert uri("Alice") in ids
    assert uri("Fido") in ids
    assert uri("Paris") in ids
    assert uri("Bob") not in ids


def test_relations_includes_directed_object_property_edge(client):
    data = client.get(
        "/api/individual-relations", params={"uri": uri("Alice")}, headers=AUTH
    ).json()
    assert any(
        e["source"] == uri("Fido") and e["target"] == uri("Alice") and e["label"] == "owns"
        for e in data["edges"]
    )


def test_relations_unknown_uri_returns_empty(client):
    data = client.get(
        "/api/individual-relations", params={"uri": uri("Ghost")}, headers=AUTH
    ).json()
    assert data["nodes"] == []
    assert data["edges"] == []
