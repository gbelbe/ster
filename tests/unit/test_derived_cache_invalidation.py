"""A cached graph must not outlive the model it was built from.

full_graph_rdflib, full_graph_oxigraph and vocabulary are memoised on the
Taxonomy, on the reasoning that a reload or an edit produces a *new* Taxonomy
so the derived state goes with the old one.

That reasoning had a hole. TaxonomyService copies the model before applying a
command, and a default deepcopy clones ``__dict__`` wholesale — including the
cache attributes. The new authority therefore inherited a graph built from the
model *before* the edit: the change reached disk, and /api/sparql_query kept answering
from before it. Taxonomy.__deepcopy__ drops anything named ``_ster_*``.

These tests cover the three ways a model changes: edited through the HTTP API,
edited through the TUI's service (the same path with persist=False), and
replaced by a fresh load, which is what the file watcher does.
"""

from __future__ import annotations

import copy

import pytest
import rdflib
from fastapi.testclient import TestClient

from ster import store
from ster.api import SSEBroadcaster, create_app
from ster.store import full_graph_oxigraph, full_graph_rdflib

E = "https://example.org/#"
TOKEN = "t"
AUTH = {"Authorization": f"Bearer {TOKEN}", "Origin": "http://localhost:8000"}
LABEL_Q = f"SELECT ?l WHERE {{ <{E}Shop> <http://www.w3.org/2000/01/rdf-schema#label> ?l }}"

TTL = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/#> .
ex:O a owl:Ontology .
ex:Shop a owl:Class ; rdfs:label "Shop"@en .
"""


@pytest.fixture
def onto(tmp_path):
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")
    return path


@pytest.fixture
def client(onto):
    app = create_app(store.load(onto), TOKEN, SSEBroadcaster(), lambda t: None, file_path=onto)
    return TestClient(app), app


def _labels(taxonomy) -> list[str]:
    g = full_graph_rdflib(taxonomy)
    return [str(o) for o in g.objects(rdflib.URIRef(E + "Shop"), rdflib.RDFS.label)]


def _query(client, q=LABEL_Q):
    return client.post("/api/sparql_query", json={"query": q}, headers=AUTH).json().get("rows", [])


# ── the mechanism ────────────────────────────────────────────────────────────


def test_deepcopy_drops_a_derived_cache(onto):
    """The fix, stated directly: a copy of a model is not a copy of its caches."""
    taxonomy = store.load(onto)
    full_graph_rdflib(taxonomy)
    assert hasattr(taxonomy, "_ster_graph_rdflib")

    clone = copy.deepcopy(taxonomy)

    assert not hasattr(clone, "_ster_graph_rdflib")


def test_deepcopy_keeps_the_model_itself(onto):
    """Dropping caches must not drop content — the obvious way to break this."""
    taxonomy = store.load(onto)
    full_graph_rdflib(taxonomy)

    clone = copy.deepcopy(taxonomy)

    assert set(clone.owl_classes) == set(taxonomy.owl_classes)
    assert clone.file_path == taxonomy.file_path


# ── ① edited through the API ─────────────────────────────────────────────────


def test_an_api_edit_is_visible_to_the_next_query(client):
    c, app = client
    assert _query(c) == [["Shop"]]

    c.post(
        "/api/entity-label",
        json={"uri": E + "Shop", "lang": "en", "value": "RENAMED"},
        headers=AUTH,
    )

    assert _query(c) == [["RENAMED"]]


def test_an_api_edit_is_visible_in_the_map_graph(client):
    """The map reads full_graph_rdflib directly, not through the query path."""
    c, app = client
    c.post(
        "/api/entity-label",
        json={"uri": E + "Shop", "lang": "en", "value": "RENAMED"},
        headers=AUTH,
    )

    assert _labels(app.state._ster["taxonomy"]) == ["RENAMED"]


def test_a_primed_vocabulary_does_not_survive_an_edit(client):
    c, app = client
    c.get("/api/vocabulary", headers=AUTH)  # prime it

    c.post("/api/entity-label", json={"uri": E + "Shop", "lang": "en", "value": "X"}, headers=AUTH)

    assert not hasattr(app.state._ster["taxonomy"], "_ster_vocabulary")


def test_a_second_edit_is_also_visible(client):
    """One invalidation is easy to get right by accident; two in a row is not."""
    c, _app = client
    for value in ("FIRST", "SECOND"):
        c.post(
            "/api/entity-label",
            json={"uri": E + "Shop", "lang": "en", "value": value},
            headers=AUTH,
        )

    assert _query(c) == [["SECOND"]]


# ── ② edited through the TUI's service ───────────────────────────────────────


def test_a_tui_style_edit_invalidates_too(onto):
    """The TUI runs the same service with persist=False, so it must behave the
    same — the in-memory authority is swapped either way."""
    from ster.core.adapters import StorePersistence
    from ster.core.commands.owl import OwlSetLabel
    from ster.core.service import TaxonomyService
    from ster.core.validation import SkosValidatorAdapter
    from ster.workspace import TaxonomyWorkspace

    taxonomy = store.load(onto)
    workspace = TaxonomyWorkspace.from_taxonomy(taxonomy, onto)
    service = TaxonomyService(workspace, StorePersistence(), SkosValidatorAdapter())
    assert _labels(taxonomy) == ["Shop"]  # prime the cache

    service.execute(OwlSetLabel(onto, E + "Shop", "en", "FROM THE TUI"), persist=False)

    assert _labels(workspace.taxonomies[onto]) == ["FROM THE TUI"]


# ── ③ replaced by a fresh load (the file watcher) ────────────────────────────


def test_a_reload_sees_what_changed_on_disk(onto):
    taxonomy = store.load(onto)
    assert _labels(taxonomy) == ["Shop"]  # prime the cache

    onto.write_text(TTL.replace('"Shop"', '"FROM DISK"'), encoding="utf-8")

    assert _labels(store.load(onto)) == ["FROM DISK"]


def test_the_oxigraph_store_is_rebuilt_too(onto):
    """Both engines cache; invalidating one and not the other would give two
    answers to the same question depending on which path a caller took."""
    taxonomy = store.load(onto)
    full_graph_oxigraph(taxonomy)

    clone = copy.deepcopy(taxonomy)

    assert not hasattr(clone, "_ster_graph_oxigraph")
