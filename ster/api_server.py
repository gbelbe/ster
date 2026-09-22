"""Server lifecycle for the ster ontology API.

Handles:
- Bearer-token creation / persistence
- File watching via watchfiles (reloads taxonomy + broadcasts SSE on change)
- Uvicorn startup
"""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# A renderer for the server's HTML landing pages: (taxonomy, root_uri, token) -> html.
# Injected by the caller so this module stays free of any front-end feature
# (the VOWL graph passes ``render_vowl_html``; the MCP server passes nothing).
# (taxonomy, root_uri, token, full, sparql) — the last is a CONSTRUCT to draw
# instead of walking the model, as /viz?q= and /map?q= both take.
HtmlRenderer = Callable[[Any, str | None, str, bool, str], str]

# The key the published model lives under in ``app.state._ster``; named once
# so the six places that read or republish it cannot drift apart.
_LIT_TAXONOMY = "taxonomy"
# The landing-page callable's key in the shared server state. Named for the
# same reason as _LIT_TAXONOMY: three places read or write it, and a typo in
# one of them is a 501 nobody can grep for.
_LIT_HTML_FN = "html_fn"

_TOKEN_FILE = Path.home() / ".config" / "ster" / "api_token"
_SERVER_CONFIG_FILE = Path.home() / ".config" / "ster" / "server_config.json"

_DEFAULT_SERVER_URL = "http://127.0.0.1"  # NOSONAR - local-only address, not a network destination
_DEFAULT_SERVER_PORT = 8765


# How much of a graph the viewer draws before it starts holding things back.
# Every one is a count of nodes, and every one is editable in `ster setup` →
# Graph Viz, because the right number depends on the ontology and on the machine
# looking at it — a 200-class vocabulary on a laptop is not a 20,000-individual
# dataset on a workstation.
GRAPH_VIZ_DEFAULTS: Final[dict[str, int]] = {
    # Above this many classes (or concepts), the first view shows roots only.
    "classCollapse": 150,
    # Above this many individuals, they are replaced by a count on their class.
    "individualCollapse": 150,
    # Most individuals one class hands back when expanded.
    "classExpand": 200,
    # Above this many nodes, edge labels and arrowheads stop being drawn.
    "lodEdges": 300,
    # Above this many nodes, node labels stop being drawn and nodes shrink.
    "lodNodes": 800,
}


def _read_config() -> dict:
    """The whole config file, or an empty dict when absent or unreadable."""
    if not _SERVER_CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(_SERVER_CONFIG_FILE.read_text())
    except Exception:  # noqa: BLE001 - an unreadable config falls back to defaults
        return {}
    return data if isinstance(data, dict) else {}


def _merge_config(**changes: object) -> None:
    """Write *changes* into the config file, leaving every other key alone.

    The file holds more than one section now, so a section that writes it whole
    silently erases the others — which is exactly what the previous
    ``save_server_config`` did.
    """
    data = _read_config()
    data.update(changes)
    _SERVER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SERVER_CONFIG_FILE.write_text(json.dumps(data, indent=2))


def load_server_config() -> tuple[str, int]:
    """Return (url, port) from persisted config, or defaults if not set."""
    data = _read_config()
    try:
        return str(data.get("url", _DEFAULT_SERVER_URL)), int(
            data.get("port", _DEFAULT_SERVER_PORT)
        )
    except (TypeError, ValueError):  # a hand-edited port that is not a number
        return _DEFAULT_SERVER_URL, _DEFAULT_SERVER_PORT


def save_server_config(url: str, port: int) -> None:
    """Persist server url and port, leaving the other config sections intact."""
    _merge_config(url=url, port=port)


def load_graph_viz_config() -> dict[str, int]:
    """The graph-viewer thresholds, each falling back to its own default.

    Per key rather than all-or-nothing: a config written by an older ster, or
    hand-edited to set one value, still gets defaults for everything it omits.
    A value that is not a positive integer is ignored in favour of the default —
    a threshold of 0 or -1 would mean "always collapse", which no one wants and
    which reads as a typo.
    """
    stored = _read_config().get("graphViz")
    stored = stored if isinstance(stored, dict) else {}
    out: dict[str, int] = {}
    for key, fallback in GRAPH_VIZ_DEFAULTS.items():
        try:
            value = int(stored[key])
        except (KeyError, TypeError, ValueError):
            value = fallback
        out[key] = value if value > 0 else fallback
    return out


