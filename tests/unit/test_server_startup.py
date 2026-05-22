"""Unit + integration tests: server actually starts on the configured address/port."""

from __future__ import annotations

import threading
import types
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


# ── shared mock helpers ────────────────────────────────────────────────────────


def _setup_globals(monkeypatch, tmp_path, url: str, port: int):
    """Reset viz_vowl globals and wire config/token to tmp files."""
    import ster.api_server as srv
    import ster.viz_vowl as vv

    monkeypatch.setattr(vv, "_api_app", None)
    monkeypatch.setattr(vv, "_api_broadcaster", None)
    monkeypatch.setattr(vv, "_api_loop", None)
    monkeypatch.setattr(vv, "_api_running", False)

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
            pass

        async def serve(self) -> None:
            pass

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def connect_ex(self, addr):
            return 0  # pretend port is immediately open

    fake_socket_mod = types.SimpleNamespace(socket=lambda *a, **kw: FakeSocket())

    with (
        patch("uvicorn.Config", FakeConfig),
        patch("uvicorn.Server", FakeServer),
        patch("ster.viz_vowl.socket", fake_socket_mod),
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

    _setup_globals(monkeypatch, tmp_path, "http://127.0.0.1", 19765)

    result = vv._start_api_server(_make_taxonomy(), None)
    assert result is True, "Server failed to start"

    req = urllib.request.Request(
        "http://127.0.0.1:19765/api/graph",
        headers={"Authorization": "Bearer test-token"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
