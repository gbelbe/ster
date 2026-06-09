"""Validation report + adapter for the service's quality gate.

The gate is *delta-based*: it blocks a command only on issues the change
*introduces*, never on pre-existing problems elsewhere in the file. This keeps
the core's behaviour identical to the legacy curses save (which never validated)
for unrelated state, while still refusing to persist a change that breaks the
ontology — the "quality check on the TTL changes" requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..validator import SkosValidator, ValidationIssue


def _key(issue: ValidationIssue) -> tuple[str, str, str, str | None]:
    """Stable identity for an issue, so before/after sets can be diffed."""
    return (issue.severity, issue.code, issue.uri, issue.related_uri)


@dataclass(frozen=True)
class ValidationReport:
    """The issues a command introduced (the delta), split by severity."""

    issues: tuple[ValidationIssue, ...] = ()

    @classmethod
    def delta(
        cls, before: tuple[ValidationIssue, ...], after: tuple[ValidationIssue, ...]
    ) -> ValidationReport:
        """Issues present *after* a change that were not present *before* it."""
        seen = {_key(i) for i in before}
        return cls(tuple(i for i in after if _key(i) not in seen))

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

    def blocks(self) -> bool:
        """True when the change introduces an error-severity issue (block-on-error)."""
        return bool(self.errors)


class SkosValidatorAdapter:
    """Validator port over :class:`ster.validator.SkosValidator` (single taxonomy)."""

    def __init__(self) -> None:
        self._validator = SkosValidator()

    def check(self, taxonomy: object) -> tuple[ValidationIssue, ...]:
        from ..workspace import TaxonomyWorkspace

        ws = TaxonomyWorkspace()
        ws.taxonomies[Path("/in-memory")] = taxonomy  # type: ignore[assignment]
        return tuple(self._validator.validate(ws))
