"""Resolving any entity to a geometry — point, polygon, multipolygon, collection.

``geo_results`` places a row only when it finds a wgs84 lat/long pair, so a
région that publishes a boundary cannot be drawn. GeoSPARQL literals carry their
own datatype, which is what makes this tractable: the geometry is recognisable
from the literal alone, so no registry of predicate names is needed and an
ontology's own vocabulary works unchanged.
"""

from __future__ import annotations

import rdflib

from ster import geo_shapes

NS = "https://example.org/geo#"

# A square, in the order WKT wants it: longitude first.
SQUARE_WKT = "POLYGON((-4.8 47.3, -1.0 47.3, -1.0 48.9, -4.8 48.9, -4.8 47.3))"


def _graph(turtle: str) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(
        data="@prefix geo: <http://www.opengis.net/ont/geosparql#> .\n"
        "@prefix wgs: <http://www.w3.org/2003/01/geo/wgs84_pos#> .\n"
        f"@prefix ex: <{NS}> .\n" + turtle,
        format="turtle",
    )
    return graph


def _node(local: str) -> rdflib.URIRef:
    return rdflib.URIRef(NS + local)


# ── detection is by datatype, never by predicate name ─────────────────────────


def test_a_wkt_polygon_on_the_standard_predicate_is_found():
    graph = _graph(f'ex:R geo:asWKT "{SQUARE_WKT}"^^geo:wktLiteral .')

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert geometry.kind == "Polygon"


def test_a_geometry_under_an_unknown_predicate_is_still_found():
    """The point of keying on the datatype: nobody agrees on predicate names.

    locn:geometry, georss, and a hundred in-house properties all carry the same
    self-describing literal, so a registry of predicates would be endless.
    """
    graph = _graph(f'ex:R ex:somePropertyNobodyHasSeen "{SQUARE_WKT}"^^geo:wktLiteral .')

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert geometry.kind == "Polygon"


def test_a_geojson_literal_is_found():
    graph = _graph(
        'ex:R geo:asGeoJSON """{"type":"MultiPolygon","coordinates":'
        '[[[[-2,47],[-1,47],[-1,48],[-2,47]]]]}"""^^geo:geoJSONLiteral .'
    )

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert geometry.kind == "MultiPolygon"


def test_a_geometry_behind_an_intermediate_node_is_found():
    """GeoSPARQL's normal shape: Feature -> hasGeometry -> Geometry -> asWKT."""
    graph = _graph(
        "ex:R a geo:Feature ; geo:hasGeometry ex:RShape .\n"
        f'ex:RShape a geo:Geometry ; geo:asWKT "{SQUARE_WKT}"^^geo:wktLiteral .'
    )

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert geometry.kind == "Polygon"


def test_a_plain_literal_is_not_mistaken_for_a_geometry():
    graph = _graph('ex:R ex:note "POLYGON is a word that appears in prose" .')

    assert geo_shapes.geometry_of(graph, _node("R")) is None


def test_an_entity_with_nothing_geographic_resolves_to_nothing():
    graph = _graph('ex:R ex:label "just a concept" .')

    assert geo_shapes.geometry_of(graph, _node("R")) is None


# ── WKT parsing ───────────────────────────────────────────────────────────────


def test_every_geometry_type_we_claim_to_support_parses():
    cases = {
        "POINT(-1.5 47.2)": "Point",
        "LINESTRING(0 0, 1 1)": "LineString",
        SQUARE_WKT: "Polygon",
        "MULTIPOINT((0 0), (1 1))": "MultiPoint",
        "MULTILINESTRING((0 0, 1 1), (2 2, 3 3))": "MultiLineString",
        "MULTIPOLYGON(((0 0, 1 0, 1 1, 0 0)))": "MultiPolygon",
        "GEOMETRYCOLLECTION(POINT(0 0), POINT(1 1))": "GeometryCollection",
    }

    for wkt, expected in cases.items():
        parsed = geo_shapes.wkt_to_geojson(wkt)
        assert parsed is not None, wkt
        assert parsed["type"] == expected, wkt


def test_a_polygon_keeps_longitude_first():
    """GeoJSON and WKT agree on lon-lat; getting this backwards moves France to Somalia."""
    parsed = geo_shapes.wkt_to_geojson(SQUARE_WKT)

    assert parsed is not None
    assert parsed["coordinates"][0][0] == [-4.8, 47.3]


