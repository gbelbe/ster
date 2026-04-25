"""Curses drawing primitives — color constants, init_colors, and reusable renderers.

All functions are pure curses calls: they take a stdscr window and draw onto it.
No viewer state or business logic here.
"""

from __future__ import annotations

import curses
import re

from ..model import Taxonomy
from .logic import _UNATTACHED_INDS_URI, TreeLine

# ──────────────────────────── colors ─────────────────────────────────────────

_C_NAVIGABLE = 1  # cyan bold — has children
_C_SEL = 2  # white on blue — selected
_C_SEL_NAV = 3  # cyan on blue — selected + navigable
_C_DIM = 4  # dim — muted text (separators, read-only)
_C_FIELD_LABEL = 5  # green — editable field name
_C_FIELD_VAL = 6  # default bold — editable field value
_C_EDIT_BAR = 7  # white on green — edit input bar
_C_DETAIL_CURSOR = 8  # selected field in detail view
_C_SEARCH_MATCH = 9  # black on yellow — search match highlight
_C_SEARCH_BAR = 10  # white on magenta — search input bar
_C_TOP_CONCEPT = 11  # magenta bold — top concept row
_C_DIFF_ADD = 12  # green — added concept/field in diff view
_C_DIFF_DEL = 13  # red   — removed concept/field in diff view
_C_DIFF_CHG = 14  # yellow — modified concept in diff view
_C_HELP_SECTION = 15  # black on green — section header bars in help
_C_FILE_NODE = 16  # bold yellow — file-level root node in multi-file tree
_C_BROKEN_REF = 17  # red — broader/narrower pointing to unloaded URI
_C_BROKEN_MAP = 18  # magenta — mapping property pointing to unloaded URI
_C_MAPPING_NAV = 19  # yellow — existing cross-scheme mapping link
# Syntax-highlighting pairs for the SPARQL editor
_C_SH_KEYWORD = 20  # blue  — keywords (SELECT, WHERE, FILTER…)
_C_SH_VAR = 21  # cyan  — ?variables
_C_SH_URI = 22  # magenta — <URIs>
_C_SH_STRING = 23  # green — "string literals"
_C_SH_FUNCTION = 24  # yellow — built-in functions (COUNT, REGEX…)
_C_SH_NS = 25  # yellow — namespace prefixes (skos:, rdf:…)


