"""The branded ``ster`` Textual theme + a quick-switch shortlist.

A custom :class:`~textual.theme.Theme` (registered in :mod:`ster.tui.app`) gives the
New-TUI its own identity. It lives *alongside* every built-in Textual theme — the
command palette (``/`` → "Change theme") switches between them with a live preview,
and ``d`` cycles a curated shortlist. Colours are referenced everywhere as semantic
variables (``$primary`` / ``$secondary`` / ``$panel`` / ``$boost`` …) so swapping the
theme restyles the whole app.
"""

from __future__ import annotations

from textual.theme import Theme

# A calm, ontology-editor palette: teal primary, amber secondary, soft-purple accent,
# coral error, slate panels on a near-black ground. Textual derives the lighten/darken/
# muted/boost variants automatically.
STER_THEME = Theme(
    name="ster",
    primary="#3BC9B0",  # teal — focus, headers, selected
    secondary="#FFC857",  # amber — cursors, hover, accents
    accent="#C792EA",  # soft purple — secondary highlights
    warning="#FFC857",
    error="#FF6B6B",  # coral — danger / delete
    success="#3BC9B0",
    foreground="#E6EDF3",
    background="#0E1116",  # near-black
    surface="#151B23",
    panel="#2A3340",  # slate — unfocused borders, scrollbars
    dark=True,
)

# One-key (``d``) cycle through a curated shortlist; the full set is in the palette.
# Starts on the default (solarized-light) so the first press lands on the branded theme.
THEME_CYCLE = ["solarized-light", "ster", "solarized-dark", "nord", "gruvbox"]
