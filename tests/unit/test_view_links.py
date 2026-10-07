"""A link to a view, or the reason there cannot be one — never an exception.

Handled in `sparql_payload` rather than in either caller, for the reason that
function exists: a protocol is a way in, not a place where behaviour lives.
Putting it in the MCP tool alone would have given an agent a capability the REST
endpoint does not have, which is the drift this module was written to avoid.

Nothing here opens a browser. The MCP server runs inside ster's API process —
possibly headless, possibly on another machine, possibly started days ago in a
terminal nobody is watching — so opening a window there is a side effect in the
wrong session, arriving through the one tool that most advertises having none.
The caller knows what it can display; this returns a URL and lets it decide.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ster import view_links
from ster.model import Label, LabelType, RDFClass, Taxonomy
from ster.sparql_query import QueryResult


@pytest.fixture
def tax() -> Taxonomy:
    t = Taxonomy()
    uri = "https://x/Thing"
    t.owl_classes[uri] = RDFClass(
        uri=uri, labels=[Label(lang="en", value="Thing", type=LabelType.PREF)]
    )
    return t


def _result(query_type: str = "SELECT", rows: int = 1) -> QueryResult:
    return QueryResult(columns=["s"], rows=[["https://x/Thing"]] * rows, query_type=query_type)


@pytest.fixture(autouse=True)  # noqa: V103
def _server_up():
    with patch.object(view_links, "_server_running", return_value=True):
        yield


def test_a_construct_gets_a_graph_link(tax):
    url, reason = view_links.link_for(tax, _result("CONSTRUCT"), "CONSTRUCT {}", "graph")

    assert reason is None
    assert "/viz?q=" in url


def test_a_select_is_refused_a_graph_with_the_fix_in_the_message(tax):
    """'No' without a next step is the answer that gets retried verbatim."""
    url, reason = view_links.link_for(tax, _result("SELECT"), "SELECT *", "graph")

    assert url is None
    assert "CONSTRUCT" in reason


def test_rows_without_coordinates_are_refused_a_map(tax):
    url, reason = view_links.link_for(tax, _result(), "SELECT *", "map")

    assert url is None
    assert "coordinates" in reason


def test_a_stopped_server_is_named_before_anything_else(tax):
    """Checked first: every other reason is about the query, and telling someone
    to rewrite a query that was fine would send them the wrong way."""
    with patch.object(view_links, "_server_running", return_value=False):
        url, reason = view_links.link_for(tax, _result("CONSTRUCT"), "CONSTRUCT {}", "graph")

    assert url is None
    assert "ster serve" in reason


def test_an_unknown_view_says_what_the_choices_are(tax):
    url, reason = view_links.link_for(tax, _result("CONSTRUCT"), "CONSTRUCT {}", "chart")

    assert url is None
    assert "map" in reason and "graph" in reason


def test_exactly_one_of_url_and_reason_is_ever_set(tax):
    for view, result in [
        ("graph", _result("CONSTRUCT")),
        ("graph", _result("SELECT")),
        ("map", _result()),
        ("chart", _result()),
    ]:
        url, reason = view_links.link_for(tax, result, "q", view)
        assert (url is None) != (reason is None)


def test_the_query_travels_percent_encoded_and_the_token_does_not():
    url = view_links.map_url("SELECT ?s WHERE { ?s ?p ?o }")

    assert " " not in url.split("?q=", 1)[1]
    assert "token" not in url


# ── what annotate() adds, and what it leaves alone ───────────────────────────


def test_no_view_asked_means_nothing_added(tax):
    payload = view_links.annotate({"rows": []}, tax, _result(), "q", None)

    assert payload == {"rows": []}


def test_the_rows_survive_a_view_that_cannot_be_built(tax):
    """A failed view is not a failed query — an agent that asked for a nicety
    must not lose the answer it actually needed."""
    payload = view_links.annotate(
        {"rows": [["a"]], "row_count": 1}, tax, _result("SELECT"), "q", "graph"
    )

    assert payload["rows"] == [["a"]]
    assert payload["view_url"] is None
    assert payload["view_unavailable"]


def test_a_usable_link_carries_a_hint_for_callers_without_a_browser(tax):
    payload = view_links.annotate({}, tax, _result("CONSTRUCT"), "CONSTRUCT {}", "graph")

    assert payload["view_url"]
    assert "browser" in payload["view_hint"]


# ---- embed: the link asks for the page without its own chrome ------------------------------------

_BASE = "http://127.0.0.1:8765"


def test_map_url_has_no_embed_unless_asked() -> None:
    assert "embed" not in view_links.map_url("SELECT 1", base=_BASE)


def test_map_url_asks_for_embed_when_told_to() -> None:
    assert view_links.map_url("SELECT 1", base=_BASE, embed=True).endswith("&embed=1")


def test_map_url_embed_comes_after_the_focus() -> None:
    url = view_links.map_url("SELECT 1", "https://x/Thing", base=_BASE, embed=True)
    assert url == f"{_BASE}/map?q=SELECT%201&focus=https%3A//x/Thing&embed=1"


def test_timeline_url_has_no_embed_unless_asked() -> None:
    assert "embed" not in view_links.timeline_url("SELECT 1", base=_BASE)


def test_timeline_url_embed_keeps_the_date_range() -> None:
    url = view_links.timeline_url(
        "SELECT 1", base=_BASE, date_range=view_links.DateRange(after="2025-01-01"), embed=True
    )
    assert "after=2025-01-01" in url
    assert url.endswith("&embed=1")


def test_embed_never_touches_the_graph_link() -> None:
    assert "embed" not in view_links.graph_url("SELECT 1", base=_BASE)