def _init_colors() -> None:
    try:
        curses.use_default_colors()
        curses.init_pair(_C_NAVIGABLE, curses.COLOR_CYAN, -1)
        curses.init_pair(_C_SEL, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(_C_SEL_NAV, curses.COLOR_CYAN, curses.COLOR_BLUE)
        curses.init_pair(_C_DIM, -1, -1)  # terminal default
        curses.init_pair(_C_FIELD_LABEL, curses.COLOR_GREEN, -1)
        curses.init_pair(_C_FIELD_VAL, -1, -1)  # terminal default
        curses.init_pair(_C_EDIT_BAR, curses.COLOR_BLACK, curses.COLOR_GREEN)
        curses.init_pair(_C_DETAIL_CURSOR, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(_C_SEARCH_MATCH, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        curses.init_pair(_C_SEARCH_BAR, curses.COLOR_WHITE, curses.COLOR_MAGENTA)
        curses.init_pair(_C_TOP_CONCEPT, curses.COLOR_MAGENTA, -1)
        curses.init_pair(_C_DIFF_ADD, curses.COLOR_GREEN, -1)
        curses.init_pair(_C_DIFF_DEL, curses.COLOR_RED, -1)
        curses.init_pair(_C_DIFF_CHG, curses.COLOR_YELLOW, -1)
        curses.init_pair(_C_HELP_SECTION, curses.COLOR_BLACK, curses.COLOR_GREEN)
        curses.init_pair(_C_FILE_NODE, curses.COLOR_YELLOW, -1)
        curses.init_pair(_C_BROKEN_REF, curses.COLOR_RED, -1)
        curses.init_pair(_C_BROKEN_MAP, curses.COLOR_MAGENTA, -1)
        curses.init_pair(_C_MAPPING_NAV, curses.COLOR_YELLOW, -1)
        curses.init_pair(_C_SH_KEYWORD, curses.COLOR_BLUE, -1)
        curses.init_pair(_C_SH_VAR, curses.COLOR_CYAN, -1)
        curses.init_pair(_C_SH_URI, curses.COLOR_MAGENTA, -1)
        curses.init_pair(_C_SH_STRING, curses.COLOR_GREEN, -1)
        curses.init_pair(_C_SH_FUNCTION, curses.COLOR_YELLOW, -1)
        curses.init_pair(_C_SH_NS, curses.COLOR_YELLOW, -1)
    except Exception:
        pass


def _draw_bar(
    stdscr: curses.window,
    y: int,
    x0: int,
    width: int,
    text: str,
    dim: bool = False,
) -> None:
    """Draw a title/footer bar spanning [x0, x0+width)."""
    t = text[: width - 1].ljust(width - 1)
    attr = curses.A_REVERSE if dim else (curses.A_REVERSE | curses.A_BOLD)
    try:
        stdscr.addstr(y, x0, t, attr)
    except curses.error:
        pass


def _render_line_with_match(
    stdscr: curses.window,
    y: int,
    x0: int,
    text: str,
    width: int,
    base_attr: int,
    pattern: re.Pattern | None,
) -> None:
    """Render one line, highlighting the first regex match."""
    padded = text.ljust(width - 1)[: width - 1]
    if pattern is None:
        try:
            stdscr.addstr(y, x0, padded, base_attr)
        except curses.error:
            pass
        return
    m = pattern.search(padded)
    if not m:
        try:
            stdscr.addstr(y, x0, padded, base_attr)
        except curses.error:
            pass
        return
    hl_attr = curses.color_pair(_C_SEARCH_MATCH) | curses.A_BOLD
    try:
        if m.start() > 0:
            stdscr.addstr(y, x0, padded[: m.start()], base_attr)
        stdscr.addstr(y, x0 + m.start(), padded[m.start() : m.end()], hl_attr)
        if m.end() < len(padded):
            stdscr.addstr(y, x0 + m.end(), padded[m.end() :], base_attr)
    except curses.error:
        pass


def render_tree_col(
    stdscr: curses.window,
    flat: list[TreeLine],
    taxonomy: Taxonomy,
    lang: str,
    rows: int,
    x0: int,
    width: int,
    scroll: int,
    cursor_idx: int,
    *,
    header_title: str = "",
    highlight_uri: str | None = None,
    search_pattern: re.Pattern | None = None,
    search_matches: list[int] | None = None,
    diff_status: dict[str, str] | None = None,
) -> None:
    """Render a taxonomy tree column.

    *diff_status* maps URI → ``"added" | "removed" | "changed" | "unchanged"``.
    When provided, concepts are coloured accordingly and unchanged concepts are
    rendered dimly.  A ``↵`` hint is appended to changed concepts.
    """
    list_h = rows - 2
    n = len(flat)
    if n and cursor_idx >= 0:
        counter = f" [{cursor_idx + 1}/{n}]"
    elif n:
        counter = f" [{n}]"
    else:
        counter = ""
    bar = f" {header_title}{counter} " if header_title else f" Taxonomy{counter} "
    _draw_bar(stdscr, 0, x0, width, bar)

    for row in range(list_h):
        idx = scroll + row
        if idx >= len(flat):
            break
        line = flat[idx]
        y = row + 1
        is_cursor = idx == cursor_idx
        is_detail = line.uri == highlight_uri

        # ── file-level root node (multi-file workspace) ───────────────────
        if line.is_file:
            fname = line.file_path.name if line.file_path else line.uri
            fold_marker = "▶" if line.is_folded else "▼"
            hidden_str = f"  (+{line.hidden_count} hidden)" if line.is_folded else ""
            text = f" {fold_marker} 📄 {fname}{hidden_str}"
            if is_cursor:
                base_attr = curses.color_pair(_C_SEL) | curses.A_BOLD
            else:
                base_attr = curses.color_pair(0) | curses.A_BOLD
            try:
                stdscr.addstr(y, x0, text.ljust(width - 1)[: width - 1], base_attr)
            except curses.error:
                pass
            continue

        # ── unattached individuals group header ───────────────────────────
        if line.uri == _UNATTACHED_INDS_URI:
            fold_marker = "▶" if line.is_folded else "▼"
            hidden_str = f"  (+{line.hidden_count} hidden)" if line.is_folded else ""
            text = f"{line.prefix}⊘{fold_marker} {line.label}{hidden_str}"
            if is_cursor:
                base_attr = curses.color_pair(_C_SEL) | curses.A_BOLD
            else:
                base_attr = curses.color_pair(_C_DIM) | curses.A_BOLD
            try:
                stdscr.addstr(y, x0, text.ljust(width - 1)[: width - 1], base_attr)
            except curses.error:
                pass
            continue

        # ── scheme header row ─────────────────────────────────────────────
        if line.is_scheme:
            if line.label:
                # Synthetic section header (e.g. "OWL Classes" in mixed view)
                text = f"{line.prefix}◦ {line.label}"
                base_attr = curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD
                try:
                    stdscr.addstr(y, x0, text.ljust(width - 1)[: width - 1], base_attr)
                except curses.error:
                    pass
                continue

            s = taxonomy.schemes.get(line.uri)
            s_title = s.title(lang) if s else line.uri

            def _count(uri: str, seen: set) -> int:
                if uri in seen:
                    return 0
                seen.add(uri)
                c = taxonomy.concepts.get(uri)
                if not c:
                    return 0
                return 1 + sum(_count(ch, seen) for ch in c.narrower)

            n_concepts = sum(_count(tc, set()) for tc in (s.top_concepts if s else []))
            count_str = f"  ·  {n_concepts} concept{'s' if n_concepts != 1 else ''}"
            fold_marker = "▶" if line.is_folded else " "
            hidden_str = f"  (+{line.hidden_count} hidden)" if line.is_folded else ""
            text = f"{line.prefix}◉{fold_marker} {s_title}{count_str}{hidden_str}"

            if is_cursor:
                base_attr = curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
            else:
                base_attr = curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD
            try:
                stdscr.addstr(y, x0, text.ljust(width - 1)[: width - 1], base_attr)
            except curses.error:
                pass
            continue

        # ── OWL individual row ────────────────────────────────────────────
        if line.node_type == "individual":
            individual = taxonomy.owl_individuals.get(line.uri)
            if not individual:
                continue
            handle = taxonomy.uri_to_handle(line.uri) or "?"
            label = individual.label(lang)
            text = f"{line.prefix}• [{handle}]  {label}"
            if is_cursor:
                base_attr = curses.color_pair(_C_SEL) | curses.A_BOLD
            elif is_detail:
                base_attr = curses.color_pair(_C_SEL) | curses.A_DIM
            else:
                base_attr = curses.A_DIM
            try:
                stdscr.addstr(y, x0, text.ljust(width - 1)[: width - 1], base_attr)
            except curses.error:
                pass
            continue

        # ── normal concept / OWL class row ───────────────────────────────
        concept = taxonomy.concepts.get(line.uri)
        rdf_class = taxonomy.owl_classes.get(line.uri)

        if not concept and not rdf_class:
            continue

        handle = taxonomy.uri_to_handle(line.uri) or "?"
        if concept:
            label = concept.pref_label(lang) or line.uri
            n_children = len(concept.narrower)
            is_top = bool(concept.top_concept_of)
        else:
            # Pure OWL class — no SKOS metadata
            assert rdf_class is not None
            label = rdf_class.label(lang)
            n_children = sum(1 for c in taxonomy.owl_classes.values() if line.uri in c.sub_class_of)
            is_top = False
        d_status = diff_status.get(line.uri, "unchanged") if diff_status else "unchanged"

        # Nav marker
        if diff_status:
            nav = {"added": "+", "removed": "−", "changed": "~"}.get(d_status)
            if nav is None:
                nav = "◈" if is_top else ("▸" if n_children else " ")
        elif line.is_folded:
            nav = "»"
        elif is_top:
            nav = "◈" if n_children else "◇"
        else:
            nav = "▸" if n_children else " "

        # Count / fold / changed hint
        if line.is_folded:
            suffix = f"  (+{line.hidden_count})"
        elif n_children and not diff_status:
            suffix = f"  ({n_children})"
        elif diff_status and d_status == "changed":
            suffix = "  ↵"
        else:
            suffix = ""

        # Cross-scheme mapping indicator (rendered separately in yellow)
        has_map = bool(
            concept
            and (
                concept.exact_match
                or concept.close_match
                or concept.broad_match
                or concept.narrow_match
                or concept.related_match
            )
        )
        map_tag = "  ⇔" if has_map else ""

        # OWL node-type indicator: ○ pure class, ⊛ promoted concept+class
        owl_tag = {"class": "  ○", "promoted": "  ⊛"}.get(line.node_type, "")

        text = f"{line.prefix}{nav} [{handle}]  {label}{suffix}{owl_tag}"
        is_match = bool(search_pattern and search_matches and idx in search_matches)

        # Color
        if diff_status:
            if is_cursor:
                base_attr = curses.color_pair(_C_SEL) | curses.A_BOLD
            elif d_status == "added":
                base_attr = curses.color_pair(_C_DIFF_ADD) | curses.A_BOLD
            elif d_status == "removed":
                base_attr = curses.color_pair(_C_DIFF_DEL) | curses.A_BOLD
            elif d_status == "changed":
                base_attr = curses.color_pair(_C_DIFF_CHG) | curses.A_BOLD
            else:
                base_attr = curses.A_DIM
        else:
            if is_cursor and n_children:
                base_attr = curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
            elif is_cursor:
                base_attr = curses.color_pair(_C_SEL) | curses.A_BOLD
            elif is_detail:
                base_attr = curses.color_pair(_C_SEL) | curses.A_DIM
            elif is_top and n_children:
                base_attr = curses.color_pair(_C_TOP_CONCEPT) | curses.A_BOLD
            elif is_top:
                base_attr = curses.color_pair(_C_TOP_CONCEPT)
            elif n_children:
                base_attr = curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD
            else:
                base_attr = curses.A_NORMAL

        if is_match and not is_cursor:
            _render_line_with_match(stdscr, y, x0, text, width, base_attr, search_pattern)
        else:
            try:
                stdscr.addstr(y, x0, text.ljust(width - 1)[: width - 1], base_attr)
            except curses.error:
                pass

        # Overlay the mapping indicator in yellow (skipped when cursor or diff mode)
        if map_tag and not is_cursor and not diff_status:
            tag_x = x0 + len(text)
            if tag_x + len(map_tag) < x0 + width - 1:
                try:
                    stdscr.addstr(
                        y,
                        tag_x,
                        map_tag,
                        curses.color_pair(_C_MAPPING_NAV) | curses.A_BOLD,
                    )
                except curses.error:
                    pass


# ──────────────────────────── AI taxonomy wizard helpers ─────────────────────


def _draw_text_input(
    stdscr: curses.window,
    rows: int,
    cols: int,
    prompt: str,
    buffer: str,
    pos: int,
    error: str = "",
    hint: str = "",
) -> None:
    """Draw a simple centred text-input widget."""
    try:
        row = rows // 2 - 2
        stdscr.addstr(row, 2, prompt[: cols - 3], curses.A_BOLD)
        row += 2
        before = buffer[:pos]
        after = buffer[pos:]
        line = f"  {before}▌{after}"
        stdscr.addstr(row, 0, line[: cols - 1], curses.color_pair(_C_SEL) | curses.A_BOLD)
        row += 1
        if error:
            stdscr.addstr(row + 1, 2, error[: cols - 3], curses.color_pair(_C_SEL) | curses.A_BOLD)
        if hint:
            _draw_bar(stdscr, rows - 1, 0, cols, hint, dim=True)
    except curses.error:
        pass
