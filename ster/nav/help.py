"""Keyboard shortcut reference displayed in the welcome overlay."""

from __future__ import annotations

# list[tuple[section_title, list[tuple[keys, description]]]]
SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Navigation",
        [
            ("↑ / ↓", "Move cursor"),
            ("→ / Enter", "Open detail"),
            ("← / Esc", "Go back"),
            ("/", "Search"),
        ],
    ),
    (
        "Actions",
        [
            ("a", "Add concept"),
            ("d", "Delete concept"),
            ("m", "Move concept"),
            ("r", "Rename label"),
            ("?", "Show this help"),
            ("q / Ctrl+C", "Quit"),
        ],
    ),
]
