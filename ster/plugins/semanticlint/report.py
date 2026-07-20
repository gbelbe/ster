"""Pure helpers that turn a flat list of lint issues into per-entity views.

An *issue* is the plain dict produced by :func:`runner.lint_overview`:
``{"severity", "check_id", "message", "subject"}``. These functions never import
semanticlint — they operate on those dicts, so the TUI can group / rank issues
without depending on the library.
"""

from __future__ import annotations

# Higher rank = more severe. Used to pick the worst issue affecting an entity.
SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}


def issues_by_subject(issues: list[dict]) -> dict[str, list[dict]]:
    """Group *issues* by their ``subject`` URI (dropping subject-less / global ones)."""
    grouped: dict[str, list[dict]] = {}
    for issue in issues:
        subject = issue.get("subject")
        if subject:
            grouped.setdefault(subject, []).append(issue)
    return grouped


def worst_severity(issues: list[dict]) -> str | None:
    """The most severe severity name among *issues*, or ``None`` when empty."""
    if not issues:
        return None
    return max(issues, key=lambda i: SEVERITY_RANK.get(i.get("severity", ""), -1))["severity"]


def worst_by_subject(issues: list[dict]) -> dict[str, str]:
    """Map each entity URI to the worst severity of the issues that name it."""
    return {uri: worst_severity(items) for uri, items in issues_by_subject(issues).items()}  # type: ignore[misc]


def issue_summary(issues: list[dict]) -> str | None:
    """A one-line count of the *error* and *warning* issues in *issues* — the red/orange
    ones — e.g. ``"⊘ 2 errors · ⚠ 1 warning"``. ``None`` when there are none (empty or
    info-only), matching the red/orange tree colouring. Used as a hover tooltip; the full
    (possibly long) list lives in the detail panel, reached by clicking the node."""
    parts: list[str] = []
    for severity, glyph in (("error", "⊘"), ("warning", "⚠")):
        n = sum(1 for i in issues if i.get("severity") == severity)
        if n:
            parts.append(f"{glyph} {n} {severity}{'s' if n != 1 else ''}")
    return " · ".join(parts) if parts else None
