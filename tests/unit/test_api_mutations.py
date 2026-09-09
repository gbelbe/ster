"""Phase 3: the editable side panel's mutation endpoints, routed through
TaxonomyService rather than the ad hoc mutate-then-save_fn pattern.

See docs/architecture/graph-editor.md, Phase 3.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Concept, Label, LabelType, RDFClass, Taxonomy

NS = "https://example.org/onto#"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def uri(name: str) -> str:
    return NS + name


def _pref(value: str) -> Label:
    return Label(lang="en", value=value, type=LabelType.PREF)


def make_taxonomy() -> Taxonomy:
    t = Taxonomy()
    t.namespace_bindings[""] = NS
    t.owl_classes[uri("Animal")] = RDFClass(uri=uri("Animal"), labels=[_pref("Animal")])
    t.concepts[uri("Mammal")] = Concept(uri=uri("Mammal"), labels=[_pref("Mammal")])
    return t


@pytest.fixture
def onto_path(tmp_path):
    return tmp_path / "onto.ttl"


@pytest.fixture
def app_with_file(onto_path):
    tax = make_taxonomy()
    bc = SSEBroadcaster()
    return create_app(tax, TOKEN, bc, lambda t: None, file_path=onto_path)


@pytest.fixture
def client(app_with_file):
    return TestClient(app_with_file)


@pytest.fixture
def app_without_file():
    tax = make_taxonomy()
    bc = SSEBroadcaster()
    return create_app(tax, TOKEN, bc, lambda t: None)


@pytest.fixture
def client_no_file(app_without_file):
    return TestClient(app_without_file)


# ── no file path configured ─────────────────────────────────────────────────


def test_set_label_without_a_file_path_returns_503(client_no_file):
    r = client_no_file.post(
        "/api/entity-label",
        json={"uri": uri("Animal"), "lang": "en", "value": "New label"},
        headers=AUTH,
    )
    assert r.status_code == 503


# ── auth ─────────────────────────────────────────────────────────────────────


def test_set_label_requires_auth(client):
    r = client.post("/api/entity-label", json={"uri": uri("Animal"), "lang": "en", "value": "x"})
    assert r.status_code in (401, 403)


# ── OWL class label/description ─────────────────────────────────────────────


def test_set_label_on_a_class_updates_it(client):
    r = client.post(
        "/api/entity-label",
        json={"uri": uri("Animal"), "lang": "en", "value": "Animal (renamed)"},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    classes = client.get("/api/classes", params={"uri": uri("Animal")}, headers=AUTH).json()
    assert classes["classes"][0]["labels"]["en"] == "Animal (renamed)"


def test_set_description_on_a_class_updates_it(client):
    r = client.post(
        "/api/entity-description",
        json={"uri": uri("Animal"), "lang": "en", "value": "A living creature."},
        headers=AUTH,
    )
    assert r.status_code == 200
    classes = client.get("/api/classes", params={"uri": uri("Animal")}, headers=AUTH).json()
    assert classes["classes"][0]["comment"]["en"] == "A living creature."


def test_set_label_persists_to_disk(client, onto_path):
    client.post(
        "/api/entity-label",
        json={"uri": uri("Animal"), "lang": "en", "value": "Persisted label"},
        headers=AUTH,
    )
    assert onto_path.exists()
    assert "Persisted label" in onto_path.read_text(encoding="utf-8")


def test_successive_edits_increment_the_version(client):
    r1 = client.post(
        "/api/entity-label", json={"uri": uri("Animal"), "lang": "en", "value": "v1"}, headers=AUTH
    )
    r2 = client.post(
        "/api/entity-label", json={"uri": uri("Animal"), "lang": "en", "value": "v2"}, headers=AUTH
    )
    assert r2.json()["version"] == r1.json()["version"] + 1


# ── SKOS concept label/description ──────────────────────────────────────────


def test_set_label_on_a_concept_updates_its_pref_label(client):
    r = client.post(
        "/api/entity-label",
        json={"uri": uri("Mammal"), "lang": "en", "value": "Mammals"},
        headers=AUTH,
    )
    assert r.status_code == 200
    graph = client.get("/api/graph", headers=AUTH).json()
    node = next(n for n in graph["nodes"] if n["id"] == uri("Mammal"))
    assert node["label"] == "Mammals"


def test_set_description_on_a_concept_sets_its_definition(client):
    r = client.post(
        "/api/entity-description",
        json={"uri": uri("Mammal"), "lang": "en", "value": "A class of vertebrates."},
        headers=AUTH,
    )
    assert r.status_code == 200


# ── unknown entity ───────────────────────────────────────────────────────────


def test_set_label_on_unknown_uri_returns_422(client):
    r = client.post(
        "/api/entity-label",
        json={"uri": uri("Nonexistent"), "lang": "en", "value": "x"},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_set_description_on_unknown_uri_returns_422(client):
    r = client.post(
        "/api/entity-description",
        json={"uri": uri("Nonexistent"), "lang": "en", "value": "x"},
        headers=AUTH,
    )
    assert r.status_code == 422


# ── Phase 4: relations between existing nodes ────────────────────────────────


def _tax_with_individuals_and_properties():
    from ster.model import OWLIndividual, OWLProperty

    t = make_taxonomy()
    t.owl_classes[uri("Dog")] = RDFClass(uri=uri("Dog"), labels=[_pref("Dog")])
    t.owl_classes[uri("Tool")] = RDFClass(uri=uri("Tool"), labels=[_pref("Tool")])
    t.owl_properties[uri("uses")] = OWLProperty(
        uri=uri("uses"),
        prop_type="ObjectProperty",
        labels=[_pref("uses")],
        domains=[uri("Dog")],
        ranges=[uri("Tool")],
    )
    t.owl_individuals[uri("Rex")] = OWLIndividual(
        uri=uri("Rex"), labels=[_pref("Rex")], types=[uri("Dog")]
    )
    t.owl_individuals[uri("Hammer1")] = OWLIndividual(
        uri=uri("Hammer1"), labels=[_pref("Hammer1")], types=[uri("Tool")]
    )
    return t


@pytest.fixture
def rel_app(onto_path):
    bc = SSEBroadcaster()
    return create_app(
        _tax_with_individuals_and_properties(), TOKEN, bc, lambda t: None, file_path=onto_path
    )


@pytest.fixture
def rel_client(rel_app):
    return TestClient(rel_app)


def test_create_relation_between_two_individuals(rel_client):
    r = rel_client.post(
        "/api/relation",
        json={"ind_uri": uri("Rex"), "prop_uri": uri("uses"), "target_uri": uri("Hammer1")},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    detail = rel_client.get("/api/node-detail", params={"uri": uri("Rex")}, headers=AUTH).json()
    assert any(rel["uri"] == uri("Hammer1") for rel in detail.get("relations", []))


def test_replace_relation_between_two_individuals(rel_client):
    rel_client.post(
        "/api/relation",
        json={"ind_uri": uri("Rex"), "prop_uri": uri("uses"), "target_uri": uri("Hammer1")},
        headers=AUTH,
    )
    r = rel_client.post(
        "/api/relation",
        json={
            "ind_uri": uri("Rex"),
            "prop_uri": uri("uses"),
            "target_uri": uri("Animal"),
            "old_target_uri": uri("Hammer1"),
        },
        headers=AUTH,
    )
    assert r.status_code == 200


def test_remove_relation_between_two_individuals(rel_client):
    rel_client.post(
        "/api/relation",
        json={"ind_uri": uri("Rex"), "prop_uri": uri("uses"), "target_uri": uri("Hammer1")},
        headers=AUTH,
    )
    r = rel_client.post(
        "/api/relation/remove",
        json={"ind_uri": uri("Rex"), "prop_uri": uri("uses"), "target_uri": uri("Hammer1")},
        headers=AUTH,
    )
    assert r.status_code == 200
    detail = rel_client.get("/api/node-detail", params={"uri": uri("Rex")}, headers=AUTH).json()
    assert not any(rel["uri"] == uri("Hammer1") for rel in detail.get("relations", []))


def test_relation_requires_auth(rel_client):
    r = rel_client.post(
        "/api/relation",
        json={"ind_uri": uri("Rex"), "prop_uri": uri("uses"), "target_uri": uri("Hammer1")},
    )
    assert r.status_code in (401, 403)


def test_relation_without_a_file_path_returns_503(client_no_file):
    r = client_no_file.post(
        "/api/relation",
        json={"ind_uri": uri("Animal"), "prop_uri": uri("Animal"), "target_uri": uri("Animal")},
        headers=AUTH,
    )
    assert r.status_code == 503


# ── Phase 4: class superclass links ─────────────────────────────────────────


def test_add_class_parent_adds_a_superclass(rel_client, onto_path):
    r = rel_client.post(
        "/api/class-parent",
        json={"child_uri": uri("Dog"), "parent_uri": uri("Animal")},
        headers=AUTH,
    )
    assert r.status_code == 200
    classes = rel_client.get("/api/classes", params={"uri": uri("Dog")}, headers=AUTH).json()
    assert uri("Animal") in classes["classes"][0]["sub_class_of"]


def test_add_class_parent_keeps_existing_superclasses(rel_client):
    rel_client.post(
        "/api/class-parent",
        json={"child_uri": uri("Dog"), "parent_uri": uri("Animal")},
        headers=AUTH,
    )
    rel_client.post(
        "/api/class-parent",
        json={"child_uri": uri("Dog"), "parent_uri": uri("Tool")},
        headers=AUTH,
    )
    classes = rel_client.get("/api/classes", params={"uri": uri("Dog")}, headers=AUTH).json()
    parents = classes["classes"][0]["sub_class_of"]
    assert uri("Animal") in parents
    assert uri("Tool") in parents


def test_remove_class_parent_removes_the_superclass(rel_client):
    rel_client.post(
        "/api/class-parent",
        json={"child_uri": uri("Dog"), "parent_uri": uri("Animal")},
        headers=AUTH,
    )
    r = rel_client.post(
        "/api/class-parent/remove",
        json={"child_uri": uri("Dog"), "parent_uri": uri("Animal")},
        headers=AUTH,
    )
    assert r.status_code == 200
    classes = rel_client.get("/api/classes", params={"uri": uri("Dog")}, headers=AUTH).json()
    assert uri("Animal") not in classes["classes"][0]["sub_class_of"]


def test_class_parent_requires_auth(rel_client):
    r = rel_client.post(
        "/api/class-parent", json={"child_uri": uri("Dog"), "parent_uri": uri("Animal")}
    )
    assert r.status_code in (401, 403)
