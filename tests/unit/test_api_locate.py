"""The map resolves rows to geometry server-side.

The map page used to locate rows itself, in JavaScript, with a SPARQL query for
``wgs:lat`` / ``wgs:long`` and nothing else — so an entity publishing a boundary
was reported as unmappable however well the Python layer understood it. Clicking
the demo showed "13 row(s) · 5 mappable" with every polygon missing.

Resolving here instead means one implementation of the geometry ladder and of WKT
parsing, in the language that already has both, rather than a second parser in the
browser.
"""

from __future__ import annotations

import pytest
import rdflib
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Taxonomy

TOKEN = "test-token"
NS = "https://example.org/geo#"
SQUARE = "POLYGON((-4.8 47.3, -1.0 47.3, -1.0 48.9, -4.8 48.9, -4.8 47.3))"

TTL = f"""\
@prefix geo:  <http://www.opengis.net/ont/geosparql#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <{NS}> .

ex:Region a skos:Concept ; skos:prefLabel "Region"@en ;
    geo:hasGeometry ex:RegionShape .
ex:RegionShape geo:asWKT "{SQUARE}"^^geo:wktLiteral .

ex:City a skos:Concept ; skos:prefLabel "City"@en ;
    wgs:lat "47.28" ; wgs:long "-2.21" .

ex:Nowhere a skos:Concept ; skos:prefLabel "Nowhere"@en .
"""


@pytest.fixture
def client(monkeypatch):
    taxonomy = Taxonomy()
    graph = rdflib.Graph()
    graph.parse(data=TTL, format="turtle")
    # The route reads the live graph; give it this one.
    monkeypatch.setattr("ster.api._graph_for_locate", lambda _tax: graph, raising=False)
    app = create_app(taxonomy, TOKEN, SSEBroadcaster(), lambda t: None)
    return TestClient(app)


def _locate(client, uris):
    return client.post(
        "/api/locate", json={"uris": uris}, headers={"Authorization": f"Bearer {TOKEN}"}
    )


def test_a_polygon_comes_back_with_its_geometry(client):
    body = _locate(client, [NS + "Region"]).json()

    assert body["places"][0]["shape"]["type"] == "Polygon"


def test_a_polygon_comes_back_with_a_point_for_clustering(client):
    place = _locate(client, [NS + "Region"]).json()["places"][0]

    assert (round(place["lat"], 2), round(place["long"], 2)) == (48.10, -2.90)


def test_a_plain_point_carries_no_redundant_shape(client):
    place = _locate(client, [NS + "City"]).json()["places"][0]

    assert place["shape"] is None
    assert (place["lat"], place["long"]) == (47.28, -2.21)


def test_an_entity_with_no_geography_is_simply_absent(client):
    body = _locate(client, [NS + "Nowhere"]).json()

    assert body["places"] == []


def test_the_label_comes_back_too(client):
    place = _locate(client, [NS + "Region"]).json()["places"][0]

    assert place["label"] == "Region"
    assert place["uri"] == NS + "Region"


def test_a_mixed_request_resolves_each_kind(client):
    body = _locate(client, [NS + "Region", NS + "City", NS + "Nowhere"]).json()

    assert [p["shape"] is None for p in body["places"]] == [False, True]


def test_the_endpoint_needs_the_token(client):
    assert client.post("/api/locate", json={"uris": [NS + "City"]}).status_code == 401


def test_an_empty_request_is_not_an_error(client):
    response = _locate(client, [])

    assert response.status_code == 200
    assert response.json()["places"] == []


def test_a_uri_that_is_not_in_the_graph_is_skipped(client):
    body = _locate(client, ["https://example.org/absent#Thing"]).json()

    assert body["places"] == []


# ── where the graph comes from ────────────────────────────────────────────────
#
# The tests above stub this out, which is exactly how the bug below survived
# them: pointing it at the wrong graph took the map from 5 mappable to 0, and
# only clicking the demo showed it.


def _write(tmp_path):
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")
    return path


def test_the_source_file_is_parsed_not_the_model_rebuilt(tmp_path):
    """Regression: taxonomy_to_graph() returns only what ster's model represents.

    A Concept modelled no arbitrary predicates, so rebuilding dropped every
    GeoSPARQL triple and the map found nothing to place. The SPARQL path reads
    the file for the same reason.
    """
    from rdflib.namespace import GEO

    from ster import store
    from ster.api import _graph_for_locate

    path = _write(tmp_path)
    taxonomy = store.load(path)

    graph = _graph_for_locate(taxonomy)

    assert list(graph.triples((None, GEO.asWKT, None))), "geometry must reach the map"


def test_an_unsaved_taxonomy_still_resolves(tmp_path):
    """No file to read — fall back to the model rather than fail the request."""
    from ster.api import _graph_for_locate

    taxonomy = Taxonomy()  # file_path is None

    assert _graph_for_locate(taxonomy) is not None


