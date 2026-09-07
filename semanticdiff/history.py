"""Orchestration: pair every commit in a range with its semantic change set."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph

from semanticdiff.changeset import compare
from semanticdiff.git_log import Commit, raw_diff, walk
from semanticdiff.loader import UnreadableRevisionError, graph_at_rev
from semanticdiff.vocabulary import ChangeSet


@dataclass(frozen=True)
class CommitChanges:
    """One commit and what it did to the vocabulary."""

    commit: Commit
    changes: ChangeSet
    unreadable: bool = False
    raw_text: str | None = None


def read_history(
    repo: Path, rev_range: str, path: str, *, with_text: bool = False
) -> list[CommitChanges]:
    """Every commit in `rev_range` touching `path`, oldest first, with its changes."""
    return [
        _entry(repo, commit, path, with_text=with_text) for commit in walk(repo, rev_range, path)
    ]


def _entry(repo: Path, commit: Commit, path: str, *, with_text: bool) -> CommitChanges:
    try:
        later = graph_at_rev(repo, commit.sha, path) or Graph()
    except UnreadableRevisionError:
        # One bad revision must not end the walk — flag it and keep going.
        return CommitChanges(commit=commit, changes=ChangeSet(()), unreadable=True)
    return CommitChanges(
        commit=commit,
        changes=compare(_parent(repo, commit.sha, path), later),
        raw_text=raw_diff(repo, commit.sha, path) if with_text else None,
    )


def _parent(repo: Path, sha: str, path: str) -> Graph:
    """The graph one commit earlier — empty at the first commit, or if it was broken."""
    try:
        return graph_at_rev(repo, f"{sha}^", path) or Graph()
    except UnreadableRevisionError:
        return Graph()
