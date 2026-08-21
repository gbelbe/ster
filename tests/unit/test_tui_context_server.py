"""The TUI's side of the MCP context server.

Two seams: the app starts the API server when it mounts (so an agent has
something to connect to), and publishes the focused entity so
``get_current_context`` reflects what is on screen. Both are best-effort —
neither may disturb the editor.
"""

from __future__ import annotations

import pytest

import ster.api_server as srv
from ster.tui.app import _publish_selection, _start_context_server

NS = "https://example.org/zoo#"


@pytest.fixture(autouse=True)
def _no_server(monkeypatch):
    """Start every test with no background server running."""
    monkeypatch.setattr(srv, "_bg", srv._Background())


class _FakeApp:
    def __init__(self, state: dict | None = None):
        self.state = type("S", (), {"_ster": state if state is not None else {}})()


# ── selection publishing ──────────────────────────────────────────────────────


def test_publish_selection_is_a_noop_when_no_server_runs():
    _publish_selection(NS + "Dog")  # must not raise


def test_publish_selection_writes_the_uri_into_server_state(monkeypatch):
    app = _FakeApp()
    monkeypatch.setattr(srv, "_bg", srv._Background(app=app))

    _publish_selection(NS + "Dog")

    assert app.state._ster["selection"] == NS + "Dog"


def test_publish_selection_records_a_cleared_selection(monkeypatch):
    """Leaving an entity must clear the context, not keep a stale one."""
    app = _FakeApp({"selection": NS + "Dog"})
    monkeypatch.setattr(srv, "_bg", srv._Background(app=app))

    _publish_selection(None)

    assert app.state._ster["selection"] is None


def test_publish_selection_swallows_errors(monkeypatch):
    """Publishing context must never break navigation."""

    def _boom():
        raise RuntimeError("server exploded")

    monkeypatch.setattr(srv, "current_app", _boom)
    _publish_selection(NS + "Dog")  # must not raise


# ── server startup ────────────────────────────────────────────────────────────


def test_start_context_server_starts_the_background_server(monkeypatch):
    calls: dict = {}

    def _fake(taxonomy, path=None, **kwargs):
        calls.update(taxonomy=taxonomy, path=path, kwargs=kwargs)
        return True

    monkeypatch.setattr(srv, "start_background", _fake)
    assert _start_context_server("TAX", "zoo.ttl") is True
    assert calls["taxonomy"] == "TAX"
    assert calls["path"] == "zoo.ttl"


def test_start_context_server_supplies_no_html_renderer(monkeypatch):
    """MCP needs a server, not a landing page — the graph viewer attaches that."""
    calls: dict = {}

    def _fake(taxonomy, path=None, **kwargs):
        calls.update(kwargs)
        return True

    monkeypatch.setattr(srv, "start_background", _fake)
    _start_context_server("TAX", None)
    assert calls.get("html_renderer") is None


def test_start_context_server_reports_failure_without_raising(monkeypatch):
    """A taken port (a second ster instance) means no MCP, not a crash."""
    monkeypatch.setattr(srv, "start_background", lambda *a, **k: False)
    assert _start_context_server("TAX", None) is False


def test_start_context_server_swallows_errors(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("address already in use")

    monkeypatch.setattr(srv, "start_background", _boom)
    assert _start_context_server("TAX", None) is False
