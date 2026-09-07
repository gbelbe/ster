"""The change vocabulary — what semanticdiff can say about an edit.

The operation names follow the basic half of COnto-Diff (Hartung, Groß & Rahm):
insert / delete / update, plus the two derived operations worth the cost here —
a rename, and a deprecation. Complex operations (merge, split, subtree move) are
deliberately out of scope.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum


class EntityKind(str, Enum):
    """What sort of thing changed."""

    CLASS = "class"
    PROPERTY = "property"
    INDIVIDUAL = "individual"
    CONCEPT = "concept"
    ONTOLOGY = "ontology"
    OTHER = "other"


class ChangeKind(str, Enum):
    """What happened to it."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    RENAMED = "renamed"
    DEPRECATED = "deprecated"


@dataclass(frozen=True)
class Change:
    """One change operation on one entity.

    `uri` is the full URI and `curie` its prefixed form (falling back to the full
    URI when no prefix is bound), because the summary reads in CURIEs but the
    caller may address an entity either way.
    """

    kind: ChangeKind
    entity: EntityKind
    uri: str
    curie: str
    label: str | None = None
    label_lang: str | None = None
    previous_uri: str | None = None
    previous_curie: str | None = None
    detail: tuple[str, ...] = ()
    # For an individual, the class it instantiates, already resolved to the name
    # a reader should see (label when there is one, else the CURIE) by the same
    # rule as `display`. Carried on the change so a summary can count individuals
    # against their class without a second pass over the graph.
    of_class: str | None = None

    @property
    def display(self) -> str:
        """The name a human should see — the label when there is one."""
        return self.label or self.curie


@dataclass(frozen=True)
class ChangeSet:
    """The changes between two versions of a graph."""

    changes: tuple[Change, ...] = ()

    def __iter__(self) -> Iterator[Change]:
        return iter(self.changes)

    def __len__(self) -> int:
        return len(self.changes)

    def counts(self) -> Counter[ChangeKind]:
        """How many changes of each kind — the material for the summary line."""
        return Counter(change.kind for change in self.changes)

    def for_uri(self, uri: str) -> tuple[Change, ...]:
        """Changes touching `uri`, given either its full URI or its CURIE."""
        return tuple(
            change
            for change in self.changes
            if uri in (change.uri, change.curie, change.previous_uri, change.previous_curie)
        )
