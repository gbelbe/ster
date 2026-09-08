"""ster's gateway to semanticdiff — the only module here that imports it.

An import contract keeps it that way, so a change of diff engine touches one
file. Nothing above this module sees a semanticdiff type: the screen gets rows
of plain strings and two rendered blocks of text.

Diffing a revision costs about a second on a large ontology — two parses and a
canonicalisation — so nothing is computed until a commit is selected, and each
is computed once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rdflib import Graph

from semanticdiff.git_log import (
    Commit,
    UnknownRevisionError,
    raw_diff,
    repo_root,
    tags_by_commit,
    walk,
)
from semanticdiff.history import CommitChanges, read_history
from semanticdiff.render.rows import Row, summarise
from semanticdiff.render.text import render_commits
from semanticdiff.vocabulary import ChangeKind, EntityKind

# Re-exported so a front end can name a change kind without importing the engine:
# the import contract allows semanticdiff in this module and nowhere else.
__all__ = ["ChangeKind", "EntityKind", "FileHistory", "HistoryRow", "Row", "open_history"]


@dataclass(frozen=True)
class HistoryRow:
    """One line of the history list."""

    sha: str
    short_sha: str
    author: str
    date: str
    subject: str
    tags: tuple[str, ...] = ()

    # Deliberately no `unreadable` flag: whether a revision parses is only known
    # by diffing it, which is the second this class exists to defer. The semantic
    # panel says so when the commit is selected.

    @property
    def day(self) -> str:
        """The date alone, for places with room for nothing else."""
        return self.date[:10]

    @property
    def when(self) -> str:
        """Date and time, minutes included.

        A day is not enough to tell two commits apart when several land on one
        afternoon, which is exactly when a reader is trying to work out what
        happened in which order.
        """
        return self.date[:16].replace("T", " ")


@dataclass
class FileHistory:
    """The commits touching one tracked file, and the views of each on demand."""

    repo: Path
    path: str
    rows: list[HistoryRow]
    _entries: dict[str, CommitChanges] = field(default_factory=dict, repr=False)
    # Parsed revisions, kept across selections: stepping from one commit to the
    # next re-reads the revision they share, which is the larger half of the cost.
    _graphs: dict[str, Graph] = field(default_factory=dict, repr=False)
    _semantic: dict[str, str] = field(default_factory=dict, repr=False)
    _rows: dict[str, list[Row]] = field(default_factory=dict, repr=False)
    _raw: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def computed(self) -> int:
        """How many revisions have actually been diffed — asserted by the tests."""
        return len(self._entries)

    def changes(self, sha: str) -> list[Row]:
        """The change rows for one commit, diffed on first ask and kept.

        Rows rather than text: the screen colours each kind and shows the
        readable name apart from the identifier, which formatted text cannot be
        taken apart again to do.
        """
        if sha not in self._rows:
            self._rows[sha] = summarise(self._entry(sha).changes)
        return self._rows[sha]

    def is_ready(self, sha: str) -> bool:
        """Whether this commit has already been diffed, so selecting it is instant."""
        return sha in self._rows

    def is_unreadable(self, sha: str) -> bool:
        """Whether the ontology fails to parse at this revision."""
        return self._entry(sha).unreadable

    def semantic(self, sha: str) -> str:
        """The change list as plain text — the same rows, rendered."""
        if sha not in self._semantic:
            self._semantic[sha] = render_commits([self._entry(sha)])
        return self._semantic[sha]

    def raw(self, sha: str) -> str:
        """The unified diff hunk — the layer below the summary."""
        if sha not in self._raw:
            self._raw[sha] = raw_diff(self.repo, sha, self.path)
        return self._raw[sha]

    def _entry(self, sha: str) -> CommitChanges:
        if sha not in self._entries:
            self._entries[sha] = self._read_one(sha)
        return self._entries[sha]

    def _read_one(self, sha: str) -> CommitChanges:
        """Just this commit. The root has no parent, so `sha~1..sha` does not
        resolve for it — and a range of `sha` alone is exactly that one commit,
        since nothing precedes it."""
        try:
            return read_history(self.repo, f"{sha}~1..{sha}", self.path, graphs=self._graphs)[0]
        except UnknownRevisionError:
            return read_history(self.repo, sha, self.path, graphs=self._graphs)[0]


def open_history(path: Path) -> FileHistory | None:
    """The history of `path`, or None when it is not inside a git repository."""
    repo = repo_root(path)
    if repo is None:
        return None
    relative = str(path.resolve().relative_to(repo.resolve()))
    tags = tags_by_commit(repo)
    commits = walk(repo, "HEAD", relative)
    return FileHistory(
        repo=repo,
        path=relative,
        rows=[_row(c, tags) for c in reversed(commits)],
    )


def _row(commit: Commit, tags: dict[str, tuple[str, ...]]) -> HistoryRow:
    return HistoryRow(
        sha=commit.sha,
        short_sha=commit.short_sha,
        author=commit.author,
        date=commit.date,
        subject=commit.subject,
        tags=tags.get(commit.sha, ()),
    )
