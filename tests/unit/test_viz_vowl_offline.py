"""Unit tests for the token-less (static-export) rendering path in viz_vowl.

render_vowl_html(api_token="") is still a real, permanent rendering mode — used
by static publish/export, which genuinely has no live server behind it, unlike
the graph-viewer's browser-open path, which now requires one (no more silent
fallback there — see test_viz_vowl_render_module.py). This file covers:
  * a token-less page carries an in-page "live server not running" banner, so
    a static export never looks like a live page;
  * ``is_live_server`` reflects whether the live API backs the page;
  * ``api_server._await_uvicorn_started`` only reports success once *our* uvicorn bound,
    so a stale server squatting the port can't be mistaken for ours.
"""

from __future__ import annotations

import ster.api_server as srv
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


def test_render_vowl_html_no_show_all_btn_when_static() -> None:
    """The 'Show all nodes' button only makes sense against a live /?full=1 —
    a static export has no server behind it to ask, so it always gets the
    unscoped graph and needs no button offering one."""
    html = vv.render_vowl_html(_tax(), file_path=None)
    assert "Show all nodes" not in html


# ── live-server predicate ──────────────────────────────────────────────────────


def test_is_live_server_true_when_api_app_set(monkeypatch) -> None:
    # is_live_server now delegates to api_server, which owns the server state.
    import ster.api_server as srv

    monkeypatch.setattr(srv, "_bg", srv._Background(app=object()))
    assert vv.is_live_server() is True


def test_is_live_server_false_when_no_api_app(monkeypatch) -> None:
    import ster.api_server as srv

    monkeypatch.setattr(srv, "_bg", srv._Background())
    assert vv.is_live_server() is False


# ── uvicorn readiness helper ───────────────────────────────────────────────────


class _FakeServer:
    def __init__(self, started: bool) -> None:
        self.started = started


def test_await_uvicorn_started_true_when_started() -> None:
    holder = {"server": _FakeServer(started=True)}
    assert srv._await_uvicorn_started(holder, sleep=lambda *_: None) is True


def test_await_uvicorn_started_false_on_startup_error() -> None:
    holder = {"server": _FakeServer(started=False), "error": RuntimeError("address in use")}
    assert srv._await_uvicorn_started(holder, sleep=lambda *_: None) is False


def test_await_uvicorn_started_false_when_serve_finished_unstarted() -> None:
    holder = {"server": _FakeServer(started=False), "done": True}
    assert srv._await_uvicorn_started(holder, sleep=lambda *_: None) is False


def test_await_uvicorn_started_false_on_timeout() -> None:
    clock = {"n": 0}

    def fake_monotonic() -> float:
        clock["n"] += 1
        return 0.0 if clock["n"] == 1 else 99.0

    holder: dict = {}
    result = srv._await_uvicorn_started(
        holder, timeout=1.0, sleep=lambda *_: None, monotonic=fake_monotonic
    )
    assert result is False


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
