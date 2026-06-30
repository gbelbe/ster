"""Regression: the on-disk analysis cache must be isolated from the real
~/.cache/ster/ during tests.

Root cause: analysis_cache writes a single JSON file keyed by absolute path,
holding every file ever analysed, and rewrites the whole blob on each save.
Tests used the developer's real ~/.cache/ster/analysis_cache.json, so every
viewer-save test re-serialised the entire accumulated cache (~900ms/save once
it grew to thousands of dead pytest tmp-path entries) and polluted it further.

The autouse `_isolate_analysis_cache` fixture in tests/conftest.py redirects
the cache to a per-test tmp dir. These tests lock that in.
"""

from __future__ import annotations

from pathlib import Path

from ster import analysis_cache


def test_cache_path_is_not_the_real_home_cache():
    home_cache = Path.home() / ".cache" / "ster"
    p = analysis_cache._cache_path()
    assert home_cache not in p.parents, (
        f"analysis cache not isolated — points at the real home cache: {p}"
    )


def test_set_cached_writes_only_to_the_isolated_path(tmp_path):
    """A save must land in the redirected cache, never the home file."""
    f = tmp_path / "v.ttl"
    f.write_text("", encoding="utf-8")

    analysis_cache.set_cached(f, "deadbeef", {})

    assert analysis_cache._cache_path().exists()
    home_cache = Path.home() / ".cache" / "ster"
    assert home_cache not in analysis_cache._cache_path().parents
