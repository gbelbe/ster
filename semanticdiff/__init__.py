"""semanticdiff — read a git history of an RDF file as semantic change.

A git diff reports characters. This package reports the vocabulary: which
classes, properties and concepts were added, modified, renamed, deprecated or
removed in each commit, so the raw text only has to be opened when the summary
is not enough.

It deliberately depends on nothing from `ster` — an import contract enforces
that — so it can be extracted into its own distribution unchanged.
"""

from __future__ import annotations

from semanticdiff.changeset import compare
from semanticdiff.history import CommitChanges, read_history
from semanticdiff.vocabulary import Change, ChangeKind, ChangeSet, EntityKind

__all__ = [
    "Change",
    "ChangeKind",
    "ChangeSet",
    "CommitChanges",
    "EntityKind",
    "compare",
    "read_history",
]
