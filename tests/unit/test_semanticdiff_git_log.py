"""Unit tests for the git adapter — the only modules that shell out to git."""

from __future__ import annotations

import pytest

from semanticdiff.git_log import (
    UnknownRevisionError,
    raw_diff,
    repo_root,
    tags_by_commit,
    walk,
)
from semanticdiff.loader import UnreadableRevisionError, graph_at_rev
from tests._ontology_repo import ONTOLOGY, RepoBuilder

CLASS_A = "ex:A a owl:Class ."
CLASS_AB = "ex:A a owl:Class . ex:B a owl:Class ."
CLASS_ABC = "ex:A a owl:Class . ex:B a owl:Class . ex:C a owl:Class ."
HEAD = "HEAD"


# ── walking the log ───────────────────────────────────────────────────────────


def test_walk_lists_commits_touching_the_path(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")
    ontology_repo.tag("v0.1")
    ontology_repo.commit(ttl=CLASS_AB, message="second")
    ontology_repo.commit(ttl=CLASS_ABC, message="third")
    ontology_repo.tag("v0.2")

    commits = walk(ontology_repo.path, "v0.1..v0.2", ONTOLOGY)

    assert [c.subject for c in commits] == ["second", "third"]


def test_walk_skips_commits_not_touching_the_path(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="ontology")
    ontology_repo.commit(files={"README.md": "hello"}, message="readme only")

    assert [c.subject for c in walk(ontology_repo.path, HEAD, ONTOLOGY)] == ["ontology"]


def test_walk_captures_author_date_and_subject(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="add class A")

    commit = walk(ontology_repo.path, HEAD, ONTOLOGY)[0]

    assert commit.author == "Ada Lovelace"
    assert commit.subject == "add class A"
    assert commit.date.startswith("20")
    assert commit.sha.startswith(commit.short_sha)


def test_walk_orders_commits_oldest_first(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="one")
    ontology_repo.commit(ttl=CLASS_AB, message="two")
    ontology_repo.commit(ttl=CLASS_ABC, message="three")

    commits = walk(ontology_repo.path, HEAD, ONTOLOGY)

    assert [c.subject for c in commits] == ["one", "two", "three"]


def test_walk_between_tags_is_exclusive_of_the_base_tag(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="base")
    ontology_repo.tag("v0.1")
    ontology_repo.commit(ttl=CLASS_AB, message="after")
    ontology_repo.tag("v0.2")

    assert [c.subject for c in walk(ontology_repo.path, "v0.1..v0.2", ONTOLOGY)] == ["after"]


def test_non_rdf_files_counted_per_commit(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(
        ttl=CLASS_A,
        files={"README.md": "hello", "notes.txt": "notes"},
        message="mixed commit",
    )

    assert walk(ontology_repo.path, HEAD, ONTOLOGY)[0].other_files == 2


def test_walk_on_an_empty_range_returns_nothing(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="only")
    ontology_repo.tag("v0.1")

    assert walk(ontology_repo.path, "v0.1..v0.1", ONTOLOGY) == []


# ── error paths ───────────────────────────────────────────────────────────────


def test_unknown_revision_raises(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="only")

    with pytest.raises(UnknownRevisionError, match="v9.9"):
        walk(ontology_repo.path, "v9.9..HEAD", ONTOLOGY)


def test_path_absent_from_repo_raises(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(files={"README.md": "hello"}, message="no ontology here")

    with pytest.raises(FileNotFoundError, match=ONTOLOGY):
        walk(ontology_repo.path, HEAD, ONTOLOGY)


# ── reading a file at a revision ──────────────────────────────────────────────


def test_graph_at_rev_parses_the_tracked_turtle(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_AB, message="two classes")

    graph = graph_at_rev(ontology_repo.path, HEAD, ONTOLOGY)

    assert graph is not None
    assert len(graph) == 2


def test_graph_at_rev_returns_none_when_the_file_is_absent(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(files={"README.md": "hello"}, message="readme")

    assert graph_at_rev(ontology_repo.path, HEAD, ONTOLOGY) is None


def test_graph_at_rev_returns_none_before_the_first_commit(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")

    assert graph_at_rev(ontology_repo.path, "HEAD^", ONTOLOGY) is None


def test_unparseable_revision_raises(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(raw="this is not turtle {{{", message="broken")

    with pytest.raises(UnreadableRevisionError):
        graph_at_rev(ontology_repo.path, HEAD, ONTOLOGY)


# ── raw text, for the last layer of the drill-down ────────────────────────────


def test_raw_diff_returns_the_unified_hunk_for_the_path(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")
    sha = ontology_repo.commit(ttl=CLASS_AB, message="second")

    text = raw_diff(ontology_repo.path, sha, ONTOLOGY)

    assert "ex:B" in text
    assert text.startswith("diff --git")


def test_raw_diff_of_the_first_commit_shows_the_whole_file(ontology_repo: RepoBuilder) -> None:
    sha = ontology_repo.commit(ttl=CLASS_A, message="first")

    assert "ex:A" in raw_diff(ontology_repo.path, sha, ONTOLOGY)


# ── locating the repository, and its tags ─────────────────────────────────────


def test_repo_root_finds_the_repository_from_a_file_inside_it(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="only")

    assert repo_root(ontology_repo.path / ONTOLOGY) == ontology_repo.path


def test_repo_root_is_none_outside_a_repository(tmp_path) -> None:
    loose = tmp_path / "loose.ttl"
    loose.write_text("# not in git", encoding="utf-8")

    assert repo_root(loose) is None


def test_tags_are_reported_against_the_commit_they_name(ontology_repo: RepoBuilder) -> None:
    first = ontology_repo.commit(ttl=CLASS_A, message="first")
    ontology_repo.tag("v0.1")
    second = ontology_repo.commit(ttl=CLASS_AB, message="second")
    ontology_repo.tag("v0.2")

    tags = tags_by_commit(ontology_repo.path)

    assert tags[first] == ("v0.1",)
    assert tags[second] == ("v0.2",)


def test_a_commit_with_two_tags_reports_both(ontology_repo: RepoBuilder) -> None:
    sha = ontology_repo.commit(ttl=CLASS_A, message="only")
    ontology_repo.tag("v0.1")
    ontology_repo.tag("release-1")

    assert sorted(tags_by_commit(ontology_repo.path)[sha]) == ["release-1", "v0.1"]


def test_an_untagged_repository_reports_no_tags(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="only")

    assert tags_by_commit(ontology_repo.path) == {}
