"""The TUI's side of the MCP server.

The app starts the API server when it mounts, so an agent has something to
connect to. Best-effort — it may never disturb the editor.
"""

from __future__ import annotations

import pytest

import ster.api_server as srv
from ster.tui.app import _context_server_notice, _start_context_server

pytestmark = pytest.mark.tui


@pytest.fixture(autouse=True)
def _no_server(monkeypatch):
    """Start every test with no background server running."""
    monkeypatch.setattr(srv, "_bg", srv._Background())


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


def test_start_context_server_supplies_a_graph_page_renderer(monkeypatch):
    """An agent's /viz link must work before the graph viewer was ever opened."""
    calls: dict = {}

    def _fake(taxonomy, path=None, **kwargs):
        calls.update(kwargs)
        return True

    monkeypatch.setattr(srv, "start_background", _fake)
    _start_context_server("TAX", None)
    assert callable(calls.get("html_renderer"))


def test_the_graph_page_renderer_loads_the_visualisation_only_when_called(monkeypatch):
    """Starting the editor must not pay for the visualisation stack."""
    import sys

    from ster.tui.app._helpers import _graph_page_renderer

    monkeypatch.delitem(sys.modules, "ster.viz_vowl._render", raising=False)
    render = _graph_page_renderer(None)
    assert "ster.viz_vowl._render" not in sys.modules

    seen: dict = {}

    def fake_render(taxonomy, path, **kwargs):
        seen.update(taxonomy=taxonomy, path=path, **kwargs)
        return "<html>g</html>"

    import ster.viz_vowl._render as vowl_render

    monkeypatch.setattr(vowl_render, "render_vowl_html", fake_render)
    assert render("TAX", "urn:root", "tok", True, "SELECT 1") == "<html>g</html>"
    assert seen["api_token"] == "tok" and seen["root_uri"] == "urn:root"
    assert seen["full"] is True and seen["sparql"] == "SELECT 1"


def test_start_context_server_reports_failure_without_raising(monkeypatch):
    """A taken port (a second ster instance) means no MCP, not a crash."""
    monkeypatch.setattr(srv, "start_background", lambda *a, **k: False)
    assert _start_context_server("TAX", None) is False


def test_start_context_server_swallows_errors(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("address already in use")

    monkeypatch.setattr(srv, "start_background", _boom)
    assert _start_context_server("TAX", None) is False


# ── the toast when the port was taken ─────────────────────────────────────────


def _claiming(monkeypatch, claim):
    """Stub claim_port; returns the confirm callables it was handed."""
    seen: list = []

    def _claim(taxonomy_file, confirm=None, host=None, port=None):
        seen.append(confirm)
        return claim

    monkeypatch.setattr("ster.viz_vowl.claim_port", _claim)
    return seen


def test_notice_is_none_when_the_server_started(monkeypatch):
    seen = _claiming(monkeypatch, None)

    assert _context_server_notice(True, None) is None
    assert seen == []  # no port probing on the happy path


def test_notice_reports_a_reused_same_file_server_as_info(monkeypatch):
    from ster.viz_vowl._claim import REUSE, Claim

    _claiming(monkeypatch, Claim(REUSE, url="http://127.0.0.1:8765"))

    message, severity = _context_server_notice(False, None)

    assert "http://127.0.0.1:8765" in message
    assert severity == "information"


def test_notice_warns_when_another_session_holds_the_port(monkeypatch):
    from ster.viz_vowl._claim import BLOCKED, Claim

    _claiming(monkeypatch, Claim(BLOCKED, "another ster session is open (x). Please close it."))

    message, severity = _context_server_notice(False, None)

    assert message.startswith("MCP is off: another ster session is open")
    assert severity == "warning"


def test_notice_never_closes_anything(monkeypatch):
    """The startup path may only look at the port: its confirm must decline."""
    from ster.viz_vowl._claim import FREE, Claim

    seen = _claiming(monkeypatch, Claim(FREE))

    _context_server_notice(False, None)

    assert seen[0]("Close it and start a fresh server?") is False


def test_notice_is_none_when_start_failed_on_a_free_port(monkeypatch):
    from ster.viz_vowl._claim import FREE, Claim

    _claiming(monkeypatch, Claim(FREE))

    assert _context_server_notice(False, None) is None


def test_notice_never_raises(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("lsof exploded")

    monkeypatch.setattr("ster.viz_vowl.claim_port", _boom)

    assert _context_server_notice(False, None) is None
