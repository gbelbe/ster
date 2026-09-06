"""Opening the map with no query of your own must still show the hierarchy.

The TUI's "open map" action sends an empty query and the server substitutes its
default. That default predated both polygon support and the place hierarchy, and
it defeated them twice over: it matched only ``wgs:lat``/``wgs:long``, so every
GeoSPARQL shape was missing, and it *selected* those as columns — which makes the
page place rows from the columns and never ask the server to resolve them. No
resolution means no level, no parent, no ancestors, so every point was drawn at
once with nothing to drill into.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import rdflib

from ster.api import _DEFAULT_MAP_QUERY

DEMO = Path("ster/tui/mixed-gear-demo.ttl")
GEO_WKT = rdflib.URIRef("http://www.opengis.net/ont/geosparql#asWKT")


@pytest.fixture(scope="module")
def demo() -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(DEMO, format="turtle")
    return graph


def _columns(graph: rdflib.Graph) -> list[str]:
    return [str(v) for v in graph.query(_DEFAULT_MAP_QUERY).vars]


def test_the_default_query_does_not_select_coordinate_columns(demo) -> None:
    """A lat/long column pair makes the page place rows itself, hierarchy and all.

    geo_map_html short-circuits on those column names, so selecting them is what
    silently turns the drill-down off.
    """
    columns = {c.lower() for c in _columns(demo)}

    assert not (columns & {"lat", "latitude"}), columns
    assert not (columns & {"long", "lon", "lng", "longitude"}), columns


def test_the_default_query_returns_the_entity_itself(demo) -> None:
    """The URI is what /api/locate resolves — without it nothing can be placed."""
    rows = list(demo.query(_DEFAULT_MAP_QUERY))

    assert rows, "the demo must yield rows"
    assert all(isinstance(row[0], rdflib.URIRef) for row in rows)


def test_the_default_query_finds_shapes_as_well_as_points(demo) -> None:
    """The old default missed every polygon: they carry no wgs:lat."""
    rows = list(demo.query(_DEFAULT_MAP_QUERY))
    with_shape = [row for row in rows if (row[0], GEO_WKT, None) in demo]

    assert len(with_shape) >= 6, f"expected the continent and countries, got {len(with_shape)}"


def test_the_default_query_spans_more_than_one_level(demo) -> None:
    """Grouping needs depth: everything at one level is the flat map again."""
    from ster import geo_shapes

    levels = {geo_shapes.place_level(demo, row[0]) for row in demo.query(_DEFAULT_MAP_QUERY)}

    assert len(levels) > 1, f"only one level present: {levels}"


def test_the_default_query_detects_shapes_by_datatype(demo) -> None:
    """Not by predicate name — the rule the whole geometry module is built on."""
    assert "wktLiteral" in _DEFAULT_MAP_QUERY
    assert "datatype(" in _DEFAULT_MAP_QUERY


def test_the_default_limit_does_not_silently_truncate_a_real_ontology() -> None:
    """200 was small enough to make a real file look wrong rather than partial.

    On the 34-place demo the cap is invisible. On an ontology of 1,267 places it
    kept an arbitrary 200 — whichever the graph happened to yield first — and the
    map read France 2, Spain 164 when the truth is France 588, Spain 266. A map
    that is confidently wrong is worse than one that is slow.
    """
    import re

    limits = [int(n) for n in re.findall(r"LIMIT\s+(\d+)", _DEFAULT_MAP_QUERY)]

    assert limits, "a default query with no limit at all could hang on a huge graph"
    assert min(limits) >= 5000, f"limit {min(limits)} truncates real ontologies"
