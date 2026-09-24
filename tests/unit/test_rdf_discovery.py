"""Which RDF files ster offers when it starts in a folder.

One function answers it for every caller (the home screen and the commands
that need a file), so the folder search cannot drift between them again.
"""

from __future__ import annotations

from pathlib import Path

from ster.cli._discovery import discover_rdf_files, subfolder_rdf_files

SUFFIXES = (".ttl", ".rdf", ".jsonld", ".owl", ".n3", ".trig", ".nt")


def _touch(root: Path, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


# ── the top level: today's behaviour, unchanged ─────────────────────────────


def test_top_level_rdf_files_are_found_sorted(tmp_path) -> None:
    _touch(tmp_path, "b.ttl", "a.ttl", "notes.md")
    assert discover_rdf_files(tmp_path) == [tmp_path / "a.ttl", tmp_path / "b.ttl"]


def test_every_rdf_suffix_counts(tmp_path) -> None:
    _touch(tmp_path, *(f"f{suffix}" for suffix in SUFFIXES))
    assert {path.suffix for path in discover_rdf_files(tmp_path)} == set(SUFFIXES)


def test_subfolders_are_not_searched_by_default(tmp_path) -> None:
    _touch(tmp_path, "top.ttl", "vocab/inner.ttl")
    assert discover_rdf_files(tmp_path) == [tmp_path / "top.ttl"]


# ── one level down, when asked ──────────────────────────────────────────────


def test_files_one_level_down_are_found_when_asked(tmp_path) -> None:
    _touch(tmp_path, "top.ttl", "vocab/inner.ttl", "data/stores.owl")
    found = discover_rdf_files(tmp_path, include_subfolders=True)
    assert found == [
        tmp_path / "top.ttl",
        tmp_path / "data/stores.owl",
        tmp_path / "vocab/inner.ttl",
    ]


def test_two_levels_down_is_too_deep(tmp_path) -> None:
    _touch(tmp_path, "vocab/deeper/far.ttl")
    assert discover_rdf_files(tmp_path, include_subfolders=True) == []


def test_hidden_folders_node_modules_and_the_publish_tree_are_skipped(tmp_path) -> None:
    """ontology/ holds ster's own published copies — offering them would offer duplicates."""
    _touch(tmp_path, ".git/x.ttl", ".venv/y.ttl", "node_modules/z.ttl", "ontology/gear.ttl")
    assert discover_rdf_files(tmp_path, include_subfolders=True) == []


def test_subfolder_rdf_files_lists_only_the_ones_below(tmp_path) -> None:
    _touch(tmp_path, "top.ttl", "vocab/inner.ttl", "ontology/gear.ttl")
    assert subfolder_rdf_files(tmp_path) == [tmp_path / "vocab/inner.ttl"]


def test_a_missing_folder_has_no_files(tmp_path) -> None:
    assert discover_rdf_files(tmp_path / "nowhere", include_subfolders=True) == []


def test_a_file_is_shown_relative_to_where_ster_started(tmp_path, monkeypatch) -> None:
    from ster.cli._discovery import shown

    monkeypatch.chdir(tmp_path)
    assert shown(tmp_path / "vocab" / "gear.ttl") == "vocab/gear.ttl"
    assert shown(tmp_path / "gear.ttl") == "gear.ttl"


def test_a_typed_subfolder_path_picks_its_file(tmp_path, monkeypatch) -> None:
    from ster.cli._file_picker import _resolve_picker_name_choice

    monkeypatch.chdir(tmp_path)
    files = [tmp_path / "gear.ttl", tmp_path / "vocab" / "gear.ttl"]
    assert _resolve_picker_name_choice("vocab/gear.ttl", files) == tmp_path / "vocab" / "gear.ttl"
