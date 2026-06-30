"""Regression tests for analysis-cache bounding.

Root cause: `analysis_cache` keeps a single JSON file holding every file ever
analysed, keyed by absolute path, and rewrites the whole blob on each save. It
never evicted, so dead paths (deleted/moved files) lingered forever and the
write cost grew without bound.

Fix: `set_cached` now prunes — it drops entries whose file no longer exists and
caps the cache to the `_MAX_ENTRIES` most-recently-written entries. These tests
lock that in. They run under the autouse `_isolate_analysis_cache` fixture, so
they only ever touch a per-test tmp cache.
"""

from __future__ import annotations

from pathlib import Path

from ster import analysis_cache


def _entry(ts: float) -> dict:
    return {"file_hash": "h", "timestamp": ts, "by_scheme": {}}


# ── _prune policy (unit) ──────────────────────────────────────────────────────


def test_prune_drops_entries_for_deleted_files(tmp_path):
    alive = tmp_path / "alive.ttl"
    alive.write_text("", encoding="utf-8")
    dead = tmp_path / "gone.ttl"  # never created

    raw = {str(alive): _entry(2.0), str(dead): _entry(1.0)}
    pruned = analysis_cache._prune(raw)

    assert str(alive) in pruned
    assert str(dead) not in pruned


def test_prune_caps_to_max_entries_keeping_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "_MAX_ENTRIES", 2)
    files = []
    raw: dict = {}
    for i in range(4):
        f = tmp_path / f"f{i}.ttl"
        f.write_text("", encoding="utf-8")
        raw[str(f)] = _entry(float(i))  # timestamps 0, 1, 2, 3
        files.append(f)

    pruned = analysis_cache._prune(raw)

    assert len(pruned) == 2
    assert str(files[2]) in pruned and str(files[3]) in pruned  # newest kept
    assert str(files[0]) not in pruned and str(files[1]) not in pruned  # oldest evicted


def test_prune_keeps_all_when_under_cap_and_alive(tmp_path):
    f = tmp_path / "a.ttl"
    f.write_text("", encoding="utf-8")
    raw = {str(f): _entry(1.0)}
    assert analysis_cache._prune(raw) == raw


# ── set_cached integration ────────────────────────────────────────────────────


def test_set_cached_bounds_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "_MAX_ENTRIES", 2)
    for i in range(4):
        f = tmp_path / f"f{i}.ttl"
        f.write_text("", encoding="utf-8")
        analysis_cache.set_cached(f, "hash", {})

    assert len(analysis_cache._load_raw()) == 2


def test_set_cached_keeps_the_just_written_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "_MAX_ENTRIES", 1)
    last: Path | None = None
    for i in range(3):
        last = tmp_path / f"f{i}.ttl"
        last.write_text("", encoding="utf-8")
        analysis_cache.set_cached(last, "hash", {})

    raw = analysis_cache._load_raw()
    assert len(raw) == 1
    assert last is not None
    assert str(last.resolve()) in raw


def test_path_exists_treats_oserror_as_missing(monkeypatch):
    """A path that raises on stat (e.g. a stale network mount) is treated as
    gone, so a problematic entry is pruned rather than crashing the save."""

    def boom(self):  # noqa: ANN001
        raise OSError("unreachable")

    monkeypatch.setattr("pathlib.Path.exists", boom)
    assert analysis_cache._path_exists("/nope/whatever.ttl") is False


def test_get_cached_roundtrip_still_works(tmp_path):
    f = tmp_path / "v.ttl"
    f.write_text("data", encoding="utf-8")
    h = analysis_cache.get_file_hash(f)

    analysis_cache.set_cached(f, h, {})

    assert analysis_cache.get_cached(f) == {}
