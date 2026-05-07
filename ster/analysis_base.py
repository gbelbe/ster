"""Shared primitives for taxonomy_analysis and owl_analysis.

Both modules import from here. A single change here is reflected in both the
SKOS (SchemeAnalysis) and OWL (OntologyAnalysis) layers and — through the
shared field-builder helpers in logic.py — in every rendered detail panel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Severity ──────────────────────────────────────────────────────────────────

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

_SEVERITY_RANK: dict[str, int] = {
    SEVERITY_ERROR: 0,
    SEVERITY_WARNING: 1,
    SEVERITY_INFO: 2,
}

# ── Generic issue ─────────────────────────────────────────────────────────────


@dataclass
class Issue:
    """A single quality issue — shared by both SKOS and OWL analysis."""

    issue_key: str
    severity: str
    entity_uri: str | None  # concept / class / individual / property URI
    message: str
    extra: dict = field(default_factory=dict)


# ── Generic per-language property coverage ────────────────────────────────────


@dataclass
class Coverage:
    """Per-language completion rate for one property.

    Mirrors taxonomy_analysis.PropertyCompletion — both the SKOS and OWL
    layers produce Coverage objects that logic.py renders with the same
    _coverage_fields() helper.
    """

    property_key: str  # "pref_label" | "rdf_label" | …
    display_name: str  # shown in the UI
    total: int  # total entities in scope
    by_language: dict[str, int]  # lang → count that have this property


# ── Utilities ─────────────────────────────────────────────────────────────────


def pct(count: int, total: int) -> int:
    """Integer percentage, safe against zero total."""
    return int(count * 100 / total) if total else 0


def pct_bar(pct_val: int, width: int = 8) -> str:
    """Compact block progress-bar, e.g. '████░░░░'."""
    filled = round(pct_val * width / 100)
    return "█" * filled + "░" * (width - filled)
