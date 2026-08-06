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
from pathlib import Path
from typing import Any

_TOKEN_FILE = Path.home() / ".config" / "ster" / "api_token"
_SERVER_CONFIG_FILE = Path.home() / ".config" / "ster" / "server_config.json"

_DEFAULT_SERVER_URL = "http://127.0.0.1"
_DEFAULT_SERVER_PORT = 8765


def load_server_config() -> tuple[str, int]:
    """Return (url, port) from persisted config, or defaults if not set."""
    if _SERVER_CONFIG_FILE.exists():
        try:
            data = json.loads(_SERVER_CONFIG_FILE.read_text())
            url = str(data.get("url", _DEFAULT_SERVER_URL))
            port = int(data.get("port", _DEFAULT_SERVER_PORT))
            return url, port
        except Exception:  # noqa: BLE001
            pass
    return _DEFAULT_SERVER_URL, _DEFAULT_SERVER_PORT


def save_server_config(url: str, port: int) -> None:
    """Persist server url and port to config file."""
    _SERVER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SERVER_CONFIG_FILE.write_text(json.dumps({"url": url, "port": port}))


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
) -> None:
    """Reload taxonomy and broadcast SSE whenever the source file changes."""
    import watchfiles  # deferred — only available when ster[api] is installed

    from .api import SSEBroadcaster
    from .store import load

    broadcaster: SSEBroadcaster = app.state._ster["broadcaster"]  # type: ignore[attr-defined]

    def _watch() -> None:
        for _ in watchfiles.watch(file_path):
            try:
                reloaded = load(file_path)
                app.state._ster["taxonomy"] = reloaded  # type: ignore[attr-defined]
                broadcaster.notify(loop)
            except Exception:  # noqa: BLE001
                pass  # don't kill the watcher on a parse error

    thread = threading.Thread(target=_watch, daemon=True, name="ster-file-watcher")
    thread.start()


def serve(
    file_path: Path,
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Start the ster API server and graph viewer.

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
    taxonomy = load(file_path)
    broadcaster = SSEBroadcaster()

    def save_fn(tax: Any) -> None:
        save(tax, file_path)

    def html_fn(root_uri: str | None = None) -> str:
        return render_vowl_html(
            app.state._ster["taxonomy"],  # type: ignore[attr-defined]
            file_path,
            api_token=token,
            root_uri=root_uri,
        )

    app = create_app(taxonomy, token, broadcaster, save_fn, html_fn=html_fn, file_path=file_path)
    # Also store broadcaster in shared state so the watcher can reach it
    app.state._ster["broadcaster"] = broadcaster  # type: ignore[attr-defined]

    def _on_startup() -> None:
        _start_file_watcher(file_path, app, asyncio.get_running_loop())

    app.router.on_startup.append(_on_startup)  # type: ignore[attr-defined]

    print("\n  ster API server")
    print(f"  URL  : http://{_host}:{_port}/")
    print(f"  Docs : http://{_host}:{_port}/docs")
    print(f"  Token: {token}")
    print(f"  (token persisted at {_TOKEN_FILE})\n")

    uvicorn.run(app, host=_host, port=_port, log_level="warning")
