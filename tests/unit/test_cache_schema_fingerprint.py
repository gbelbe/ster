"""A cache written by an older ster must never be served to a newer one.

Unpickling a dataclass whose fields have changed does not raise: pickle restores
the ``__dict__`` exactly as saved, so a Taxonomy cached before a field existed
comes back missing it. Nothing fails at load — the object is simply wrong, and
the first attribute access far away blows up:

    AttributeError: 'Taxonomy' object has no attribute 'context_source'

which reaches the user as a 500 from the graph server. `_try_load_cache` catches
AttributeError, but by then the object is already returned. The only reliable
guard is to not treat such a file as this version's cache at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import store

TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://example.org/t#> .
ex:Scheme a skos:ConceptScheme .
ex:Tent a skos:Concept ; skos:prefLabel "Tent"@en ; skos:inScheme ex:Scheme .
"""


@pytest.fixture
def source(tmp_path, monkeypatch) -> Path:
    # conftest disables the cache for the suite at large; these tests are about it.
    monkeypatch.delenv("STER_NO_CACHE", raising=False)
    monkeypatch.setattr(store._cache, "_bin_cache_dir", lambda: tmp_path / "cache")
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")
    return path


# ── the fingerprint itself ────────────────────────────────────────────────────


def test_the_fingerprint_covers_the_model_dataclasses():
    """It has to move when a model field is added, removed or renamed."""
    from dataclasses import dataclass, field

    before = store._model_schema_fingerprint()

    @dataclass
    class _Newcomer:
        uri: str = ""
        added_later: list[str] = field(default_factory=list)

    import ster.model as model

    try:
        model._Newcomer = _Newcomer  # a model gaining a dataclass
        store._model_schema_fingerprint.cache_clear()
        after = store._model_schema_fingerprint()
    finally:
        del model._Newcomer
        store._model_schema_fingerprint.cache_clear()

    assert after != before


def test_the_fingerprint_is_stable_within_one_schema():
    assert store._model_schema_fingerprint() == store._model_schema_fingerprint()


def test_the_cache_path_carries_the_fingerprint(source):
    assert store._model_schema_fingerprint() in store._get_bin_cache_path(source).name


# ── the behaviour that matters ────────────────────────────────────────────────


def test_a_cache_from_another_schema_is_not_used(source, monkeypatch):
    """The regression: an upgrade must not serve the old build's pickle."""
    store.load(source)  # populate the cache under today's fingerprint
    stale = store._get_bin_cache_path(source)
    assert stale.is_file(), "precondition: the cache was written"

    monkeypatch.setattr(store._cache, "_model_schema_fingerprint", lambda: "0ldschema")
    store._model_schema_fingerprint.cache_clear() if hasattr(
        store._model_schema_fingerprint, "cache_clear"
    ) else None

    assert store._get_bin_cache_path(source) != stale, "a new schema means a new cache file"


def test_the_cache_still_works_within_one_schema(source):
    """The guard must not disable caching altogether."""
    first = store.load(source)
    cache_path = store._get_bin_cache_path(source)
    assert cache_path.is_file()

    second = store.load(source)

    assert sorted(second.concepts) == sorted(first.concepts)


def test_a_stale_schema_cache_is_cleaned_up(source):
    """The upgrade sequence: yesterday's cache is on disk, today's build loads.

    Without this every release that touches the model leaves one orphan per
    cached file behind, forever.
    """
    cache_dir = source.parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    current = store._get_bin_cache_path(source)
    orphan = cache_dir / current.name.replace(store._model_schema_fingerprint(), "0ldschema")
    orphan.write_bytes(b"written by an older ster")

    store.load(source)  # a miss under the new schema: parse, prune, then save

    assert not orphan.exists(), "the previous schema's cache should be gone"
    assert current.is_file(), "and this schema's cache written in its place"


def test_pruning_leaves_other_files_caches_alone(source):
    """The glob is scoped to one source file's own prefix."""
    cache_dir = source.parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    unrelated = cache_dir / "somebody_else_deadbeefdeadbeef_0ldschema.pickle"
    unrelated.write_bytes(b"another file's cache")

    store.load(source)

    assert unrelated.exists()


def test_a_failing_prune_never_breaks_the_load(source, monkeypatch):
    """A read-only or vanished cache dir is a housekeeping problem, not a load error."""

    def denied(_self, _pattern):
        raise PermissionError("cache dir is read-only")

    monkeypatch.setattr(Path, "glob", denied)

    taxonomy = store.load(source)  # must not raise

    assert "https://example.org/t#Tent" in taxonomy.concepts


def test_a_symlinked_cache_is_never_unlinked(source):
    """The loader already refuses to read symlinked caches; do not delete them either."""
    cache_dir = source.parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / "elsewhere.pickle"
    target.write_bytes(b"not ours to remove")
    current = store._get_bin_cache_path(source)
    link = cache_dir / current.name.replace(store._model_schema_fingerprint(), "0ldschema")
    link.symlink_to(target)

    store.load(source)

    assert link.is_symlink(), "a symlink is someone else's business"
    assert target.exists()


# ── what the key follows: the code that fills the model, not the release number ──


def test_a_new_release_that_left_the_loader_alone_keeps_the_cache(monkeypatch):
    before = store._model_schema_fingerprint()
    monkeypatch.setattr("ster._version.__version__", "9.9.9")
    store._model_schema_fingerprint.cache_clear()
    try:
        assert store._model_schema_fingerprint() == before
    finally:
        store._model_schema_fingerprint.cache_clear()


def test_a_change_to_the_loader_source_looks_elsewhere(monkeypatch):
    before = store._cache._loader_source_hash()
    real = Path.read_bytes
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda self: real(self) + (b"# edited" if self.name == "_load_save.py" else b""),
    )

    assert store._cache._loader_source_hash() != before


def test_unreadable_sources_fall_back_to_the_version(monkeypatch):
    def refuse(_self):
        raise OSError("no sources")

    monkeypatch.setattr(Path, "read_bytes", refuse)

    from ster._version import __version__

    assert store._cache._loader_source_hash() == __version__
