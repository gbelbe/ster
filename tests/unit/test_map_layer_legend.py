"""A colour ramp with no legend is decoration.

A temperature or rainfall overlay paints the map in colours that mean something
specific, and without a scale the reader cannot tell 2°C from 20°C. WMS servers
publish one through GetLegendGraphic, so it is derived rather than asked for; a
layer may also state its own.
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

ex:temp a ster:MapLayer ;
    rdfs:label "Temperature"@en ;
    ster:tileUrl "https://maps.example.org/geoserver/wms" ;
    ster:wmsLayers "x:T2M" .

ex:tiles a ster:MapLayer ;
    rdfs:label "Terrain"@en ;
    ster:tileUrl "https://tile.example.org/{{z}}/{{x}}/{{y}}.png" .

ex:stated a ster:MapLayer ;
    rdfs:label "Stated"@en ;
    ster:tileUrl "https://tile.example.org/s/{{z}}/{{x}}/{{y}}.png" ;
    ster:legendUrl "https://example.org/my-legend.png" .
"""


@pytest.fixture
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return g


def _by_label(graph):
    return {x["label"]: x for x in geo_shapes.map_layers(graph)}


def test_a_wms_layer_gets_a_legend_without_being_asked(graph):
    """GetLegendGraphic is part of WMS, so the URL can be derived."""
    legend = str(_by_label(graph)["Temperature"]["legendUrl"])

    assert "GetLegendGraphic" in legend
    assert "layer=x%3AT2M" in legend or "layer=x:T2M" in legend


def test_a_stated_legend_wins(graph):
    """If the file names one, that is the author's answer."""
    assert _by_label(graph)["Stated"]["legendUrl"] == "https://example.org/my-legend.png"


def test_a_plain_tile_layer_has_no_legend(graph):
    """There is no standard way to ask a tile service for one."""
    assert _by_label(graph)["Terrain"]["legendUrl"] == ""


def test_a_stated_legend_must_be_http(graph):
    graph.add(
        (
            rdflib.URIRef(NS + "stated"),
            rdflib.URIRef(STER + "legendUrl"),
            rdflib.Literal("javascript:alert(1)"),
        )
    )

    legends = [str(x["legendUrl"]) for x in geo_shapes.map_layers(graph)]

    assert not any(x.startswith("javascript:") for x in legends)


# ── the page itself ────────────────────────────────────────────────────────────
# These assert on the JS source, which catches a missing wire but never a
# rendering fault. The map is checked in a browser as well.


def test_the_page_shows_a_legend_when_a_layer_is_switched_on():
    from ster import geo_map_html

    page = geo_map_html._PAGE

    assert "overlayadd" in page
    assert "overlayremove" in page
    assert "legendUrl" in page


def test_the_legend_url_is_vetted_like_every_other_url():
    """It becomes an <img src>, so it goes through safeUrl."""
    from ster import geo_map_html

    assert "safeUrl(spec.legendUrl" in geo_map_html._PAGE


def test_the_demo_offers_a_24h_precipitation_layer_and_no_dropped_ones():
    from pathlib import Path

    ttl = Path("ster/tui/mixed-gear-demo.ttl").read_text(encoding="utf-8")

    assert "TOTPREC24H" in ttl
    for gone in ("Cycle routes", "Precipitation (NASA)", "Railways"):
        assert gone not in ttl
