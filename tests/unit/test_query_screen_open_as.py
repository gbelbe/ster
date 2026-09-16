"""Opening a query's result as a map or as a graph, and saying when you cannot.

Both views are named on every run — the unavailable one dimmed, with its reason
— rather than the available one appearing and the other staying invisible. A
control you only see when it works is one you never learn exists.

The two have different preconditions, and conflating them would make one of the
buttons lie:

  map    needs coordinates, which `locate()` finds either on the row itself or
         on any entity the row names, so a query returning stores with no
         lat/long still maps when the store carries geometry
  graph  needs triples. A SELECT returns columns; wrapping rows into triples
         would invent a graph the query never asked for, so it stays unavailable
         rather than opening something empty and looking broken
"""

from __future__ import annotations

import pytest

from ster.sparql_query import QueryResult
from ster.tui import query


def _result(query_type: str, rows: int = 1) -> QueryResult:
    return QueryResult(
        columns=["s", "p", "o"],
        rows=[["a", "b", "c"]] * rows,
        query_type=query_type,
    )


@pytest.mark.parametrize("query_type", ["CONSTRUCT", "DESCRIBE"])
def test_triple_producing_queries_can_be_graphed(query_type):
    assert query.is_graphable(_result(query_type))


@pytest.mark.parametrize("query_type", ["SELECT", "ASK"])
def test_row_producing_queries_cannot(query_type):
    """The whole point of keeping it grey: a SELECT would draw nothing."""
    assert not query.is_graphable(_result(query_type))


def test_a_construct_that_matched_nothing_is_not_graphable():
    """Right type, no triples — opening it would show an empty canvas."""
    assert not query.is_graphable(_result("CONSTRUCT", rows=0))


def test_the_graph_url_carries_the_query_and_not_the_token():
    """Mirrors map_url: the query travels in the URL, the token is embedded by
    the page, so it stays out of browser history."""
    url = query.graph_url("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")

    assert "/viz?q=" in url
    assert "CONSTRUCT" in url
    assert "token" not in url


def test_the_graph_url_percent_encodes_the_query():
    url = query.graph_url("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")

    assert " " not in url.split("?q=", 1)[1]


def test_a_query_replaces_the_model_walk_in_the_rendered_page():
    """The page renders whichever payload it is given without knowing which
    produced it — the same property /api/graph?q relies on."""
    import json
    import re

    from ster import store
    from ster.viz_vowl import render_vowl_html

    taxonomy = store.load("ster/tui/demo.ttl")

    def _payload(page: str) -> dict:
        match = re.search(r"__STER_GRAPH__\s*=\s*(\{)", page)
        start, depth = match.start(1), 0
        for end in range(start, len(page)):
            if page[end] == "{":
                depth += 1
            elif page[end] == "}":
                depth -= 1
                if depth == 0:
                    break
        return json.loads(page[start : end + 1])["data"]

    model = _payload(render_vowl_html(taxonomy, "demo.ttl", api_token="t"))
    queried = _payload(
        render_vowl_html(
            taxonomy,
            "demo.ttl",
            api_token="t",
            sparql="CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o } LIMIT 5",
        )
    )

    assert model["nodes"] != queried["nodes"], "the query drove the page"
