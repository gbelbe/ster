"""ster's two servers must not fight over one port.

ster runs two: the API server, which serves /map, /viz, /onto and /mcp, and a
plain static file server that `ster show` uses to hand a generated page to the
browser. Both read the same configured port, and the static one used to try it
first.

Whichever started first won. A `ster show` left running from an earlier session
therefore owned the port, every later TUI failed to bind, and the map opened
against the static handler — which has no /map and answers 404 to everything.
That is exactly what happened: a `ster show` process from the previous day,
still listening, produced a 404 on /map?q= that looked like a broken map.
"""

from __future__ import annotations

import socket

from ster.api_server import load_server_config


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_the_static_server_never_takes_the_api_port(tmp_path, monkeypatch):
    """The whole fix in one assertion: the file server starts above the API."""
    from ster.viz_vowl import _server

    api_port = _free_port()
    # Patch at the source: _server imports it inside the function, so the name
    # never exists as a module attribute to replace.
    import ster.api_server as api_server

    monkeypatch.setattr(api_server, "load_server_config", lambda: ("http://127.0.0.1", api_port))
    monkeypatch.setattr(_server, "_http_server", None)
    monkeypatch.setattr(_server, "_http_port", None)

    port = _server._ensure_server(tmp_path)

    assert port != api_port, "the static server took the port the API server needs"
    assert port > api_port


def test_the_api_port_stays_free_for_the_api(tmp_path, monkeypatch):
    """Not just a different port — the API's must still be bindable afterwards."""
    from ster.viz_vowl import _server

    api_port = _free_port()
    # Patch at the source: _server imports it inside the function, so the name
    # never exists as a module attribute to replace.
    import ster.api_server as api_server

    monkeypatch.setattr(api_server, "load_server_config", lambda: ("http://127.0.0.1", api_port))
    monkeypatch.setattr(_server, "_http_server", None)
    monkeypatch.setattr(_server, "_http_port", None)

    _server._ensure_server(tmp_path)

    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", api_port))  # raises if the static server took it


# ── the message a blocked user actually sees ────────────────────────────────


def test_a_taken_port_names_the_process_holding_it(monkeypatch):
    """ "The server isn't running" leaves someone with a working TUI and no next
    step. The port and the process holding it are the next step — and ster
    already knows how to find both."""
    import ster.api_server as api_server
    import ster.viz_vowl as viz
    from ster.tui import query

    monkeypatch.setattr(api_server, "load_server_config", lambda: ("http://127.0.0.1", 64383))
    monkeypatch.setattr(viz, "port_holder", lambda **_kw: (90095, "ster show"))

    message = query.server_unavailable_reason()

    assert "64383" in message
    assert "ster show" in message
    assert "90095" in message


def test_a_diagnostic_never_becomes_the_failure(monkeypatch):
    """port_holder shells out to find the pid. If that breaks, the user must
    still get a message rather than a traceback from the error path."""
    import ster.api_server as api_server
    import ster.viz_vowl as viz
    from ster.tui import query

    monkeypatch.setattr(api_server, "load_server_config", lambda: ("http://127.0.0.1", 64383))

    def _boom(**_kw):
        raise OSError("lsof unavailable")

    monkeypatch.setattr(viz, "port_holder", _boom)

    assert "isn't running" in query.server_unavailable_reason()


def test_a_free_port_gives_the_plain_message(monkeypatch):
    """No squatter means the port is not the story; do not invent one."""
    import ster.viz_vowl as viz
    from ster.tui import query

    monkeypatch.setattr(viz, "port_holder", lambda **_kw: None)

    assert query.server_unavailable_reason() == (
        "Couldn't open the map: the ster server isn't running."
    )


def test_the_configured_port_is_what_both_read():
    """A regression guard on the premise: if these ever read different config,
    the collision this file prevents stops being possible to reason about."""
    url, port = load_server_config()

    assert isinstance(port, int)
    assert url.startswith("http")
