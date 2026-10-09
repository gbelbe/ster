"""While a graph is still loading, the tools that need it say so at once instead of keeping the caller waiting."""

import threading

import pytest

from ster import mcp_server, warmup
from ster.model import Taxonomy


@pytest.fixture
def loading(monkeypatch):
    """A taxonomy whose warm-up is held open until the test lets it finish."""
    release = threading.Event()
    monkeypatch.setattr("ster.mcp_context.overview", lambda *_a: release.wait(5))
    monkeypatch.setattr("ster.mcp_context.vocabulary", lambda *_a: None)
    tax = Taxonomy()
    warmup.start(tax)
    yield tax
    release.set()
    warmup._current["done"].wait(5)


def _call(tax, name):
    return mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        },
        tax,
    )


def test_a_graph_tool_answers_loading_with_the_seconds_so_far(loading):
    result = _call(loading, "get_overview")["result"]
    assert result["isError"] is True
    assert "still loading" in result["content"][0]["text"]


def test_a_tool_that_reads_only_the_model_is_not_held_back(loading):
    result = _call(loading, "search_entities")["result"]
    assert "still loading" not in str(result)


def test_ready_once_the_warmup_finishes(loading):
    assert warmup.loading_seconds(loading) is not None
    warmup._current["done"].set()
    assert warmup.loading_seconds(loading) is None


def test_a_taxonomy_never_warmed_is_never_loading():
    assert warmup.loading_seconds(Taxonomy()) is None


def test_the_rest_overview_answers_503_with_retry_after_while_loading(loading, tmp_path):
    from fastapi.testclient import TestClient

    from ster.api import SSEBroadcaster, create_app

    app = create_app(loading, "tok", SSEBroadcaster(), lambda t: None, file_path=tmp_path / "q.ttl")
    response = TestClient(app).get("/api/overview", headers={"Authorization": "Bearer tok"})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "10"
    assert "still loading" in response.json()["detail"]