def save_graph_viz_config(values: dict[str, int]) -> None:
    """Persist the graph-viewer thresholds, leaving url/port intact."""
    _merge_config(graphViz={k: int(values[k]) for k in GRAPH_VIZ_DEFAULTS if k in values})


def _load_or_create_token() -> str:
    if _TOKEN_FILE.exists():
        return _TOKEN_FILE.read_text().strip()
    token = secrets.token_urlsafe(32)
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(token)
    return token


def load_token() -> str:
    """Return the persisted API bearer token (creating one if absent)."""
    return _load_or_create_token()


def save_token(token: str) -> None:
    """Persist the API bearer token."""
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(token.strip())


def _start_file_watcher(
    file_path: Path,
    app: Any,  # FastAPI app — typed as Any to avoid hard import
    loop: asyncio.AbstractEventLoop,
    context: list[Path] | None = None,
) -> None:
    """Reload taxonomy and broadcast SSE whenever the source file changes.

    The reload carries *context* too. Without it the first edit would drop every
    context entity from the live view — the file on disk is only the editable
    half, so re-reading it alone is not the same graph.
    """
    import watchfiles  # deferred — only available when ster[api] is installed

    from .api import SSEBroadcaster
    from .store import load

    broadcaster: SSEBroadcaster = app.state._ster["broadcaster"]  # type: ignore[attr-defined]

    def _watch() -> None:
        for _ in watchfiles.watch(file_path):
            try:
                reloaded = load(file_path, context=context or [])
                app.state._ster[_LIT_TAXONOMY] = reloaded  # type: ignore[attr-defined]
                broadcaster.notify(loop)
            except Exception:  # noqa: BLE001
                pass  # don't kill the watcher on a parse error

    thread = threading.Thread(target=_watch, daemon=True, name="ster-file-watcher")
    thread.start()


# ── Background (non-blocking) server ──────────────────────────────────────────
#
# ``serve()`` below blocks, which suits ``ster serve``. Long-running front-ends
# (the TUI) instead need the server running *alongside* them, so they can keep
# rendering while the API answers requests. Everything here is feature-agnostic:
# the VOWL graph viewer and the MCP context server both start the same server
# and differ only in the HTML renderer they inject.


@dataclass
class _Background:
    """The one running background server, if any."""

    app: Any = None
    broadcaster: Any = None
    loop: Any = None
    running: bool = False

    def reset(self) -> None:
        self.app = self.broadcaster = self.loop = None
        self.running = False


_bg = _Background()


def is_running() -> bool:
    """True when a background API server is up (vs. no server / a static fallback)."""
    return _bg.app is not None


def current_app() -> Any | None:
    """The running background FastAPI app, or None."""
    return _bg.app


def push_taxonomy(taxonomy: Any) -> None:
    """Publish an updated *taxonomy* to the running server and wake SSE subscribers."""
    if _bg.app is None:
        return
    _bg.app.state._ster[_LIT_TAXONOMY] = taxonomy
    _bg.broadcaster.notify(_bg.loop)


def _persist_to_working_file(state: dict[str, Any], tax: Any) -> None:
    """Save *tax* to whatever file the session currently treats as writable.

    Read from the live state on every save rather than closed over when the
    server started: the editor can change which file is writable underneath a
    running server (see :func:`publish_working_file`), and a captured path would
    keep writing every later edit into the file the server happened to open with.
    """
    target = state.get("file_path")
    if target is not None:
        from .store import save  # noqa: PLC0415

        save(tax, target)


def publish_working_file(taxonomy: Any, file_path: Path, context: list[Path]) -> None:
    """Republish the session after the editor changed which file is writable.

    ``push_taxonomy``'s sibling: the model alone is not enough, because "what
    may be edited" is answered from three places that each cache it.

    * ``taxonomy`` — its ``context_source`` is what ``_require_editable`` reads,
      so the 403s move with it.
    * ``file_path`` — the save target and the raw-ontology view. It is read from
      this state on every use rather than closed over, so that republishing here
      is enough to redirect writes.
    * ``_mutation_backend`` — a lazily built ``(service, workspace, path)``
      cached for the life of the app. Left alone, every later write would go
      through the *previous* file's workspace and land in the previous file, so
      it is dropped and rebuilt against the new state on the next mutation.

    A no-op when no server is running: the TUI starts one best-effort (a taken
    port means no MCP that session) and switching files must work regardless.
    """
    if _bg.app is None:
        return
    state = _bg.app.state._ster
    state[_LIT_TAXONOMY] = taxonomy
    state["file_path"] = file_path
    state["context"] = list(context)
    state.pop("_mutation_backend", None)
    _bg.broadcaster.notify(_bg.loop)


