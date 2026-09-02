"""A hardcoded date in a layer URL is a layer that stops working.

Most open geodata carries a time dimension, and many services will not serve
their default step — a 24-hour accumulation has nothing to show until 24 hours
into the forecast. Writing today's date into the ontology fixes it until
tomorrow, so the file states an offset and ster resolves it per request.
"""

from __future__ import annotations

import datetime as dt

import pytest
import rdflib

from ster import geo_shapes

STER = "https://ster.dev/ns/map#"
NS = "https://example.org/l#"


def _layer(url: str) -> list[dict]:
    graph = rdflib.Graph()
    graph.parse(
        data=f"""\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ster: <{STER}> .
@prefix ex: <{NS}> .
ex:l a ster:MapLayer ; rdfs:label "L"@en ; ster:tileUrl "{url}" .
""",
        format="turtle",
    )
    return geo_shapes.map_layers(graph)


@pytest.mark.parametrize("offset", [0, 2, -1])
def test_a_date_offset_resolves_against_today(offset: int) -> None:
    expected = (dt.date.today() + dt.timedelta(days=offset)).isoformat()

    sign = "+" if offset >= 0 else "-"
    url = _layer(f"https://x.example.org/wms?time={{date:{sign}{abs(offset)}d}}")[0]["url"]

    assert url.endswith("time=" + expected)


def test_a_layer_without_a_placeholder_is_untouched() -> None:
    assert _layer("https://x.example.org/{z}/{x}/{y}.png")[0]["url"].endswith("/{z}/{x}/{y}.png")


def test_a_malformed_date_placeholder_drops_the_layer() -> None:
    """Sending a literal brace to a tile server is worse than showing nothing."""
    assert _layer("https://x.example.org/wms?time={date:soon}") == []


def test_the_demo_asks_for_a_forward_date_not_a_fixed_one() -> None:
    from pathlib import Path

    ttl = Path("ster/tui/mixed-gear-demo.ttl").read_text(encoding="utf-8")
    line = next(x for x in ttl.splitlines() if "TOTPREC24H" in x)
    block = ttl[ttl.index("gear:layer-dwd-rain") : ttl.index("gear:layer-dwd-rain") + 600]

    assert "Icon_reg025" in line, "the ensemble layer renders probabilities, not millimetres"
    assert "{date:+" in block
