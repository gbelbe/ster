"""WMS layers, which is what most public geodata actually serves.

Tile services ({z}/{x}/{y}) are the minority once you leave OpenStreetMap's
orbit: national weather services, environment agencies and everything under
INSPIRE publish WMS. A layer that names WMS layer names is served that way; one
that does not stays a tile layer, so the two live side by side in one menu.
"""

from __future__ import annotations

import pytest
import rdflib

from ster import geo_shapes

STER = "https://ster.dev/ns/map#"
NS = "https://example.org/l#"

TTL = f"""\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ster: <{STER}> .
@prefix ex:   <{NS}> .

ex:felt a ster:MapLayer ;
    rdfs:label "Perceived temperature"@en ;
    ster:tileUrl "https://maps.dwd.de/geoserver/dwd/wms" ;
    ster:wmsLayers "dwd:GefuehlteTemp" ;
    ster:attribution "© Deutscher Wetterdienst" ;
    ster:opacity "0.6" .

ex:tiles a ster:MapLayer ;
    rdfs:label "Terrain"@en ;
    ster:tileUrl "https://tile.example.org/{{z}}/{{x}}/{{y}}.png" .
"""


@pytest.fixture
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return g


def _by_label(graph):
    return {layer["label"]: layer for layer in geo_shapes.map_layers(graph)}


def test_naming_wms_layers_makes_it_a_wms_layer(graph):
    felt = _by_label(graph)["Perceived temperature"]

    assert felt["kind"] == "wms"
    assert felt["wmsLayers"] == "dwd:GefuehlteTemp"


def test_a_layer_without_wms_names_stays_a_tile_layer(graph):
    assert _by_label(graph)["Terrain"]["kind"] == "tile"


def test_wms_defaults_suit_an_overlay(graph):
    """Transparent, or it hides the basemap and everything drawn under it."""
    felt = _by_label(graph)["Perceived temperature"]

    assert felt["wmsFormat"] == "image/png"
    assert felt["wmsTransparent"] is True


def test_format_and_transparency_can_be_stated(graph):
    graph.add(
        (
            rdflib.URIRef(NS + "felt"),
            rdflib.URIRef(STER + "wmsFormat"),
            rdflib.Literal("image/jpeg"),
        )
    )
    graph.add(
        (
            rdflib.URIRef(NS + "felt"),
            rdflib.URIRef(STER + "wmsTransparent"),
            rdflib.Literal("false"),
        )
    )

    felt = _by_label(graph)["Perceived temperature"]

    assert felt["wmsFormat"] == "image/jpeg"
    assert felt["wmsTransparent"] is False


def test_a_wms_url_needs_no_tile_placeholders(graph):
    """The point: a WMS endpoint is a plain URL, and requiring {z}/{x}/{y} would
    have excluded every service that publishes this way."""
    felt = _by_label(graph)["Perceived temperature"]

    assert "{z}" not in str(felt["url"])
    assert str(felt["url"]).startswith("https://")


def test_a_wms_url_is_vetted_like_any_other(graph):
    graph.add((rdflib.URIRef(NS + "evil"), rdflib.RDF.type, rdflib.URIRef(STER + "MapLayer")))
    graph.add(
        (
            rdflib.URIRef(NS + "evil"),
            rdflib.URIRef(STER + "tileUrl"),
            rdflib.Literal("javascript:alert(1)"),
        )
    )
    graph.add((rdflib.URIRef(NS + "evil"), rdflib.URIRef(STER + "wmsLayers"), rdflib.Literal("x")))

    assert not any(str(x["url"]).startswith("javascript:") for x in geo_shapes.map_layers(graph))


def test_a_wms_endpoint_can_take_its_key_from_the_environment(graph, monkeypatch):
    """Some national services are open; others want a key. Same rule as tiles."""
    monkeypatch.setenv("DEMO_WMS_KEY", "abc")
    graph.add((rdflib.URIRef(NS + "paid"), rdflib.RDF.type, rdflib.URIRef(STER + "MapLayer")))
    graph.add(
        (
            rdflib.URIRef(NS + "paid"),
            rdflib.URIRef(STER + "tileUrl"),
            rdflib.Literal("https://geo.example.org/wms?key={env:DEMO_WMS_KEY}"),
        )
    )
    graph.add(
        (rdflib.URIRef(NS + "paid"), rdflib.URIRef(STER + "wmsLayers"), rdflib.Literal("temp"))
    )

    urls = [str(x["url"]) for x in geo_shapes.map_layers(graph)]

    assert any(u.endswith("key=abc") for u in urls)