def _await_uvicorn_started(
    holder: dict[str, Any],
    *,
    timeout: float = 10.0,
    poll: float = 0.05,
    sleep: Any = None,
    monotonic: Any = None,
) -> bool:
    """Block until *our* uvicorn server reports it has bound and is serving.

    *holder* is the dict the server thread fills in: ``server`` (the
    ``uvicorn.Server`` once constructed), ``error`` (a startup exception, e.g. a
    bind failure), and ``done`` (set once ``serve()`` returns). Returns True only
    when ``server.started`` flips True — so a stale server squatting the
    configured port can never be mistaken for ours. Returns False on a startup
    error, when ``serve()`` finished without starting, or on timeout.
    """
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    deadline = monotonic() + timeout
    while True:
        server = holder.get("server")
        if server is not None and getattr(server, "started", False):
            return True
        if holder.get("error") is not None or holder.get("done"):
            return False
        if monotonic() >= deadline:
            return False
        sleep(poll)


def _server_deps() -> tuple[Any, Any, Any] | None:
    """Return ``(uvicorn, SSEBroadcaster, create_app)``, or None when unavailable."""
    try:
        import uvicorn  # noqa: PLC0415

        from .api import SSEBroadcaster, create_app  # noqa: PLC0415
    except ImportError:
        return None
    return uvicorn, SSEBroadcaster, create_app


def _make_html_fn(app: Any, renderer: HtmlRenderer, token: str) -> Callable[..., str]:
    """Bind *renderer* to *app*'s live taxonomy, as the landing-page callable.

    Reads the taxonomy from app state on every call, so the page tracks later
    ``push_taxonomy`` updates rather than freezing the one it started with.
    """

    def html_fn(root_uri: str | None = None, full: bool = False, sparql: str = "") -> str:
        return renderer(app.state._ster[_LIT_TAXONOMY], root_uri, token, full, sparql)

    return html_fn


def _publish_dir_for(file_path: Path | None) -> Path | None:
    """The project's publish tree (``ontology/``), created up-front.

    Made eagerly so the StaticFiles mount exists even before the first publish.
    """
    if file_path is None:
        return None
    publish_dir = file_path.parent / "ontology"
    publish_dir.mkdir(parents=True, exist_ok=True)
    return publish_dir


def _spawn_uvicorn(app: Any, host: str, port: int, uvicorn: Any) -> dict[str, Any]:
    """Run *app* under uvicorn on a daemon thread; return the thread's status holder."""
    holder: dict[str, Any] = {}
    ready = threading.Event()

    def _run() -> None:
        async def _serve_async() -> None:
            holder["loop"] = asyncio.get_running_loop()
            server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
            holder["server"] = server
            ready.set()
            try:
                await server.serve()
            # A bind failure (OSError: address already in use) must be recorded for
            # the caller rather than killing this daemon thread. Deliberately not
            # BaseException: KeyboardInterrupt / SystemExit are shutdown signals and
            # must keep propagating.
            except Exception as exc:  # noqa: BLE001
                holder["error"] = exc

        asyncio.run(_serve_async())
        holder["done"] = True

    threading.Thread(target=_run, daemon=True, name="ster-api-server").start()
    ready.wait(timeout=10)
    return holder


