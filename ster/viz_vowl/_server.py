"""Standalone preview HTTP server: port management, the API server bootstrap, and the static-file server used by 'ster show'.

Note: _listening_pid / _process_name / _port_is_free / port_holder / free_port stay
together in this module because tests monkeypatch them via module-attribute
lookup (see tests/unit/test_viz_vowl_port.py) — splitting them apart would
silently break those patches."""

from __future__ import annotations

import functools
import http.server
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Final

from ..model import Taxonomy
from ..viz import (
    _label_for,  # noqa: F401  (re-exported for potential callers)
)
from . import _detail, _render

_LIT_N_127_0_1: Final = "127.0.0.1"


def _listening_pid(port: int) -> int | None:
    """The PID listening on *port* via ``lsof``, or None when the port is free, ``lsof``
    is unavailable, or nothing can be parsed (never raises — best-effort)."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for token in result.stdout.split():
        try:
            return int(token)
        except ValueError:
            continue
    return None


def _process_name(pid: int) -> str:
    """A human description (the command line) of *pid* via ``ps``, else ``"PID <n>"``."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        name = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        name = ""
    return name or f"PID {pid}"


def port_holder(host: str | None = None, port: int | None = None) -> tuple[int, str] | None:
    """The ``(pid, command)`` of the process listening on the configured server port, or
    None when the port is free or the process cannot be identified. Used to warn — and
    offer to close — when the graph's live-server port is already taken."""
    host, port = _detail._server_host_port(host, port)
    pid = _listening_pid(port)
    # A port held by *this* process (our own in-process server thread) is not something to
    # reclaim — returning it would make the caller SIGTERM our own PID, killing the TUI
    # (the terminal is left in mouse-tracking mode → escape codes garble the screen).
    if pid is None or pid == os.getpid():
        return None
    return (pid, _process_name(pid))


def _port_is_free(host: str, port: int) -> bool:
    """True when *host*:*port* can be bound (nothing is holding it)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def free_port(
    pid: int,
    host: str | None = None,
    port: int | None = None,
    *,
    timeout: float = 5.0,
    poll: float = 0.1,
) -> bool:
    """Gracefully terminate *pid* (``SIGTERM``) and wait until the server port is free.
    Returns True once the port can be bound, False on timeout (or if it never frees)."""
    host, port = _detail._server_host_port(host, port)
    if pid == os.getpid():
        # Never signal ourselves — SIGTERM to our own PID would kill the running TUI.
        return _port_is_free(host, port)
    try:
        # Safe to signal: *pid* is only ever whatever `lsof` reports as currently
        # listening on our own local preview port (127.0.0.1), never an
        # externally-supplied value, and the self-PID check above already
        # refuses to signal this process itself.
        os.kill(pid, signal.SIGTERM)  # NOSONAR - PID from lsof on our own port, not untrusted
    except OSError:
        return _port_is_free(host, port)  # already gone / not ours → report the port state
    deadline = time.monotonic() + timeout
    while True:
        if _port_is_free(host, port):
            return True
        if time.monotonic() >= deadline:
            return _port_is_free(host, port)
        time.sleep(poll)


API_PORT: int = 8765

_out_path: Path | None = None

_file_path: Path | None = None

# One-per-process HTTP server that serves the ster cache directory.
_http_server: http.server.HTTPServer | None = None

_http_port: int | None = None


def _vowl_html(taxonomy: Taxonomy, root_uri: str | None, token: str) -> str:
    """Render the VOWL landing page for the background server."""
    return _render.render_vowl_html(taxonomy, _api_file_path, api_token=token, root_uri=root_uri)


_api_file_path: Path | None = None


def _start_api_server(
    taxonomy: Taxonomy,
    file_path: Path | None,
    on_change_fn: Any = None,
) -> bool:
    """Start the shared API server with the VOWL graph as its landing page.

    Server lifecycle itself lives in :mod:`ster.api_server` — this only supplies
    the graph-viewer HTML, so other features (the MCP context server) can start
    the same server without pulling in the visualisation stack.
    """
    global _api_file_path
    from ..api_server import start_background  # noqa: PLC0415

    _api_file_path = file_path
    return start_background(taxonomy, file_path, html_renderer=_vowl_html, on_change=on_change_fn)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler that suppresses access-log noise.

    It also refuses directory listings: the server backs specific ``*_vowl.html``
    files, so a request for a folder (most visibly ``/``) must 404 rather than
    expose an index of the whole ``~/.cache/ster`` directory.
    """

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def list_directory(self, path: str) -> None:  # type: ignore[override]
        self.send_error(404, "Not found")
        return None

    def end_headers(self) -> None:
        # The graph page inlines its JS, so a browser-cached page kept serving an
        # old build until a manual hard-reload. Forbid caching so a plain reload
        # (or reopening from ster) always gets the current page.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


def _ensure_server(directory: Path) -> int:
    """Start the local HTTP server on first call; return its port on all calls.

    Uses the port from the ster server config so the browser origin is stable
    across restarts and localStorage graph state is preserved.
    """
    global _http_server, _http_port
    if _http_server is not None:
        return _http_port  # type: ignore[return-value]
    from ..api_server import load_server_config  # noqa: PLC0415

    _cfg_url, preferred = load_server_config()
    handler = functools.partial(_QuietHandler, directory=str(directory))
    for port in [preferred + i for i in range(20)]:
        try:
            server = http.server.HTTPServer((_LIT_N_127_0_1, port), handler)
            break
        except OSError:
            continue
    else:
        with socket.socket() as s:
            s.bind((_LIT_N_127_0_1, 0))
            port = s.getsockname()[1]
        server = http.server.HTTPServer((_LIT_N_127_0_1, port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _http_server = server
    _http_port = port
    return port
