"""Unit tests for ontology-agnostic geographic detection in query results."""

from __future__ import annotations

import rdflib

from ster.geo_results import cluster_options, has_geodata, locate
from ster.sparql_query import QueryResult

BOATS = "https://example.org/sailboat#"
MUSEUMS = "https://example.org/culture#"
WGS = "http://www.w3.org/2003/01/geo/wgs84_pos#"
SKOS = "http://www.w3.org/2004/02/skos/core#"


def _graph(turtle: str) -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(
        data=f"""
        @prefix wgs:  <{WGS}> .
        @prefix skos: <{SKOS}> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix sb:   <{BOATS}> .
        @prefix cu:   <{MUSEUMS}> .
        {turtle}
        """,
        format="turtle",
    )
    return g


def _placed() -> rdflib.Graph:
    return _graph("""
        sb:brest rdfs:label "Brest" ; wgs:lat 48.39 ; wgs:long -4.48 .
        sb:nowhere rdfs:label "Nowhere" .
    """)


# ── locating rows ────────────────────────────────────────────────────────────


def test_locate_finds_entity_with_wgs_coordinates() -> None:
    result = QueryResult(columns=["place"], rows=[[BOATS + "brest"]])
    points = locate(_placed(), result)
    assert len(points) == 1
    assert (round(points[0].lat, 2), round(points[0].long, 2)) == (48.39, -4.48)


def test_locate_reads_bare_lat_long_columns() -> None:
    result = QueryResult(columns=["name", "lat", "long"], rows=[["Anywhere", "1.5", "2.5"]])
    points = locate(_placed(), result)
    assert len(points) == 1
    assert (points[0].lat, points[0].long) == (1.5, 2.5)


def test_locate_prefers_explicit_columns_over_entity_lookup() -> None:
    """Explicit coordinates win: the query said them outright."""
    result = QueryResult(columns=["place", "lat", "long"], rows=[[BOATS + "brest", "10.0", "20.0"]])
    points = locate(_placed(), result)
    assert (points[0].lat, points[0].long) == (10.0, 20.0)


def test_locate_skips_rows_without_coordinates() -> None:
    result = QueryResult(columns=["place"], rows=[[BOATS + "nowhere"]])
    assert locate(_placed(), result) == []


def test_locate_skips_entity_with_lat_but_no_long() -> None:
    graph = _graph('sb:half rdfs:label "Half" ; wgs:lat 48.0 .')
    result = QueryResult(columns=["place"], rows=[[BOATS + "half"]])
    assert locate(graph, result) == []


def test_locate_skips_non_numeric_coordinates() -> None:
    graph = _graph('sb:bad rdfs:label "Bad" ; wgs:lat "north" ; wgs:long "west" .')
    result = QueryResult(columns=["place"], rows=[[BOATS + "bad"]])
    assert locate(graph, result) == []


def test_locate_uses_first_locatable_column_when_several() -> None:
    graph = _graph("""
        sb:a rdfs:label "A" ; wgs:lat 1.0 ; wgs:long 1.0 .
        sb:b rdfs:label "B" ; wgs:lat 2.0 ; wgs:long 2.0 .
    """)
    result = QueryResult(columns=["first", "second"], rows=[[BOATS + "a", BOATS + "b"]])
    points = locate(graph, result)
    assert (points[0].lat, points[0].long) == (1.0, 1.0)


def test_locate_is_agnostic_to_the_ontology() -> None:
    """Nothing about detection knows the sailboat vocabulary."""
    graph = _graph('cu:louvre rdfs:label "Louvre" ; wgs:lat 48.86 ; wgs:long 2.34 .')
    result = QueryResult(columns=["museum"], rows=[[MUSEUMS + "louvre"]])
    points = locate(graph, result)
    assert len(points) == 1
    assert points[0].label == "Louvre"


def test_locate_records_the_originating_row() -> None:
    result = QueryResult(columns=["place"], rows=[[BOATS + "nowhere"], [BOATS + "brest"]])
    points = locate(_placed(), result)
    assert [p.row for p in points] == [1]


# ── the mappable predicate ───────────────────────────────────────────────────


def test_has_geodata_true_when_any_row_located() -> None:
    result = QueryResult(columns=["place"], rows=[[BOATS + "nowhere"], [BOATS + "brest"]])
    assert has_geodata(_placed(), result) is True


def test_has_geodata_false_when_nothing_located() -> None:
    result = QueryResult(columns=["place"], rows=[[BOATS + "nowhere"]])
    assert has_geodata(_placed(), result) is False


def test_has_geodata_false_for_empty_result() -> None:
    assert has_geodata(_placed(), QueryResult(columns=["place"], rows=[])) is False


def test_has_geodata_false_for_errored_result() -> None:
    result = QueryResult(columns=[], rows=[], error="boom")
    assert has_geodata(_placed(), result) is False


def test_has_geodata_false_for_non_select_result() -> None:
    result = QueryResult(columns=["x"], rows=[[BOATS + "brest"]], query_type="ASK")
    assert has_geodata(_placed(), result) is False


# ── clustering options ───────────────────────────────────────────────────────


def test_cluster_options_lists_uri_valued_columns() -> None:
    graph = _graph("""
        sb:brest rdfs:label "Brest" ; wgs:lat 48.39 ; wgs:long -4.48 .
        sb:bretagne rdfs:label "Bretagne" .
    """)
    result = QueryResult(columns=["place", "region"], rows=[[BOATS + "brest", BOATS + "bretagne"]])
    options = cluster_options(graph, result)
    assert "region" in [o.key for o in options]


def test_cluster_options_excludes_the_locating_column() -> None:
    """Grouping points by themselves is not a clustering."""
    graph = _graph('sb:brest rdfs:label "Brest" ; wgs:lat 48.39 ; wgs:long -4.48 .')
    result = QueryResult(columns=["place"], rows=[[BOATS + "brest"]])
    assert [o.key for o in cluster_options(graph, result)] == []


def test_cluster_options_includes_skos_broader_ancestors() -> None:
    graph = _graph("""
        sb:brest rdfs:label "Brest" ; wgs:lat 48.39 ; wgs:long -4.48 ;
                 skos:broader sb:bretagne .
        sb:bretagne rdfs:label "Bretagne" ; skos:broader sb:france .
        sb:france rdfs:label "France" .
    """)
    result = QueryResult(columns=["place"], rows=[[BOATS + "brest"]])
    labels = [o.label for o in cluster_options(graph, result)]
    assert "Bretagne" in labels or "broader" in " ".join(labels).lower()


def test_cluster_options_empty_when_nothing_groups() -> None:
    result = QueryResult(columns=["place", "n"], rows=[[BOATS + "brest", "3"]])
    assert cluster_options(_placed(), result) == []
