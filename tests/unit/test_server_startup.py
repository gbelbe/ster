"""Unit + integration tests: server actually starts on the configured address/port."""

from __future__ import annotations

import threading
import urllib.request
from unittest.mock import patch

import pytest

from ster.model import RDFClass, Taxonomy

NS = "https://example.org/onto#"

_MINIMAL_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/test> a owl:Ontology .
<https://example.org/onto#Animal> a owl:Class ; rdfs:label "Animal"@en .
"""


def _make_taxonomy() -> Taxonomy:
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    return tax


def _free_port() -> int:
    """Return an OS-assigned free TCP port.

    Real-server tests must not hard-code a port: each leaks a daemon uvicorn for
    the rest of the session, so a fixed port collides with a leftover server (or
    a TIME_WAIT socket) across the 3 sequential Python-version CI runs.
    """
    import socket as _socket

    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── shared mock helpers ────────────────────────────────────────────────────────


def _setup_globals(monkeypatch, tmp_path, url: str, port: int):
    """Reset the background-server state and wire config/token to tmp files."""
    import ster.api_server as srv

    # Server lifecycle lives in api_server; viz_vowl only injects the HTML renderer.
    monkeypatch.setattr(srv, "_bg", srv._Background())

    cfg_file = tmp_path / "server_config.json"
    monkeypatch.setattr(srv, "_SERVER_CONFIG_FILE", cfg_file)
    srv.save_server_config(url, port)

    token_file = tmp_path / "api_token"
    token_file.write_text("test-token")
    monkeypatch.setattr(srv, "_TOKEN_FILE", token_file)


def _mock_uvicorn_start(monkeypatch, tmp_path, url: str, port: int) -> dict:
    """Call _start_api_server with uvicorn fully mocked; return captured Config kwargs."""
    import ster.viz_vowl as vv

    _setup_globals(monkeypatch, tmp_path, url, port)

    captured: dict = {}
    config_ready = threading.Event()

    class FakeConfig:
        def __init__(self, app, host, port, log_level="info"):  # noqa: A002
            captured["host"] = host
            captured["port"] = port
            config_ready.set()

    class FakeServer:
        def __init__(self, config):
            self.started = False

        async def serve(self) -> None:
            # Mimic uvicorn flagging itself as serving once the socket is bound;
            # _start_api_server keys success off this, not a bare port probe.
            self.started = True

    with (
        patch("uvicorn.Config", FakeConfig),
        patch("uvicorn.Server", FakeServer),
    ):
        result = vv._start_api_server(_make_taxonomy(), None)

    config_ready.wait(timeout=5)
    assert result is True, "_start_api_server must return True"
    return captured


# ── _start_api_server unit tests ──────────────────────────────────────────────


def test_start_api_server_uses_configured_port(monkeypatch, tmp_path):
    captured = _mock_uvicorn_start(monkeypatch, tmp_path, "http://127.0.0.1", 9111)
    assert captured["port"] == 9111


def test_start_api_server_uses_configured_host(monkeypatch, tmp_path):
    captured = _mock_uvicorn_start(monkeypatch, tmp_path, "http://127.0.0.1", 9222)
    assert captured["host"] == "127.0.0.1"


# ── serve() unit tests ────────────────────────────────────────────────────────


def _mock_serve(monkeypatch, tmp_path, cfg_port: int, explicit_port: int | None = None):
    """Call serve() with uvicorn.run mocked; return captured run kwargs."""
    import ster.api_server as srv

    cfg_file = tmp_path / "server_config.json"
    monkeypatch.setattr(srv, "_SERVER_CONFIG_FILE", cfg_file)
    srv.save_server_config("http://127.0.0.1", cfg_port)

    token_file = tmp_path / "api_token"
    token_file.write_text("test-token")
    monkeypatch.setattr(srv, "_TOKEN_FILE", token_file)

    ttl_file = tmp_path / "test.ttl"
    ttl_file.write_text(_MINIMAL_TTL)

    captured: dict = {}

    def fake_run(app, host, port, log_level="info"):  # noqa: A002
        captured["host"] = host
        captured["port"] = port

    kwargs: dict = {}
    if explicit_port is not None:
        kwargs["port"] = explicit_port

    with (
        patch("uvicorn.run", fake_run),
        patch("ster.api_server._start_file_watcher"),
    ):
        srv.serve(ttl_file, **kwargs)

    return captured


def test_serve_uses_configured_port(monkeypatch, tmp_path):
    captured = _mock_serve(monkeypatch, tmp_path, cfg_port=9333)
    assert captured["port"] == 9333


def test_serve_uses_configured_host(monkeypatch, tmp_path):
    captured = _mock_serve(monkeypatch, tmp_path, cfg_port=9333)
    assert captured["host"] == "127.0.0.1"


def test_serve_explicit_port_overrides_config(monkeypatch, tmp_path):
    captured = _mock_serve(monkeypatch, tmp_path, cfg_port=9333, explicit_port=9444)
    assert captured["port"] == 9444


# ── real server integration test ──────────────────────────────────────────────


@pytest.mark.integration
def test_real_server_responds_on_configured_port(monkeypatch, tmp_path):
    """_start_api_server starts a real uvicorn instance; GET /api/graph returns 200."""
    import ster.viz_vowl as vv

    port = _free_port()
    _setup_globals(monkeypatch, tmp_path, "http://127.0.0.1", port)

    result = vv._start_api_server(_make_taxonomy(), None)
    assert result is True, "Server failed to start"

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/graph",
        headers={"Authorization": "Bearer test-token"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200


def test_start_api_server_reports_failure_when_uvicorn_cannot_bind(monkeypatch, tmp_path):
    """A stale server squatting the configured port must NOT count as ours.

    Regression for the "main menu shows a directory listing" symptom: the old
    readiness probe only checked whether the port was open, so any foreign
    listener (e.g. the static cache server) made _start_api_server return True.
    Callers then opened ``/`` against that foreign server. With the fix, when our
    uvicorn cannot bind the socket (``serve()`` raises), _start_api_server reports
    failure and resets the globals, so callers fall back to a real static graph
    file instead.
    """
    import ster.api_server as srv
    import ster.viz_vowl as vv

    _setup_globals(monkeypatch, tmp_path, "http://127.0.0.1", 9555)

    class FailingConfig:
        def __init__(self, app, host, port, log_level="info"):  # noqa: A002
            pass

    class FailingServer:
        def __init__(self, config):
            self.started = False  # never flips: binding failed

        async def serve(self) -> None:
            raise OSError("address already in use")

    with (
        patch("uvicorn.Config", FailingConfig),
        patch("uvicorn.Server", FailingServer),
    ):
        result = vv._start_api_server(_make_taxonomy(), None)

    assert result is False, "must not claim success when uvicorn fails to bind"
    assert srv.current_app() is None


def test_serve_binds_a_landing_page_that_matches_how_it_is_called() -> None:
    """`ster serve` answered 500 on every graph page: its own hand-written
    html_fn took (root_uri, full) while _graph_html_response always passes
    three — GET / and GET /viz both route through it, and /viz carries the
    query. The existing tests could not catch it, because they pass a mock as
    html_fn and a mock accepts any signature.

    So this pins the real binding: whatever `serve` attaches must accept the
    call the route actually makes.
    """
    import inspect

    from ster import api_server

    source = inspect.getsource(api_server.serve)
    # serve must not hand-roll a second landing-page callable; it shares the
    # one seam the background server already uses, so the two cannot drift.
    assert "_make_html_fn(app, _renderer, token)" in source
    assert "def html_fn(" not in source


def test_the_shared_landing_page_binding_takes_root_full_and_query() -> None:
    """The three arguments _graph_html_response passes, positionally."""
    import inspect

    from ster.api_server import _make_html_fn

    class _App:
        class state:  # noqa: N801
            _ster = {"taxonomy": object()}

    seen: list[tuple] = []

    def renderer(tax, root_uri, token, full, sparql):  # noqa: ANN001, ANN202
        seen.append((root_uri, token, full, sparql))
        return "<html/>"

    html_fn = _make_html_fn(_App, renderer, "tok")
    assert html_fn("some:uri", True, "SELECT *") == "<html/>"
    assert seen == [("some:uri", "tok", True, "SELECT *")]
    # and the defaults the route relies on
    params = inspect.signature(html_fn).parameters
    assert list(params) == ["root_uri", "full", "sparql"]
