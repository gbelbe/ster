"""A cache written by a different build of ster is never read by this one.

The fingerprint already covered the model's *shape* — add a field and the cache
key changes, so an older build's pickle is simply looked for elsewhere. What it
did not cover is a change to the logic that *fills* those fields, and that is
the more common kind of change.

It bit during development: a fix to how the residue is computed left the model's
fields untouched, so the fingerprint was unchanged and every run kept reading
the pre-fix taxonomy. The same thing would happen to a user upgrading ster —
they would keep the old behaviour until the file itself changed.

Mixing in the source of the model and the loader fixes both cases at once and
cannot be forgotten, since it is read from the code itself. A release that left
both alone keeps its cache; it no longer costs a user a minutes-long reload.
"""

from __future__ import annotations

from ster.store._cache import _get_bin_cache_path, _model_schema_fingerprint


def test_the_fingerprint_follows_the_loader_code(monkeypatch) -> None:
    """Two builds whose loader differs must not share a cache entry."""
    _model_schema_fingerprint.cache_clear()
    monkeypatch.setattr("ster.store._cache._loader_source_hash", lambda: "loader-a")
    first = _model_schema_fingerprint()

    _model_schema_fingerprint.cache_clear()
    monkeypatch.setattr("ster.store._cache._loader_source_hash", lambda: "loader-b")
    second = _model_schema_fingerprint()
    _model_schema_fingerprint.cache_clear()

    assert first != second, "a changed loader reused the previous build's cache"


def test_the_same_build_keeps_its_cache(monkeypatch) -> None:
    """Invalidating on every call would make the cache pointless."""
    _model_schema_fingerprint.cache_clear()
    monkeypatch.setattr("ster._version.__version__", "1.2.3", raising=False)
    first = _model_schema_fingerprint()
    _model_schema_fingerprint.cache_clear()
    second = _model_schema_fingerprint()

    assert first == second


def test_the_fingerprint_reaches_the_cache_filename(tmp_path) -> None:
    """The key is only useful if it is actually in the path."""
    _model_schema_fingerprint.cache_clear()

    assert _model_schema_fingerprint() in _get_bin_cache_path(tmp_path / "t.ttl").name
