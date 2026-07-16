"""MD5-based disk cache for semanticlint overview results.

Cache location: ``~/.cache/ster/lint_cache.json``
Cache key:      absolute file path
Cache validity: the file's MD5 **and** the quality-config hash both still match —
                so editing the ontology (new md5) or changing the thresholds (new
                config hash) both miss and force a recompute.

The semanticlint pass (pyshacl) costs ~2 s on a large ontology, so caching lets a
re-open of an *unchanged* file paint instantly instead of relinting. Kept behind
this thin module so the rest of the app never re-implements the cache logic.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path

# One entry per linted file; a user opens dozens, not thousands. Capping keeps the
# single JSON small so the full-blob rewrite on each write stays cheap.
_MAX_ENTRIES = 100

# The cached value: (severity → count, list of issue dicts). Plain JSON types only.
LintResult = tuple[dict[str, int], list[dict[str, str]]]


def _cache_path() -> Path:
    return Path.home() / ".cache" / "ster" / "lint_cache.json"


def _file_hash(path: Path) -> str:
    """MD5 hex-digest of *path*'s bytes, or '' on error (→ never cache/serve)."""
    try:
        return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
    except OSError:
        return ""


def config_hash(config: dict) -> str:
    """Stable hash of the lint config — a cached result is invalid once it changes."""
    blob = json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    return hashlib.md5(blob, usedforsecurity=False).hexdigest()


def _path_exists(path_str: str) -> bool:
    try:
        return Path(path_str).exists()
    except OSError:
        return False


def _prune(raw: dict) -> dict:
    """Drop entries whose file no longer exists, then keep the newest ``_MAX_ENTRIES``."""
    alive = {k: v for k, v in raw.items() if _path_exists(k)}
    if len(alive) <= _MAX_ENTRIES:
        return alive
    newest = sorted(alive.items(), key=lambda kv: kv[1].get("timestamp", 0), reverse=True)
    return dict(newest[:_MAX_ENTRIES])


def _load_raw() -> dict:
    p = _cache_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — a corrupt cache must never break the app
        return {}


def _save_raw(data: dict) -> None:
    p = _cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(p)
    except Exception:  # noqa: BLE001 — caching is best-effort
        pass


def get_cached(path: Path, cfg_hash: str) -> LintResult | None:
    """Return the cached lint result when the file md5 **and** config hash still match."""
    entry = _load_raw().get(str(path.resolve()))
    if not entry:
        return None
    if entry.get("file_hash") != _file_hash(path) or entry.get("config_hash") != cfg_hash:
        return None
    return entry["counts"], entry["issues"]


def set_cached(path: Path, cfg_hash: str, result: LintResult) -> None:
    """Persist *result* for *path* under its current md5 + *cfg_hash*."""
    file_hash = _file_hash(path)
    if not file_hash:
        return
    counts, issues = result
    raw = _load_raw()
    raw[str(path.resolve())] = {
        "file_hash": file_hash,
        "config_hash": cfg_hash,
        "timestamp": time.time(),
        "counts": counts,
        "issues": issues,
    }
    _save_raw(_prune(raw))


def get_or_compute(
    path: Path,
    cfg_hash: str,
    compute: Callable[[], LintResult],
    on_compute: Callable[[], None] | None = None,
) -> LintResult:
    """Return the cached lint result, or compute → cache → return.

    *on_compute* fires (once, before computing) only on a cache miss — so callers can
    show a "Checking…" message on first open / after a change, and stay silent on a hit.
    """
    cached = get_cached(path, cfg_hash)
    if cached is not None:
        return cached
    if on_compute is not None:
        on_compute()
    result = compute()
    set_cached(path, cfg_hash, result)
    return result
