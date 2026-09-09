"""An edit built on a stale read is refused, not silently applied.

``TaxonomyService.execute`` has always taken a *base_version* and returned
``rejected`` when it did not match the current one. Nothing ever sent it, so the
guard short-circuited and the last writer won without anybody being told.

That was tolerable for the TUI — one user, one process, holding the lock. It is
not tolerable for an HTTP API, which is multi-client by construction: two browser
tabs, or a browser open beside a TUI, is the ordinary case rather than the exotic
one. The lock already prevents a torn write; nothing prevented a lost one.

The check stays opt-in. A body without *base_version* behaves exactly as before,
so existing callers are unaffected — the version is something a client asks for
and chooses to send.
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


def make_taxonomy() -> Taxonomy:
    t = Taxonomy()
    t.namespace_bindings[""] = NS
    t.owl_classes[uri("Animal")] = RDFClass(
        uri=uri("Animal"), labels=[Label(lang="en", value="Animal", type=LabelType.PREF)]
    )
    t.concepts[uri("Mammal")] = Concept(
        uri=uri("Mammal"), labels=[Label(lang="en", value="Mammal", type=LabelType.PREF)]
    )
    return t


@pytest.fixture
def client(tmp_path):
    app = create_app(
        make_taxonomy(), TOKEN, SSEBroadcaster(), lambda t: None, file_path=tmp_path / "o.ttl"
    )
    return TestClient(app)


def _label(client, value, *, base_version=None):
    body = {"uri": uri("Animal"), "lang": "en", "value": value}
    if base_version is not None:
        body["base_version"] = base_version
    return client.post("/api/entity-label", json=body, headers=AUTH)


def test_a_client_can_read_the_version_it_should_build_on(client):
    r = client.get("/api/version", headers=AUTH)

    assert r.status_code == 200
    assert r.json() == {"version": 0, "editable": True}


def test_a_read_only_session_reports_zero_rather_than_failing(tmp_path):
    """No file means nothing can go stale, so the caller needs no special case."""
    app = create_app(make_taxonomy(), TOKEN, SSEBroadcaster(), lambda t: None)
    body = TestClient(app).get("/api/version", headers=AUTH).json()

    assert body == {"version": 0, "editable": False}


def test_the_version_advances_with_each_edit(client):
    assert _label(client, "One").json()["version"] == 1
    assert _label(client, "Two").json()["version"] == 2
    assert client.get("/api/version", headers=AUTH).json()["version"] == 2


def test_an_edit_on_the_current_version_is_applied(client):
    version = client.get("/api/version", headers=AUTH).json()["version"]

    r = _label(client, "Fresh", base_version=version)

    assert r.status_code == 200
    assert r.json()["version"] == version + 1


def test_an_edit_on_a_stale_version_is_refused(client):
    stale = client.get("/api/version", headers=AUTH).json()["version"]
    _label(client, "Someone else got here first")  # advances the version

    r = _label(client, "Built on what I read earlier", base_version=stale)

    assert r.status_code == 409
    assert "version conflict" in r.json()["detail"]


def test_the_refused_edit_did_not_land(client):
    """A 409 must leave the winner's value in place, not half-apply the loser's."""
    stale = client.get("/api/version", headers=AUTH).json()["version"]
    _label(client, "Winner")

    _label(client, "Loser", base_version=stale)

    detail = client.get("/api/node-detail", params={"uri": uri("Animal")}, headers=AUTH).json()
    assert "Loser" not in str(detail)
    assert "Winner" in str(detail)


def test_omitting_the_version_keeps_the_previous_behaviour(client):
    """Opt-in: a caller that never asks for a version is never rejected."""
    _label(client, "First")

    r = _label(client, "Second with no base_version")

    assert r.status_code == 200


@pytest.mark.parametrize(
    ("endpoint", "body"),
    [
        ("/api/entity-label", {"uri": uri("Animal"), "lang": "en", "value": "x"}),
        ("/api/entity-description", {"uri": uri("Animal"), "lang": "en", "value": "x"}),
        (
            "/api/relation",
            {"ind_uri": uri("a"), "prop_uri": uri("p"), "target_uri": uri("b")},
        ),
        (
            "/api/relation/remove",
            {"ind_uri": uri("a"), "prop_uri": uri("p"), "target_uri": uri("b")},
        ),
        ("/api/class-parent", {"child_uri": uri("a"), "parent_uri": uri("b")}),
        ("/api/class-parent/remove", {"child_uri": uri("a"), "parent_uri": uri("b")}),
    ],
)
def test_every_mutation_endpoint_accepts_a_base_version(client, endpoint, body):
    """The guard is worth nothing if one endpoint quietly skips it."""
    _label(client, "advance the version")

    r = client.post(endpoint, json={**body, "base_version": 0}, headers=AUTH)

    assert r.status_code == 409, f"{endpoint} ignored base_version"
