"""The manifest a merged cache keeps of its source files, and how it is checked."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ster.store import _cache

pytestmark = pytest.mark.mutation  # noqa: V107  # pytest reads it to select the mutation tests

OLD = 1_000_000_000  # a modification time well before the files were written
TEXT = "utf-8"


@pytest.fixture
def sources(tmp_path) -> list[Path]:
    files = []
    for name in ("a", "b"):
        path = tmp_path / f"{name}.ttl"
        path.write_text(f"content of {name}", encoding=TEXT)
        files.append(path)
    return files


@pytest.fixture
def cache(tmp_path, sources) -> Path:
    path = tmp_path / "merged.pickle"
    path.write_bytes(b"x")
    _cache._write_manifest(path, _cache._source_manifest(sources))
    return path


def test_manifest_records_size_mtime_and_hash_per_file(sources):
    manifest = _cache._source_manifest(sources)
    entry = manifest[str(sources[0].resolve())]
    assert entry["size"] == sources[0].stat().st_size
    assert entry["mtime_ns"] == sources[0].stat().st_mtime_ns
    assert len(entry["sha256"]) == 64  # noqa: PLR2004 - a hex SHA-256


def test_manifest_matches_when_nothing_changed(cache, sources):
    assert _cache._is_merged_cache_valid(cache, sources)


def test_manifest_mismatch_when_content_changes_with_same_size(cache, sources):
    sources[0].write_text("content of Z", encoding=TEXT)  # same length as "content of a"
    assert not _cache._is_merged_cache_valid(cache, sources)


def test_manifest_mismatch_when_older_mtime_but_different_content(cache, sources):
    # Regression: the old check only asked whether the cache was newer than the sources,
    # so a file restored with an old timestamp kept serving the stale graph.
    sources[0].write_text("something else entirely", encoding=TEXT)
    os.utime(sources[0], (OLD, OLD))
    assert not _cache._is_merged_cache_valid(cache, sources)


def test_manifest_matches_when_touched_but_content_identical(cache, sources):
    os.utime(sources[0], None)
    os.utime(sources[0], (OLD, OLD))
    assert _cache._is_merged_cache_valid(cache, sources)


def test_unchanged_files_are_not_hashed(cache, sources, monkeypatch):
    def refuse(_path):
        raise AssertionError("hashed a file whose size and time are unchanged")

    monkeypatch.setattr(_cache, "_file_sha256", refuse)
    assert _cache._is_merged_cache_valid(cache, sources)


def test_manifest_mismatch_when_file_added(cache, sources, tmp_path):
    extra = tmp_path / "c.ttl"
    extra.write_text("new", encoding=TEXT)
    assert not _cache._is_merged_cache_valid(cache, [*sources, extra])


def test_manifest_mismatch_when_file_removed(cache, sources):
    assert not _cache._is_merged_cache_valid(cache, sources[:1])


def test_manifest_mismatch_when_file_missing(cache, sources):
    sources[1].unlink()
    assert not _cache._is_merged_cache_valid(cache, sources)


def test_a_cache_without_a_manifest_is_not_valid(cache, sources):
    _cache._manifest_path(cache).unlink()
    assert not _cache._is_merged_cache_valid(cache, sources)


def test_a_damaged_manifest_is_not_valid(cache, sources):
    _cache._manifest_path(cache).write_text("{not json", encoding=TEXT)
    assert not _cache._is_merged_cache_valid(cache, sources)


def test_a_missing_cache_file_is_not_valid(cache, sources):
    cache.unlink()
    assert not _cache._is_merged_cache_valid(cache, sources)
