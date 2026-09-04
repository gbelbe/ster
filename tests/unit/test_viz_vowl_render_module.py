"""Unit tests for the ster.viz_vowl._render entry points: ensure_published_server,
open_in_browser, push_update, open_focused_in_browser.

The actual HTML rendering, the live FastAPI server, and the browser are all
mocked out — these tests are about the control flow (live-server vs static
fallback, is_running vs not) rather than re-testing render_vowl_html or the
server modules, which have their own coverage.
"""

from __future__ import annotations

from unittest.mock import patch

from ster.model import Taxonomy
from ster.viz_vowl import _render, _server


def _reset_server_state():
    _server._out_path = None
    _server._file_path = None


# ── ensure_published_server ───────────────────────────────────────────────────


def test_ensure_published_server_returns_none_when_api_unavailable():
    with patch.object(_server, "_start_api_server", return_value=False):
        assert _render.ensure_published_server(Taxonomy()) is None


def test_ensure_published_server_returns_base_url_when_started():
    with (
        patch.object(_server, "_start_api_server", return_value=True),
        patch("ster.api_server.load_server_config", return_value=("http://127.0.0.1", 8765)),
    ):
        assert _render.ensure_published_server(Taxonomy()) == "http://127.0.0.1:8765"


# ── open_in_browser ────────────────────────────────────────────────────────────


def test_open_in_browser_uses_live_server_when_available():
    with (
        patch.object(_server, "_start_api_server", return_value=True),
        patch("ster.api_server.load_server_config", return_value=("http://127.0.0.1", 8765)),
        patch("ster.viz_vowl._render.webbrowser.open") as wb_open,
    ):
        url = _render.open_in_browser(Taxonomy())
    assert url == "http://127.0.0.1:8765/"
    wb_open.assert_called_once_with(url)


def test_open_in_browser_falls_back_to_static_server_when_api_unavailable(tmp_path):
    _reset_server_state()
    try:
        with (
            patch.object(_server, "_start_api_server", return_value=False),
            patch.object(_render, "_graph_path", return_value=tmp_path / "graph_vowl.html"),
            patch.object(_render, "_write_html") as write_html,
            patch.object(_render, "_write_data_json") as write_json,
            patch.object(_server, "_ensure_server", return_value=9001),
            patch("ster.viz_vowl._render.webbrowser.open") as wb_open,
        ):
            url = _render.open_in_browser(Taxonomy())
        assert url == "http://127.0.0.1:9001/graph_vowl.html"
        write_html.assert_called_once()
        write_json.assert_called_once()
        wb_open.assert_called_once_with(url)
    finally:
        _reset_server_state()


# ── push_update ────────────────────────────────────────────────────────────────


def test_push_update_pushes_via_live_server_when_running():
    with (
        patch("ster.api_server.is_running", return_value=True),
        patch("ster.api_server.push_taxonomy") as push,
    ):
        _render.push_update(Taxonomy())
    push.assert_called_once()


def test_push_update_rewrites_static_files_when_not_running_and_published():
    _reset_server_state()
    try:
        _server._out_path = "sentinel-out.html"
        _server._file_path = "sentinel-file.ttl"
        with (
            patch("ster.api_server.is_running", return_value=False),
            patch.object(_render, "_write_html") as write_html,
            patch.object(_render, "_write_data_json") as write_json,
        ):
            _render.push_update(Taxonomy())
        assert write_html.call_args[0][1:] == ("sentinel-file.ttl", "sentinel-out.html")
        write_json.assert_called_once()
    finally:
        _reset_server_state()


def test_push_update_is_a_no_op_when_not_running_and_never_published():
    _reset_server_state()
    try:
        with (
            patch("ster.api_server.is_running", return_value=False),
            patch.object(_render, "_write_html") as write_html,
            patch.object(_render, "_write_data_json") as write_json,
        ):
            _render.push_update(Taxonomy())
        write_html.assert_not_called()
        write_json.assert_not_called()
    finally:
        _reset_server_state()


# ── open_focused_in_browser ───────────────────────────────────────────────────


def test_open_focused_in_browser_uses_live_server_when_available():
    with (
        patch("ster.api_server.is_running", return_value=True),
        patch("ster.api_server.load_server_config", return_value=("http://127.0.0.1", 8765)),
        patch("ster.viz_vowl._render.webbrowser.open") as wb_open,
    ):
        url = _render.open_focused_in_browser(Taxonomy(), "https://ex.org/Root")
    assert url.startswith("http://127.0.0.1:8765/?root=")
    wb_open.assert_called_once_with(url)


def test_open_focused_in_browser_falls_back_to_static_server(tmp_path):
    with (
        patch("ster.api_server.is_running", return_value=False),
        patch.object(_render._query_result, "_ster_cache_dir", return_value=tmp_path),
        patch.object(_render, "render_vowl_html", return_value="<html></html>"),
        patch.object(_server, "_ensure_server", return_value=9002),
        patch("ster.viz_vowl._render.webbrowser.open") as wb_open,
    ):
        url = _render.open_focused_in_browser(Taxonomy(), "https://ex.org/Root")
    assert url.startswith("http://127.0.0.1:9002/")
    wb_open.assert_called_once_with(url)
