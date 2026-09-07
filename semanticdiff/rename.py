"""Rename detection.

A URI change under an unchanged label is a rename, not a delete plus an add.
Left undetected it is the ugliest false signal a graph diff produces, so it is
the one derived operation worth paying for here.

The rule is deliberately conservative: a removal and an addition pair only when
they agree on entity kind, label text *and* language tag, and when that key is
unique on both sides. Anything ambiguous stays reported as a delete and an add,
because a wrong pairing is worse than a missed one.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from semanticdiff.vocabulary import Change, ChangeKind, ChangeSet

_Key = tuple[object, str, str | None]


def detect_renames(changes: ChangeSet) -> ChangeSet:
    """Fold matching removal/addition pairs into single rename operations."""
    removed = _by_label(changes, ChangeKind.REMOVED)
    added = _by_label(changes, ChangeKind.ADDED)
    pairs = {
        key: (removed[key][0], added[key][0])
        for key in removed.keys() & added.keys()
        if len(removed[key]) == 1 and len(added[key]) == 1
    }
    if not pairs:
        return changes
    return ChangeSet(tuple(_rewrite(changes, pairs)))


def _by_label(changes: ChangeSet, kind: ChangeKind) -> dict[_Key, list[Change]]:
    grouped: dict[_Key, list[Change]] = defaultdict(list)
    for change in changes:
        if change.kind is kind and change.label is not None:
            grouped[_key(change)].append(change)
    return grouped


def _key(change: Change) -> _Key:
    assert change.label is not None
    return (change.entity, change.label, change.label_lang)


def _rewrite(changes: ChangeSet, pairs: dict[_Key, tuple[Change, Change]]) -> Iterator[Change]:
    """Emit the changes with each paired removal/addition replaced by one rename."""
    consumed = {change for pair in pairs.values() for change in pair}
    emitted: set[_Key] = set()
    for change in changes:
        if change not in consumed:
            yield change
            continue
        key = _key(change)
        if key in emitted:
            continue
        emitted.add(key)
        yield _renamed(*pairs[key])


def _renamed(old: Change, new: Change) -> Change:
    return Change(
        kind=ChangeKind.RENAMED,
        entity=new.entity,
        uri=new.uri,
        curie=new.curie,
        label=new.label,
        label_lang=new.label_lang,
        previous_uri=old.uri,
        previous_curie=old.curie,
        detail=new.detail,
    )
