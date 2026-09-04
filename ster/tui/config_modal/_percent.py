"""Percent-string helpers for the Semantic Lint tab's coverage-threshold fields
(stored as 0.0-1.0, edited as a percent string)."""

from __future__ import annotations


def _pct_display(value: object) -> str:
    """A stored 0.0–1.0 coverage threshold as a percent string ('' when unset/invalid),
    e.g. ``1.0`` → ``"100"``, ``0.5`` → ``"50"``."""
    if value in (None, ""):
        return ""
    try:
        return f"{float(value) * 100:g}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""


def _pct_parse(raw: str) -> float | None:
    """Parse a percent field back to a 0.0–1.0 threshold (clamped); ``None`` when blank
    or non-numeric, so the caller keeps the stored value."""
    text = raw.strip().rstrip("%").strip()
    try:
        return max(0.0, min(1.0, float(text) / 100))
    except ValueError:
        return None
