"""Port management and the API server bootstrap for the VOWL graph viewer.

Note: _listening_pid / _process_name / _port_is_free / port_holder / free_port stay
together in this module because tests monkeypatch them via module-attribute
lookup (see tests/unit/test_viz_vowl_port.py) — splitting them apart would
silently break those patches.

The graph view requires this live server: it used to fall back to a static,
read-only HTML snapshot (served by a second, plain http.server) whenever the
port could not be bound. That fallback is gone — a caller that cannot start
the server gets ``unavailable_reason()``'s message instead, so the person
sees an actionable error rather than a silently degraded page."""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Final

from ..model import Taxonomy
from ..viz import (
    _label_for,  # noqa: F401  (re-exported for potential callers)
)
from . import _detail, _render


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


# The invocation this looks for, named once: it is matched, filtered on, and
# split at, and three spellings of one string is three chances to drift.
_SERVE_CMD = "ster serve"


def other_ster_servers() -> list[tuple[int, str]]:
    """Every *other* running ``ster serve`` on this machine, as ``(pid, command)``.

    Not for killing anything. Two ster installs commonly coexist — a ``uv tool``
    copy and a project venv, the latter often editable and tracking whichever
    branch is checked out — and a server started from one keeps serving its own
    build until it is stopped. Updating the other install then looks like it did
    nothing, which is confusing precisely because the version string *did*
    change.

    Best-effort and silent on failure: this exists to explain a surprise, never
    to block a launch.
    """
    # pgrep -a is Linux-only; on macOS it yields an empty command, so the PIDs
    # come from pgrep and the command line from ps via _process_name.
    try:
        result = subprocess.run(
            ["pgrep", "-f", _SERVE_CMD], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return []
    mine = {os.getpid(), os.getppid()}
    found: list[tuple[int, str]] = []
    seen_args: set[str] = set()
    for line in result.stdout.split():
        try:
            pid = int(line)
        except ValueError:
            continue
        # Skip ourselves and our own parent — a TUI that started its own server
        # is not a stale one, and reporting it would cry wolf on every launch.
        if pid in mine:
            continue
        command = _process_name(pid)
        # pgrep -f matches anything whose command line merely *mentions* the
        # phrase — a shell running a script that greps for it, for instance —
        # so require a real invocation.
        if _SERVE_CMD not in command or " -c " in command:
            continue
        # `uv run ... ster serve X` and the python it execs are one server, not
        # two. They share everything after the subcommand, so that is the key.
        tail = command.split(_SERVE_CMD, 1)[1].strip()
        if tail in seen_args:
            continue
        seen_args.add(tail)
        found.append((pid, command))
    return found


# What is sitting on the live-server port. The distinction matters because the
# caller SIGTERMs what it reclaims, and "a process holding port 8765" is not the
# same thing as "a stale graph window".
SERVER: Final = "server"  # a `ster serve` — a view, safe to replace
EDITOR: Final = "editor"  # an interactive ster session — someone is working in it
FOREIGN: Final = "foreign"  # not ster at all — never ours to kill

# \b keeps this off "raster", "semanticdiff-ster" and the like: the preceding
# character must be a path separator, whitespace, or the start of the line.
_STER_INVOCATION = re.compile(r"(?:^|[/\s])ster(?:\s|$)")


def holder_kind(command: str) -> str:
    """Classify the command line of whatever holds the port.

    A `ster serve` is a view of an ontology and replacing it costs nothing. An
    interactive session is someone's open editor — SIGTERM there kills the TUI
    mid-render and leaves the terminal in mouse-tracking mode, which is why the
    screen fills with escape codes. And a process that is not ster has no
    business being closed by ster at all.
    """
    if "ster serve" in command:
        return SERVER
    return EDITOR if _STER_INVOCATION.search(command) else FOREIGN


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


def holder_message(pid: int, command: str, port: int) -> str:
    """What to tell the reader about a process holding *port*, by who it is.

    A clause (no capital, no full stop framing of its own): it is read after a
    caller's own prefix such as "Couldn't open the graph: ". Each kind gets its
    own next step, because "close that process" is wrong advice for all but one
    of them — see :func:`holder_kind`.
    """
    kind = holder_kind(command)
    if kind == EDITOR:
        return (
            f"another ster session is open ({command}, pid {pid}) and holds port {port}. "
            "Please close it first to release the port, then try again."
        )
    if kind == SERVER:
        return (
            f"port {port} is held by {command} (pid {pid}), so ster's server "
            "could not start. Close that process and reopen the file."
        )
    return (
        f"port {port} is held by {command} (pid {pid}), which is not ster, so it "
        "was left alone. Free that port, then try again."
    )


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


def unavailable_reason(host: str | None = None, port: int | None = None) -> str:
    """Why the graph's live server could not start, in terms the reader can act on.

    Names the port and the process holding it when known — "the server isn't
    running" alone leaves the reader with no next step. A reason clause, not a
    full sentence: unlike :func:`ster.tui.query.server_unavailable_reason`
    (shown to the reader as-is), this one only ever reaches a reader inside a
    caught ``RuntimeError``'s message, so it carries no "Couldn't open..."
    prefix of its own — each caller supplies the framing that fits it
    (``"Couldn't open the graph: "`` in the TUI, ``"Graph error: "`` in the
    CLI), and composing it twice would read as a doubled sentence.
    """
    if port is None:
        from ..api_server import load_server_config  # noqa: PLC0415

        _cfg_url, port = load_server_config()
    try:
        holder = port_holder(host, port)
    except Exception:  # noqa: BLE001 — a diagnostic must never be the thing that fails
        holder = None
    if holder is not None:
        return holder_message(holder[0], holder[1], port)
    return "the ster server isn't running."


def _vowl_html(
    taxonomy: Taxonomy,
    root_uri: str | None,
    token: str,
    full: bool = False,
    sparql: str = "",
) -> str:
    """Render the VOWL landing page for the background server."""
    return _render.render_vowl_html(
        taxonomy, _api_file_path, api_token=token, root_uri=root_uri, full=full, sparql=sparql
    )


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
