"""GET / PUT / DELETE /api/layout — the graph page reading and saving node positions."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Label, RDFClass, Taxonomy

NS = "https://example.org/g#"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _uri(name: str) -> str:
    return NS + name


def _taxonomy() -> Taxonomy:
    t = Taxonomy()
    for name in ("A", "B"):
        t.owl_classes[_uri(name)] = RDFClass(uri=_uri(name), labels=[Label("en", name)])
    return t


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr("ster.graph_layout._git_root", lambda cwd: None)
    path = tmp_path / "gear.ttl"
    path.write_text("", encoding="utf-8")
    return path


@pytest.fixture
def client(source):
    app = create_app(_taxonomy(), TOKEN, SSEBroadcaster(), lambda t: None, file_path=source)
    return TestClient(app)


def test_every_route_requires_auth(client) -> None:
    assert client.get("/api/layout").status_code == 401
    assert client.put("/api/layout", json={"positions": {}}).status_code == 401
    assert client.delete("/api/layout").status_code == 401


def test_a_fresh_project_has_no_positions(client) -> None:
    assert client.get("/api/layout", headers=AUTH).json() == {"positions": {}}


def test_saved_positions_come_back(client) -> None:
    saved = client.put("/api/layout", json={"positions": {_uri("A"): [10.2, 20.7]}}, headers=AUTH)
    assert saved.status_code == 200
    assert client.get("/api/layout", headers=AUTH).json() == {"positions": {_uri("A"): [10, 21]}}


def test_a_save_merges_with_what_is_stored(client) -> None:
    client.put("/api/layout", json={"positions": {_uri("A"): [1, 1]}}, headers=AUTH)
    client.put("/api/layout", json={"positions": {_uri("B"): [2, 2]}}, headers=AUTH)
    positions = client.get("/api/layout", headers=AUTH).json()["positions"]
    assert positions == {_uri("A"): [1, 1], _uri("B"): [2, 2]}


def test_a_position_for_a_node_not_in_the_model_is_not_kept(client) -> None:
    client.put("/api/layout", json={"positions": {_uri("Ghost"): [1, 1]}}, headers=AUTH)
    assert client.get("/api/layout", headers=AUTH).json() == {"positions": {}}


def test_reset_forgets_every_position(client) -> None:
    client.put("/api/layout", json={"positions": {_uri("A"): [1, 1]}}, headers=AUTH)
    assert client.delete("/api/layout", headers=AUTH).status_code == 200
    assert client.get("/api/layout", headers=AUTH).json() == {"positions": {}}


@pytest.mark.parametrize(
    "body",
    [{"positions": {_uri("A"): [1]}}, {"positions": {_uri("A"): "x"}}, {"nodes": {}}],
)
def test_a_malformed_save_is_refused(client, body) -> None:
    assert client.put("/api/layout", json=body, headers=AUTH).status_code == 422


def test_without_a_file_there_is_nowhere_to_remember(tmp_path) -> None:
    app = create_app(_taxonomy(), TOKEN, SSEBroadcaster(), lambda t: None)
    client = TestClient(app)
    assert client.get("/api/layout", headers=AUTH).json() == {"positions": {}}
    saved = client.put("/api/layout", json={"positions": {_uri("A"): [1, 1]}}, headers=AUTH)
    assert saved.status_code == 409