def test_a_polygon_with_a_hole_keeps_both_rings():
    outer_and_hole = "POLYGON((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 2 1, 2 2, 1 2, 1 1))"

    parsed = geo_shapes.wkt_to_geojson(outer_and_hole)

    assert parsed is not None
    assert len(parsed["coordinates"]) == 2, "outer ring plus one hole"


def test_a_crs84_prefix_is_accepted_and_stripped():
    """CRS84 is GeoSPARQL's default and is already lon-lat: nothing to swap."""
    wkt = f"<http://www.opengis.net/def/crs/OGC/1.3/CRS84> {SQUARE_WKT}"

    parsed = geo_shapes.wkt_to_geojson(wkt)

    assert parsed is not None
    assert parsed["coordinates"][0][0] == [-4.8, 47.3]


def test_an_epsg_4326_prefix_flips_the_axis_order():
    """EPSG:4326 is lat-lon, the opposite of the bare default. Read it, do not guess."""
    wkt = "<http://www.opengis.net/def/crs/EPSG/0/4326> POINT(47.2 -1.5)"

    parsed = geo_shapes.wkt_to_geojson(wkt)

    assert parsed is not None
    assert parsed["coordinates"] == [-1.5, 47.2], "stored lat-lon, emitted lon-lat"


def test_a_projected_crs_is_refused_rather_than_misplaced():
    """Reprojecting needs pyproj; drawing metres as degrees is worse than nothing."""
    wkt = "<http://www.opengis.net/def/crs/EPSG/0/3857> POINT(-167000 5990000)"

    assert geo_shapes.wkt_to_geojson(wkt) is None


def test_z_ordinates_are_dropped_not_fatal():
    parsed = geo_shapes.wkt_to_geojson("POINT Z (-1.5 47.2 30)")

    assert parsed is not None
    assert parsed["coordinates"] == [-1.5, 47.2]


def test_an_empty_geometry_yields_nothing():
    assert geo_shapes.wkt_to_geojson("POLYGON EMPTY") is None


def test_malformed_wkt_returns_none_rather_than_raising():
    """Ontology data is arbitrary; a bad literal must not take down the map."""
    for bad in ("POLYGON((0 0, oops", "", "NOTAGEOMETRY(1 2)", "POINT()"):
        assert geo_shapes.wkt_to_geojson(bad) is None, bad


# ── which geometry wins ───────────────────────────────────────────────────────


def test_the_default_geometry_wins_over_the_others():
    graph = _graph(
        "ex:R geo:hasDefaultGeometry ex:Centre ; geo:hasGeometry ex:Centre, ex:Bounds .\n"
        'ex:Centre geo:asWKT "POINT(-1.55 47.22)"^^geo:wktLiteral .\n'
        f'ex:Bounds geo:asWKT "{SQUARE_WKT}"^^geo:wktLiteral .'
    )

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert geometry.kind == "Point"


def test_wgs84_coordinates_are_used_when_there_is_no_geometry():
    """The existing behaviour has to survive: today's point maps must keep working."""
    graph = _graph('ex:R wgs:lat "47.28" ; wgs:long "-2.21" .')

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert geometry.kind == "Point"
    assert geometry.geojson["coordinates"] == [-2.21, 47.28]


def test_a_geometry_is_preferred_over_bare_coordinates():
    """A boundary says more than the point someone also recorded."""
    graph = _graph(
        f'ex:R wgs:lat "47.28" ; wgs:long "-2.21" ; geo:asWKT "{SQUARE_WKT}"^^geo:wktLiteral .'
    )

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert geometry.kind == "Polygon"


# ── centroids keep shapes in the clustering feature ───────────────────────────


def test_a_polygon_reports_a_centroid():
    """Clustering groups by point; without this a shape drops out of the control.

    Asserted exactly, not just "inside the box": a looser check let a closing-
    vertex bug through, which put the centroid on a corner instead of the middle.
    """
    graph = _graph(f'ex:R geo:asWKT "{SQUARE_WKT}"^^geo:wktLiteral .')

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    lat, long = geometry.centroid
    assert (round(lat, 2), round(long, 2)) == (48.10, -2.90)


