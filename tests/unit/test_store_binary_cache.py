from __future__ import annotations

import os
import pickle
import time
from pathlib import Path
from unittest.mock import patch

from ster import store
from ster.model import Taxonomy

_VALID_TTL = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
    "@prefix ex: <https://example.org/> .\n"
    "ex:Scheme a skos:ConceptScheme .\n"
    "ex:Concept a skos:Concept ; skos:inScheme ex:Scheme .\n"
)


def test_load_creates_binary_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STER_NO_CACHE", "0")
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL)
    cache_path = store._get_bin_cache_path(ttl)

    assert not cache_path.exists()

    # First load creates the cache
    taxonomy = store.load(ttl)
    assert isinstance(taxonomy, Taxonomy)
    assert cache_path.exists()

    # Verify it's a valid pickle
    with open(cache_path, "rb") as f:
        # S301 is waived because the test creates and verifies its own trusted pickle.
        cached = pickle.load(f)  # noqa: S301
    assert isinstance(cached, Taxonomy)
    assert cached.file_path == ttl


def test_load_uses_binary_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STER_NO_CACHE", "0")
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL)

    # First load to create cache
    store.load(ttl)

    # Second load should use cache. We mock pickle.load to verify.
    with patch("pickle.load") as mock_load:
        # Mock load to return a dummy taxonomy
        dummy = Taxonomy()
        mock_load.return_value = dummy

        # Ensure mtime of cache > mtime of source
        cache_path = store._get_bin_cache_path(ttl)
        os.utime(cache_path, (time.time() + 100, time.time() + 100))

        result = store.load(ttl)
        assert result is dummy
        assert mock_load.called


def test_load_skips_stale_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STER_NO_CACHE", "0")
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL)

    # First load to create cache
    store.load(ttl)

    # Make source NEWER than cache
    os.utime(ttl, (time.time() + 200, time.time() + 200))

    with patch("pickle.load") as mock_load:
        store.load(ttl)
        # Should NOT have used pickle.load because cache is stale
        assert not mock_load.called


def test_load_handles_corrupt_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STER_NO_CACHE", "0")
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL)
    cache_path = store._get_bin_cache_path(ttl)

    # Create a corrupt cache file
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("NOT A PICKLE")
    # Ensure it's "fresh" by mtime
    os.utime(cache_path, (time.time() + 100, time.time() + 100))

    # Should fall back to parsing instead of crashing
    taxonomy = store.load(ttl)
    assert isinstance(taxonomy, Taxonomy)


def test_load_honors_disable_flag(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STER_NO_CACHE", "1")
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL)
    cache_path = store._get_bin_cache_path(ttl)

    # Load should NOT create the cache
    store.load(ttl)
    assert not cache_path.exists()


def test_load_handles_save_cache_error(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STER_NO_CACHE", "0")
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL)

    with patch("pickle.dump") as mock_dump:
        mock_dump.side_effect = pickle.PicklingError("failed")
        # Should not crash if saving cache fails
        taxonomy = store.load(ttl)
        assert isinstance(taxonomy, Taxonomy)
