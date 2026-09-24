"""`open_view` shows a query's result in one of ster's views, through the API.

The tool never runs a query or reads the model itself: it asks
`POST /api/sparql_query` for the view, exactly as a page or a script would, and
only decides what to do with the answer — open a browser for a caller on this
machine, or hand back the link. These tests give it a fake API and a fake
browser, so they check that decision and nothing the API already owns.
"""

from __future__ import annotations

from typing import Any

import pytest

from ster import mcp_views

URL = "http://127.0.0.1:9123/map?q=SELECT"


class FakeApi:
    """Records each call and answers with a canned (status, body)."""

    def __init__(self, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status = status
        self.body = body if body is not None else _ready("map", 2)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self.calls.append((path, payload))
        return self.status, self.body


def _ready(view: str, count: int) -> dict[str, Any]:
    page = {"map": "map", "timeline": "timeline", "graph": "viz"}[view]
    return {
        "rows": [["https://x/a"]],
        "row_count": 1,
        "view_url": f"http://127.0.0.1:9123/{page}?q=SELECT",
        "view_unavailable": None,
        "view_count": count,
    }


class FakeBrowser:
    def __init__(self, works: bool = True) -> None:
        self.works = works
        self.opened: list[str] = []

    def __call__(self, url: str) -> bool:
        self.opened.append(url)
        return self.works


def _open(api, browser=None, **args):
    return mcp_views.open_view({"view": "map", "query": "SELECT ?s {}", **args}, api, browser)


@pytest.mark.parametrize(
    ("view", "noun"), [("map", "places"), ("timeline", "moments"), ("graph", "triples")]
)
def test_each_view_asks_the_sparql_api_once_with_the_view(view, noun):
    api = FakeApi(body=_ready(view, 3))
    result = mcp_views.open_view({"view": view, "query": "Q"}, api, FakeBrowser())

    assert api.calls == [("/api/sparql_query", {"query": "Q", "view": view})]
    assert result["count"] == 3
    assert result["summary"] == f"3 {noun}"


def test_a_single_item_is_not_pluralised():
    result = _open(FakeApi(body=_ready("timeline", 1)), FakeBrowser(), view="timeline")

    assert result["summary"] == "1 moment"


def test_a_local_caller_gets_the_page_opened():
    browser = FakeBrowser()
    result = _open(FakeApi(), browser)

    assert browser.opened == [URL]
    assert result["opened"] is True
    assert result["url"] == URL


def test_a_remote_caller_gets_a_link_only():
    """No opener means the caller is not on this machine: a window here is
    a window nobody asking can see."""
    result = _open(FakeApi(), None)

    assert result["opened"] is False
    assert result["url"] == URL
    assert "link" in result["hint"]


def test_open_false_returns_the_link_only():
    browser = FakeBrowser()
    result = _open(FakeApi(), browser, open=False)

    assert browser.opened == []
    assert result["opened"] is False
    assert result["url"] == URL


def test_a_browser_that_fails_to_open_reports_opened_false():
    """`webbrowser.open` answers False on a machine with no browser to run."""
    result = _open(FakeApi(), FakeBrowser(works=False))

    assert result["opened"] is False
    assert result["url"] == URL
    assert "link" in result["hint"]


def test_an_empty_view_is_not_opened_and_says_why():
    body = {"rows": [], "row_count": 0, "view_url": None, "view_unavailable": "no place"}
    browser = FakeBrowser()
    result = _open(FakeApi(body=body), browser)

    assert browser.opened == []
    assert result["opened"] is False
    assert result["url"] is None
    assert result["view_unavailable"] == "no place"


def test_a_query_error_from_the_api_is_passed_on_not_raised():
    body = {"error": "query_error", "message": "bad syntax"}
    browser = FakeBrowser()
    result = _open(FakeApi(body=body), browser)

    assert browser.opened == []
    assert result == {"error": "query_error", "message": "bad syntax"}


def test_an_http_failure_from_the_api_is_reported_not_raised():
    result = _open(FakeApi(status=403, body={"detail": "Origin not allowed"}), FakeBrowser())

    assert result["error"] == "api_error"
    assert "403" in result["message"]
    assert "Origin not allowed" in result["message"]


def test_an_unknown_view_is_refused_before_the_api_is_asked():
    api = FakeApi()
    result = mcp_views.open_view({"view": "chart", "query": "Q"}, api, FakeBrowser())

    assert api.calls == []
    assert result["error"] == "unknown_view"
    assert "graph, map, timeline" in result["message"]


@pytest.mark.parametrize(
    ("length", "refused"),
    [(mcp_views.MAX_QUERY_CHARS, False), (mcp_views.MAX_QUERY_CHARS + 1, True)],
)
def test_a_query_too_long_for_a_link_is_refused(length, refused):
    api = FakeApi()
    result = mcp_views.open_view({"view": "map", "query": "x" * length}, api, FakeBrowser())

    assert (result.get("error") == "query_too_long") is refused
    assert (api.calls == []) is refused


def test_without_an_api_the_tool_says_it_needs_the_http_server():
    """Called outside an HTTP request (tests, an embedded use) there is no API
    to go through, and the tool must not fall back to calling ster directly."""
    result = mcp_views.open_view({"view": "map", "query": "Q"}, None, FakeBrowser())

    assert result["error"] == "no_api"
