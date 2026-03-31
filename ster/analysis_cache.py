"""MD5-based disk cache for taxonomy analysis results.

Cache location: ~/.cache/ster/analysis_cache.json
Cache key:      absolute file path
Cache validity: MD5 hash of the taxonomy file matches the stored hash

Typical call sites
------------------
On viewer start-up (before curses):
    by_scheme = analysis_cache.get_or_compute(taxonomy, file_path, on_compute=callback)

After any mutation + save:
    analysis_cache.invalidate(file_path)
    by_scheme = analysis_cache.get_or_compute(taxonomy, file_path)
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path

from .taxonomy_analysis import (
    SchemeAnalysis,
    analyze_taxonomy,
    scheme_analysis_from_dict,
    scheme_analysis_to_dict,
)

# ── File hashing ──────────────────────────────────────────────────────────────


def get_file_hash(path: Path) -> str:
    """Return the MD5 hex-digest of *path*, or '' on error."""
    h = hashlib.md5(usedforsecurity=False)
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65_536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


# ── Cache I/O ─────────────────────────────────────────────────────────────────


def _cache_path() -> Path:
    return Path.home() / ".cache" / "ster" / "analysis_cache.json"


def _load_raw() -> dict:
    p = _cache_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_raw(data: dict) -> None:
    p = _cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────


def get_cached(file_path: Path) -> dict[str, SchemeAnalysis] | None:
    """Return cached analysis if the file hash still matches, else None."""
    raw = _load_raw()
    entry = raw.get(str(file_path.resolve()))
    if not entry:
        return None
    current_hash = get_file_hash(file_path)
    if not current_hash or entry.get("file_hash") != current_hash:
        return None
    try:
        return {
            scheme_uri: scheme_analysis_from_dict(d)
            for scheme_uri, d in entry.get("by_scheme", {}).items()
        }
    except Exception:
        return None


def set_cached(
    file_path: Path,
    file_hash: str,
    analysis: dict[str, SchemeAnalysis],
) -> None:
    """Persist analysis for the given file."""
    raw = _load_raw()
    raw[str(file_path.resolve())] = {
        "file_hash": file_hash,
        "timestamp": time.time(),
        "by_scheme": {uri: scheme_analysis_to_dict(a) for uri, a in analysis.items()},
    }
    _save_raw(raw)


def invalidate(file_path: Path) -> None:
    """Remove the cached entry for *file_path* (call after every mutation + save)."""
    raw = _load_raw()
    key = str(file_path.resolve())
    if key in raw:
        del raw[key]
        _save_raw(raw)


def get_or_compute(
    taxonomy,  # Taxonomy — forward ref avoids circular import
    file_path: Path,
    on_compute: Callable[[], None] | None = None,
) -> dict[str, SchemeAnalysis]:
    """Return cached analysis, or compute → cache → return.

    *on_compute* is called (with no arguments) just before computing starts,
    allowing the caller to display a status message.
    """
    cached = get_cached(file_path)
    if cached is not None:
        return cached

    if on_compute:
        on_compute()

    analysis = analyze_taxonomy(taxonomy)
    file_hash = get_file_hash(file_path)
    if file_hash:
        set_cached(file_path, file_hash, analysis)
    return analysis
