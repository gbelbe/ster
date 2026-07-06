"""Pure presentation hooks for the semanticlint TUI integration.

No Textual / semanticlint imports — these map a severity name to how it should look,
so they are trivially unit-testable and reused across the tree, detail panel and
quality block.
"""

from __future__ import annotations

# Worst-severity → tree-icon Rich colour. error → red, warning → orange, anything
# else (info / no issue) → green, matching the user's red/orange/green rule.
_ICON_COLOUR = {"error": "red", "warning": "dark_orange"}

# Severity → (glyph, Rich colour) for the detail panel's per-issue annotation.
_DETAIL_STYLE = {
    "error": ("⊘", "red"),
    "warning": ("⚠", "dark_orange"),
    "info": ("ⓘ", "blue"),
}


def icon_colour(worst_severity: str | None) -> str:
    """Rich colour for an entity's tree icon given the worst severity affecting it."""
    return _ICON_COLOUR.get(worst_severity or "", "green")


def detail_glyph(severity: str) -> str:
    """A coloured Rich-markup glyph for one issue of *severity* (detail panel)."""
    glyph, colour = _DETAIL_STYLE.get(severity, ("•", "green"))
    return f"[{colour}]{glyph}[/{colour}]"


# Severity → whole-row quality colour (the detail panel's q-red/orange/green classes).
_ROW_COLOUR = {"error": "red", "warning": "orange", "info": "green"}
_ROW_GLYPH = {"error": "⊘", "warning": "⚠", "info": "ⓘ"}


def issue_fields(issues: list[dict]) -> list:
    """A 'Quality issues' section (list of :class:`DetailField`) for one entity — one
    coloured row per lint issue (glyph + check id, message as the value). Empty when
    there are no issues."""
    from ster.nav.logic import DetailField, _colored, _sep, _stat

    if not issues:
        return []
    fields: list[DetailField] = [_sep("Quality issues")]
    for issue in issues:
        severity = issue.get("severity", "info")
        display = f"{_ROW_GLYPH.get(severity, '•')} {issue.get('check_id', '')}"
        key = f"lint:{issue.get('check_id', '')}:{issue.get('subject', '')}"
        row = _stat(key, display, issue.get("message", ""))
        fields.append(_colored(row, _ROW_COLOUR.get(severity, "green")))
    return fields


def quality_summary_fields(counts: dict, *, title: str) -> list:
    """A quality summary section: one coloured count row per severity. When everything
    is clean a single green 'no issues' row is shown instead."""
    from ster.nav.logic import DetailField, _colored, _sep, _stat

    fields: list[DetailField] = [_sep(title)]
    if not sum(counts.values()):
        fields.append(_colored(_stat("stq:clean", "✓ no issues", ""), "green"))
        return fields
    for severity, colour in (("error", "red"), ("warning", "orange"), ("info", "green")):
        count = counts.get(severity, 0)
        row = _stat(f"stq:{severity}", f"{severity.capitalize()}s", str(count))
        fields.append(_colored(row, colour if count else "green"))
    return fields
