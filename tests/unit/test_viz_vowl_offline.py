"""Unit tests for the static-fallback safeguards in viz_vowl.

Covers scope A of the "graph opens an older/static version" bug:
  * the static HTTP server must never serve a cache directory listing;
  * a token-less (static) page must carry an in-page "live server not running"
    banner so the degraded experience is never silent;
  * ``is_live_server`` reflects whether the live API backs the page;
  * ``_await_uvicorn_started`` only reports success once *our* uvicorn bound,
    so a stale server squatting the port can't be mistaken for ours.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import ster.viz_vowl as vv
from ster.model import RDFClass, Taxonomy

NS = "https://example.org/onto#"


def _tax() -> Taxonomy:
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    return tax


# ── offline banner ─────────────────────────────────────────────────────────────


def test_offline_banner_present_without_token() -> None:
    banner = vv._offline_banner("")
    assert banner
    assert "offline-banner" in banner


def test_offline_banner_absent_with_token() -> None:
    assert vv._offline_banner("a-real-token") == ""


def test_offline_banner_has_close_button() -> None:
    # The warning must be dismissable so it doesn't permanently cover the graph.
    assert "offline-banner-close" in vv._offline_banner("")


def test_offline_banner_close_wired_in_app_js() -> None:
    assert "offline-banner-close" in vv._app_js()


def test_render_vowl_html_shows_offline_banner_when_static() -> None:
    html = vv.render_vowl_html(_tax(), None, api_token="")
    assert 'id="offline-banner"' in html
    # No leftover template placeholder.
    assert "__OFFLINE_BANNER__" not in html


def test_render_vowl_html_hides_offline_banner_when_live() -> None:
    html = vv.render_vowl_html(_tax(), None, api_token="live-token")
    assert 'id="offline-banner"' not in html
    assert "__OFFLINE_BANNER__" not in html


def test_query_result_html_shows_offline_banner() -> None:
    # Query-result pages are always static (token=""), so they must warn too.
    _graph, html = vv._build_query_result_html(_tax(), {NS + "Animal"})
    assert 'id="offline-banner"' in html
    assert "__OFFLINE_BANNER__" not in html


# ── directory-listing safeguard ────────────────────────────────────────────────


def test_quiet_handler_refuses_directory_listing() -> None:
    """The static server must answer a directory request with 404, never a listing.

    Root cause of the "root page with html files" symptom: the bare
    SimpleHTTPRequestHandler renders an index of ~/.cache/ster when hit at ``/``.
    """
    import http.server

    # It must *override* the base lister (which renders an index page)...
    assert (
        vv._QuietHandler.list_directory is not http.server.SimpleHTTPRequestHandler.list_directory
    )

    # ...and answer with a 404 for an existing directory rather than a listing.
    handler = vv._QuietHandler.__new__(vv._QuietHandler)
    handler.send_error = MagicMock()  # type: ignore[method-assign]
    result = handler.list_directory("/tmp")
    assert result is None
    handler.send_error.assert_called_once()
    assert handler.send_error.call_args[0][0] == 404


def test_quiet_handler_sets_no_cache_headers(monkeypatch) -> None:
    """Static graph pages must not be browser-cached.

    The JS is inlined in the page, so a cached page served a stale build until a
    manual hard-reload — the recurring "it only works after Ctrl+Shift+R".
    """
    import http.server

    handler = vv._QuietHandler.__new__(vv._QuietHandler)
    handler.send_header = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(http.server.SimpleHTTPRequestHandler, "end_headers", lambda self: None)

    handler.end_headers()

    sent = {c.args[0]: c.args[1] for c in handler.send_header.call_args_list}
    assert "no-store" in sent.get("Cache-Control", "")


# ── live-server predicate ──────────────────────────────────────────────────────


def test_is_live_server_true_when_api_app_set(monkeypatch) -> None:
    monkeypatch.setattr(vv, "_api_app", object())
    assert vv.is_live_server() is True


def test_is_live_server_false_when_no_api_app(monkeypatch) -> None:
    monkeypatch.setattr(vv, "_api_app", None)
    assert vv.is_live_server() is False


# ── uvicorn readiness helper ───────────────────────────────────────────────────


class _FakeServer:
    def __init__(self, started: bool) -> None:
        self.started = started


def test_await_uvicorn_started_true_when_started() -> None:
    holder = {"server": _FakeServer(started=True)}
    assert vv._await_uvicorn_started(holder, sleep=lambda *_: None) is True


def test_await_uvicorn_started_false_on_startup_error() -> None:
    holder = {"server": _FakeServer(started=False), "error": RuntimeError("address in use")}
    assert vv._await_uvicorn_started(holder, sleep=lambda *_: None) is False


def test_await_uvicorn_started_false_when_serve_finished_unstarted() -> None:
    holder = {"server": _FakeServer(started=False), "done": True}
    assert vv._await_uvicorn_started(holder, sleep=lambda *_: None) is False


def test_await_uvicorn_started_false_on_timeout() -> None:
    clock = {"n": 0}

    def fake_monotonic() -> float:
        clock["n"] += 1
        return 0.0 if clock["n"] == 1 else 99.0

    holder: dict = {}
    result = vv._await_uvicorn_started(
        holder, timeout=1.0, sleep=lambda *_: None, monotonic=fake_monotonic
    )
    assert result is False


# ── viewer graph-opened status ─────────────────────────────────────────────────


def test_graph_opened_status_live_server(monkeypatch) -> None:
    from ster.nav.viewer import TaxonomyViewer

    monkeypatch.setattr(vv, "_api_app", object())  # is_live_server() → True
    msg = TaxonomyViewer._graph_opened_status("http://localhost:8765")
    assert "static snapshot" not in msg
    assert "Graph opened in browser" in msg


def test_graph_opened_status_static_fallback(monkeypatch) -> None:
    from ster.nav.viewer import TaxonomyViewer

    monkeypatch.setattr(vv, "_api_app", None)  # is_live_server() → False
    msg = TaxonomyViewer._graph_opened_status("file:///tmp/graph.html")
    assert "static snapshot" in msg
    assert "no live server" in msg


# ── html title escaping (XSS) ─────────────────────────────────────────────────


def test_render_vowl_html_escapes_title() -> None:
    """A root_uri containing HTML special chars must not appear raw in the page title."""
    tax = _tax()
    # Fragment-based URI: _local() extracts the fragment, which would be injected
    # verbatim into __TITLE__ without escaping.
    html = vv.render_vowl_html(
        tax, None, root_uri="https://example.org/onto#<script>alert(1)</script>"
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_title_is_escaped_in_query_result_html() -> None:
    """Query-result pages: the __TITLE__ slot must be HTML-escaped."""
    tax = _tax()
    tax.ontology_label = "<b>Injected</b>"
    _graph, html = vv._build_query_result_html(tax, {NS + "Animal"})
    assert "<b>Injected</b>" not in html.split("</title>")[0]
    assert "&lt;b&gt;Injected&lt;/b&gt;" in html
