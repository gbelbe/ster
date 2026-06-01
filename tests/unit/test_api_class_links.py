"""Unit tests for GET /api/class-links — the class linked-classes subgraph."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Label, OWLProperty, RDFClass, Taxonomy

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
    t.owl_classes[uri("Pet")] = RDFClass(uri=uri("Pet"), labels=[Label("en", "Pet")])
    t.owl_classes[uri("Unrelated")] = RDFClass(uri=uri("Unrelated"), labels=[Label("en", "U")])
    t.owl_properties[uri("owns")] = OWLProperty(
        uri=uri("owns"),
        prop_type="ObjectProperty",
        labels=[Label("en", "owns")],
        domains=[uri("Person")],
        ranges=[uri("Pet")],
    )
    return t


@pytest.fixture
def client():
    return TestClient(create_app(make_taxonomy(), TOKEN, SSEBroadcaster(), lambda t: None))


def test_class_links_requires_auth(client):
    assert client.get("/api/class-links", params={"uri": uri("Person")}).status_code == 401


def test_class_links_wrong_token_401(client):
    r = client.get(
        "/api/class-links",
        params={"uri": uri("Person")},
        headers={"Authorization": "Bearer bad"},
    )
    assert r.status_code == 401


def test_class_links_returns_subgraph(client):
    r = client.get("/api/class-links", params={"uri": uri("Person")}, headers=AUTH)
    assert r.status_code == 200
    ids = {n["id"] for n in r.json()["nodes"]}
    assert uri("Person") in ids
    assert uri("Agent") in ids
    assert uri("Pet") in ids
    assert uri("Unrelated") not in ids


def test_class_links_unknown_uri_returns_empty(client):
    data = client.get("/api/class-links", params={"uri": uri("Ghost")}, headers=AUTH).json()
    assert data["nodes"] == []
    assert data["edges"] == []
