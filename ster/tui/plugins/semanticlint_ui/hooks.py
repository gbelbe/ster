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