def start_background(
    taxonomy: Any,
    file_path: Path | None = None,
    *,
    html_renderer: HtmlRenderer | None = None,
    on_change: Callable[[], None] | None = None,
) -> bool:
    """Start the API server on a daemon thread. True once it is actually serving.

    Idempotent: a second call re-publishes *taxonomy* onto the already-running
    server instead of starting a second one. If that call supplies an
    *html_renderer* and the running server has none, the renderer is attached —
    the TUI starts this server for MCP with no landing page, and opening the
    graph viewer afterwards must still get its page rather than a 501.
    """
    if _bg.app is not None:
        state = _bg.app.state._ster
        state[_LIT_TAXONOMY] = taxonomy
        if html_renderer is not None and state.get(_LIT_HTML_FN) is None:
            state[_LIT_HTML_FN] = _make_html_fn(_bg.app, html_renderer, state["token"])
        return True

    deps = _server_deps()
    if deps is None:
        return False
    uvicorn, sse_broadcaster, create_app = deps

    url, port = load_server_config()
    host = url.split("://", 1)[-1]  # strip scheme for the bind address
    token = _load_or_create_token()
    broadcaster = sse_broadcaster()

    def save_fn(tax: Any) -> None:
        _persist_to_working_file(app.state._ster, tax)
        if on_change is not None:
            on_change()

    app = create_app(
        taxonomy,
        token,
        broadcaster,
        save_fn,
        file_path=file_path,
        publish_dir=_publish_dir_for(file_path),
    )
    app.state._ster["broadcaster"] = broadcaster
    app.state._ster["token"] = token
    if html_renderer is not None:
        app.state._ster[_LIT_HTML_FN] = _make_html_fn(app, html_renderer, token)
    _bg.app, _bg.broadcaster = app, broadcaster

    holder = _spawn_uvicorn(app, host, port, uvicorn)
    _bg.loop = holder.get("loop")
    # Success only once *our* uvicorn reports started — a bare "is the port open?"
    # probe would accept a stale server squatting the configured port.
    if _bg.loop is None or not _await_uvicorn_started(holder):
        _bg.reset()
        return False
    _bg.running = True
    return True


def serve(
    file_path: Path,
    host: str | None = None,
    port: int | None = None,
    context: list[Path] | None = None,
) -> None:
    """Start the ster API server and graph viewer.

    *context* names files merged in read-only, exactly as ``ster edit`` does it
    — same ``store.load`` call, same ``Taxonomy.context_source``, so a context
    entity is locked here for the same reason and by the same mechanism it is
    locked in the TUI. Only *file_path* is ever written.

    Blocks until the server is stopped (Ctrl-C).
    """
    import uvicorn  # deferred — only available when ster[api] is installed

    from .api import SSEBroadcaster, create_app
    from .store import load, save
    from .viz_vowl import render_vowl_html

    cfg_url, cfg_port = load_server_config()
    _host = host if host is not None else cfg_url.split("://", 1)[-1]
    _port = port if port is not None else cfg_port

    token = _load_or_create_token()
    context = [Path(c) for c in (context or [])]
    taxonomy = load(file_path, context=context)
    broadcaster = SSEBroadcaster()

    def save_fn(tax: Any) -> None:
        save(tax, file_path)

    # Bound through _make_html_fn, the same seam the background server uses,
    # rather than a second hand-written landing-page callable. The duplicate
    # here had fallen a parameter behind: _graph_html_response always passes
    # three (GET / and GET /viz both route through it, and /viz carries the
    # query), so every landing-page request under `ster serve` raised TypeError
    # and answered 500 before rendering anything. One binding cannot drift from
    # itself.
    def _renderer(
        taxonomy_now: Any, root_uri: str | None, api_token: str, full: bool, sparql: str
    ) -> str:
        return render_vowl_html(
            taxonomy_now,
            file_path,
            api_token=api_token,
            root_uri=root_uri,
            full=full,
            sparql=sparql,
        )

    app = create_app(
        taxonomy,
        token,
        broadcaster,
        save_fn,
        file_path=file_path,
        context=context,
    )
    # Also store broadcaster in shared state so the watcher can reach it
    app.state._ster["broadcaster"] = broadcaster  # type: ignore[attr-defined]
    app.state._ster[_LIT_HTML_FN] = _make_html_fn(app, _renderer, token)  # type: ignore[attr-defined]

    def _on_startup() -> None:
        _start_file_watcher(file_path, app, asyncio.get_running_loop(), context)

    app.router.on_startup.append(_on_startup)  # type: ignore[attr-defined]

    # Printed for the user's own terminal — the server it just started, on
    # their own machine, not a remote address.
    _local_prefix = "http://"  # NOSONAR - local-only address, not a network destination
    print("\n  ster API server")
    print(f"  URL  : {_local_prefix}{_host}:{_port}/")
    print(f"  Docs : {_local_prefix}{_host}:{_port}/docs")
    print(f"  MCP  : {_local_prefix}{_host}:{_port}/mcp   (read-only ontology context)")
    print(f"  Token: {token}")
    print(f"  (token persisted at {_TOKEN_FILE})\n")

    uvicorn.run(app, host=_host, port=_port, log_level="warning")
