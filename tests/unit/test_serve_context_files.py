"""``ster serve`` opens the same way ``ster edit`` does: one writable file, the
rest read-only.

An ontology split across files is still one graph. A vocabulary beside the data
that uses it, third-party reference data beside your own — the map and the
relation view are only correct when they can see all of it, and before this
``serve`` took exactly one path, so half the graph was simply invisible.

The mechanism is not new and is deliberately not a second implementation:
``store.load(path, context=[...])`` already merged context read-only, recorded
each entity in ``Taxonomy.context_source`` and excluded it from saving, and the
graph viewer already withheld the edit affordance from a ``readOnly`` node.
What was missing was a way to
give ``serve`` those files, and — more importantly — an actual refusal on the
server when a write aims at one. The viewer hiding a button is a convention;
``store.is_editable`` consulted on every mutation is the rule, and it holds for
curl and for any other front-end too.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ster import store
from ster.api import SSEBroadcaster, create_app

TOKEN = "t"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
MAIN = "https://example.org/main#"
CTX = "https://example.org/ctx#"

MAIN_TTL = f"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix m: <{MAIN}> .
@prefix c: <{CTX}> .
m:O a owl:Ontology ; rdfs:label "Main"@en .
m:Shop a owl:Class ; rdfs:label "Shop"@en ; m:sells c:Paint .
"""

CTX_TTL = f"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix c: <{CTX}> .
c:O a owl:Ontology ; rdfs:label "Vocabulary"@en .
c:Paint a owl:Class ; rdfs:label "Paint"@en .
"""


@pytest.fixture
def files(tmp_path):
    main, ctx = tmp_path / "main.ttl", tmp_path / "ctx.ttl"
    main.write_text(MAIN_TTL, encoding="utf-8")
    ctx.write_text(CTX_TTL, encoding="utf-8")
    return main, ctx


@pytest.fixture
def client(files):
    main, ctx = files
    tax = store.load(main, context=[ctx])
    app = create_app(tax, TOKEN, SSEBroadcaster(), lambda t: None, file_path=main, context=[ctx])
    return TestClient(app)


def _rename(client, uri, value="Renamed"):
    return client.post(
        "/api/entity-label", json={"uri": uri, "lang": "en", "value": value}, headers=AUTH
    )


def test_the_context_file_is_part_of_the_graph(files):
    """Without this, half the ontology is invisible and the map is wrong."""
    main, ctx = files

    tax = store.load(main, context=[ctx])

    assert CTX + "Paint" in tax.owl_classes


def test_serve_without_context_does_not_see_it(files):
    """The regression being fixed: one path meant one file."""
    main, _ctx = files

    assert CTX + "Paint" not in store.load(main).owl_classes


def test_the_editable_file_can_be_edited(client):
    assert _rename(client, MAIN + "Shop").status_code == 200


def test_a_context_entity_cannot_be_edited(client):
    r = _rename(client, CTX + "Paint")

    assert r.status_code == 409
    assert "read-only context" in r.json()["detail"]


def test_the_refusal_names_the_file_it_belongs_to(client):
    """ "It is locked" is unhelpful without "and here is where it lives"."""
    assert "ctx.ttl" in _rename(client, CTX + "Paint").json()["detail"]


def test_a_refused_edit_changes_nothing(client, files):
    _main, ctx = files
    before = ctx.read_text(encoding="utf-8")

    _rename(client, CTX + "Paint", "Should not land")

    assert ctx.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    ("endpoint", "body"),
    [
        ("/api/entity-label", {"uri": CTX + "Paint", "lang": "en", "value": "x"}),
        ("/api/entity-description", {"uri": CTX + "Paint", "lang": "en", "value": "x"}),
        (
            "/api/relation",
            {"ind_uri": CTX + "Paint", "prop_uri": MAIN + "p", "target_uri": MAIN + "Shop"},
        ),
        (
            "/api/relation/remove",
            {"ind_uri": CTX + "Paint", "prop_uri": MAIN + "p", "target_uri": MAIN + "Shop"},
        ),
        ("/api/class-parent", {"child_uri": CTX + "Paint", "parent_uri": MAIN + "Shop"}),
        ("/api/class-parent/remove", {"child_uri": CTX + "Paint", "parent_uri": MAIN + "Shop"}),
    ],
)
def test_no_mutation_endpoint_can_write_to_context(client, endpoint, body):
    """A guard one endpoint skips is not a guard."""
    r = client.post(endpoint, json=body, headers=AUTH)

    assert r.status_code == 409, f"{endpoint} accepted a write to a context entity"


def test_saving_never_writes_the_context_file(client, files):
    main, ctx = files
    before = ctx.read_text(encoding="utf-8")

    _rename(client, MAIN + "Shop", "Edited")

    assert ctx.read_text(encoding="utf-8") == before
    assert "Edited" in main.read_text(encoding="utf-8")


def test_the_context_entity_is_not_written_into_the_editable_file(client, files):
    """Merged for reading only — a save must not absorb the other file's content."""
    main, _ctx = files

    _rename(client, MAIN + "Shop", "Edited")

    assert CTX + "Paint" not in main.read_text(encoding="utf-8")
