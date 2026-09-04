"""Unit tests for ster.viz_vowl._server: port helpers, the quiet static handler,
and _ensure_server's actual startup path (the rest of the module is exercised
indirectly, through mocks, by the higher-level graph/query tests)."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from ster.viz_vowl import _server

# ── _process_name ────────────────────────────────────────────────────────────


def test_process_name_falls_back_to_pid_label_on_subprocess_error():
    with patch("ster.viz_vowl._server.subprocess.run", side_effect=OSError("no ps")):
        assert _server._process_name(4242) == "PID 4242"


def test_process_name_returns_command_line():
    result = MagicMock(stdout="python -m ster serve\n")
    with patch("ster.viz_vowl._server.subprocess.run", return_value=result):
        assert _server._process_name(1) == "python -m ster serve"


# ── _port_is_free ─────────────────────────────────────────────────────────────


def test_port_is_free_true_for_an_unused_port():
    # Bind to port 0 to get a genuinely free ephemeral port, release it, then check.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    assert _server._port_is_free("127.0.0.1", free_port) is True


def test_port_is_free_false_when_port_is_held():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        port = held.getsockname()[1]
        assert _server._port_is_free("127.0.0.1", port) is False


# ── _QuietHandler.list_directory ──────────────────────────────────────────────


def test_quiet_handler_list_directory_returns_404():
    handler = _server._QuietHandler.__new__(_server._QuietHandler)
    sent: list[tuple[int, str]] = []
    handler.send_error = lambda code, msg=None: sent.append((code, msg))  # type: ignore[method-assign]
    result = handler.list_directory("/tmp")
    assert result is None
    assert sent == [(404, "Not found")]


# ── _ensure_server ────────────────────────────────────────────────────────────


@pytest.fixture
def _reset_server_globals():
    """_ensure_server caches its HTTPServer/port in module globals; save, clear,
    and restore them so this test doesn't leak a live server into the rest of
    the suite (or pick one up from an earlier test)."""
    saved_server, saved_port = _server._http_server, _server._http_port
    _server._http_server, _server._http_port = None, None
    yield
    if _server._http_server is not None:
        _server._http_server.shutdown()
        _server._http_server.server_close()
    _server._http_server, _server._http_port = saved_server, saved_port


def test_ensure_server_starts_once_and_reuses_port(tmp_path, _reset_server_globals):
    with patch("ster.api_server.load_server_config", return_value=("http://127.0.0.1:0", 0)):
        first_port = _server._ensure_server(tmp_path)
        second_port = _server._ensure_server(tmp_path)  # cached — no new server started

    assert isinstance(first_port, int)
    assert first_port == second_port


# ── _listening_pid: token-parsing skips non-integer tokens ────────────────────


def test_listening_pid_skips_non_integer_tokens_before_finding_one():
    result = MagicMock(stdout="not-a-pid 4242\n")
    with patch("ster.viz_vowl._server.subprocess.run", return_value=result):
        assert _server._listening_pid(9999) == 4242


# ── _vowl_html ──────────────────────────────────────────────────────────────


def test_vowl_html_delegates_to_render_vowl_html():
    taxonomy = MagicMock()
    with patch(
        "ster.viz_vowl._server._render.render_vowl_html", return_value="<html>ok</html>"
    ) as render:
        result = _server._vowl_html(taxonomy, "https://ex.org/Root", "tok123")
    render.assert_called_once()
    assert result == "<html>ok</html>"


# ── _QuietHandler: log_message is a no-op, end_headers adds Cache-Control ─────


def test_quiet_handler_log_message_is_a_silent_no_op():
    handler = _server._QuietHandler.__new__(_server._QuietHandler)
    assert handler.log_message("%s", "anything") is None  # doesn't raise, doesn't print


def test_quiet_handler_end_headers_forbids_caching():
    handler = _server._QuietHandler.__new__(_server._QuietHandler)
    sent_headers: list[tuple[str, str]] = []
    handler.send_header = lambda k, v: sent_headers.append((k, v))  # type: ignore[method-assign]
    with patch("http.server.SimpleHTTPRequestHandler.end_headers", lambda self: None):
        handler.end_headers()
    assert ("Cache-Control", "no-cache, no-store, must-revalidate") in sent_headers


# ── _ensure_server: every preferred port taken → falls back to an ephemeral one ──


def test_ensure_server_falls_back_to_ephemeral_port_when_all_preferred_are_taken(
    tmp_path, _reset_server_globals
):
    with (
        patch("ster.api_server.load_server_config", return_value=("http://127.0.0.1:0", 0)),
        patch(
            "ster.viz_vowl._server.http.server.HTTPServer",
            side_effect=[OSError("taken")] * 20 + [MagicMock()],
        ),
    ):
        port = _server._ensure_server(tmp_path)

    assert isinstance(port, int)
