"""Unit tests for the ster.viz_vowl._render entry points: ensure_published_server,
open_in_browser, push_update, open_focused_in_browser.

The actual HTML rendering, the live FastAPI server, and the browser are all
mocked out — these tests are about the control flow (live server started vs.
not, is_running vs not) rather than re-testing render_vowl_html or the server
modules, which have their own coverage. There is no static, offline fallback
to test any more: a caller that cannot start the live server gets a clear
RuntimeError instead.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ster.model import Taxonomy
from ster.viz_vowl import _render, _server

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


def test_open_in_browser_raises_clearly_when_api_unavailable():
    """No fallback: a caller that cannot start the live server gets a clear
    RuntimeError naming why, and no browser tab opens for a page it does not back."""
    with (
        patch.object(_server, "_start_api_server", return_value=False),
        patch.object(_server, "unavailable_reason", return_value="port 8765 is held by X"),
        patch("ster.viz_vowl._render.webbrowser.open") as wb_open,
        pytest.raises(RuntimeError, match="port 8765 is held by X"),
    ):
        _render.open_in_browser(Taxonomy())
    wb_open.assert_not_called()


# ── push_update ────────────────────────────────────────────────────────────────


def test_push_update_pushes_via_live_server_when_running():
    with (
        patch("ster.api_server.is_running", return_value=True),
        patch("ster.api_server.push_taxonomy") as push,
    ):
        _render.push_update(Taxonomy())
    push.assert_called_once()


def test_push_update_is_a_no_op_when_not_running():
    """Nothing to push to: there is no static page to keep in sync any more."""
    with patch("ster.api_server.is_running", return_value=False):
        _render.push_update(Taxonomy())  # must not raise


# ── open_focused_in_browser ───────────────────────────────────────────────────


def test_open_focused_in_browser_uses_live_server_when_available():
    with (
        patch.object(_server, "_start_api_server", return_value=True),
        patch("ster.api_server.load_server_config", return_value=("http://127.0.0.1", 8765)),
        patch("ster.viz_vowl._render.webbrowser.open") as wb_open,
    ):
        url = _render.open_focused_in_browser(Taxonomy(), "https://ex.org/Root")
    assert url.startswith("http://127.0.0.1:8765/?root=")
    wb_open.assert_called_once_with(url)


def test_open_focused_in_browser_starts_the_server_from_a_cold_start():
    """Unlike the old is_running()-only check, this must actually try to start
    the server — a focused graph should open even when nothing started it yet."""
    with (
        patch.object(_server, "_start_api_server", return_value=True) as start,
        patch("ster.api_server.load_server_config", return_value=("http://127.0.0.1", 8765)),
        patch("ster.viz_vowl._render.webbrowser.open"),
    ):
        _render.open_focused_in_browser(Taxonomy(), "https://ex.org/Root")
    start.assert_called_once()


def test_open_focused_in_browser_raises_clearly_when_api_unavailable():
    with (
        patch.object(_server, "_start_api_server", return_value=False),
        patch.object(_server, "unavailable_reason", return_value="port 8765 is held by X"),
        patch("ster.viz_vowl._render.webbrowser.open") as wb_open,
        pytest.raises(RuntimeError, match="port 8765 is held by X"),
    ):
        _render.open_focused_in_browser(Taxonomy(), "https://ex.org/Root")
    wb_open.assert_not_called()
