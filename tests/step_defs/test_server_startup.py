"""BDD step definitions for server startup scenarios."""

from __future__ import annotations

import threading
import types
import urllib.request
from unittest.mock import patch

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/api/server_startup.feature")

NS = "https://example.org/onto#"
_MINIMAL_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<https://example.org/test> a owl:Ontology .
<https://example.org/onto#Animal> a owl:Class .
"""


def _make_taxonomy():
    from ster.model import RDFClass, Taxonomy

    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    return tax


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    return {"tmp_path": tmp_path, "monkeypatch": monkeypatch}


# ── Given ─────────────────────────────────────────────────────────────────────


@given('server config is set to URL "http://127.0.0.1" and port 9111')
def given_config_9111(ctx):
    _write_config(ctx, "http://127.0.0.1", 9111)


@given('server config is set to URL "http://127.0.0.1" and port 9222')
def given_config_9222(ctx):
    _write_config(ctx, "http://127.0.0.1", 9222)


@given('server config is set to URL "http://127.0.0.1" and port 9333')
def given_config_9333(ctx):
    _write_config(ctx, "http://127.0.0.1", 9333)


@given('server config is set to URL "http://127.0.0.1" and port 19766')
def given_config_19766(ctx):
    _write_config(ctx, "http://127.0.0.1", 19766)


def _write_config(ctx, url: str, port: int) -> None:
    import ster.api_server as srv
    import ster.viz_vowl as vv

    mp = ctx["monkeypatch"]
    tmp = ctx["tmp_path"]

    mp.setattr(vv, "_api_app", None)
    mp.setattr(vv, "_api_broadcaster", None)
    mp.setattr(vv, "_api_loop", None)
    mp.setattr(vv, "_api_running", False)

    cfg_file = tmp / "server_config.json"
    mp.setattr(srv, "_SERVER_CONFIG_FILE", cfg_file)
    srv.save_server_config(url, port)

    token_file = tmp / "api_token"
    token_file.write_text("test-token")
    mp.setattr(srv, "_TOKEN_FILE", token_file)

    ctx["url"] = url
    ctx["port"] = port


# ── When ──────────────────────────────────────────────────────────────────────


@when("_start_api_server is invoked")
def when_start_api_server(ctx):
    import ster.viz_vowl as vv

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
            return 0

    fake_socket_mod = types.SimpleNamespace(socket=lambda *a, **kw: FakeSocket())

    with (
        patch("uvicorn.Config", FakeConfig),
        patch("uvicorn.Server", FakeServer),
        patch("ster.viz_vowl.socket", fake_socket_mod),
    ):
        vv._start_api_server(_make_taxonomy(), None)

    config_ready.wait(timeout=5)
    ctx["uvicorn_cfg"] = captured


@when("serve() is called without explicit host or port")
def when_serve_no_override(ctx):
    _run_serve(ctx, {})


@when("serve() is called with explicit port 9444")
def when_serve_explicit_port(ctx):
    _run_serve(ctx, {"port": 9444})


def _run_serve(ctx, overrides: dict) -> None:
    import ster.api_server as srv

    ttl_file = ctx["tmp_path"] / "test.ttl"
    ttl_file.write_text(_MINIMAL_TTL)

    captured: dict = {}

    def fake_run(app, host, port, log_level="info"):  # noqa: A002
        captured["host"] = host
        captured["port"] = port

    with (
        patch("uvicorn.run", fake_run),
        patch("ster.api_server._start_file_watcher"),
    ):
        srv.serve(ttl_file, **overrides)

    ctx["uvicorn_run"] = captured


@when("the server is started via _start_api_server")
def when_real_server_start(ctx):
    import ster.viz_vowl as vv

    result = vv._start_api_server(_make_taxonomy(), None)
    ctx["server_started"] = result


# ── Then ──────────────────────────────────────────────────────────────────────


@then("uvicorn.Config was called with port 9111")
def then_cfg_port_9111(ctx):
    assert ctx["uvicorn_cfg"]["port"] == 9111


@then('uvicorn.Config was called with host "127.0.0.1"')
def then_cfg_host(ctx):
    assert ctx["uvicorn_cfg"]["host"] == "127.0.0.1"


@then("uvicorn.run was called with port 9333")
def then_run_port_9333(ctx):
    assert ctx["uvicorn_run"]["port"] == 9333


@then('uvicorn.run was called with host "127.0.0.1"')
def then_run_host(ctx):
    assert ctx["uvicorn_run"]["host"] == "127.0.0.1"


@then("uvicorn.run was called with port 9444")
def then_run_port_9444(ctx):
    assert ctx["uvicorn_run"]["port"] == 9444


@then("GET /api/graph on port 19766 returns HTTP 200")
def then_real_server_200(ctx):
    assert ctx["server_started"] is True
    req = urllib.request.Request(
        "http://127.0.0.1:19766/api/graph",
        headers={"Authorization": "Bearer test-token"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
