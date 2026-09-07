"""Terminal rendering — the three layers of the drill-down.

Layer 0 is the summary over a range, layer 1 the per-commit change list, layer 2
one entity's story. Layer 3, the raw hunk, is only ever printed on request:
the whole point is that the text is the escape hatch, not the default.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from semanticdiff.history import CommitChanges
from semanticdiff.render.rows import Row, summarise
from semanticdiff.vocabulary import Change, ChangeKind

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
    return "\n".join([_header(entry), *(_row_line(r) for r in summarise(hits))])


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
    return [_row_line(row) for row in summarise(entry.changes)]


def _row_line(row: Row) -> str:
    where = f"   ({row.of_class})" if row.counted and row.of_class else ""
    if row.counted:
        return f"{_INDENT}{_MARKERS[row.kind]}{row.name}{where}"
    detail = f"   {' \u00b7 '.join(row.detail)}" if row.detail else ""
    name = _row_name(row)
    return f"{_INDENT}{_MARKERS[row.kind]} {row.entity.value:<10} {name}{detail}"


def _row_name(row: Row) -> str:
    """The readable name, with the identifier beside it when they differ."""
    if row.kind is ChangeKind.RENAMED:
        return f"{row.previous} \u2192 {row.curie}"
    if row.curie and row.curie != row.name:
        return f"{row.name} ({row.curie})"
    return row.name


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
