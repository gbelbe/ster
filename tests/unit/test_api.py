"""Unit tests for the ster ontology REST API (sync endpoints).

Tests cover: schema introspection, individual CRUD, auth, slugify helpers.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, _slugify, _unique_uri, create_app
from ster.model import Label, LabelType, OWLIndividual, OWLProperty, RDFClass, Taxonomy

NS = "https://example.org/onto#"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def uri(name: str) -> str:
    return NS + name


def make_taxonomy() -> Taxonomy:
    t = Taxonomy()
    t.namespace_bindings[""] = NS
    for name in ("Animal", "Dog", "Cat", "Tool", "Hammer"):
        t.owl_classes[uri(name)] = RDFClass(
            uri=uri(name),
            labels=[Label(lang="en", value=name, type=LabelType.PREF)],
        )
    t.owl_classes[uri("Dog")].sub_class_of = [uri("Animal")]
    t.owl_classes[uri("Cat")].sub_class_of = [uri("Animal")]
    t.owl_classes[uri("Hammer")].sub_class_of = [uri("Tool")]
    t.owl_properties[uri("uses")] = OWLProperty(
        uri=uri("uses"),
        prop_type="ObjectProperty",
        labels=[Label(lang="en", value="uses", type=LabelType.PREF)],
        domains=[uri("Dog")],
        ranges=[uri("Hammer")],
    )
    return t


@pytest.fixture
def app():
    tax = make_taxonomy()
    bc = SSEBroadcaster()
    return create_app(tax, TOKEN, bc, lambda t: None)


@pytest.fixture
def client(app):
    return TestClient(app)


# ── Schema: GET /api/classes ──────────────────────────────────────────────────


def test_get_classes_returns_200(client):
    assert client.get("/api/classes", headers=AUTH).status_code == 200


def test_get_classes_contains_expected_uris(client):
    data = client.get("/api/classes", headers=AUTH).json()
    uris = {c["uri"] for c in data["classes"]}
    for name in ("Animal", "Dog", "Cat", "Tool", "Hammer"):
        assert uri(name) in uris


def test_get_classes_hierarchy_sub_class_of(client):
    data = client.get("/api/classes", headers=AUTH).json()
    by_uri = {c["uri"]: c for c in data["classes"]}
    assert uri("Animal") in by_uri[uri("Dog")]["sub_class_of"]
    assert uri("Tool") in by_uri[uri("Hammer")]["sub_class_of"]


def test_get_classes_hierarchy_child_classes(client):
    data = client.get("/api/classes", headers=AUTH).json()
    by_uri = {c["uri"]: c for c in data["classes"]}
    animal_children = by_uri[uri("Animal")]["child_classes"]
    assert uri("Dog") in animal_children
    assert uri("Cat") in animal_children


def test_get_class_detail_single_result(client):
    r = client.get("/api/classes", headers=AUTH, params={"uri": uri("Dog")})
    assert r.status_code == 200
    classes = r.json()["classes"]
    assert len(classes) == 1
    assert classes[0]["uri"] == uri("Dog")


def test_get_class_detail_includes_applicable_property(client):
    r = client.get("/api/classes", headers=AUTH, params={"uri": uri("Dog")})
    props = r.json()["classes"][0]["applicable_properties"]
    prop_uris = [p["uri"] for p in props]
    assert uri("uses") in prop_uris


def test_get_class_detail_property_range(client):
    r = client.get("/api/classes", headers=AUTH, params={"uri": uri("Dog")})
    props = {p["uri"]: p for p in r.json()["classes"][0]["applicable_properties"]}
    assert props[uri("uses")]["range_uri"] == uri("Hammer")
    assert props[uri("uses")]["range_label"] == "Hammer"


def test_get_class_detail_unknown_uri_404(client):
    r = client.get("/api/classes", headers=AUTH, params={"uri": uri("Ghost")})
    assert r.status_code == 404


def test_get_classes_no_auth_401(client):
    assert client.get("/api/classes").status_code == 401


def test_get_classes_wrong_token_401(client):
    r = client.get("/api/classes", headers={"Authorization": "Bearer bad-token"})
    assert r.status_code == 401


# ── Individuals: POST /api/individuals ───────────────────────────────────────


def test_create_individual_returns_201(client):
    body = {"class_uri": uri("Dog"), "labels": [{"lang": "en", "value": "Fido"}]}
    assert client.post("/api/individuals", json=body, headers=AUTH).status_code == 201


def test_create_individual_response_has_uri(client):
    body = {"class_uri": uri("Dog"), "labels": [{"lang": "en", "value": "Fido"}]}
    r = client.post("/api/individuals", json=body, headers=AUTH)
    assert "uri" in r.json()


def test_create_individual_uri_from_local_name(client):
    body = {
        "class_uri": uri("Dog"),
        "local_name": "RexTheDog",
        "labels": [{"lang": "en", "value": "Rex"}],
    }
    r = client.post("/api/individuals", json=body, headers=AUTH)
    assert r.json()["uri"].endswith("RexTheDog")


def test_create_individual_uri_slugified_from_label(client):
    body = {"class_uri": uri("Dog"), "labels": [{"lang": "en", "value": "Fido Smith"}]}
    r = client.post("/api/individuals", json=body, headers=AUTH)
    assert r.json()["uri"].endswith("Fido_Smith")


def test_create_individual_uri_collision_appends_suffix(app):
    client = TestClient(app)
    body = {"class_uri": uri("Dog"), "local_name": "Buddy"}
    client.post("/api/individuals", json=body, headers=AUTH)
    r = client.post("/api/individuals", json=body, headers=AUTH)
    assert r.status_code == 201
    assert r.json()["uri"].endswith("Buddy_1")


def test_create_individual_missing_class_uri_422(client):
    r = client.post(
        "/api/individuals",
        json={"labels": [{"lang": "en", "value": "X"}]},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_create_individual_unknown_class_uri_422(client):
    r = client.post(
        "/api/individuals",
        json={"class_uri": uri("Ghost"), "labels": [{"lang": "en", "value": "X"}]},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_create_individual_with_property_values(app):
    client = TestClient(app)
    r1 = client.post(
        "/api/individuals",
        json={"class_uri": uri("Tool"), "local_name": "Hammer1"},
        headers=AUTH,
    )
    hammer_uri = r1.json()["uri"]
    r2 = client.post(
        "/api/individuals",
        json={
            "class_uri": uri("Dog"),
            "local_name": "Rex",
            "property_values": [{"property_uri": uri("uses"), "target_uri": hammer_uri}],
        },
        headers=AUTH,
    )
    assert r2.status_code == 201
    pv = r2.json()["property_values"]
    assert len(pv) == 1
    assert pv[0]["property_uri"] == uri("uses")
    assert pv[0]["target_uri"] == hammer_uri


def test_create_individual_no_auth_401(client):
    body = {"class_uri": uri("Dog"), "labels": [{"lang": "en", "value": "X"}]}
    assert client.post("/api/individuals", json=body).status_code == 401


# ── Individuals: GET /api/individuals ────────────────────────────────────────


def test_get_individuals_returns_list(client):
    r = client.get("/api/individuals", headers=AUTH)
    assert r.status_code == 200
    assert "individuals" in r.json()


def test_get_individuals_contains_created(app):
    client = TestClient(app)
    client.post(
        "/api/individuals", json={"class_uri": uri("Dog"), "local_name": "Buddy"}, headers=AUTH
    )
    r = client.get("/api/individuals", headers=AUTH)
    uris_ = [i["uri"] for i in r.json()["individuals"]]
    assert any(u.endswith("Buddy") for u in uris_)


def test_get_individuals_filtered_by_type(app):
    client = TestClient(app)
    client.post(
        "/api/individuals", json={"class_uri": uri("Dog"), "local_name": "Buddy"}, headers=AUTH
    )
    client.post(
        "/api/individuals", json={"class_uri": uri("Tool"), "local_name": "Hammer1"}, headers=AUTH
    )
    r = client.get("/api/individuals", headers=AUTH, params={"type": uri("Dog")})
    ind_uris = [i["uri"] for i in r.json()["individuals"]]
    assert any(u.endswith("Buddy") for u in ind_uris)
    assert not any(u.endswith("Hammer1") for u in ind_uris)


# ── Graph: GET /api/graph ─────────────────────────────────────────────────────


def test_get_graph_returns_200(client):
    assert client.get("/api/graph", headers=AUTH).status_code == 200


def test_get_graph_has_nodes_and_edges(client):
    data = client.get("/api/graph", headers=AUTH).json()
    assert "nodes" in data
    assert "edges" in data


# ── SSE: GET /api/events ──────────────────────────────────────────────────────


def test_sse_endpoint_returns_event_stream(app):
    """SSE endpoint must return 200 and text/event-stream content type."""
    from unittest.mock import patch

    async def _one_shot():
        yield 'data: {"type": "test"}\n\n'

    with patch.object(SSEBroadcaster, "subscribe", return_value=_one_shot()):
        r = TestClient(app).get(f"/api/events?token={TOKEN}")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]


def test_sse_wrong_token_401(client):
    r = client.get("/api/events?token=bad")
    assert r.status_code == 401


# ── Helpers ───────────────────────────────────────────────────────────────────


def test_slugify_plain():
    assert _slugify("Hello World") == "Hello_World"


def test_slugify_accented_chars():
    assert _slugify("Château") == "Chateau"


def test_slugify_special_chars():
    assert _slugify("foo!bar?baz") == "foo_bar_baz"


def test_slugify_empty_returns_individual():
    assert _slugify("") == "individual"


def test_unique_uri_no_collision():
    tax = Taxonomy()
    assert _unique_uri(tax, NS, "Fido") == NS + "Fido"


def test_unique_uri_first_collision():
    tax = Taxonomy()
    tax.owl_individuals[NS + "Fido"] = OWLIndividual(uri=NS + "Fido", types=[])
    assert _unique_uri(tax, NS, "Fido") == NS + "Fido_1"


def test_unique_uri_multiple_collisions():
    tax = Taxonomy()
    tax.owl_individuals[NS + "Fido"] = OWLIndividual(uri=NS + "Fido", types=[])
    tax.owl_individuals[NS + "Fido_1"] = OWLIndividual(uri=NS + "Fido_1", types=[])
    assert _unique_uri(tax, NS, "Fido") == NS + "Fido_2"


# ── POST side-effects: save callback and SSE broadcast ───────────────────────


def test_create_individual_calls_save_fn():
    from unittest.mock import MagicMock

    save_fn = MagicMock()
    tax = make_taxonomy()
    client = TestClient(create_app(tax, TOKEN, SSEBroadcaster(), save_fn))
    client.post(
        "/api/individuals",
        json={"class_uri": uri("Dog"), "labels": [{"lang": "en", "value": "Fido"}]},
        headers=AUTH,
    )
    save_fn.assert_called_once_with(tax)


def test_create_individual_broadcasts_to_sse_queue():
    import asyncio

    bc = SSEBroadcaster()
    q: asyncio.Queue = asyncio.Queue()
    bc._queues.append(q)
    client = TestClient(create_app(make_taxonomy(), TOKEN, bc, lambda _: None))
    client.post(
        "/api/individuals",
        json={"class_uri": uri("Dog"), "labels": [{"lang": "en", "value": "Fido"}]},
        headers=AUTH,
    )
    assert not q.empty()
    assert q.get_nowait() == "updated"


# ── GET / root endpoint with html_fn ─────────────────────────────────────────


def test_root_with_root_param_calls_html_fn_with_uri():
    from unittest.mock import MagicMock

    html_fn = MagicMock(return_value="<html/>")
    app = create_app(make_taxonomy(), TOKEN, SSEBroadcaster(), lambda _: None, html_fn=html_fn)
    TestClient(app).get("/", params={"root": uri("Dog")})
    html_fn.assert_called_once_with(uri("Dog"))


def test_root_without_root_param_calls_html_fn_with_none():
    from unittest.mock import MagicMock

    html_fn = MagicMock(return_value="<html/>")
    app = create_app(make_taxonomy(), TOKEN, SSEBroadcaster(), lambda _: None, html_fn=html_fn)
    TestClient(app).get("/")
    html_fn.assert_called_once_with(None)


# ── graph page caching ─────────────────────────────────────────────────────────


def test_root_graph_page_is_not_cached():
    """The live server's graph page must send no-store so reloads pick up new JS."""
    tax = make_taxonomy()
    bc = SSEBroadcaster()
    app = create_app(tax, TOKEN, bc, lambda t: None, html_fn=lambda root=None: "<html>g</html>")
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "no-store" in r.headers.get("cache-control", "")


def test_root_without_html_fn_returns_501():
    """GET / must return 501 when no HTML renderer is configured."""
    app = create_app(make_taxonomy(), TOKEN, SSEBroadcaster(), lambda _: None, html_fn=None)
    r = TestClient(app).get("/")
    assert r.status_code == 501
