"""A second ster takes the next free port instead of going without a server, and everything it opens follows it."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import ster.api_server as srv
from ster.model import RDFClass, Taxonomy
from ster.tui.app import _helpers

ONTOLOGY = "https://example.org/onto#"
BASE = 9611
LOCAL = "http://127.0.0.1"
START = "start_background"
HELD = "address already in use"


def _taxonomy() -> Taxonomy:
    tax = Taxonomy()
    tax.owl_classes[ONTOLOGY + "Animal"] = RDFClass(uri=ONTOLOGY + "Animal")
    return tax


@pytest.fixture(autouse=True)  # noqa: V103  # pytest runs autouse fixtures by itself
def _fresh_state(monkeypatch, tmp_path):
    monkeypatch.setattr(srv, "_bg", srv._Background())
    monkeypatch.setattr(srv, "_SERVER_CONFIG_FILE", tmp_path / "server_config.json")
    srv.save_server_config(LOCAL, BASE)
    token = tmp_path / "api_token"
    token.write_text("test-token")
    monkeypatch.setattr(srv, "_TOKEN_FILE", token)


def _uvicorn(held: set[int], tried: list[int]):
    """A uvicorn whose servers cannot bind the ports in *held*; the ports it was asked for go into *tried*."""

    class Config:
        def __init__(self, app, host, port, log_level="info"):  # noqa: A002, V107  # the fake takes what uvicorn.Config takes
            self.port = port  # noqa: V101  # read by the fake Server below

    class Server:
        def __init__(self, config):
            self.started = False
            self.port = config.port

        async def serve(self) -> None:
            tried.append(self.port)
            if self.port in held:
                raise OSError(HELD)
            self.started = True

    return Config, Server


def _start(held: set[int], **kwargs) -> tuple[bool, list[int]]:
    tried: list[int] = []
    config, server = _uvicorn(held, tried)
    with patch("uvicorn.Config", config), patch("uvicorn.Server", server):
        return srv.start_background(_taxonomy(), None, **kwargs), tried


def test_the_configured_port_is_used_when_it_is_free():
    ok, tried = _start(set(), fallback_ports=3)
    assert ok is True
    assert tried == [BASE]
    assert srv.bound_port() == BASE


def test_a_held_port_means_no_server_unless_fallback_is_allowed():
    ok, tried = _start({BASE})
    assert ok is False
    assert tried == [BASE]
    assert srv.bound_port() is None


def test_a_held_port_makes_the_next_free_one_the_servers():
    ok, tried = _start({BASE, BASE + 1}, fallback_ports=3)
    assert ok is True
    assert tried == [BASE, BASE + 1, BASE + 2]
    assert srv.bound_port() == BASE + 2


def test_every_link_and_page_follows_the_port_actually_bound():
    _start({BASE}, fallback_ports=2)
    assert srv.load_server_config() == (LOCAL, BASE + 1)
    assert srv.configured_server() == (LOCAL, BASE)


def test_before_any_server_the_configured_port_is_what_is_asked_for():
    assert srv.load_server_config() == (LOCAL, BASE)


def test_when_every_port_in_range_is_held_there_is_no_server_and_no_half_state():
    ok, tried = _start({BASE, BASE + 1, BASE + 2}, fallback_ports=2)
    assert ok is False
    assert tried == [BASE, BASE + 1, BASE + 2]
    assert (srv.bound_port(), srv.current_app()) == (None, None)
    assert srv.load_server_config()[1] == BASE


def test_a_stopped_server_gives_the_configured_port_back():
    _start({BASE}, fallback_ports=2)
    srv._bg.reset()
    assert srv.load_server_config()[1] == BASE


# ── the TUI's starter ─────────────────────────────────────────────────────────


def test_the_tui_tries_the_configured_port_first_and_asks_nothing_else_when_it_works(monkeypatch):
    calls: list[set] = []
    monkeypatch.setattr(srv, START, lambda *a, **k: calls.append(set(k)) or True)
    assert _helpers._start_context_server("TAX", None) is True
    assert calls == [{"html_renderer"}]


def test_the_tui_takes_a_free_port_when_the_configured_one_is_held_by_another_ster(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(srv, START, lambda *a, **k: calls.append(k) or ("fallback_ports" in k))
    monkeypatch.setattr(_helpers, "_served_by_same_file", lambda _path: False)
    assert _helpers._start_context_server("TAX", None) is True
    assert [set(c) for c in calls] == [{"html_renderer"}, {"html_renderer", "fallback_ports"}]
    assert calls[1]["fallback_ports"] == _helpers.FALLBACK_PORTS


def test_the_tui_leaves_a_same_file_ster_serve_as_the_server(monkeypatch):
    calls: list[set] = []
    monkeypatch.setattr(srv, START, lambda *a, **k: calls.append(set(k)) or False)
    monkeypatch.setattr(_helpers, "_served_by_same_file", lambda _path: True)
    assert _helpers._start_context_server("TAX", None) is False
    assert calls == [{"html_renderer"}]


def test_the_probe_for_a_same_file_server_is_false_when_it_cannot_run(monkeypatch):
    def broken(*_a, **_k):
        raise OSError("no lsof")

    monkeypatch.setattr("ster.viz_vowl.claim_port", broken)
    assert _helpers._served_by_same_file(None) is False


def test_the_probe_is_true_only_for_a_reusable_server(monkeypatch):
    from ster.viz_vowl._claim import BLOCKED, FREE, REUSE, Claim

    for outcome, expected in ((REUSE, True), (BLOCKED, False), (FREE, False)):
        monkeypatch.setattr("ster.viz_vowl.claim_port", lambda *_a, _o=outcome, **_k: Claim(_o))
        assert _helpers._served_by_same_file(None) is expected


# ── the toast ─────────────────────────────────────────────────────────────────


def test_a_server_on_another_port_says_so():
    _start({BASE}, fallback_ports=2)
    message, severity = _helpers._context_server_notice(True, None)  # type: ignore[misc]
    assert str(BASE + 1) in message
    assert f"{BASE} is held by another ster" in message
    assert severity == "information"


def test_a_server_on_the_configured_port_has_nothing_to_say():
    _start(set())
    assert _helpers._context_server_notice(True, None) is None


# ── only a bound server counts for the agent key ──────────────────────────────


def test_a_server_that_is_still_binding_is_running_but_not_yet_serving(monkeypatch):
    monkeypatch.setattr(srv, "_bg", srv._Background(app=object()))
    assert srv.is_running() is True
    assert srv.is_serving() is False


def test_a_server_that_is_bound_is_serving():
    _start(set())
    assert srv.is_serving() is True


def test_a_server_that_could_not_bind_is_neither():
    _start({BASE})
    assert (srv.is_running(), srv.is_serving()) == (False, False)


def test_the_tui_waits_for_a_bound_server_not_one_that_is_only_starting(monkeypatch):
    from ster.tui import query

    monkeypatch.setattr(srv, "_bg", srv._Background(app=object()))
    assert query.server_is_serving() is False
    assert query.wait_for_server(0.02, every=0.005) is False
