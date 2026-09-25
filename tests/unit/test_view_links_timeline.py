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


# ── after/before bound the timeline view, not the entities a query names ──────


def test_a_range_that_excludes_every_moment_is_reported_as_unavailable(tmp_path):
    payload = sparql_payload(_load(tmp_path), DATED, "timeline", BASE, after="2999-01-01")

    assert payload["view_url"] is None
    assert "date" in payload["view_unavailable"]


def test_the_view_count_reflects_the_range_not_just_the_rows(tmp_path):
    """DATED names one row; the fixture's entity is dated once, before 2999, so
    asking for after 2999 must drop it from the count too, not just the link."""
    unfiltered = sparql_payload(_load(tmp_path), DATED, "timeline", BASE)
    filtered = sparql_payload(_load(tmp_path), DATED, "timeline", BASE, before="1900-01-01")

    assert unfiltered["view_count"] >= 1
    assert filtered["view_url"] is None
    assert filtered["view_count"] == 0


def test_the_opened_link_carries_the_range_so_reopening_it_stays_bounded(tmp_path):
    payload = sparql_payload(
        _load(tmp_path), DATED, "timeline", BASE, after="1980-01-01", before="2000-01-01"
    )

    assert "after=1980-01-01" in payload["view_url"]
    assert "before=2000-01-01" in payload["view_url"]


def test_no_range_given_leaves_the_link_exactly_as_before(tmp_path):
    payload = sparql_payload(_load(tmp_path), DATED, "timeline", BASE)

    assert "after=" not in payload["view_url"]
    assert "before=" not in payload["view_url"]