def test_a_closed_ring_does_not_weight_its_first_corner_twice():
    """Regression: a ring repeats its first vertex as its last.

    Averaging the raw positions counted that corner twice and dragged the centre
    towards it — France landed on its south-west corner rather than its middle,
    which is exactly where the cluster dot would have been drawn.
    """
    square = "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))"

    centroid = geo_shapes._centroid_of(geo_shapes.wkt_to_geojson(square))

    assert centroid == (5.0, 5.0), "the middle, not pulled towards (0, 0)"


def test_an_asserted_centroid_is_preferred_over_a_computed_one():
    """geo:hasCentroid is the author's answer; do not second-guess it."""
    graph = _graph(
        f'ex:R geo:asWKT "{SQUARE_WKT}"^^geo:wktLiteral ; geo:hasCentroid ex:C .\n'
        'ex:C geo:asWKT "POINT(-3.0 48.0)"^^geo:wktLiteral .'
    )

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert geometry.centroid == (48.0, -3.0)


def test_a_point_is_its_own_centroid():
    graph = _graph('ex:R geo:asWKT "POINT(-1.5 47.2)"^^geo:wktLiteral .')

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert geometry.centroid == (47.2, -1.5)


# ── what reaches the map ──────────────────────────────────────────────────────


class _Result:
    """The minimal shape of a SPARQL result that locate() accepts."""

    def __init__(self, columns, rows):
        self.columns, self.rows = columns, rows
        self.error, self.query_type = "", "SELECT"


def test_a_located_shape_carries_its_geojson_to_the_map():
    from ster.geo_results import locate

    graph = _graph(
        f'ex:R geo:asWKT "{SQUARE_WKT}"^^geo:wktLiteral ; '
        '<http://www.w3.org/2000/01/rdf-schema#label> "Bretagne" .'
    )

    [point] = locate(graph, _Result(["region"], [[NS + "R"]]))

    assert point.shape is not None
    assert point.shape["type"] == "Polygon"
    assert point.label == "Bretagne"


def test_a_located_shape_still_has_a_point_for_clustering():
    """lat/long are the centroid, so the cluster control needs no special case."""
    from ster.geo_results import locate

    graph = _graph(f'ex:R geo:asWKT "{SQUARE_WKT}"^^geo:wktLiteral .')

    [point] = locate(graph, _Result(["region"], [[NS + "R"]]))

    assert -4.8 <= point.long <= -1.0
    assert 47.3 <= point.lat <= 48.9


def test_a_plain_point_sends_no_redundant_shape():
    """lat/long already carry it; shipping a Point geometry too is dead weight."""
    from ster.geo_results import locate

    graph = _graph('ex:R wgs:lat "47.28" ; wgs:long "-2.21" .')

    [point] = locate(graph, _Result(["place"], [[NS + "R"]]))

    assert point.shape is None
    assert (point.lat, point.long) == (47.28, -2.21)


def test_a_result_mixing_points_and_shapes_locates_both():
    from ster.geo_results import locate

    graph = _graph(
        'ex:P wgs:lat "47.28" ; wgs:long "-2.21" .\n'
        f'ex:S geo:asWKT "{SQUARE_WKT}"^^geo:wktLiteral .'
    )

    points = locate(graph, _Result(["x"], [[NS + "P"], [NS + "S"]]))

    assert [p.shape is None for p in points] == [True, False]


# ── the browser half ──────────────────────────────────────────────────────────


def _map_js() -> str:
    from ster.geo_map_html import render_map_html

    return render_map_html("SELECT * WHERE {?s ?p ?o}", "tok")


def test_the_map_draws_geometry_with_leaflets_geojson_layer():
    assert "L.geoJSON(only.shape" in _map_js()


def test_shapes_appear_only_when_zoomed_in_enough():
    """Zoomed out, a hundred boundaries are unreadable and slow to draw."""
    js = _map_js()

    assert "const SHAPE_ZOOM" in js
    assert "map.getZoom() >= SHAPE_ZOOM" in js


def test_crossing_the_zoom_threshold_redraws_without_refitting():
    """Regression guard: refitting from the zoom handler re-fires the handler.

    draw() calls fitBounds, so an unconditional redraw on zoomend would move the
    map the reader just moved and loop.
    """
    js = _map_js()

    assert "if (wantsShapes() !== shapeMode) draw(false)" in js
    assert "function draw(fit = true)" in js


