"""Shared building blocks for the actionable "Health & Issues" section.

Reused by every per-entity presenter so the actionable gaps look and behave the
same across the overview, classes, properties, … See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.nav.logic import DetailField, _colored, _sep, _stat


def gap_row(key: str, label: str, count: int) -> DetailField:
    """One Health checklist row: a *count* of affected items, green at 0 else orange.

    Always rendered (even at 0) so the same categories appear on every entity — a
    stable checklist rather than rows that come and go."""
    return _colored(_stat(key, label, str(count)), "green" if count == 0 else "orange")


def health_section(rows: list[DetailField]) -> list[DetailField]:
    """Wrap the checklist *rows* in a 'Health & Issues' section (nothing if empty)."""
    return [_sep("Health & Issues"), *rows] if rows else []


def insert_after_identity(base: list[DetailField], extra: list[DetailField]) -> list[DetailField]:
    """Splice *extra* in just after the leading Identity section (before its next
    separator), so the entity's URI still heads the panel."""
    if not extra:
        return base
    nexts = [i for i, f in enumerate(base) if i and f.meta.get("type", "").startswith("separator")]
    idx = nexts[0] if nexts else len(base)
    return base[:idx] + extra + base[idx:]
