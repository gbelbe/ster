"""Unit tests for the feature-agnostic background server in :mod:`ster.api_server`.

Server lifecycle used to live inside ``viz_vowl``, which tied "run a server" to
the graph-viewer feature. These cover the extracted units directly, so a second
consumer (the MCP context server) can rely on them without importing the
visualisation stack.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

import ster.api_server as srv
from ster.model import RDFClass, Taxonomy

NS = "https://example.org/onto#"


def _taxonomy() -> Taxonomy:
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    return tax


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch, tmp_path):
    """Every test starts with no server running and config/token in tmp files."""
    monkeypatch.setattr(srv, "_bg", srv._Background())
    cfg = tmp_path / "server_config.json"
    monkeypatch.setattr(srv, "_SERVER_CONFIG_FILE", cfg)
    srv.save_server_config("http://127.0.0.1", 9611)
    token_file = tmp_path / "api_token"
    token_file.write_text("test-token")
    monkeypatch.setattr(srv, "_TOKEN_FILE", token_file)


# ── is_running / current_app ──────────────────────────────────────────────────


def test_is_running_false_before_any_server_starts():
    assert srv.is_running() is False


def test_current_app_none_before_any_server_starts():
    assert srv.current_app() is None


def test_is_running_true_once_app_is_set(monkeypatch):
    monkeypatch.setattr(srv, "_bg", srv._Background(app=object()))
    assert srv.is_running() is True


# ── push_taxonomy ─────────────────────────────────────────────────────────────


def test_push_taxonomy_is_noop_when_no_server_running():
    srv.push_taxonomy(_taxonomy())  # must not raise


def test_notify_is_a_noop_on_a_closed_loop():
    """Regression: a stopped server leaves a closed loop cached in _bg.loop.

    ``call_soon_threadsafe`` on a closed loop raises
    ``RuntimeError: Event loop is closed``, which propagated up through
    viz_vowl.push_update into the TUI's save path. Surfaced as a Python 3.12-only
    CI failure — on 3.13 the fake loop in tests happened to close later.
    """
    import asyncio

    from ster.api import SSEBroadcaster

    loop = asyncio.new_event_loop()
    loop.close()

    SSEBroadcaster().notify(loop)  # must not raise


def test_push_taxonomy_survives_a_stopped_server(monkeypatch):
    """The whole path, not just the broadcaster: a save after the server died."""
    import asyncio

    from ster.api import SSEBroadcaster

    class _App:
        def __init__(self):
            self.state = type("S", (), {"_ster": {"taxonomy": None}})()

    loop = asyncio.new_event_loop()
    loop.close()
    app = _App()
    monkeypatch.setattr(
        srv, "_bg", srv._Background(app=app, broadcaster=SSEBroadcaster(), loop=loop)
    )

    tax = _taxonomy()
    srv.push_taxonomy(tax)  # must not raise

    assert app.state._ster["taxonomy"] is tax, "the taxonomy must still be published"


def test_push_taxonomy_updates_state_and_notifies(monkeypatch):
    class _App:
        def __init__(self):
            self.state = type("S", (), {"_ster": {"taxonomy": None}})()

    class _Broadcaster:
        def __init__(self):
            self.notified_with = "unset"

        def notify(self, loop=None):
            self.notified_with = loop

    app, bc, loop = _App(), _Broadcaster(), object()
    monkeypatch.setattr(srv, "_bg", srv._Background(app=app, broadcaster=bc, loop=loop))

    tax = _taxonomy()
    srv.push_taxonomy(tax)

    assert app.state._ster["taxonomy"] is tax
    assert bc.notified_with is loop


# ── _publish_dir_for ──────────────────────────────────────────────────────────


def test_publish_dir_for_none_file_returns_none():
    assert srv._publish_dir_for(None) is None


def test_publish_dir_for_creates_ontology_sibling(tmp_path):
    result = srv._publish_dir_for(tmp_path / "onto.ttl")
    assert result == tmp_path / "ontology"
    assert result.is_dir(), "the mount must exist before the first publish"


# ── _server_deps ──────────────────────────────────────────────────────────────


def test_server_deps_returns_triple_when_available():
    deps = srv._server_deps()
    assert deps is not None and len(deps) == 3


# ── start_background ──────────────────────────────────────────────────────────


def _fake_uvicorn(captured: dict, ready: threading.Event, *, bind_ok: bool = True):
    class FakeConfig:
        def __init__(self, app, host, port, log_level="info"):  # noqa: A002
            captured.update(host=host, port=port, app=app)
            ready.set()

    class FakeServer:
        def __init__(self, config):
            self.started = False

        async def serve(self) -> None:
            if not bind_ok:
                raise OSError("address already in use")
            self.started = True

    return FakeConfig, FakeServer


def _start(monkeypatch, **kwargs) -> tuple[bool, dict]:
    captured: dict = {}
    ready = threading.Event()
    cfg, server = _fake_uvicorn(captured, ready, bind_ok=kwargs.pop("bind_ok", True))
    with patch("uvicorn.Config", cfg), patch("uvicorn.Server", server):
        result = srv.start_background(_taxonomy(), None, **kwargs)
    ready.wait(timeout=5)
    return result, captured


def test_start_background_binds_configured_host_and_port(monkeypatch):
    ok, captured = _start(monkeypatch)
    assert ok is True
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9611


def test_start_background_reports_failure_when_bind_fails(monkeypatch):
    ok, _ = _start(monkeypatch, bind_ok=False)
    assert ok is False
    assert srv.current_app() is None, "failed startup must leave no half-set state"


def test_start_background_works_without_an_html_renderer(monkeypatch):
    """The MCP server needs a server but no landing page — html_renderer is optional."""
    ok, _ = _start(monkeypatch)
    assert ok is True
    assert srv.is_running() is True


def test_start_background_is_idempotent_and_republishes(monkeypatch):
    ok, _ = _start(monkeypatch)
    assert ok is True
    first_app = srv.current_app()

    second_tax = _taxonomy()
    assert srv.start_background(second_tax, None) is True
    assert srv.current_app() is first_app, "must not start a second server"
    assert first_app.state._ster["taxonomy"] is second_tax


def test_renderer_attaches_to_a_server_started_without_one(monkeypatch):
    """Regression: the TUI starts this server for MCP with no landing page, then
    opening the graph viewer re-calls start_background with the VOWL renderer.
    Before html_fn moved into app state it was closed over at create_app time,
    so that second call silently did nothing and the graph 501'd."""
    ok, _ = _start(monkeypatch)  # TUI-style start: no renderer
    assert ok is True
    app = srv.current_app()
    assert app.state._ster.get("html_fn") is None

    # Graph viewer starts "the server" again, this time supplying a renderer.
    assert (
        srv.start_background(_taxonomy(), None, html_renderer=lambda *a: "<html>g</html>") is True
    )

    html_fn = app.state._ster["html_fn"]
    assert html_fn is not None
    assert html_fn(None) == "<html>g</html>"


