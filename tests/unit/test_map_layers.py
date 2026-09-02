"""Overlay layers a file declares, not ones ster hard-codes.

A map is more useful with context on it — rainfall, terrain, railways, a national
WMS. Which layers are available is a property of the data being mapped, not of
ster, so they are read from the ontology exactly as the drill levels are: declare
one, and it appears in the layer menu with no change here.
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

ex:topo a ster:MapLayer ;
    rdfs:label "Terrain"@en ;
    ster:tileUrl "https://tile.opentopomap.org/{{z}}/{{x}}/{{y}}.png" ;
    ster:attribution "© OpenTopoMap" .

ex:rail a ster:MapLayer ;
    rdfs:label "Railways"@en ;
    ster:tileUrl "https://tiles.openrailwaymap.org/standard/{{z}}/{{x}}/{{y}}.png" ;
    ster:opacity "0.6" .
"""


@pytest.fixture
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return g


def test_a_declared_layer_is_offered(graph):
    layers = geo_shapes.map_layers(graph)

    assert [layer["label"] for layer in layers] == ["Railways", "Terrain"]


def test_a_layer_carries_what_leaflet_needs(graph):
    terrain = next(layer for layer in geo_shapes.map_layers(graph) if layer["label"] == "Terrain")

    assert terrain["url"] == "https://tile.opentopomap.org/{z}/{x}/{y}.png"
    assert terrain["attribution"] == "© OpenTopoMap"


def test_opacity_is_optional_and_defaults_to_opaque(graph):
    by = {layer["label"]: layer for layer in geo_shapes.map_layers(graph)}

    assert by["Railways"]["opacity"] == 0.6
    assert by["Terrain"]["opacity"] == 1.0


def test_a_file_declaring_none_offers_none():
    empty = rdflib.Graph()
    empty.parse(data="@prefix ex: <https://example.org/> . ex:a ex:b ex:c .", format="turtle")

    assert geo_shapes.map_layers(empty) == []


def test_a_layer_without_a_tile_url_is_skipped(graph):
    """A declaration ster cannot draw is not offered rather than half-offered."""
    graph.add((rdflib.URIRef(NS + "broken"), rdflib.RDF.type, rdflib.URIRef(STER + "MapLayer")))

    assert "broken" not in {layer["label"] for layer in geo_shapes.map_layers(graph)}


def test_a_layer_url_must_be_http(graph):
    """These come from the loaded file: a javascript: URL must never reach a tile
    request, and a file:// one must not read the user's disk."""
    graph.add((rdflib.URIRef(NS + "evil"), rdflib.RDF.type, rdflib.URIRef(STER + "MapLayer")))
    graph.add(
        (
            rdflib.URIRef(NS + "evil"),
            rdflib.URIRef(STER + "tileUrl"),
            rdflib.Literal("javascript:alert(1)"),
        )
    )

    urls = [layer["url"] for layer in geo_shapes.map_layers(graph)]

    assert not any(u.startswith("javascript:") for u in urls)


def test_a_layer_falls_back_to_its_local_name(graph):
    graph.add((rdflib.URIRef(NS + "unlabelled"), rdflib.RDF.type, rdflib.URIRef(STER + "MapLayer")))
    graph.add(
        (
            rdflib.URIRef(NS + "unlabelled"),
            rdflib.URIRef(STER + "tileUrl"),
            rdflib.Literal("https://example.org/{z}/{x}/{y}.png"),
        )
    )

    assert "unlabelled" in {layer["label"] for layer in geo_shapes.map_layers(graph)}
