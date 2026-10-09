"""Opening a project with context files reports what it is doing and does not read them again the next time."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ster import store
from ster.store import _load_save

pytestmark = pytest.mark.mutation  # noqa: V107  # pytest reads it to select the mutation tests

PREFIXES = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n@prefix ex: <https://example.org/t#> .\n"
)
MAIN = PREFIXES + "ex:Main a owl:Class .\n"
OTHERS = ("Alpha", "Beta", "Gamma")
FUTURE = 4_000_000_000  # a modification time later than any cache written during the test
BYTES = "bytes"
TEXT = "utf-8"
FULL = 100  # percent: the load is complete


def _ttl(name: str) -> str:
    return PREFIXES + f"ex:{name} a owl:Class .\n"


@pytest.fixture
def project(tmp_path, monkeypatch) -> tuple[Path, list[Path]]:
    # conftest turns the cache off for the suite at large; these tests are about it.
    monkeypatch.delenv("STER_NO_CACHE", raising=False)
    monkeypatch.setattr(store._cache, "_bin_cache_dir", lambda: tmp_path / "cache")
    main = tmp_path / "main.ttl"
    main.write_text(MAIN, encoding=TEXT)
    context = []
    for name in OTHERS:
        path = tmp_path / f"{name.lower()}.ttl"
        path.write_text(_ttl(name), encoding=TEXT)
        context.append(path)
    return main, context


@pytest.fixture
def parses(monkeypatch) -> list[Path]:
    """Every file the loader reads with rdflib, in order."""
    seen: list[Path] = []
    real = _load_save._parse_graph

    def counting(path):
        seen.append(Path(path))
        return real(path)

    monkeypatch.setattr(_load_save, "_parse_graph", counting)
    return seen


def _contexts_read(parses: list[Path], context: list[Path]) -> list[Path]:
    return [p for p in parses if p in context]


# ── what the progress says ────────────────────────────────────────────────────


def test_the_editable_file_alone_does_not_look_like_the_whole_load(project):
    main, context = project
    reports: list[tuple[int, str]] = []
    store.load(main, progress_callback=lambda p, m: reports.append((p, m)), context=context)
    first_context = next(i for i, (_, m) in enumerate(reports) if "context" in m)
    assert max(p for p, _ in reports[:first_context]) <= _load_save._MAIN_SHARE


def test_the_progress_only_goes_forward_and_the_closing_work_is_named_before_100(project):
    main, context = project
    reports: list[tuple[int, str]] = []
    store.load(main, progress_callback=lambda p, m: reports.append((p, m)), context=context)
    percents = [p for p, _ in reports]
    assert percents == sorted(percents)
    assert (
        percents[-1] == _load_save._ALMOST_DONE
    )  # 100 is for the caller, once the model is in its hands
    assert [m for p, m in reports if p == _load_save._ALMOST_DONE] == [
        "Assigning handles",
        "Updating cache",
    ]


def test_every_context_file_is_named_while_it_is_read_and_while_it_is_merged(project):
    main, context = project
    messages: list[str] = []
    store.load(main, progress_callback=lambda _p, m: messages.append(m), context=context)
    for index, path in enumerate(context, start=1):
        assert f"Reading context {index}/{len(context)}: {path.name}" in messages
        assert f"Merging context {index}/{len(context)}: {path.name}" in messages


def test_a_load_without_context_reports_as_it_always_did(project):
    main, _ = project
    percents: list[int] = []
    store.load(main, progress_callback=lambda p, _m: percents.append(p))
    assert percents[-1] == FULL


def test_a_load_that_nobody_watches_still_merges_the_context(project):
    main, context = project
    taxonomy = store.load(main, context=context)
    assert {c.name for c in taxonomy.context_files} == {p.name for p in context}


# ── each file is read once ────────────────────────────────────────────────────


def test_each_context_file_is_parsed_once_not_twice(project, parses):
    main, context = project
    store.load(main, context=context)
    assert sorted(_contexts_read(parses, context)) == sorted(context)


# ── the merged cache ──────────────────────────────────────────────────────────


def test_the_second_open_reads_no_context_file_and_gives_the_same_model(project, parses):
    main, context = project
    first = store.load(main, context=context)
    parses.clear()
    second = store.load(main, context=context)
    assert _contexts_read(parses, context) == []
    assert set(second.owl_classes) == set(first.owl_classes)
    assert second.context_source == first.context_source


def test_a_cache_hit_says_so_at_100_percent(project):
    main, context = project
    store.load(main, context=context)
    reports: list[tuple[int, str]] = []
    store.load(main, progress_callback=lambda p, m: reports.append((p, m)), context=context)
    assert reports[-1] == (FULL, "Loaded from cache")


def test_a_context_file_that_changed_is_read_again_and_its_change_is_seen(project, parses):
    main, context = project
    store.load(main, context=context)
    context[0].write_text(_ttl("Delta"), encoding=TEXT)
    os.utime(context[0], (FUTURE, FUTURE))
    parses.clear()
    taxonomy = store.load(main, context=context)
    assert context[0] in parses
    assert "https://example.org/t#Delta" in taxonomy.owl_classes


def test_an_editable_file_that_changed_is_read_again(project, parses):
    main, context = project
    store.load(main, context=context)
    main.write_text(MAIN + "ex:Added a owl:Class .\n", encoding=TEXT)
    parses.clear()
    store.load(main, context=context)
    assert _contexts_read(parses, context) != []


def test_a_cache_with_no_manifest_is_rebuilt_not_trusted(project, parses):
    main, context = project
    store.load(main, context=context)
    store._cache._manifest_path(store._cache._get_context_cache_path(main, context)).unlink()
    parses.clear()
    store.load(main, context=context)
    assert _contexts_read(parses, context) == context


def test_a_damaged_cache_is_rebuilt_and_rewritten(project, parses):
    main, context = project
    store.load(main, context=context)
    store._cache._get_context_cache_path(main, context).write_bytes(b"not a pickle")
    parses.clear()
    taxonomy = store.load(main, context=context)
    assert _contexts_read(parses, context) == context
    parses.clear()
    store.load(main, context=context)
    assert _contexts_read(parses, context) == []
    assert "https://example.org/t#Alpha" in taxonomy.owl_classes


def test_a_different_list_of_context_files_has_its_own_cache(project, parses):
    main, context = project
    store.load(main, context=context)
    parses.clear()
    taxonomy = store.load(main, context=context[:1])
    assert _contexts_read(parses, context) == context[:1]
    assert set(taxonomy.context_files) == set(context[:1])


def test_a_context_file_that_has_gone_does_not_leave_a_cache_that_vouches_for_it(project):
    main, context = project
    store.load(main, context=context)
    cache = store._cache._get_context_cache_path(main, context)
    context[0].unlink()
    assert not store._cache._is_merged_cache_valid(cache, [main, *context])


def test_nothing_is_cached_or_used_when_the_cache_is_switched_off(project, parses, monkeypatch):
    main, context = project
    monkeypatch.setenv("STER_NO_CACHE", "1")
    store.load(main, context=context)
    parses.clear()
    store.load(main, context=context)
    assert _contexts_read(parses, context) == context
    assert not store._cache._get_context_cache_path(main, context).exists()


def test_a_merged_cache_written_by_another_build_is_removed_and_ours_is_kept(project):
    main, context = project
    store.load(main, context=context)
    ours = store._cache._get_context_cache_path(main, context)
    stale = ours.with_name(ours.name.rsplit("_", 1)[0] + "_00000000.pickle")
    stale.write_bytes(BYTES.encode())
    store.load(main, context=context)
    assert ours.exists()
    assert not stale.exists()


def test_the_cache_of_the_file_alone_is_left_to_its_own_pruning(project):
    main, context = project
    store.load(main, context=context)
    alone = store._get_bin_cache_path(main)
    other = alone.with_name(alone.name.rsplit("_", 1)[0] + "_00000000.pickle")
    other.write_bytes(BYTES.encode())
    store._cache._prune_stale_context_caches(main, context)
    assert other.exists()


# ── what merging a context file brings in ─────────────────────────────────────

EXTRA = "https://example.org/extra#"
THEIRS = PREFIXES + f"@prefix extra: <{EXTRA}> .\n"
EDITABLE_SIDE = THEIRS + 'ex:Main a owl:Class .\nex:Both a owl:Class .\nex:Loose2 extra:q "w" .\n'
CONTEXT_SIDE = (
    THEIRS
    + "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    + 'ex:Main rdfs:comment "said by the context file"@en .\n'
    + "ex:Both a owl:Class .\n"
    + 'ex:Fresh a owl:Class .\nex:Loose extra:p "v" .\nex:Loose2 extra:q "w" .\n'
)
BASE = "https://example.org/t#"


@pytest.fixture
def merged(tmp_path):
    main, context = tmp_path / "editable.ttl", tmp_path / "theirs.ttl"
    main.write_text(EDITABLE_SIDE, encoding=TEXT)
    context.write_text(CONTEXT_SIDE, encoding=TEXT)
    return store.load(main, context=[context]), context


def _subjects(statements) -> set[str]:
    return {str(subject) for subject, _, _ in statements}


def test_an_entity_after_one_the_editable_file_defines_is_still_taken(merged):
    taxonomy, context = merged
    assert (
        taxonomy.context_source[BASE + "Fresh"] == context
    )  # "Both" comes first and is already known
    assert BASE + "Both" not in taxonomy.context_source


def test_what_a_context_file_says_about_an_editable_entity_is_recorded_under_that_file(merged):
    taxonomy, context = merged
    assert BASE + "Main" in _subjects(taxonomy.context_statements[context])


def test_the_prefixes_of_a_context_file_are_taken_over(merged):
    taxonomy, _ = merged
    assert taxonomy.namespace_bindings["extra"] == EXTRA


def test_an_unmodelled_triple_is_kept_as_residue_of_the_file_that_said_it(merged):
    taxonomy, context = merged
    assert _subjects(taxonomy.context_residue[context]) == {BASE + "Loose"}


def test_a_triple_the_editable_file_says_too_is_not_credited_to_the_context_file(merged):
    taxonomy, context = merged
    assert BASE + "Loose2" not in _subjects(taxonomy.context_residue[context])


def test_merging_one_file_straight_reads_it_when_it_was_not_parsed_beforehand(tmp_path):
    from rdflib import Graph

    main, context = tmp_path / "editable.ttl", tmp_path / "theirs.ttl"
    main.write_text(EDITABLE_SIDE, encoding=TEXT)
    context.write_text(CONTEXT_SIDE, encoding=TEXT)
    taxonomy = store.load(main)
    _load_save._merge_context(taxonomy, context, frozenset(), Graph())
    assert taxonomy.context_files == [context]
    assert BASE + "Fresh" in taxonomy.context_source
