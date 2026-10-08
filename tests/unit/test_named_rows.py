"""Rows that give a name where an IRI belonged still tell a page whether a map or a timeline would have something to draw."""

from __future__ import annotations

import pytest
import rdflib
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Taxonomy
from ster.named_rows import MAX_NAMED, dated_named, entities_named, placed_named

TOKEN = "test-token"
PLACED_STORES = 2  # Lille and Arras have coordinates; Nowhere has none
DATED_EVENTS = 2  # Launch and Party carry a date
SHARED_NAME = 2  # two entities are both labelled "Twin"
TTL = """\
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix ex:   <https://example.org/n#> .

ex:lille a ex:Store ; rdfs:label "Store Lille"@fr ; wgs:lat "50.63" ; wgs:long "3.06" .
ex:arras a ex:Store ; skos:prefLabel "Store Arras" ; wgs:lat "50.29" ; wgs:long "2.78" .
ex:nowhere a ex:Store ; rdfs:label "Store Nowhere" .
ex:launch a ex:Event ; rdfs:label "Launch" ; ex:on "2026-08-18"^^xsd:date .
ex:party a ex:Event ; rdfs:label "Party" ; ex:on "2026-09-18"^^xsd:date .
ex:twin1 a ex:Store ; rdfs:label "Twin" ; wgs:lat "1" ; wgs:long "1" .
ex:twin2 a ex:Store ; rdfs:label "Twin" ; wgs:lat "2" ; wgs:long "2" .
"""


@pytest.fixture
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return g


def test_a_label_in_any_language_finds_its_entity(graph):
    found = entities_named(
        graph, ["Store Lille", "Store Arras"]
    )  # rdfs:label @fr, and skos:prefLabel
    assert set(found) == {"https://example.org/n#lille", "https://example.org/n#arras"}


def test_blank_and_unknown_labels_find_nothing(graph):
    assert entities_named(graph, ["", "  ", "No such name"]) == []
    assert entities_named(graph, []) == []


def test_a_name_shared_by_two_entities_finds_both(graph):
    assert len(entities_named(graph, ["Twin"])) == SHARED_NAME


def test_only_named_entities_with_somewhere_to_be_drawn_count_as_places(graph):
    assert (
        placed_named(graph, ["Store Lille", "Store Arras", "Store Nowhere", "Launch"])
        == PLACED_STORES
    )


def test_only_named_entities_with_a_date_count_as_dated(graph):
    assert dated_named(graph, ["Launch", "Party", "Store Lille"], None, None) == DATED_EVENTS


def test_the_date_bounds_apply_to_named_entities_too(graph):
    assert dated_named(graph, ["Launch", "Party"], "2026-09-01", None) == 1


def test_the_number_of_entities_looked_at_is_bounded():
    g = rdflib.Graph()
    for i in range(MAX_NAMED + 50):
        g.add(
            (
                rdflib.URIRef(f"https://example.org/n#e{i}"),
                rdflib.RDFS.label,
                rdflib.Literal("Same"),
            )
        )
    assert len(entities_named(g, ["Same"])) == MAX_NAMED


@pytest.fixture
def client(monkeypatch, graph):
    monkeypatch.setattr("ster.api._graph_for_locate", lambda _tax: graph, raising=False)
    return TestClient(create_app(Taxonomy(), TOKEN, SSEBroadcaster(), lambda t: None))


def _post(client, path, body):
    return client.post(path, json=body, headers={"Authorization": f"Bearer {TOKEN}"}).json()


def test_locate_reports_how_many_named_entities_it_could_draw(client):
    out = _post(client, "/api/locate", {"uris": [], "labels": ["Store Lille", "Store Arras"]})
    assert out["named"] == PLACED_STORES
    assert out["places"] == []  # naming is only counted: what is drawn still comes from IRIs


def test_locate_without_labels_reports_none(client):
    assert _post(client, "/api/locate", {"uris": []})["named"] == 0


def test_timeline_reports_how_many_named_entities_it_could_date(client):
    out = _post(client, "/api/timeline", {"uris": [], "labels": ["Launch", "Party"]})
    assert out["named"] == DATED_EVENTS
    assert out["items"] == []


def test_timeline_without_labels_reports_none(client):
    assert _post(client, "/api/timeline", {"uris": []})["named"] == 0
