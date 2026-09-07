"""One commit's changes as rows, before anything decides how to print them.

The tally — bulk individuals counted against their class — used to live inside
the text renderer, which meant a second front end had to either re-derive it or
parse text back. It belongs here: the text renderer formats these rows, and so
can anything else.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from semanticdiff.vocabulary import Change, ChangeKind, EntityKind

# Above this many individuals of one class, in one commit, they are counted
# rather than named. On a real ontology individuals are ~99% of every commit and
# bury the class and property changes the reader came for. Below it nothing
# changes: three names say more than the number three.
TALLY_ABOVE = 5

# A rename or a deprecation is rare and is the most interesting thing that can
# happen to an individual, so it is named however many of its siblings counted.
_NEVER_TALLIED = (ChangeKind.RENAMED, ChangeKind.DEPRECATED)


@dataclass(frozen=True)
class Row:
    """A line of the change list: either one named entity, or a count of many."""

    kind: ChangeKind
    entity: EntityKind
    name: str
    # The identifier, kept beside the readable name rather than folded into it,
    # so a front end can show them apart — "Vehicle" large, "ex:Vehicle" dim.
    curie: str | None = None
    detail: tuple[str, ...] = ()
    previous: str | None = None
    count: int = 1
    of_class: str | None = None

    @property
    def counted(self) -> bool:
        """Whether this row stands for many entities rather than one."""
        return self.count > 1


def summarise(changes: Iterable[Change]) -> list[Row]:
    """The rows for one commit: entities worth naming, then the counts."""
    named, counted = _partition(changes)
    return [_named_row(c) for c in named] + _counted_rows(counted)


def _partition(changes: Iterable[Change]) -> tuple[list[Change], dict]:
    buckets: dict[tuple[ChangeKind, str | None], list[Change]] = defaultdict(list)
    named: list[Change] = []
    for change in changes:
        key = _tally_key(change)
        if key is None:
            named.append(change)
        else:
            buckets[key].append(change)
    counted = {k: g for k, g in buckets.items() if len(g) > TALLY_ABOVE}
    for key, group in buckets.items():
        if key not in counted:
            named.extend(group)
    return named, counted


def _tally_key(change: Change) -> tuple[ChangeKind, str | None] | None:
    """The bucket a change is counted in, or None when it must be named."""
    if change.entity is not EntityKind.INDIVIDUAL or change.kind in _NEVER_TALLIED:
        return None
    return (change.kind, change.of_class)


def _named_row(change: Change) -> Row:
    return Row(
        kind=change.kind,
        entity=change.entity,
        name=change.display,
        curie=change.curie,
        detail=change.detail,
        previous=change.previous_curie,
    )


def _counted_rows(counted: dict[tuple[ChangeKind, str | None], list[Change]]) -> list[Row]:
    return [
        Row(
            kind=kind,
            entity=EntityKind.INDIVIDUAL,
            name=f"{len(group)} individuals",
            count=len(group),
            of_class=of_class,
        )
        for (kind, of_class), group in sorted(counted.items(), key=lambda kv: str(kv[0]))
    ]
