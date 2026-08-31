"""BDD step definitions for tests/features/sparql/geo_results.feature."""

from __future__ import annotations

from typing import Any

import pytest
import rdflib
from pytest_bdd import given, parsers, scenarios, then, when

from ster.geo_results import has_geodata, locate
from ster.sparql_query import QueryResult

scenarios("../features/sparql/geo_results.feature")

BOATS = "https://example.org/sailboat#"
MUSEUMS = "https://example.org/culture#"
WGS = "http://www.w3.org/2003/01/geo/wgs84_pos#"


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {"graph": rdflib.Graph(), "result": None, "points": []}


def _parse(ctx: dict[str, Any], turtle: str) -> None:
    ctx["graph"].parse(
        data=f"""
        @prefix wgs:  <{WGS}> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix sb:   <{BOATS}> .
        @prefix cu:   <{MUSEUMS}> .
        {turtle}
        """,
        format="turtle",
    )


@given(parsers.parse('a graph where "{name}" has WGS84 coordinates'))
def graph_with_place(ctx: dict[str, Any], name: str) -> None:
    _parse(ctx, f'sb:brest rdfs:label "{name}" ; wgs:lat 48.39 ; wgs:long -4.48 .')


@given(parsers.parse('a graph where "{name}" has WGS84 coordinates and "{other}" has none'))
def graph_with_one_placed(ctx: dict[str, Any], name: str, other: str) -> None:
    _parse(
        ctx,
        f'sb:brest rdfs:label "{name}" ; wgs:lat 48.39 ; wgs:long -4.48 .\n'
        f'sb:nowhere rdfs:label "{other}" .',
    )


@given(parsers.parse('a graph of museums where "{name}" has WGS84 coordinates'))
def graph_of_museums(ctx: dict[str, Any], name: str) -> None:
    _parse(ctx, f'cu:louvre rdfs:label "{name}" ; wgs:lat 48.86 ; wgs:long 2.34 .')


@when(parsers.parse('a query returns the entity "{name}"'))
def query_returns_entity(ctx: dict[str, Any], name: str) -> None:
    uri = MUSEUMS + "louvre" if name == "Louvre" else BOATS + "brest"
    ctx["result"] = QueryResult(columns=["thing"], rows=[[uri]])


@when("a query returns a row with no entity carrying coordinates")
def query_returns_unplaced(ctx: dict[str, Any]) -> None:
    ctx["result"] = QueryResult(columns=["thing"], rows=[["just a literal"]])


@when("a query returns bare lat and long columns")
def query_returns_bare_columns(ctx: dict[str, Any]) -> None:
    ctx["result"] = QueryResult(columns=["name", "lat", "long"], rows=[["X", "1.0", "2.0"]])


@when("a query returns both entities")
def query_returns_both(ctx: dict[str, Any]) -> None:
    ctx["result"] = QueryResult(columns=["thing"], rows=[[BOATS + "nowhere"], [BOATS + "brest"]])


@then("the result is reported as mappable")
def reported_mappable(ctx: dict[str, Any]) -> None:
    assert has_geodata(ctx["graph"], ctx["result"]) is True


@then("the result is reported as not mappable")
def reported_not_mappable(ctx: dict[str, Any]) -> None:
    assert has_geodata(ctx["graph"], ctx["result"]) is False


@then(parsers.parse("{count:d} row is located"))
def rows_located(ctx: dict[str, Any], count: int) -> None:
    assert len(locate(ctx["graph"], ctx["result"])) == count