def test_attached_renderer_is_not_replaced_on_later_calls(monkeypatch):
    _start(monkeypatch, html_renderer=lambda *a: "<html>first</html>")
    app = srv.current_app()
    srv.start_background(_taxonomy(), None, html_renderer=lambda *a: "<html>second</html>")
    assert app.state._ster["html_fn"](None) == "<html>first</html>"


def test_start_background_returns_false_when_deps_missing(monkeypatch):
    monkeypatch.setattr(srv, "_server_deps", lambda: None)
    assert srv.start_background(_taxonomy(), None) is False


def test_start_background_sets_no_html_fn_without_a_renderer(monkeypatch):
    """The MCP server wants a server, not a landing page."""
    _start(monkeypatch)
    assert srv.current_app().state._ster.get("html_fn") is None


def test_start_background_wires_injected_renderer_with_live_taxonomy_and_token(monkeypatch):
    """The renderer is called with the *live* taxonomy, so it tracks later pushes."""
    got: dict = {}

    def renderer(taxonomy, root_uri, token):
        got.update(taxonomy=taxonomy, root_uri=root_uri, token=token)
        return "<html>graph</html>"

    _start(monkeypatch, html_renderer=renderer)

    html_fn = srv.current_app().state._ster["html_fn"]
    assert html_fn("root:X") == "<html>graph</html>"
    assert got["token"] == "test-token"
    assert got["root_uri"] == "root:X"
    assert got["taxonomy"] is srv.current_app().state._ster["taxonomy"]


def test_pushed_taxonomy_reaches_the_landing_page(monkeypatch):
    """The page must render the current taxonomy, not the one it started with."""
    # Identify taxonomies by a value, not by id(): CPython reuses ids once an
    # object is collected, which made an id-based assertion flaky under xdist.
    _start(monkeypatch, html_renderer=lambda tax, _root, _token: f"<html>{tax.ontology_uri}</html>")
    app = srv.current_app()

    replacement = _taxonomy()
    replacement.ontology_uri = "https://example.org/replacement"
    srv.push_taxonomy(replacement)

    assert app.state._ster["html_fn"](None) == "<html>https://example.org/replacement</html>"
