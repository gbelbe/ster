"""Step definitions for tests/features/sparql/geo_shapes.feature."""

from __future__ import annotations

import pytest
import rdflib
from pytest_bdd import given, scenarios, then, when

from ster import geo_shapes

scenarios("../features/sparql/geo_shapes.feature")

NS = "https://example.org/geo#"
SQUARE = "POLYGON((-4.8 47.3, -1.0 47.3, -1.0 48.9, -4.8 48.9, -4.8 47.3))"
PREFIXES = (
    "@prefix geo: <http://www.opengis.net/ont/geosparql#> .\n"
    "@prefix wgs: <http://www.w3.org/2003/01/geo/wgs84_pos#> .\n"
    f"@prefix ex: <{NS}> .\n"
)


@pytest.fixture
def ctx() -> dict:
    return {}


def _load(ctx: dict, turtle: str) -> None:
    graph = rdflib.Graph()
    graph.parse(data=PREFIXES + turtle, format="turtle")
    ctx["graph"] = graph
    ctx["node"] = rdflib.URIRef(NS + "R")


# ── Given ──────────────────────────────────────────────────────────────────────


@given("an entity whose geometry is a GeoSPARQL WKT polygon")
def given_wkt_polygon(ctx):
    _load(ctx, f'ex:R geo:asWKT "{SQUARE}"^^geo:wktLiteral .')


@given("an entity whose polygon hangs off a predicate ster has never seen")
def given_unknown_predicate(ctx):
    _load(ctx, f'ex:R ex:inHouseShapeProperty "{SQUARE}"^^geo:wktLiteral .')


@given("an entity whose geometry is a GeoSPARQL GeoJSON multipolygon")
def given_geojson(ctx):
    _load(
        ctx,
        'ex:R geo:asGeoJSON """{"type":"MultiPolygon","coordinates":'
        '[[[[-2,47],[-1,47],[-1,48],[-2,47]]]]}"""^^geo:geoJSONLiteral .',
    )


@given("an entity carrying both a point and a polygon")
def given_two_geometries(ctx):
    _load(
        ctx,
        "ex:R geo:hasGeometry ex:Centre, ex:Bounds .\n"
        'ex:Centre geo:asWKT "POINT(-1.55 47.22)"^^geo:wktLiteral .\n'
        f'ex:Bounds geo:asWKT "{SQUARE}"^^geo:wktLiteral .',
    )


@given("the point is marked as its default geometry")
def given_default_geometry(ctx):
    ctx["graph"].add((ctx["node"], geo_shapes.GEO.hasDefaultGeometry, rdflib.URIRef(NS + "Centre")))


@given("an entity carrying only wgs84 latitude and longitude")
def given_coordinates(ctx):
    _load(ctx, 'ex:R wgs:lat "47.28" ; wgs:long "-2.21" .')


@given("an entity whose WKT literal declares a projected coordinate system")
def given_projected_crs(ctx):
    _load(
        ctx,
        'ex:R geo:asWKT "<http://www.opengis.net/def/crs/EPSG/0/3857> '
        'POINT(-167000 5990000)"^^geo:wktLiteral .',
    )


# ── When ───────────────────────────────────────────────────────────────────────


@when("ster resolves its geometry")
def when_resolve(ctx):
    ctx["geometry"] = geo_shapes.geometry_of(ctx["graph"], ctx["node"])


# ── Then ───────────────────────────────────────────────────────────────────────


@then("it is mapped as a Polygon")
def then_polygon(ctx):
    assert ctx["geometry"] is not None
    assert ctx["geometry"].kind == "Polygon"


@then("it is mapped as a MultiPolygon")
def then_multipolygon(ctx):
    assert ctx["geometry"] is not None
    assert ctx["geometry"].kind == "MultiPolygon"


@then("it is mapped as a Point")
def then_point(ctx):
    assert ctx["geometry"] is not None
    assert ctx["geometry"].kind == "Point"


@then("it reports a centroid so it can be grouped with points")
def then_centroid(ctx):
    assert ctx["geometry"] is not None
    latitude, longitude = ctx["geometry"].centroid
    assert 47.3 <= latitude <= 48.9
    assert -4.8 <= longitude <= -1.0


@then("nothing is mapped for it")
def then_nothing(ctx):
    assert ctx["geometry"] is None
