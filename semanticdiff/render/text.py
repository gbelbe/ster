"""Terminal rendering — the three layers of the drill-down.

Layer 0 is the summary over a range, layer 1 the per-commit change list, layer 2
one entity's story. Layer 3, the raw hunk, is only ever printed on request:
the whole point is that the text is the escape hatch, not the default.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

from semanticdiff.history import CommitChanges
from semanticdiff.vocabulary import Change, ChangeKind, EntityKind

_MARKERS = {
    ChangeKind.ADDED: "+",
    ChangeKind.REMOVED: "-",
    ChangeKind.MODIFIED: "~",
    ChangeKind.RENAMED: "»",
    ChangeKind.DEPRECATED: "⊘",
}

_ORDER = (
    ChangeKind.ADDED,
    ChangeKind.MODIFIED,
    ChangeKind.RENAMED,
    ChangeKind.DEPRECATED,
    ChangeKind.REMOVED,
)

_NO_COMMITS = "no commits touching this file in this range"
_INDENT = "    "

# Above this many individuals of one class, in one commit, the report counts them
# instead of naming them. On a real ontology individuals are the overwhelming
# majority of every commit — 9 301 of 9 414 lines on adeo-retail-geography, 98.8%
# — and they bury the class and property changes the reader came for. Below it
# nothing changes: three names say more than the number three.
_TALLY_ABOVE = 5

# A rename or a deprecation is rare and is the most interesting thing that can
# happen to an individual, so it is named however many of its siblings are
# counted. "city-ro-sibiu → region-ro-sibiu" is the whole point of the report.
_NEVER_TALLIED = (ChangeKind.RENAMED, ChangeKind.DEPRECATED)


def render_summary(history: Sequence[CommitChanges], rev_range: str) -> str:
    """Layer 0 — the headline: how many commits, and how much moved."""
    if not history:
        return f"{rev_range} — {_NO_COMMITS}"
    counts: Counter[ChangeKind] = Counter()
    for entry in history:
        counts.update(entry.changes.counts())
    tallies = [f"{counts[kind]} {kind.value}" for kind in _ORDER if counts[kind]]
    headline = f"{rev_range} — {_plural(len(history), 'commit')}"
    return f"{headline}\n{'  '.join(tallies)}" if tallies else headline


def render_commits(history: Sequence[CommitChanges], *, show_text: bool = False) -> str:
    """Layer 1 — every commit, and what it did to the vocabulary."""
    if not history:
        return _NO_COMMITS
    return "\n\n".join(_block(entry, show_text=show_text) for entry in history)


def render_entity(history: Sequence[CommitChanges], uri: str) -> str:
    """Layer 2 — only the commits that touched one entity."""
    blocks = [
        _entity_block(entry, hits) for entry in history if (hits := entry.changes.for_uri(uri))
    ]
    if not blocks:
        return f"{uri} never changed in this range"
    return "\n\n".join(blocks)


def _block(entry: CommitChanges, *, show_text: bool) -> str:
    lines = [_header(entry), *_change_lines(entry)]
    if entry.commit.other_files:
        lines.append(f"{_INDENT}({_plural(entry.commit.other_files, 'non-RDF file')} changed)")
    if show_text and entry.raw_text:
        lines.append(entry.raw_text)
    return "\n".join(lines)


def _entity_block(entry: CommitChanges, hits: tuple[Change, ...]) -> str:
    return "\n".join([_header(entry), *(_change_line(hit) for hit in hits)])


def _header(entry: CommitChanges) -> str:
    commit = entry.commit
    return f"● {commit.short_sha}  {commit.subject}  — {commit.author}  {commit.date[:10]}"


def _change_lines(entry: CommitChanges) -> list[str]:
    if entry.unreadable:
        return [f"{_INDENT}(ontology unreadable at this revision)"]
    if not entry.changes:
        # The walk only lists commits that touched the file, so an empty
        # changeset means the bytes moved and the graph did not: the file was
        # re-spelled, not edited. Say that outright — "no semantic change" alone
        # reads like the tool gave up, when it is in fact the answer.
        return [f"{_INDENT}(no semantic change \u2014 pure formatting)"]
    named, tallied = _partition(entry.changes)
    return [_change_line(change) for change in named] + _tally_lines(tallied)


def _tally_key(change: Change) -> tuple[ChangeKind, str | None] | None:
    """The bucket a change is counted in, or None when it must be named."""
    if change.entity is not EntityKind.INDIVIDUAL or change.kind in _NEVER_TALLIED:
        return None
    return (change.kind, change.of_class)


def _partition(changes: Iterable[Change]) -> tuple[list[Change], dict]:
    """Split into the changes to name and the buckets big enough to count."""
    buckets: dict[tuple[ChangeKind, str | None], list[Change]] = defaultdict(list)
    named: list[Change] = []
    for change in changes:
        key = _tally_key(change)
        if key is None:
            named.append(change)
        else:
            buckets[key].append(change)
    counted = {key: group for key, group in buckets.items() if len(group) > _TALLY_ABOVE}
    for key, group in buckets.items():
        if key not in counted:
            named.extend(group)
    return named, counted


def _tally_lines(counted: dict[tuple[ChangeKind, str | None], list[Change]]) -> list[str]:
    lines = []
    for (kind, of_class), group in sorted(counted.items(), key=lambda kv: str(kv[0])):
        where = f"   ({of_class})" if of_class else ""
        lines.append(f"{_INDENT}{_MARKERS[kind]}{len(group)} individuals{where}")
    return lines


def _change_line(change: Change) -> str:
    detail = f"   {' · '.join(change.detail)}" if change.detail else ""
    marker = _MARKERS[change.kind]
    return f"{_INDENT}{marker} {change.entity.value:<10} {_name(change)}{detail}"


def _name(change: Change) -> str:
    if change.kind is ChangeKind.RENAMED:
        return f"{change.previous_curie} → {change.curie}"
    return f"{change.label} ({change.curie})" if change.label else change.curie


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
