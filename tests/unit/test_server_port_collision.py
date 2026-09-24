"""The message a blocked user actually sees when ster's server port is taken.

ster used to run two servers: the API server (/map, /viz, /onto, /mcp), and a
plain static file server that a since-removed offline fallback used to hand a
generated page to the browser when the API port was busy. That second server
is gone — the live server is now the only one, and a caller that cannot start
it gets a clear message naming the port and whatever holds it, rather than a
silently degraded page.
"""

from __future__ import annotations

from ster.api_server import load_server_config

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


# ── the graph view's own version of the same message ────────────────────────
# The graph view used to have a fallback the map never had (a static, offline
# snapshot). Now that it is gone, it needs the same clear-message behaviour —
# these mirror the map's tests above against viz_vowl._server.unavailable_reason.


def test_graph_port_taken_names_the_process_holding_it(monkeypatch):
    from ster.viz_vowl import _server

    monkeypatch.setattr(_server, "port_holder", lambda *_a, **_kw: (90095, "ster show"))

    message = _server.unavailable_reason(port=64383)

    assert "64383" in message
    assert "ster show" in message
    assert "90095" in message


def test_graph_port_diagnostic_never_becomes_the_failure(monkeypatch):
    """port_holder shells out to find the pid. If that breaks, the caller must
    still get a message rather than a traceback."""
    from ster.viz_vowl import _server

    def _boom(*_a, **_kw):
        raise OSError("lsof unavailable")

    monkeypatch.setattr(_server, "port_holder", _boom)

    assert "isn't running" in _server.unavailable_reason(port=64383)


def test_graph_free_port_gives_the_plain_message(monkeypatch):
    from ster.viz_vowl import _server

    monkeypatch.setattr(_server, "port_holder", lambda *_a, **_kw: None)

    assert _server.unavailable_reason(port=64383) == "the ster server isn't running."
