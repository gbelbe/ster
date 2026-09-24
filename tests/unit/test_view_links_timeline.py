"""The timeline joins the map and the graph as a view a query can ask for.

Added to `view_links`, so `POST /api/sparql_query`, `run_sparql` and
`open_view` all offer it by construction, and each view says how much it would
show — the number `open_view` reports back to the agent.
"""

from __future__ import annotations

from ster.mcp_context import sparql_payload
from ster.mcp_server import TOOLS
from tests._places_and_dates import CONSTRUCT, DATED, NOTHING_PLACED, PLACES
from tests._places_and_dates import load_places_and_dates as _load

BASE = "http://127.0.0.1:9123"


def test_dated_rows_get_a_timeline_link(tmp_path):
    payload = sparql_payload(_load(tmp_path), DATED, "timeline", BASE)

    assert payload["view_unavailable"] is None
    assert payload["view_url"].startswith(BASE + "/timeline?q=")


def test_rows_without_dates_are_refused_a_timeline_with_the_fix(tmp_path):
    payload = sparql_payload(_load(tmp_path), NOTHING_PLACED, "timeline", BASE)

    assert payload["view_url"] is None
    assert "date" in payload["view_unavailable"]


def test_each_view_reports_how_much_it_would_show(tmp_path):
    tax = _load(tmp_path)

    assert sparql_payload(tax, PLACES, "map", BASE)["view_count"] == 2
    assert sparql_payload(tax, PLACES, "timeline", BASE)["view_count"] == 1
    assert sparql_payload(tax, CONSTRUCT, "graph", BASE)["view_count"] == 3


def test_an_empty_view_reports_zero(tmp_path):
    assert sparql_payload(_load(tmp_path), NOTHING_PLACED, "map", BASE)["view_count"] == 0


def test_a_construct_with_no_triples_is_not_blamed_on_its_type(tmp_path):
    empty = CONSTRUCT.replace(
        "WHERE { ?c skos:inScheme ?s }", "WHERE { ?c skos:inScheme ?s FILTER(false) }"
    )
    reason = sparql_payload(_load(tmp_path), empty, "graph", BASE)["view_unavailable"]

    assert "no triples" in reason


def test_run_sparql_offers_the_timeline_too():
    run_sparql = next(tool for tool in TOOLS if tool["name"] == "run_sparql")

    assert "timeline" in run_sparql["inputSchema"]["properties"]["view"]["enum"]
