from __future__ import annotations

import json
import tempfile
import threading
import urllib.request
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("ster")
except PackageNotFoundError:
    __version__ = "0.0.0"

_PYPI_URL = "https://pypi.org/pypi/ster/json"
_VERSION_CACHE = Path(tempfile.gettempdir()) / "ster_version_check.json"


def _newer(a: str, b: str) -> bool:
    def _t(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)

    return _t(a) > _t(b)


def check_update() -> str | None:
    """Return the latest PyPI version if newer than installed, else None.

    Non-blocking: reads from a temp-file cache (12 h TTL) and starts a
    background daemon thread to refresh it. Returns None on cache miss or
    when the installed version is already current.
    Shares the cache file with the CLI's version check.
    """
    now = datetime.now()
    cached_latest: str | None = None

    if _VERSION_CACHE.exists():
        try:
            data = json.loads(_VERSION_CACHE.read_text())
            checked = datetime.fromisoformat(data["checked"])
            if now - checked < timedelta(hours=12):
                cached_latest = data.get("latest")
        except Exception:
            pass

    def _fetch() -> None:
        try:
            with urllib.request.urlopen(_PYPI_URL, timeout=3) as resp:  # noqa: S310
                payload = json.loads(resp.read())
            latest = payload["info"]["version"]
            existing: dict = {}
            if _VERSION_CACHE.exists():
                try:
                    existing = json.loads(_VERSION_CACHE.read_text())
                except Exception:
                    pass
            existing.update({"checked": now.isoformat(), "latest": latest})
            _VERSION_CACHE.write_text(json.dumps(existing))
        except Exception:
            pass

    threading.Thread(target=_fetch, daemon=True).start()

    if cached_latest and _newer(cached_latest, __version__):
        return cached_latest
    return None
