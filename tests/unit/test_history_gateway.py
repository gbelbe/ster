"""Unit tests for ster's gateway to semanticdiff.

`ster.history` is the only module in ster allowed to import semanticdiff, so a
change of engine touches one file. An import contract enforces it.
"""

from __future__ import annotations

from pathlib import Path

from ster.history import open_history
from tests._ontology_repo import ONTOLOGY, RepoBuilder

CLASS_A = "ex:A a owl:Class ."
CLASS_AB = "ex:A a owl:Class . ex:B a owl:Class ."


def test_a_file_outside_a_repository_has_no_history(tmp_path: Path) -> None:
    loose = tmp_path / "loose.ttl"
    loose.write_text("# not in git", encoding="utf-8")

    assert open_history(loose) is None


def test_rows_are_newest_first(ontology_repo: RepoBuilder) -> None:
    """A history list reads downwards from what just happened."""
    ontology_repo.commit(ttl=CLASS_A, message="older")
    ontology_repo.commit(ttl=CLASS_AB, message="newer")

    history = open_history(ontology_repo.path / ONTOLOGY)

    assert [r.subject for r in history.rows] == ["newer", "older"]


def test_a_row_carries_what_the_list_shows(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="add class A")

    row = open_history(ontology_repo.path / ONTOLOGY).rows[0]

    assert row.author == "Ada Lovelace"
    assert row.subject == "add class A"
    assert row.date.startswith("20")
    assert row.sha.startswith(row.short_sha)


def test_tags_are_carried_on_the_commit_they_mark(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")
    ontology_repo.tag("v0.1")
    ontology_repo.commit(ttl=CLASS_AB, message="second")

    history = open_history(ontology_repo.path / ONTOLOGY)
    by_subject = {r.subject: r.tags for r in history.rows}

    assert by_subject["first"] == ("v0.1",)
    assert by_subject["second"] == ()


def test_the_semantic_view_names_what_changed(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")
    ontology_repo.commit(ttl=CLASS_AB, message="second")

    history = open_history(ontology_repo.path / ONTOLOGY)

    assert "ex:B" in history.semantic(history.rows[0].sha)


def test_a_formatting_only_commit_says_so(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl='ex:A a owl:Class ; rdfs:label "A"@en .', message="first")
    ontology_repo.commit(ttl='ex:A rdfs:label "A"@en ; a owl:Class .', message="reformat")

    history = open_history(ontology_repo.path / ONTOLOGY)

    assert "pure formatting" in history.semantic(history.rows[0].sha).lower()


def test_the_raw_view_is_the_git_hunk(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")
    ontology_repo.commit(ttl=CLASS_AB, message="second")

    history = open_history(ontology_repo.path / ONTOLOGY)

    assert history.raw(history.rows[0].sha).startswith("diff --git")


def test_nothing_is_computed_until_a_commit_is_asked_for(ontology_repo: RepoBuilder) -> None:
    """Opening the screen must not diff every revision — that is ~1s each."""
    ontology_repo.commit(ttl=CLASS_A, message="first")
    ontology_repo.commit(ttl=CLASS_AB, message="second")

    history = open_history(ontology_repo.path / ONTOLOGY)

    assert history.computed == 0
    history.semantic(history.rows[0].sha)
    assert history.computed == 1


def test_a_commit_is_diffed_once_however_often_it_is_selected(
    ontology_repo: RepoBuilder,
) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")
    ontology_repo.commit(ttl=CLASS_AB, message="second")
    history = open_history(ontology_repo.path / ONTOLOGY)
    sha = history.rows[0].sha

    first = history.semantic(sha)
    again = history.semantic(sha)

    assert first == again
    assert history.computed == 1


def test_an_unreadable_revision_is_reported_rather_than_raising(
    ontology_repo: RepoBuilder,
) -> None:
    """Listing cannot know a revision does not parse without diffing it, which is
    the cost being deferred — so the panel says it, on selection."""
    ontology_repo.commit(ttl=CLASS_A, message="good")
    ontology_repo.commit(raw="not turtle {{{", message="broken")

    history = open_history(ontology_repo.path / ONTOLOGY)

    assert history.rows[0].subject == "broken"
    assert "unreadable" in history.semantic(history.rows[0].sha).lower()
