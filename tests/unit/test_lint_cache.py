"""Unit tests for the md5 + config keyed semanticlint disk cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from ster.plugins.semanticlint import lint_cache

_RESULT = ({"error": 1, "warning": 2}, [{"severity": "error", "check_id": "x", "subject": "s"}])


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(lint_cache, "_cache_path", lambda: tmp_path / "lint_cache.json")


def _ttl(tmp_path: Path, text: str = "x") -> Path:
    f = tmp_path / "o.ttl"
    f.write_text(text, encoding="utf-8")
    return f


def test_get_cached_is_none_when_nothing_stored(tmp_path):
    assert lint_cache.get_cached(_ttl(tmp_path), "cfg") is None


def test_set_then_get_round_trips(tmp_path):
    f = _ttl(tmp_path)
    lint_cache.set_cached(f, "cfg", _RESULT)
    assert lint_cache.get_cached(f, "cfg") == _RESULT


def test_a_different_config_hash_misses(tmp_path):
    f = _ttl(tmp_path)
    lint_cache.set_cached(f, "cfg-A", _RESULT)
    assert lint_cache.get_cached(f, "cfg-B") is None  # thresholds changed → recompute


def test_a_changed_file_misses(tmp_path):
    f = _ttl(tmp_path, "before")
    lint_cache.set_cached(f, "cfg", _RESULT)
    f.write_text("after — edited", encoding="utf-8")  # new md5
    assert lint_cache.get_cached(f, "cfg") is None


def test_get_or_compute_miss_computes_fires_hook_and_caches(tmp_path):
    f = _ttl(tmp_path)
    calls, notes = [], []
    out = lint_cache.get_or_compute(
        f, "cfg", compute=lambda: calls.append(1) or _RESULT, on_compute=lambda: notes.append(1)
    )
    assert out == _RESULT
    assert calls == [1] and notes == [1]  # computed once, hook fired
    assert lint_cache.get_cached(f, "cfg") == _RESULT  # now cached


def test_get_or_compute_hit_skips_compute_and_hook(tmp_path):
    f = _ttl(tmp_path)
    lint_cache.set_cached(f, "cfg", _RESULT)
    calls, notes = [], []

    def _boom():
        calls.append(1)
        raise AssertionError("should not compute on a hit")

    out = lint_cache.get_or_compute(f, "cfg", compute=_boom, on_compute=lambda: notes.append(1))
    assert out == _RESULT
    assert calls == [] and notes == []  # neither compute nor the hook ran


def test_config_hash_is_stable_and_order_independent(tmp_path):
    a = lint_cache.config_hash({"select": ["x"], "ignore": [], "quality": {"k": 1}})
    b = lint_cache.config_hash({"quality": {"k": 1}, "ignore": [], "select": ["x"]})
    c = lint_cache.config_hash({"select": ["y"], "ignore": [], "quality": {"k": 1}})
    assert a == b  # key order does not change the hash
    assert a != c  # different config → different hash


def test_prune_caps_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(lint_cache, "_MAX_ENTRIES", 3)
    files = []
    for i in range(5):
        f = tmp_path / f"o{i}.ttl"
        f.write_text(str(i), encoding="utf-8")
        files.append(f)
        lint_cache.set_cached(f, "cfg", _RESULT)
    raw = lint_cache._load_raw()
    assert len(raw) == 3  # capped to the newest _MAX_ENTRIES


def test_file_hash_of_a_missing_file_is_empty(tmp_path):
    assert lint_cache._file_hash(tmp_path / "nope.ttl") == ""


def test_a_corrupt_cache_file_is_ignored(tmp_path):
    (tmp_path / "lint_cache.json").write_text("{ not json", encoding="utf-8")
    assert lint_cache.get_cached(_ttl(tmp_path), "cfg") is None  # tolerates garbage → miss


def test_set_cached_is_a_noop_for_a_missing_file(tmp_path):
    lint_cache.set_cached(tmp_path / "gone.ttl", "cfg", _RESULT)  # no md5 → no entry, no crash
    assert lint_cache._load_raw() == {}
