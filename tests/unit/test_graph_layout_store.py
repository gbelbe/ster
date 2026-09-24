"""The graph layout remembered in the project: .ster/graph-layout.json.

Positions used to live in the browser's localStorage, which is per origin —
and ster serves the graph on a new port each launch, so every restart started
from nothing. They now live in the project, committed with it.
"""

from __future__ import annotations

import json

import pytest

from ster import graph_layout
from ster.model import Label, OWLIndividual, RDFClass, Taxonomy

NS = "https://example.org/g#"
VIEW = graph_layout.ONTOLOGY_VIEW


def _uri(name: str) -> str:
    return NS + name


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project folder (not a git repo) holding one ontology file."""
    monkeypatch.setattr("ster.graph_layout._git_root", lambda cwd: None)
    source = tmp_path / "gear.ttl"
    source.write_text("", encoding="utf-8")
    return source


def _layout_file(source):
    return source.parent / ".ster" / "graph-layout.json"


def _taxonomy(*names: str) -> Taxonomy:
    t = Taxonomy()
    for name in names:
        t.owl_classes[_uri(name)] = RDFClass(uri=_uri(name), labels=[Label("en", name)])
    return t


# ── where and how it is stored ──────────────────────────────────────────────


def test_the_layout_lives_in_the_project_ster_folder(project) -> None:
    assert graph_layout.layout_path(project) == _layout_file(project)


def test_a_git_project_keeps_it_at_the_repository_root(tmp_path, monkeypatch) -> None:
    (tmp_path / "sub").mkdir()
    source = tmp_path / "sub" / "gear.ttl"
    monkeypatch.setattr("ster.graph_layout._git_root", lambda cwd: tmp_path)
    assert graph_layout.layout_path(source) == tmp_path / ".ster" / "graph-layout.json"


def test_positions_survive_a_round_trip(project) -> None:
    tax = _taxonomy("A", "B")
    graph_layout.save_positions(project, VIEW, {_uri("A"): (10.4, -20.6)}, tax)
    assert graph_layout.load_positions(project, VIEW, tax) == {_uri("A"): (10, -21)}


def test_the_file_is_one_node_per_line_sorted_with_whole_numbers(project) -> None:
    """Small, readable diffs — and a merge conflict is one line."""
    tax = _taxonomy("B", "A")
    graph_layout.save_positions(project, VIEW, {_uri("B"): (1.6, 2), _uri("A"): (3, 4)}, tax)
    lines = _layout_file(project).read_text().splitlines()
    node_lines = [line for line in lines if NS in line]
    assert node_lines == [f'    "{_uri("A")}": [3, 4],', f'    "{_uri("B")}": [2, 2]']
    json.loads(_layout_file(project).read_text())  # still valid JSON


# ── keeping it true to the model ────────────────────────────────────────────


def test_a_save_merges_rather_than_replaces(project) -> None:
    """Two tabs, or a partial save, must not erase each other's nodes."""
    tax = _taxonomy("A", "B")
    graph_layout.save_positions(project, VIEW, {_uri("A"): (1, 1)}, tax)
    graph_layout.save_positions(project, VIEW, {_uri("B"): (2, 2)}, tax)
    assert graph_layout.load_positions(project, VIEW, tax) == {_uri("A"): (1, 1), _uri("B"): (2, 2)}


def test_a_deleted_node_is_dropped_on_the_next_save(project) -> None:
    graph_layout.save_positions(
        project, VIEW, {_uri("A"): (1, 1), _uri("B"): (2, 2)}, _taxonomy("A", "B")
    )
    graph_layout.save_positions(project, VIEW, {_uri("A"): (5, 5)}, _taxonomy("A"))  # B deleted
    assert _uri("B") not in _layout_file(project).read_text()


def test_a_deleted_node_is_ignored_when_loading(project) -> None:
    graph_layout.save_positions(
        project, VIEW, {_uri("A"): (1, 1), _uri("B"): (2, 2)}, _taxonomy("A", "B")
    )
    assert graph_layout.load_positions(project, VIEW, _taxonomy("A")) == {_uri("A"): (1, 1)}


def test_a_node_only_hidden_keeps_its_position(project) -> None:
    """Collapsed individuals are not on screen, but they are still in the model."""
    tax = _taxonomy("Shop")
    tax.owl_individuals[_uri("s1")] = OWLIndividual(uri=_uri("s1"), types=[_uri("Shop")])
    graph_layout.save_positions(project, VIEW, {_uri("s1"): (7, 7)}, tax)
    graph_layout.save_positions(project, VIEW, {_uri("Shop"): (0, 0)}, tax)  # s1 not sent
    assert graph_layout.load_positions(project, VIEW, tax)[_uri("s1")] == (7, 7)


def test_a_rename_moves_the_position_to_the_new_uri(project) -> None:
    graph_layout.save_positions(project, VIEW, {_uri("A"): (4, 4)}, _taxonomy("A"))
    graph_layout.rename_nodes(project, {_uri("A"): _uri("Z")})
    assert graph_layout.load_positions(project, VIEW, _taxonomy("Z")) == {_uri("Z"): (4, 4)}


def test_a_rename_of_nodes_never_saved_changes_nothing(project) -> None:
    graph_layout.rename_nodes(project, {_uri("A"): _uri("Z")})
    assert not _layout_file(project).exists()


def test_forgetting_a_view_clears_it(project) -> None:
    tax = _taxonomy("A")
    graph_layout.save_positions(project, VIEW, {_uri("A"): (1, 1)}, tax)
    graph_layout.forget_positions(project, VIEW)
    assert graph_layout.load_positions(project, VIEW, tax) == {}


# ── never in the way ────────────────────────────────────────────────────────


def test_a_broken_file_reads_as_empty_and_is_rewritten(project) -> None:
    _layout_file(project).parent.mkdir()
    _layout_file(project).write_text("{ not json <<<<<<< HEAD", encoding="utf-8")
    tax = _taxonomy("A")
    assert graph_layout.load_positions(project, VIEW, tax) == {}
    graph_layout.save_positions(project, VIEW, {_uri("A"): (1, 1)}, tax)
    assert graph_layout.load_positions(project, VIEW, tax) == {_uri("A"): (1, 1)}


def test_entries_that_are_not_two_numbers_are_skipped(project) -> None:
    _layout_file(project).parent.mkdir()
    bad = {VIEW: {_uri("A"): [1, 2], _uri("B"): "oops", _uri("C"): [1]}}
    _layout_file(project).write_text(json.dumps(bad), encoding="utf-8")
    assert graph_layout.load_positions(project, VIEW, _taxonomy("A", "B", "C")) == {
        _uri("A"): (1, 2)
    }


def test_without_a_file_there_is_no_layout(project) -> None:
    assert graph_layout.load_positions(project, VIEW, _taxonomy("A")) == {}
    assert not _layout_file(project).exists()
