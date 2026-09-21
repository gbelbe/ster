"""Opening the map on what the reader had selected.

`m` opened the map on the whole file, whatever the tree was showing, and opened
it even when the file held no geography at all — which produces an empty map,
and an empty map reads as a broken feature rather than as an answer.

The focus travels as an entity IRI, not as a query. The server turns one into
the other, because a brand reaches every one of its stores and 145 IRIs in a
query string is a link nobody can send. The page then carries that query where
"Show query" can show it, so a map that has filtered itself can say why.
"""

from __future__ import annotations

import rdflib

from ster.api import _DEFAULT_MAP_QUERY, _focused_map_query

NS = "https://ex.org/geo#"

TURTLE = """
@prefix ex:   <https://ex.org/geo#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .

ex:Castorama rdfs:label "Castorama" .
ex:bu-fr     ex:partOfBrand ex:Castorama .
ex:shop-1    ex:operatedBy ex:bu-fr ; rdfs:label "Shop 1" ; wgs:lat 48.11 ; wgs:long -1.68 .
ex:shop-2    ex:operatedBy ex:bu-fr ; rdfs:label "Shop 2" ; wgs:lat 47.90 ; wgs:long -2.10 .
ex:colour    rdfs:label "colour" .
"""


def _query_for(uri: str, turtle: str = TURTLE) -> str:
    """The query the server would prime the page with, for a focus of *uri*."""
    import ster.api as api

    graph = rdflib.Graph().parse(data=turtle, format="turtle")
    original = api._graph_for_locate
    api._graph_for_locate = lambda _tax: graph  # type: ignore[assignment]
    try:
        return _focused_map_query(None, uri)
    finally:
        api._graph_for_locate = original  # type: ignore[assignment]


# ── the query the focus becomes ───────────────────────────────────────────────


def test_a_brand_becomes_a_query_over_its_stores():
    """Two hops: the brand holds no coordinates, the unit none, the stores all."""
    query = _query_for(NS + "Castorama")

    assert f"<{NS}shop-1>" in query
    assert f"<{NS}shop-2>" in query
    assert "VALUES ?thing" in query


def test_a_located_entity_becomes_a_query_over_itself():
    query = _query_for(NS + "shop-1")

    assert f"<{NS}shop-1>" in query
    assert f"<{NS}shop-2>" not in query


def test_an_entity_that_reaches_nothing_produces_no_query():
    """So the caller falls back to the default rather than serving a query that
    selects nothing and a map that looks broken."""
    assert _query_for(NS + "colour") == ""


def test_the_query_asks_for_the_label_the_map_draws():
    query = _query_for(NS + "Castorama")

    assert "?thing ?name" in query
    assert "OPTIONAL { ?thing rdfs:label ?name }" in query


def test_the_focus_query_is_not_the_default_one():
    """Regression guard: falling through to the default silently maps the whole
    file, which is exactly what pressing m on one brand is meant to avoid."""
    assert _query_for(NS + "Castorama") != _DEFAULT_MAP_QUERY


# ── how it reaches the page ───────────────────────────────────────────────────


def test_the_link_carries_the_entity_rather_than_the_query(monkeypatch):
    """Short enough to send whether it reaches one store or a thousand — which
    is the whole reason the server builds the query instead of the TUI."""
    import ster.api_server as api_server
    import ster.tui.query as tui_query

    monkeypatch.setattr(api_server, "load_server_config", lambda: ("http://127.0.0.1", 8765))

    plain = tui_query.map_url("")
    focused = tui_query.map_url("", NS + "Castorama")

    assert "focus=" not in plain
    assert focused.endswith("focus=https%3A//ex.org/geo%23Castorama")
    assert len(focused) < 120
