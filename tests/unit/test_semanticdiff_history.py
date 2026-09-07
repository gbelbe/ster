"""Unit tests for the history orchestration — git walk paired with graph compare."""

from __future__ import annotations

from semanticdiff.history import read_history
from semanticdiff.vocabulary import ChangeKind
from tests._ontology_repo import ONTOLOGY, RepoBuilder

CLASS_A = "ex:A a owl:Class ."
CLASS_AB = "ex:A a owl:Class . ex:B a owl:Class ."
BROKEN = "not turtle at all {{{"
HEAD = "HEAD"


def test_first_commit_reports_every_entity_as_added(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_AB, message="initial ontology")

    history = read_history(ontology_repo.path, HEAD, ONTOLOGY)

    assert len(history) == 1
    assert {c.curie for c in history[0].changes} == {"ex:A", "ex:B"}
    assert all(c.kind is ChangeKind.ADDED for c in history[0].changes)


def test_each_commit_is_compared_against_its_parent(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")
    ontology_repo.commit(ttl=CLASS_AB, message="second")

    history = read_history(ontology_repo.path, HEAD, ONTOLOGY)

    assert [c.curie for c in history[1].changes] == ["ex:B"]


def test_a_reformatting_commit_reports_an_empty_changeset(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl='ex:A a owl:Class ; rdfs:label "A"@en .', message="first")
    ontology_repo.commit(ttl='ex:A rdfs:label "A"@en ; a owl:Class .', message="reformat")

    history = read_history(ontology_repo.path, HEAD, ONTOLOGY)

    assert len(history) == 2
    assert len(history[1].changes) == 0


def test_unreadable_revision_is_marked_and_the_walk_continues(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="good one")
    ontology_repo.commit(raw=BROKEN, message="broken one")
    ontology_repo.commit(ttl=CLASS_AB, message="good two")

    history = read_history(ontology_repo.path, HEAD, ONTOLOGY)

    assert [entry.commit.subject for entry in history] == ["good one", "broken one", "good two"]
    assert history[1].unreadable is True
    assert history[2].unreadable is False


def test_a_commit_following_a_broken_one_reports_against_the_broken_parent(
    ontology_repo: RepoBuilder,
) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="good one")
    ontology_repo.commit(raw=BROKEN, message="broken one")
    ontology_repo.commit(ttl=CLASS_AB, message="good two")

    history = read_history(ontology_repo.path, HEAD, ONTOLOGY)

    assert {c.curie for c in history[2].changes} == {"ex:A", "ex:B"}
    assert history[2].unreadable is False


def test_raw_text_is_omitted_by_default(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")

    assert read_history(ontology_repo.path, HEAD, ONTOLOGY)[0].raw_text is None


def test_raw_text_is_loaded_when_requested(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")

    history = read_history(ontology_repo.path, HEAD, ONTOLOGY, with_text=True)

    assert history[0].raw_text is not None
    assert "ex:A" in history[0].raw_text


def test_non_rdf_file_count_is_carried_through(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(
        ttl=CLASS_A,
        files={"README.md": "hi", "notes.txt": "n"},
        message="mixed",
    )

    assert read_history(ontology_repo.path, HEAD, ONTOLOGY)[0].commit.other_files == 2