def test_a_grouped_view_stays_a_dot():
    """Clustering summarises many rows; one member's outline would misrepresent it."""
    assert "!grouped && shapeMode && only && only.shape" in _map_js()


# ── the guards, exercised ─────────────────────────────────────────────────────
#
# These are the branches that matter when someone opens a file ster did not
# write. Each one is a way arbitrary RDF can be wrong; none may raise.


def test_an_unterminated_crs_prefix_is_survivable():
    assert geo_shapes.wkt_to_geojson("<http://example.org/crs POINT(1 2)") is None


def test_a_geometry_with_no_parenthesis_at_all():
    assert geo_shapes.wkt_to_geojson("POINT") is None


def test_a_tag_that_is_only_whitespace():
    assert geo_shapes.wkt_to_geojson("   (1 2)") is None


def test_a_ring_that_is_not_parenthesised():
    assert geo_shapes.wkt_to_geojson("POLYGON(0 0, 1 1)") is None


def test_a_polygon_whose_ring_is_empty():
    assert geo_shapes.wkt_to_geojson("POLYGON(())") is None


def test_a_coordinate_with_a_single_ordinate():
    assert geo_shapes.wkt_to_geojson("POINT(5)") is None


def test_a_collection_whose_members_are_all_unusable():
    assert geo_shapes.wkt_to_geojson("GEOMETRYCOLLECTION(NOTAGEOMETRY(1 2))") is None


def test_a_collection_is_not_parenthesised():
    assert geo_shapes.wkt_to_geojson("GEOMETRYCOLLECTION POINT(0 0)") is None


def test_a_lat_first_collection_flips_each_member():
    """The CRS applies to the members, which are parsed one level down."""
    parsed = geo_shapes.wkt_to_geojson(
        "<http://www.opengis.net/def/crs/EPSG/0/4326> GEOMETRYCOLLECTION(POINT(47.2 -1.5))"
    )

    assert parsed is not None
    assert parsed["geometries"][0]["coordinates"] == [-1.5, 47.2]


def test_a_collection_reports_a_centroid_over_its_members():
    graph = _graph('ex:R geo:asWKT "GEOMETRYCOLLECTION(POINT(0 0), POINT(2 4))"^^geo:wktLiteral .')

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert geometry.centroid == (2.0, 1.0)


def test_a_geojson_literal_that_is_not_json():
    graph = _graph('ex:R geo:asGeoJSON "{not json at all"^^geo:geoJSONLiteral .')

    assert geo_shapes.geometry_of(graph, _node("R")) is None


def test_a_geojson_literal_that_is_json_but_not_a_geometry():
    graph = _graph('ex:R geo:asGeoJSON "[1, 2, 3]"^^geo:geoJSONLiteral .')

    assert geo_shapes.geometry_of(graph, _node("R")) is None


def test_a_geometry_with_no_positions_yields_nothing():
    """An otherwise well-formed GeoJSON with nothing to place has no centroid."""
    graph = _graph(
        'ex:R geo:asGeoJSON """{"type":"Polygon","coordinates":[]}"""^^geo:geoJSONLiteral .'
    )

    assert geo_shapes.geometry_of(graph, _node("R")) is None


def test_an_unusable_geometry_node_falls_through_to_the_next():
    """A broken hasGeometry must not shadow a good one."""
    graph = _graph(
        "ex:R geo:hasGeometry ex:Broken, ex:Good .\n"
        'ex:Broken geo:asWKT "POLYGON((0 0, oops"^^geo:wktLiteral .\n'
        f'ex:Good geo:asWKT "{SQUARE_WKT}"^^geo:wktLiteral .'
    )

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert geometry.kind == "Polygon"


def test_an_unusable_asserted_centroid_falls_back_to_the_computed_one():
    graph = _graph(
        f'ex:R geo:asWKT "{SQUARE_WKT}"^^geo:wktLiteral ; geo:hasCentroid ex:C .\n'
        'ex:C geo:asWKT "GARBAGE"^^geo:wktLiteral .'
    )

    geometry = geo_shapes.geometry_of(graph, _node("R"))

    assert geometry is not None
    assert 47.3 <= geometry.centroid[0] <= 48.9
