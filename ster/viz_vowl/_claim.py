"""Claiming ster's live-server port before a view (graph, map, timeline) opens.

One decision, shared by the TUI, the CLI and ``ster serve``, so they cannot
disagree about what to do with a process already on the port:

* nothing there → go ahead;
* a ster server of the **same build** already showing this file → reuse it;
* any other ``ster serve`` → a view, replaceable (after *confirm*, if given);
* an interactive ster session or a non-ster process → never touched; say so.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from . import _detail, _server

FREE: Final = "free"  # the port is usable (it was free, or the old server was closed)
REUSE: Final = "reuse"  # a suitable server is already up at ``Claim.url``
BLOCKED: Final = "blocked"  # not ours to free, or declined; ``Claim.message`` says why

_LIT_API: Final = "/api/"


@dataclass(frozen=True)
class Claim:
    """The result of :func:`claim_port`. *message* is a clause, like
    :func:`ster.viz_vowl._server.unavailable_reason` — callers add the framing."""

    outcome: str
    message: str = ""
    url: str = ""


def _get_json(base_url: str, endpoint: str, token: str, timeout: float = 3.0) -> Any:
    """The decoded JSON body of ``GET base_url/endpoint``, or None on any failure.

    Best-effort and silent: only used to tell a live ster server from anything
    else on the port, never to decide whether touching it is safe.
    """
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read())
    except (ValueError, OSError):  # URLError is an OSError
        return None


def server_overview(base_url: str, token: str, timeout: float = 3.0) -> dict[str, Any] | None:
    """``GET /api/overview`` on a (possibly foreign) ster server: which file it serves."""
    data = _get_json(base_url, f"{_LIT_API}overview", token, timeout)
    return data if isinstance(data, dict) else None


def server_build(base_url: str, token: str, timeout: float = 3.0) -> str | None:
    """The ster version a server reports on ``GET /api/version``, or None."""
    data = _get_json(base_url, f"{_LIT_API}version", token, timeout)
    build = data.get("ster") if isinstance(data, dict) else None
    return build if isinstance(build, str) else None


def _why_replace(served: str | None, taxonomy_file: Path | None, build: str | None) -> str:
    """Why a healthy ster server on the port is not the one this view needs."""
    from .._version import __version__  # noqa: PLC0415

    if served is not None and (taxonomy_file is None or Path(served) != taxonomy_file.resolve()):
        return f"is serving {Path(served).name}"
    return f"is ster {build or 'of another build'}, not {__version__}"


def _is_current(served: str | None, taxonomy_file: Path | None, build: str | None) -> bool:
    """True when the server shows *taxonomy_file* and is the same ster build as us."""
    from .._version import __version__  # noqa: PLC0415

    if served is None or taxonomy_file is None:
        return False
    return Path(served) == taxonomy_file.resolve() and build == __version__


def _replace_server(
    pid: int,
    command: str,
    reason: str,
    confirm: Callable[[str], bool] | None,
    host: str,
    port: int,
) -> Claim:
    """Close a ster server that is a view, once *confirm* (when given) agrees."""
    if confirm is not None and not confirm(
        f"ster (pid {pid}) {reason}. Close it and start a fresh server?"
    ):
        return Claim(BLOCKED, f"the ster server on port {port} {reason} and was left running.")
    if _server.free_port(pid, host, port):
        return Claim(FREE)
    return Claim(BLOCKED, f"couldn't stop {command} (pid {pid}) to free port {port}.")


def _settle_server(
    taxonomy_file: Path | None,
    holder: tuple[int, str],
    confirm: Callable[[str], bool] | None,
    host: str,
    port: int,
) -> Claim:
    """A ``ster serve`` holds the port: reuse it, replace it, or leave it."""
    from ..api_server import load_server_config, load_token  # noqa: PLC0415

    pid, command = holder
    base_url = f"{load_server_config()[0]}:{port}"  # scheme from config, never a literal
    token = load_token()
    served = (server_overview(base_url, token) or {}).get("file")
    if served is None:
        return Claim(BLOCKED, _server.holder_message(pid, command, port))
    build = server_build(base_url, token)
    if _is_current(served, taxonomy_file, build):
        return Claim(REUSE, url=base_url)
    reason = _why_replace(served, taxonomy_file, build)
    return _replace_server(pid, command, reason, confirm, host, port)


def claim_port(
    taxonomy_file: Path | None,
    confirm: Callable[[str], bool] | None = None,
    host: str | None = None,
    port: int | None = None,
) -> Claim:
    """Make the live-server port usable for a view of *taxonomy_file*, if it is ours to.

    *confirm* is asked before an existing ``ster serve`` is closed; None means
    close it without asking (the TUI, where a blocking prompt froze the UI).
    An interactive session or a foreign process is never closed either way.
    """
    host, port = _detail._server_host_port(host, port)
    holder = _server.port_holder(host, port)
    if holder is None:
        return Claim(FREE)
    if _server.holder_kind(holder[1]) != _server.SERVER:
        return Claim(BLOCKED, _server.holder_message(holder[0], holder[1], port))
    return _settle_server(taxonomy_file, holder, confirm, host, port)
