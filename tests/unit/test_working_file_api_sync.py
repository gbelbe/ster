"""The running API must follow a working-file switch made in the editor.

The editor and the API server share one session: the TUI starts the server on a
daemon thread beside itself and hands it the same ``Taxonomy``. So "which file
may I edit?" has to have one answer, not two. Three pieces of state cached that
answer independently, and each one had to be repointed for the API to agree:
the published model, the save target, and the lazily built mutation backend.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import api_server, store

NS = "https://example.org/t#"

GEAR = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <{NS}> .
ex:Scheme a skos:ConceptScheme .
ex:Tent a skos:Concept ; skos:prefLabel "Tent"@en ; skos:inScheme ex:Scheme .
"""

PLACES = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <{NS}> .
ex:PlaceScheme a skos:ConceptScheme .
ex:Alps a skos:Concept ; skos:prefLabel "Alps"@en ; skos:inScheme ex:PlaceScheme .
"""

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def session(tmp_path: Path):
    """A background server publishing the gear file, with places as context."""
    from ster.api import SSEBroadcaster, create_app

    gear = tmp_path / "gear.ttl"
    places = tmp_path / "places.ttl"
    gear.write_text(GEAR, encoding="utf-8")
    places.write_text(PLACES, encoding="utf-8")

    taxonomy = store.load(gear, context=[places])

    def save_fn(tax) -> None:
        # The real helper the running server uses, not a copy of it — a
        # reimplementation here would keep passing if the shipped one regressed.
        api_server._persist_to_working_file(app.state._ster, tax)

    app = create_app(
        taxonomy,
        TOKEN,
        SSEBroadcaster(),
        save_fn,
        file_path=gear,
        context=[places],
    )
    app.state._ster["broadcaster"] = SSEBroadcaster()

    api_server._bg.app = app
    api_server._bg.broadcaster = app.state._ster["broadcaster"]
    api_server._bg.loop = None
    try:
        yield {"app": app, "gear": gear, "places": places, "tmp_path": tmp_path}
    finally:
        api_server._bg.reset()


def _client(session):
    from fastapi.testclient import TestClient

    return TestClient(session["app"])


def _switch_to_places(session):
    """What the editor does after its own reload: republish the new roles."""
    taxonomy = store.load(session["places"], context=[session["gear"]])
    api_server.publish_working_file(taxonomy, session["places"], [session["gear"]])
    return taxonomy


def uri(name: str) -> str:
    return NS + name


# ── the published state ───────────────────────────────────────────────────────


def test_switch_repoints_api_taxonomy(session):
    taxonomy = _switch_to_places(session)
    assert session["app"].state._ster["taxonomy"] is taxonomy


def test_switch_repoints_api_file_path(session):
    _switch_to_places(session)
    assert session["app"].state._ster["file_path"] == session["places"]


def test_switch_repoints_api_context_list(session):
    _switch_to_places(session)
    assert session["app"].state._ster["context"] == [session["gear"]]


# ── what the endpoints now allow ──────────────────────────────────────────────


def test_api_write_guard_follows_the_switch(session):
    """Before the switch the gear file's entity is writable and the places
    file's is not; afterwards it is the other way round."""
    client = _client(session)
    before = client.post(
        "/api/entity-label",
        json={"uri": uri("Alps"), "lang": "en", "value": "Alpes"},
        headers=AUTH,
    )
    assert before.status_code == 409  # the read-only guard's status

    _switch_to_places(session)

    after = client.post(
        "/api/entity-label",
        json={"uri": uri("Alps"), "lang": "en", "value": "Alpes"},
        headers=AUTH,
    )
    assert after.status_code == 200


def test_api_refuses_the_old_working_file_after_the_switch(session):
    _switch_to_places(session)
    client = _client(session)

    response = client.post(
        "/api/entity-label",
        json={"uri": uri("Tent"), "lang": "en", "value": "Tente"},
        headers=AUTH,
    )
    assert response.status_code == 409  # the read-only guard's status


# ── the two stale caches ──────────────────────────────────────────────────────


def test_switch_invalidates_the_cached_mutation_backend_regression(session):
    """Root cause: ``_mutation_backend`` caches ``(service, workspace, path)`` on
    the app state for the life of the app. Left in place across a switch, every
    later write went through the previous file's workspace and landed in the
    previous file."""
    client = _client(session)
    client.post(  # force the backend to be built against the gear file
        "/api/entity-label",
        json={"uri": uri("Tent"), "lang": "en", "value": "Tente"},
        headers=AUTH,
    )
    assert session["app"].state._ster.get("_mutation_backend") is not None

    _switch_to_places(session)

    assert session["app"].state._ster.get("_mutation_backend") is None


def test_api_save_target_follows_the_switch_regression(session):
    """Root cause: ``start_background``'s ``save_fn`` closed over *file_path*, so
    a republished session kept writing to the file the server started with."""
    _switch_to_places(session)
    client = _client(session)

    response = client.post(
        "/api/entity-label",
        json={"uri": uri("Alps"), "lang": "en", "value": "Alpes"},
        headers=AUTH,
    )
    assert response.status_code == 200

    assert "Alpes" in session["places"].read_text(encoding="utf-8")
    assert "Alpes" not in session["gear"].read_text(encoding="utf-8")


# ── no server running ─────────────────────────────────────────────────────────


def test_publishing_without_a_running_server_is_a_no_op(tmp_path):
    """The TUI starts the server best-effort — a taken port means no server that
    session, and switching files must still work."""
    api_server._bg.reset()
    api_server.publish_working_file("model", tmp_path / "x.ttl", [])


# ── the save target, tested on the shipped helper ─────────────────────────────


def test_persist_writes_to_the_live_working_file(tmp_path):
    """The helper ``start_background``'s save_fn delegates to."""
    target = tmp_path / "out.ttl"
    src = tmp_path / "src.ttl"
    src.write_text(GEAR, encoding="utf-8")
    tax = store.load(src)

    api_server._persist_to_working_file({"file_path": target}, tax)

    assert "Tent" in target.read_text(encoding="utf-8")


def test_persist_follows_a_changed_working_file(tmp_path):
    """Regression: the save target used to be captured when the server started,
    so a session that switched files kept writing to the original one."""
    first, second = tmp_path / "first.ttl", tmp_path / "second.ttl"
    src = tmp_path / "src.ttl"
    src.write_text(GEAR, encoding="utf-8")
    tax = store.load(src)
    state = {"file_path": first}

    api_server._persist_to_working_file(state, tax)
    state["file_path"] = second  # the editor switched working file
    api_server._persist_to_working_file(state, tax)

    assert second.exists() and "Tent" in second.read_text(encoding="utf-8")


def test_persist_is_a_no_op_without_a_file(tmp_path):
    """A read-only session has nothing to save to, and must not crash trying."""
    src = tmp_path / "src.ttl"
    src.write_text(GEAR, encoding="utf-8")

    api_server._persist_to_working_file({"file_path": None}, store.load(src))
