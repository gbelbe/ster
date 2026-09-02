"""A twenty-row image is a poor way to read a temperature.

A WMS GetLegendGraphic image lists every bucket the style defines, which for a
temperature field means a tall strip covering the whole of the atmosphere's
range. When a layer states its ramp as value/colour pairs instead, the same
information fits in a small gradient bar with a few labelled ticks.
"""

from __future__ import annotations

import pytest
import rdflib

from ster import geo_shapes

STER = "https://ster.dev/ns/map#"
NS = "https://example.org/l#"


def _layers(extra: str) -> list[dict]:
    graph = rdflib.Graph()
    graph.parse(
        data=f"""\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ster: <{STER}> .
@prefix ex:   <{NS}> .
ex:l a ster:MapLayer ; rdfs:label "L"@en ;
    ster:tileUrl "https://x.example.org/wms" ; ster:wmsLayers "a:b" ;
    {extra} .
""",
        format="turtle",
    )
    return geo_shapes.map_layers(graph)


def test_a_stated_ramp_becomes_ordered_value_colour_stops():
    scale = _layers('ster:legendScale "-30:#7a0177, 0:#c7e9b4, 40:#b10026"')[0]["legendScale"]

    assert [x["value"] for x in scale] == [-30.0, 0.0, 40.0]
    assert [x["color"] for x in scale] == ["#7a0177", "#c7e9b4", "#b10026"]


def test_stops_are_sorted_so_the_gradient_runs_one_way():
    scale = _layers('ster:legendScale "40:#b10026, -30:#7a0177, 0:#c7e9b4"')[0]["legendScale"]

    assert [x["value"] for x in scale] == [-30.0, 0.0, 40.0]


def test_a_unit_travels_with_the_scale():
    assert _layers('ster:legendScale "0:#fff" ; ster:legendUnit "°C"')[0]["legendUnit"] == "°C"


@pytest.mark.parametrize(
    "bad",
    [
        '"-30:red, 0:#c7e9b4"',  # a colour name could be anything
        '"-30:#7a0177, hot:#c7e9b4"',  # a tick must be a number
        '"-30:#7a0177, 0:#c7e9b4; background:url(x)"',  # CSS injected through the stop
        '"-30"',  # no colour at all
    ],
)
def test_a_malformed_ramp_is_dropped_rather_than_half_drawn(bad):
    """It becomes a CSS gradient, so nothing unvetted may reach the style sheet."""
    layer = _layers(f"ster:legendScale {bad}")[0]

    assert layer["legendScale"] == []


def test_a_single_stop_is_not_a_gradient():
    """Two points are the minimum that can describe a ramp."""
    assert _layers('ster:legendScale "0:#c7e9b4"')[0]["legendScale"] == []


def test_a_layer_without_a_ramp_still_gets_its_image_legend():
    layer = _layers('ster:attribution "x"')[0]

    assert layer["legendScale"] == []
    assert "GetLegendGraphic" in layer["legendUrl"]
