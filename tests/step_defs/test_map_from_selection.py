"""Step definitions for map_from_selection.feature."""

from __future__ import annotations

import pytest
import rdflib
from pytest_bdd import given, scenarios, then

from ster.geo_shapes import anything_located, located_from

scenarios("../features/tui/map_from_selection.feature")

NS = "https://ex.org/geo#"

_PREFIXES = """
@prefix ex:   <https://ex.org/geo#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix geo:  <http://www.opengis.net/ont/geosparql#> .
"""


@pytest.fixture
def ctx() -> dict:
    return {}


def _load(ctx: dict, turtle: str) -> None:
    ctx["graph"] = rdflib.Graph().parse(data=_PREFIXES + turtle, format="turtle")


@given("a taxonomy with no coordinates")
def no_coordinates(ctx: dict) -> None:
    _load(ctx, 'ex:Fruit rdfs:label "Fruit" . ex:Apple rdfs:subClassOf ex:Fruit .')


@given("a file whose only geography is a region outline")
def only_a_shape(ctx: dict) -> None:
    _load(ctx, 'ex:Region geo:asWKT "POLYGON((0 0,1 0,1 1,0 0))"^^geo:wktLiteral .')


@given("a brand two hops from its located stores")
def brand_and_stores(ctx: dict) -> None:
    _load(
        ctx,
        """
ex:Castorama rdfs:label "Castorama" .
ex:bu-fr     ex:partOfBrand ex:Castorama .
ex:shop-1    ex:operatedBy ex:bu-fr ; wgs:lat 48.11 ; wgs:long -1.68 .
ex:shop-2    ex:operatedBy ex:bu-fr ; wgs:lat 47.90 ; wgs:long -2.10 .
ex:colour    rdfs:label "colour" .
""",
    )


@then("the file reports that nothing can be placed")
def nothing_placeable(ctx: dict) -> None:
    assert anything_located(ctx["graph"]) is False


@then("the file reports that something can be placed")
def something_placeable(ctx: dict) -> None:
    assert anything_located(ctx["graph"]) is True


@then("the selection resolves to those stores")
def resolves_to_stores(ctx: dict) -> None:
    reached = located_from(ctx["graph"], rdflib.URIRef(NS + "Castorama"))
    assert sorted(reached) == [NS + "shop-1", NS + "shop-2"]


@then("the page is primed with a query over them")
def query_over_them(ctx: dict) -> None:
    import ster.api as api

    original = api._graph_for_locate
    api._graph_for_locate = lambda _tax: ctx["graph"]
    try:
        query = api._focused_map_query(None, NS + "Castorama")
    finally:
        api._graph_for_locate = original
    assert "VALUES ?thing" in query
    assert f"<{NS}shop-1>" in query


@then("an unrelated entity resolves to nothing")
def unrelated_resolves_to_nothing(ctx: dict) -> None:
    assert located_from(ctx["graph"], rdflib.URIRef(NS + "colour")) == []


@then("no query is built for it")
def no_query_built(ctx: dict) -> None:
    import ster.api as api

    original = api._graph_for_locate
    api._graph_for_locate = lambda _tax: ctx["graph"]
    try:
        assert api._focused_map_query(None, NS + "colour") == ""
    finally:
        api._graph_for_locate = original