def test_an_unreadable_file_falls_back_rather_than_failing(tmp_path, monkeypatch):
    """A vanished or permission-denied file is not a reason to 500 the map."""
    from ster import store
    from ster.api import _graph_for_locate

    path = _write(tmp_path)
    taxonomy = store.load(path)

    def denied(_paths):
        raise OSError("permission denied")

    monkeypatch.setattr("ster.sparql_query.load_graph", denied)

    assert _graph_for_locate(taxonomy) is not None


def test_the_route_uses_the_real_graph_end_to_end(tmp_path):
    """No stubbing: the endpoint must place a polygon from a file on disk."""
    from ster import store

    path = _write(tmp_path)
    app = create_app(store.load(path), TOKEN, SSEBroadcaster(), lambda t: None)
    unstubbed = TestClient(app)

    body = _locate(unstubbed, [NS + "Region"]).json()

    assert body["places"][0]["shape"]["type"] == "Polygon"


# ── the hierarchy the result induces ──────────────────────────────────────────


CTX_TTL = f"""\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix geo:  <http://www.opengis.net/ont/geosparql#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix ex:   <{NS}> .

ex:Place a owl:Class ; rdfs:label "Place"@en .
ex:Country a owl:Class ; rdfs:label "Country"@en ; rdfs:subClassOf ex:Place .
ex:City a owl:Class ; rdfs:label "City"@en ; rdfs:subClassOf ex:Place .
ex:Shop a owl:Class ; rdfs:label "Shop"@en ; rdfs:subClassOf ex:Place .
ex:within a owl:ObjectProperty ; rdfs:domain ex:Place ; rdfs:range ex:Place .
ex:turnover a owl:DatatypeProperty ; rdfs:label "turnover"@en .

ex:Gaul a owl:NamedIndividual, ex:Country ; rdfs:label "Gaul"@en ;
    geo:asWKT "{SQUARE}"^^geo:wktLiteral .
ex:Withshop a owl:NamedIndividual, ex:City ; rdfs:label "Withshop"@en ; ex:within ex:Gaul ;
    wgs:lat "47.0" ; wgs:long "-2.0" .
ex:Noshop a owl:NamedIndividual, ex:City ; rdfs:label "Noshop"@en ; ex:within ex:Gaul ;
    wgs:lat "48.0" ; wgs:long "-1.0" .
ex:Forum a owl:NamedIndividual, ex:Shop ; rdfs:label "Forum"@en ; ex:within ex:Withshop ;
    wgs:lat "47.1" ; wgs:long "-2.1" ; ex:turnover "500"^^xsd:decimal .
"""


@pytest.fixture
def ctx_client(tmp_path):
    from ster import store

    path = tmp_path / "ctx.ttl"
    path.write_text(CTX_TTL, encoding="utf-8")
    return TestClient(create_app(store.load(path), TOKEN, SSEBroadcaster(), lambda t: None))


def test_the_places_containing_a_result_come_back_as_context(ctx_client):
    """A query for shops must be groupable by city and country without asking."""
    body = _locate(ctx_client, [NS + "Forum"]).json()
    by = {p["label"]: p for p in body["places"]}

    assert set(by) == {"Forum", "Withshop", "Gaul"}
    assert by["Forum"]["result"] is True
    assert by["Withshop"]["result"] is False


def test_a_place_holding_no_result_never_appears(ctx_client):
    """The behaviour that makes a city vanish when its last shop is removed."""
    labels = {p["label"] for p in _locate(ctx_client, [NS + "Forum"]).json()["places"]}

    assert "Noshop" not in labels


def test_querying_the_cities_returns_them_all(ctx_client):
    """The same mechanism, the other way round: the result decides the hierarchy."""
    labels = {
        p["label"] for p in _locate(ctx_client, [NS + "Withshop", NS + "Noshop"]).json()["places"]
    }

    assert {"Withshop", "Noshop"} <= labels


def test_each_place_carries_its_level_kind_and_ancestors(ctx_client):
    by = {p["label"]: p for p in _locate(ctx_client, [NS + "Forum"]).json()["places"]}

    assert (by["Gaul"]["level"], by["Withshop"]["level"], by["Forum"]["level"]) == (0, 1, 2)
    assert by["Withshop"]["kind"] == "City"
    assert by["Forum"]["ancestors"] == [NS + "Withshop", NS + "Gaul"]


def test_numeric_properties_travel_with_the_place(ctx_client):
    """So the map can total a branch without a request per node."""
    by = {p["label"]: p for p in _locate(ctx_client, [NS + "Forum"]).json()["places"]}

    assert [(f["label"], f["value"]) for f in by["Forum"]["figures"]] == [("turnover", 500.0)]
    assert by["Gaul"]["figures"] == []
