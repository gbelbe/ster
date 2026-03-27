"""Help text for ster — used by the TUI welcome screen and the README."""
from __future__ import annotations

VERSION = "0.1.0"
AUTHOR  = "ster contributors"

# ──────────────────────────── structured help ─────────────────────────────────
# Each entry is either a section header (ALL CAPS string) or a (keys, desc) tuple.

SECTIONS: list[tuple[str, list[tuple[str, str] | str]]] = [
    ("NAVIGATION  (tree view)", [
        ("↑↓ / j·k",          "move up and down the tree"),
        ("→ / Enter",          "open concept detail  (or expand children)"),
        ("← / h",              "go back / go to parent"),
        ("g / G",              "jump to first / last concept"),
        ("Ctrl+D / Ctrl+U",    "half-page down / up"),
        ("Space",              "fold / unfold concept or scheme"),
        ("◉  (top row)",       "open taxonomy scheme settings"),
    ]),
    ("SEARCH  (tree view)", [
        ("/",                  "start a search  (regex supported)"),
        ("Tab / Shift+Tab",    "next / previous match while typing"),
        ("n / N",              "next / previous match after search"),
        ("Enter",              "open the currently matched concept"),
        ("Esc",                "clear search and highlights"),
    ]),
    ("CONCEPT DETAIL  (detail view)", [
        ("i / Enter",          "edit the selected field"),
        ("d",                  "delete the selected field value"),
        ("← / Esc",            "go back to tree"),
    ]),
    ("CONCEPT ACTIONS  (action rows in detail view)", [
        ("Enter  on  + Add narrower",   "create a child concept"),
        ("Enter  on  ↗ Link to broader","add an extra broader without moving"),
        ("m  or  Enter  on  ↷ Move",    "move concept to a different parent"),
        ("-  or  Enter  on  ⊘ Delete",  "delete concept (asks confirmation)"),
        ("b  or  Enter  on  ↗ Link",    "shortcut for 'add broader link'"),
    ]),
    ("EDIT MODE  (text input bar)", [
        ("Enter",              "save the value"),
        ("Esc",                "cancel without saving"),
        ("Ctrl+A / Ctrl+E",    "go to start / end of line"),
        ("Ctrl+W",             "delete word backward"),
        ("Ctrl+K",             "delete from cursor to end"),
        ("Alt+← / Alt+→",      "jump one word left / right"),
    ]),
    ("TAXONOMY SETTINGS  (◉ scheme row)", [
        ("Enter  on  display language",   "open language picker"),
        ("i / Enter  on  any field",      "edit title, description, creator …"),
        ("Enter  on  ➕ Add new scheme",  "create an additional ConceptScheme"),
    ]),
    ("GENERAL", [
        ("q / Esc",            "quit ster"),
        ("?",                  "show this help screen"),
    ]),
]


def welcome_lines(title: str = "", n_concepts: int = 0, lang: str = "en") -> list[str]:
    """Return the list of text lines shown in the TUI welcome/help overlay."""
    lines: list[str] = []

    if title:
        lines += [f"  {title}",
                  f"  {n_concepts} concept{'s' if n_concepts != 1 else ''}  ·  lang: {lang}",
                  ""]

    key_w = 26  # column width for the keys column

    for section_title, entries in SECTIONS:
        lines.append(f"  {section_title}")
        for entry in entries:
            keys, desc = entry
            lines.append(f"  {keys:<{key_w}}{desc}")
        lines.append("")

    lines.append("  Press any key to continue …")
    return lines


def readme_section() -> str:
    """Return a Markdown string suitable for embedding in the project README."""
    out: list[str] = ["## Keyboard shortcuts\n"]
    for section_title, entries in SECTIONS:
        out.append(f"### {section_title}\n")
        out.append("| Keys | Action |")
        out.append("|------|--------|")
        for entry in entries:
            keys, desc = entry
            out.append(f"| `{keys}` | {desc} |")
        out.append("")
    return "\n".join(out)
