"""Shared building blocks for the actionable "Health & Issues" section.

Reused by every per-entity presenter so the actionable gaps look and behave the
same across the overview, classes, properties, … See docs/architecture/detail-presenter.md.
"""

from __future__ import annotations

from ster.nav.logic import DetailField, _colored, _sep, _stat


def gap_row(key: str, label: str) -> DetailField:
    """A single actionable gap — always orange (it exists only when something's missing)."""
    return _colored(_stat(key, label, "—"), "orange")


def health_section(gaps: list[DetailField]) -> list[DetailField]:
    """Wrap *gaps* in a 'Health & Issues' section, or nothing when there are none."""
    return [_sep("Health & Issues"), *gaps] if gaps else []


def insert_after_identity(base: list[DetailField], extra: list[DetailField]) -> list[DetailField]:
    """Splice *extra* in just after the leading Identity section (before its next
    separator), so the entity's URI still heads the panel."""
    if not extra:
        return base
    nexts = [i for i, f in enumerate(base) if i and f.meta.get("type", "").startswith("separator")]
    idx = nexts[0] if nexts else len(base)
    return base[:idx] + extra + base[idx:]
