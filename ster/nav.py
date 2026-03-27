"""Interactive taxonomy TUI (curses) and REPL shell (cmd.Cmd).

TaxonomyViewer — full-screen curses navigator
  Tree mode   ↑↓ navigate  →/Enter open detail  ← parent  Esc exit
  Detail mode ↑↓ fields    i/Enter edit          ← back    d delete
  Edit mode   text editing  Enter save            Esc cancel

TaxonomyShell — bash-like REPL (ster nav)
"""
from __future__ import annotations
import curses
import json
import re
import sys
from cmd import Cmd
from dataclasses import dataclass, field as dc_field
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import operations, store
from .display import render_concept_detail, render_tree, console
from .exceptions import SkostaxError
from .model import Definition, Label, LabelType, Taxonomy

err = Console(stderr=True)


# ──────────────────────────── lang persistence ────────────────────────────────

def _lang_prefs_path() -> Path:
    return Path.home() / ".config" / "ster" / "lang_prefs.json"


def _load_lang_pref(file_path: Path) -> str | None:
    p = _lang_prefs_path()
    if p.exists():
        try:
            data = json.loads(p.read_text())
            return data.get(str(file_path.resolve()))
        except Exception:
            pass
    return None


def _save_lang_pref(file_path: Path, lang: str) -> None:
    p = _lang_prefs_path()
    try:
        data: dict = {}
        if p.exists():
            data = json.loads(p.read_text())
        data[str(file_path.resolve())] = lang
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


# ──────────────────────────── general prefs ──────────────────────────────────

def _prefs_path() -> Path:
    return Path.home() / ".config" / "ster" / "prefs.json"


def _load_prefs() -> dict:
    p = _prefs_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _save_prefs(data: dict) -> None:
    p = _prefs_path()
    try:
        existing: dict = {}
        if p.exists():
            existing = json.loads(p.read_text())
        existing.update(data)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(existing, indent=2))
    except Exception:
        pass


# ──────────────────────────── tree helpers ────────────────────────────────────

_ACTION_ADD_SCHEME = "__ster:add_scheme__"   # sentinel URI for action rows

@dataclass
class TreeLine:
    uri: str
    depth: int
    prefix: str          # e.g. "│   ├── "
    is_scheme: bool = False
    is_folded: bool = False
    hidden_count: int = 0
    is_action: bool = False  # synthetic row (not a concept/scheme node)


def _count_descendants(taxonomy: Taxonomy, uri: str) -> int:
    """Count total reachable descendants of a concept (excluding itself)."""
    seen: set[str] = set()

    def _count(u: str) -> int:
        if u in seen:
            return 0
        seen.add(u)
        c = taxonomy.concepts.get(u)
        if not c:
            return 0
        return len(c.narrower) + sum(_count(ch) for ch in c.narrower)

    return _count(uri)


def flatten_tree(
    taxonomy: Taxonomy,
    folded: "set[str] | None" = None,
) -> list[TreeLine]:
    """Flatten the full taxonomy tree into a list of displayable lines.

    Each ConceptScheme appears as a ◉ header row followed by its top concepts.
    All schemes in the taxonomy are shown (not just the primary one).
    URIs in *folded* have their children hidden; the node is marked is_folded=True
    and hidden_count is set to the number of hidden descendants.
    """
    if folded is None:
        folded = set()
    result: list[TreeLine] = []

    def visit(uri: str, depth: int, prefix: str, is_last: bool) -> None:
        connector = "└── " if is_last else "├── "
        concept = taxonomy.concepts.get(uri)
        children = concept.narrower if concept else []
        is_fold = uri in folded and bool(children)
        hidden = _count_descendants(taxonomy, uri) if is_fold else 0
        result.append(TreeLine(
            uri=uri, depth=depth, prefix=prefix + connector,
            is_folded=is_fold, hidden_count=hidden,
        ))
        if not is_fold and concept:
            ext = "    " if is_last else "│   "
            for i, child in enumerate(children):
                visit(child, depth + 1, prefix + ext, i == len(children) - 1)

    for scheme in taxonomy.schemes.values():
        scheme_folded = scheme.uri in folded
        tops = list(scheme.top_concepts)
        hidden_under_scheme = 0
        if scheme_folded:
            for tc in tops:
                hidden_under_scheme += 1 + _count_descendants(taxonomy, tc)
        result.append(TreeLine(
            uri=scheme.uri, depth=0, prefix="", is_scheme=True,
            is_folded=scheme_folded, hidden_count=hidden_under_scheme,
        ))
        if not scheme_folded:
            for i, uri in enumerate(tops):
                visit(uri, 0, "", i == len(tops) - 1)

    return result


def _children(taxonomy: Taxonomy, uri: str | None) -> list[str]:
    if uri is None:
        scheme = taxonomy.primary_scheme()
        return list(scheme.top_concepts) if scheme else []
    concept = taxonomy.concepts.get(uri)
    return list(concept.narrower) if concept else []


def _parent_uri(taxonomy: Taxonomy, uri: str | None) -> str | None:
    if uri is None:
        return None
    concept = taxonomy.concepts.get(uri)
    return concept.broader[0] if concept and concept.broader else None


def _breadcrumb(taxonomy: Taxonomy, uri: str | None) -> str:
    if uri is None:
        return "/"
    parts: list[str] = []
    current: str | None = uri
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        parts.append(taxonomy.uri_to_handle(current) or "?")
        current = _parent_uri(taxonomy, current)
    return "/" + "/".join(f"[{h}]" for h in reversed(parts))


# ──────────────────────────── detail fields ───────────────────────────────────

@dataclass
class DetailField:
    key: str
    display: str
    value: str
    editable: bool
    meta: dict = dc_field(default_factory=dict)


def build_detail_fields(taxonomy: Taxonomy, uri: str, lang: str) -> list[DetailField]:
    concept = taxonomy.concepts.get(uri)
    if not concept:
        return []

    fields: list[DetailField] = []

    fields.append(DetailField("uri", "URI", uri, editable=False, meta={"type": "uri"}))

    if concept.top_concept_of:
        scheme = taxonomy.schemes.get(concept.top_concept_of)
        scheme_label = scheme.title(lang) if scheme else concept.top_concept_of
        fields.append(DetailField(
            "top_concept_of", "◈ topConceptOf", scheme_label, editable=False,
            meta={"type": "top_concept_of", "uri": concept.top_concept_of},
        ))

    pref: dict[str, str] = {
        lbl.lang: lbl.value for lbl in concept.labels if lbl.type == LabelType.PREF
    }
    for lg, val in sorted(pref.items()):
        fields.append(DetailField(
            f"pref:{lg}", f"prefLabel [{lg}]", val, editable=True,
            meta={"type": "pref", "lang": lg},
        ))

    alt: dict[str, list[str]] = {}
    for lbl in concept.labels:
        if lbl.type == LabelType.ALT:
            alt.setdefault(lbl.lang, []).append(lbl.value)
    for lg, vals in sorted(alt.items()):
        for idx, val in enumerate(vals):
            fields.append(DetailField(
                f"alt:{lg}:{idx}", f"altLabel [{lg}]", val, editable=True,
                meta={"type": "alt", "lang": lg, "idx": idx},
            ))

    defs: dict[str, str] = {d.lang: d.value for d in concept.definitions}
    for lg, val in sorted(defs.items()):
        fields.append(DetailField(
            f"def:{lg}", f"definition [{lg}]", val, editable=True,
            meta={"type": "def", "lang": lg},
        ))

    for child_uri in concept.narrower:
        h = taxonomy.uri_to_handle(child_uri) or "?"
        child = taxonomy.concepts.get(child_uri)
        lbl = child.pref_label(lang) if child else child_uri
        fields.append(DetailField(
            f"narrower:{child_uri}", "↓ narrower", f"[{h}]  {lbl}", editable=False,
            meta={"type": "relation", "uri": child_uri},
        ))

    for p_uri in concept.broader:
        h = taxonomy.uri_to_handle(p_uri) or "?"
        parent = taxonomy.concepts.get(p_uri)
        lbl = parent.pref_label(lang) if parent else p_uri
        fields.append(DetailField(
            f"broader:{p_uri}", "↑ broader", f"[{h}]  {lbl}", editable=False,
            meta={"type": "relation", "uri": p_uri},
        ))

    for r_uri in concept.related:
        h = taxonomy.uri_to_handle(r_uri) or "?"
        rel = taxonomy.concepts.get(r_uri)
        lbl = rel.pref_label(lang) if rel else r_uri
        fields.append(DetailField(
            f"related:{r_uri}", "~ related", f"[{h}]  {lbl}", editable=False,
            meta={"type": "relation", "uri": r_uri},
        ))

    # ── action fields ──────────────────────────────────────────────────────────
    fields.append(DetailField(
        "action:add_child", "+ Add narrower concept", "",
        editable=False, meta={"type": "action", "action": "add_narrower"},
    ))
    fields.append(DetailField(
        "action:link_broader", "↗ Link to broader", "",
        editable=False, meta={"type": "action", "action": "link_broader"},
    ))
    fields.append(DetailField(
        "action:delete", "⊘ Delete concept", "",
        editable=False, meta={"type": "action", "action": "delete"},
    ))
    fields.append(DetailField(
        "action:move", "↷ Move concept", "",
        editable=False, meta={"type": "action", "action": "move"},
    ))

    return fields


def _available_langs(taxonomy: Taxonomy) -> list[str]:
    """Return sorted list of all language codes present in the taxonomy."""
    langs: set[str] = set()
    scheme = taxonomy.primary_scheme()
    if scheme:
        for lbl in scheme.labels:
            langs.add(lbl.lang)
        for desc in scheme.descriptions:
            langs.add(desc.lang)
        langs.update(scheme.languages)
    for concept in taxonomy.concepts.values():
        for lbl in concept.labels:
            langs.add(lbl.lang)
        for defn in concept.definitions:
            langs.add(defn.lang)
    return sorted(langs)


def build_scheme_fields(
    taxonomy: Taxonomy,
    lang: str,
    scheme_uri: str | None = None,
) -> list[DetailField]:
    """Build DetailField list for the ConceptScheme settings panel.

    If *scheme_uri* is given, use that scheme; otherwise fall back to the
    primary (first) scheme.
    """
    if scheme_uri is not None:
        scheme = taxonomy.schemes.get(scheme_uri)
    else:
        scheme = taxonomy.primary_scheme()
    if not scheme:
        return []

    fields: list[DetailField] = []

    # Display language first — action field: Enter opens the language picker
    fields.append(DetailField(
        "display_lang", "display language", lang,
        editable=False,
        meta={"type": "action", "action": "pick_lang"},
    ))

    fields.append(DetailField("scheme_uri", "URI", scheme.uri, editable=False,
                              meta={"type": "scheme_uri"}))
    fields.append(DetailField("base_uri", "base URI", scheme.base_uri or "", editable=True,
                              meta={"type": "scheme_base_uri"}))

    # Titles per language
    pref_titles: dict[str, str] = {
        lbl.lang: lbl.value for lbl in scheme.labels if lbl.type == LabelType.PREF
    }
    for lg, val in sorted(pref_titles.items()):
        fields.append(DetailField(f"title:{lg}", f"title [{lg}]", val, editable=True,
                                  meta={"type": "scheme_title", "lang": lg}))

    # Descriptions per language
    for desc in sorted(scheme.descriptions, key=lambda d: d.lang):
        fields.append(DetailField(f"desc:{desc.lang}", f"description [{desc.lang}]",
                                  desc.value, editable=True,
                                  meta={"type": "scheme_desc", "lang": desc.lang}))

    fields.append(DetailField("creator", "creator", scheme.creator, editable=True,
                              meta={"type": "scheme_creator"}))
    fields.append(DetailField("created", "created", scheme.created, editable=True,
                              meta={"type": "scheme_created"}))
    fields.append(DetailField("languages", "declared langs",
                              ", ".join(scheme.languages), editable=True,
                              meta={"type": "scheme_languages"}))

    # Action: add a top concept to this scheme
    fields.append(DetailField(
        "action:add_top_concept", "➕ Add top concept", "",
        editable=False, meta={"type": "action", "action": "add_top_concept"},
    ))

    # Action: add a new scheme
    fields.append(DetailField(
        "action:add_scheme", "➕ Add new scheme", "",
        editable=False, meta={"type": "action", "action": "add_scheme"},
    ))

    return fields


# ──────────────────────────── colors ─────────────────────────────────────────

_C_NAVIGABLE     = 1   # cyan bold — has children
_C_SEL           = 2   # white on blue — selected
_C_SEL_NAV       = 3   # cyan on blue — selected + navigable
_C_DIM           = 4   # dim
_C_FIELD_LABEL   = 5   # green — editable field name
_C_FIELD_VAL     = 6   # white bold — editable field value
_C_EDIT_BAR      = 7   # white on green — edit input bar
_C_DETAIL_CURSOR = 8   # selected field in detail view
_C_SEARCH_MATCH  = 9   # black on yellow — search match highlight
_C_SEARCH_BAR    = 10  # white on magenta — search input bar
_C_TOP_CONCEPT   = 11  # magenta bold — top concept row
_C_DIFF_ADD      = 12  # green — added concept/field in diff view
_C_DIFF_DEL      = 13  # red   — removed concept/field in diff view
_C_DIFF_CHG      = 14  # yellow — modified concept in diff view
_C_HELP_HINT     = 15  # black on cyan — the "? help" badge
_C_HELP_SECTION  = 16  # black on green — section header bars in help


def _init_colors() -> None:
    try:
        curses.use_default_colors()
        curses.init_pair(_C_NAVIGABLE,     curses.COLOR_CYAN,    -1)
        curses.init_pair(_C_SEL,           curses.COLOR_WHITE,    curses.COLOR_BLUE)
        curses.init_pair(_C_SEL_NAV,       curses.COLOR_CYAN,     curses.COLOR_BLUE)
        curses.init_pair(_C_DIM,           curses.COLOR_WHITE,    -1)
        curses.init_pair(_C_FIELD_LABEL,   curses.COLOR_GREEN,    -1)
        curses.init_pair(_C_FIELD_VAL,     curses.COLOR_WHITE,    -1)
        curses.init_pair(_C_EDIT_BAR,      curses.COLOR_BLACK,    curses.COLOR_GREEN)
        curses.init_pair(_C_DETAIL_CURSOR, curses.COLOR_BLACK,    curses.COLOR_CYAN)
        curses.init_pair(_C_SEARCH_MATCH,  curses.COLOR_BLACK,    curses.COLOR_YELLOW)
        curses.init_pair(_C_SEARCH_BAR,    curses.COLOR_WHITE,    curses.COLOR_MAGENTA)
        curses.init_pair(_C_TOP_CONCEPT,   curses.COLOR_MAGENTA,  -1)
        curses.init_pair(_C_DIFF_ADD,      curses.COLOR_GREEN,    -1)
        curses.init_pair(_C_DIFF_DEL,      curses.COLOR_RED,      -1)
        curses.init_pair(_C_DIFF_CHG,      curses.COLOR_YELLOW,   -1)
        curses.init_pair(_C_HELP_HINT,     curses.COLOR_BLACK,    curses.COLOR_CYAN)
        curses.init_pair(_C_HELP_SECTION,  curses.COLOR_BLACK,    curses.COLOR_GREEN)
    except Exception:
        pass


def _draw_bar(
    stdscr: "curses.window",
    y: int,
    x0: int,
    width: int,
    text: str,
    dim: bool = False,
) -> None:
    """Draw a title/footer bar spanning [x0, x0+width)."""
    t = text[:width - 1].ljust(width - 1)
    attr = curses.A_REVERSE if dim else (curses.A_REVERSE | curses.A_BOLD)
    try:
        stdscr.addstr(y, x0, t, attr)
    except curses.error:
        pass


def _render_line_with_match(
    stdscr: "curses.window",
    y: int,
    x0: int,
    text: str,
    width: int,
    base_attr: int,
    pattern: "re.Pattern | None",
) -> None:
    """Render one line, highlighting the first regex match."""
    padded = text.ljust(width - 1)[:width - 1]
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
            stdscr.addstr(y, x0, padded[:m.start()], base_attr)
        stdscr.addstr(y, x0 + m.start(), padded[m.start():m.end()], hl_attr)
        if m.end() < len(padded):
            stdscr.addstr(y, x0 + m.end(), padded[m.end():], base_attr)
    except curses.error:
        pass


def render_tree_col(
    stdscr: "curses.window",
    flat: "list[TreeLine]",
    taxonomy: "Taxonomy",
    lang: str,
    rows: int,
    x0: int,
    width: int,
    scroll: int,
    cursor_idx: int,
    *,
    header_title: str = "",
    highlight_uri: "str | None" = None,
    search_pattern: "re.Pattern | None" = None,
    search_matches: "list[int] | None" = None,
    diff_status: "dict[str, str] | None" = None,
) -> None:
    """Render a taxonomy tree column.

    *diff_status* maps URI → ``"added" | "removed" | "changed" | "unchanged"``.
    When provided, concepts are coloured accordingly and unchanged concepts are
    rendered dimly.  A ``↵`` hint is appended to changed concepts.
    """
    list_h = rows - 2
    n = len(flat)
    counter = f" [{cursor_idx + 1}/{n}]" if n else ""
    bar = f" {header_title}{counter} " if header_title else f" Taxonomy{counter} "
    _draw_bar(stdscr, 0, x0, width, bar)

    for row in range(list_h):
        idx = scroll + row
        if idx >= len(flat):
            break
        line      = flat[idx]
        y         = row + 1
        is_cursor = idx == cursor_idx
        is_detail = line.uri == highlight_uri

        # ── action row (e.g. "➕ Add new scheme") ─────────────────────────
        if line.is_action:
            text = "  ➕ Add new scheme"
            if is_cursor:
                base_attr = curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
            else:
                base_attr = curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD
            try:
                stdscr.addstr(y, x0, text.ljust(width - 1)[:width - 1], base_attr)
            except curses.error:
                pass
            continue

        # ── scheme header row ─────────────────────────────────────────────
        if line.is_scheme:
            s       = taxonomy.schemes.get(line.uri)
            s_title = s.title(lang) if s else line.uri

            def _count(uri: str, seen: set) -> int:
                if uri in seen:
                    return 0
                seen.add(uri)
                c = taxonomy.concepts.get(uri)
                if not c:
                    return 0
                return 1 + sum(_count(ch, seen) for ch in c.narrower)

            n_concepts  = sum(_count(tc, set()) for tc in (s.top_concepts if s else []))
            count_str   = f"  ·  {n_concepts} concept{'s' if n_concepts != 1 else ''}"
            fold_marker = "▶" if line.is_folded else " "
            hidden_str  = f"  (+{line.hidden_count} hidden)" if line.is_folded else ""
            text = f"◉{fold_marker} {s_title}{count_str}{hidden_str}"

            if is_cursor:
                base_attr = curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
            else:
                base_attr = curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD
            try:
                stdscr.addstr(y, x0, text.ljust(width - 1)[:width - 1], base_attr)
            except curses.error:
                pass
            continue

        # ── normal concept row ────────────────────────────────────────────
        concept = taxonomy.concepts.get(line.uri)
        if not concept:
            continue

        handle     = taxonomy.uri_to_handle(line.uri) or "?"
        label      = concept.pref_label(lang) or line.uri
        n_children = len(concept.narrower)
        is_top     = bool(concept.top_concept_of)
        d_status   = diff_status.get(line.uri, "unchanged") if diff_status else "unchanged"

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

        text     = f"{line.prefix}{nav} [{handle}]  {label}{suffix}"
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
                stdscr.addstr(y, x0, text.ljust(width - 1)[:width - 1], base_attr)
            except curses.error:
                pass


# ──────────────────────────── TaxonomyViewer ─────────────────────────────────

class TaxonomyViewer:
    """Full-screen curses TUI for taxonomy navigation and inline editing."""

    _TREE    = "tree"
    _DETAIL  = "detail"
    _EDIT    = "edit"
    _WELCOME = "welcome"
    _CREATE         = "create"
    _CONFIRM_DELETE = "confirm_delete"
    _MOVE_PICK      = "move_pick"
    _LINK_PICK      = "link_pick"
    _LANG_PICK      = "lang_pick"
    _SCHEME_CREATE  = "scheme_create"

    # Minimum terminal width for side-by-side tree + detail
    _SPLIT_MIN_COLS = 120

    def __init__(
        self,
        taxonomy: Taxonomy,
        file_path: Path,
        lang: str = "en",
        git_manager: "object | None" = None,
    ) -> None:
        self.taxonomy    = taxonomy
        self.file_path   = file_path
        # Load persisted language preference; fall back to argument
        self.lang        = _load_lang_pref(file_path) or lang
        self._git_manager = git_manager

        self._flat: list[TreeLine] = []
        self._cursor    = 0
        self._tree_scroll = 0

        self._detail_uri: str | None = None
        self._detail_fields: list[DetailField] = []
        self._field_cursor  = 0
        self._detail_scroll = 0

        self._edit_value = ""
        self._edit_pos   = 0

        self._mode    = self._TREE if _load_prefs().get("help_seen") else self._WELCOME
        self._history: list[dict] = []
        self._status  = ""

        # ── search ────────────────────────────────────────────────────────────
        self._search_query    = ""
        self._search_active   = False          # True while typing in the search bar
        self._search_matches: list[int] = []   # indices into self._flat
        self._search_idx      = 0              # which match the cursor is on
        self._search_pattern: "re.Pattern | None" = None

        self._edit_return_mode: str = self._DETAIL
        self._edit_field: "DetailField | None" = None

        self._create_parent_uri: "str | None" = None
        self._create_fields: "list[DetailField]" = []
        self._create_cursor  = 0
        self._create_scroll  = 0
        self._create_error   = ""
        self._create_return_mode: str = self._DETAIL  # where Esc goes from CREATE/SCHEME_CREATE

        self._scheme_create_fields: "list[DetailField]" = []
        self._scheme_create_cursor  = 0
        self._scheme_create_scroll  = 0
        self._scheme_create_error   = ""

        self._move_source_uri = ""
        self._move_candidates: "list[tuple[str,str]]" = []
        self._move_filter     = ""
        self._move_cursor     = 0
        self._move_scroll     = 0

        self._link_source_uri = ""

        self._lang_options:  "list[str]" = []
        self._lang_cursor    = 0
        self._lang_scroll    = 0

        self._folded: set[str] = set()

        self._rebuild()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        self._flat = flatten_tree(self.taxonomy, folded=self._folded)
        # Prepend the synthetic "Add new scheme" action row at position 0
        self._flat.insert(0, TreeLine(
            uri=_ACTION_ADD_SCHEME, depth=0, prefix="", is_action=True,
        ))

    def _push(self) -> None:
        self._history.append(dict(
            mode=self._mode,
            cursor=self._cursor,
            tree_scroll=self._tree_scroll,
            detail_uri=self._detail_uri,
            field_cursor=self._field_cursor,
            detail_scroll=self._detail_scroll,
        ))

    def _pop(self) -> bool:
        if not self._history:
            return False
        s = self._history.pop()
        self._mode           = s["mode"]
        self._cursor         = s["cursor"]
        self._tree_scroll    = s["tree_scroll"]
        self._detail_uri     = s["detail_uri"]
        self._field_cursor   = s["field_cursor"]
        self._detail_scroll  = s["detail_scroll"]
        if self._detail_uri:
            if self._detail_uri in self.taxonomy.schemes:
                self._detail_fields = build_scheme_fields(
                    self.taxonomy, self.lang, scheme_uri=self._detail_uri
                )
            else:
                self._detail_fields = build_detail_fields(
                    self.taxonomy, self._detail_uri, self.lang
                )
        return True

    def _save_file(self) -> None:
        try:
            store.save(self.taxonomy, self.file_path)
            self._status = f"Saved  {self.file_path.name}"
            if self._git_manager:
                self._git_manager.stage_file()
        except Exception as exc:
            self._status = f"Error saving: {exc}"

    def _open_detail(self) -> None:
        if not (0 <= self._cursor < len(self._flat)):
            return
        line = self._flat[self._cursor]
        if line.is_action:
            self._trigger_action("add_scheme")
            return
        self._push()
        self._detail_uri = line.uri
        if line.is_scheme:
            self._detail_fields = build_scheme_fields(
                self.taxonomy, self.lang, scheme_uri=line.uri
            )
        else:
            self._detail_fields = build_detail_fields(
                self.taxonomy, self._detail_uri, self.lang
            )
        self._field_cursor   = 0
        self._detail_scroll  = 0
        self._mode           = self._DETAIL

    def _back(self) -> None:
        if not self._pop():
            self._mode = self._TREE

    # ── entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            console.print(render_tree(self.taxonomy, lang=self.lang))
            return
        try:
            curses.wrapper(self._loop)
        except KeyboardInterrupt:
            pass

    def _loop(self, stdscr: "curses.window") -> None:
        curses.curs_set(0)
        _init_colors()
        stdscr.keypad(True)

        while True:
            rows, cols = stdscr.getmaxyx()

            if self._mode == self._WELCOME:
                self._draw_welcome(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                _save_prefs({"help_seen": True})
                self._mode = self._TREE
                continue

            if self._mode == self._TREE:
                self._draw_tree(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                if self._on_tree(key, rows):
                    break

            elif self._mode == self._DETAIL:
                self._draw_split(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                if self._on_detail(key, rows):
                    break

            elif self._mode == self._EDIT:
                if self._edit_return_mode == self._CREATE:
                    self._draw_create(stdscr, rows, cols)
                elif self._edit_return_mode == self._SCHEME_CREATE:
                    self._draw_scheme_create(stdscr, rows, cols)
                else:
                    self._draw_split(stdscr, rows, cols)
                self._draw_edit_bar(stdscr, rows, cols)
                action = self._getch_edit(stdscr)
                if action == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_edit(action)

            elif self._mode == self._CREATE:
                self._draw_create(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_create(key, rows)

            elif self._mode == self._CONFIRM_DELETE:
                self._draw_confirm(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_confirm_delete(key)

            elif self._mode == self._MOVE_PICK:
                self._draw_move(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_move_pick(key, rows)

            elif self._mode == self._LINK_PICK:
                self._draw_move(stdscr, rows, cols,
                                title=" ↗ Link to broader — pick new parent ")
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_link_pick(key, rows)

            elif self._mode == self._LANG_PICK:
                self._draw_lang_pick(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_lang_pick(key, rows)

            elif self._mode == self._SCHEME_CREATE:
                self._draw_scheme_create(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_scheme_create(key, rows)

    # ─────────────────────────── WELCOME screen ──────────────────────────────

    def _draw_welcome(self, stdscr: "curses.window", rows: int, cols: int) -> None:
        """Draw a centred floating help overlay."""
        from .help import SECTIONS
        stdscr.erase()

        scheme     = self.taxonomy.primary_scheme()
        title      = scheme.title(self.lang) if scheme else self.file_path.stem
        n_concepts = len(self.taxonomy.concepts)

        KEY_W = 26  # key column width inside the box

        # Build content rows: list of (text, kind)
        # kind: "info" | "blank" | "header" | "entry"
        content: list[tuple[str, str]] = [
            (f"  {title}  ·  {n_concepts} concept{'s' if n_concepts != 1 else ''}  ·  lang: {self.lang}", "info"),
            ("", "blank"),
        ]
        for section_title, entries in SECTIONS:
            content.append((f"  {section_title}", "header"))
            for keys, desc in entries:
                content.append((f"  {keys:<{KEY_W}}{desc}", "entry"))
            content.append(("", "blank"))

        box_w = min(cols - 4, 70)
        # title bar + hint bar + content rows + bottom padding bar
        box_h = min(rows - 2, len(content) + 3)
        box_y = max(0, (rows - box_h) // 2)
        box_x = max(0, (cols - box_w) // 2)

        # Row 0: title bar
        _draw_bar(stdscr, box_y, box_x, box_w,
                  " ster — Keyboard Shortcuts & Help ", dim=False)

        # Row 1: hint (dim reverse)
        _draw_bar(stdscr, box_y + 1, box_x, box_w,
                  "  Press any key to continue  ·  ? to re-open  ", dim=True)

        # Content rows
        visible = box_h - 3   # rows available between hint and bottom bar
        for i, (text, kind) in enumerate(content[:visible]):
            y = box_y + 2 + i
            if y >= rows - 1:
                break
            clipped = text[:box_w - 1].ljust(box_w - 1)
            if kind == "header":
                try:
                    stdscr.addstr(y, box_x, clipped,
                                  curses.color_pair(_C_HELP_SECTION) | curses.A_BOLD)
                except curses.error:
                    pass
            elif kind == "info":
                try:
                    stdscr.addstr(y, box_x, clipped,
                                  curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                except curses.error:
                    pass
            elif kind == "entry":
                key_end = 2 + KEY_W           # indent(2) + key column
                key_part  = text[:key_end]
                desc_part = text[key_end:box_w - 1]
                try:
                    stdscr.addstr(y, box_x, key_part[:box_w - 1],
                                  curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                    if desc_part:
                        stdscr.addstr(y, box_x + key_end, desc_part)
                except curses.error:
                    pass
            else:
                try:
                    stdscr.addstr(y, box_x, clipped)
                except curses.error:
                    pass

        # Bottom bar
        _draw_bar(stdscr, box_y + box_h - 1, box_x, box_w, "", dim=True)

        stdscr.refresh()

    # ─────────────────────────── help hint ───────────────────────────────────

    def _draw_help_hint(self, stdscr: "curses.window", cols: int) -> None:
        """Draw a small '? help' badge at the top-right corner of any screen."""
        badge = " ? help "
        x = max(0, cols - len(badge) - 1)
        try:
            stdscr.addstr(0, x, badge,
                          curses.color_pair(_C_HELP_HINT) | curses.A_BOLD)
        except curses.error:
            pass

    # ─────────────────────────── search ──────────────────────────────────────

    def _search_text(self, uri: str) -> str:
        """Build the full text we search against for one concept."""
        concept = self.taxonomy.concepts.get(uri)
        if not concept:
            return ""
        parts: list[str] = []
        h = self.taxonomy.uri_to_handle(uri)
        if h:
            parts.append(h)
        # local name from URI
        local = uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        parts.append(local)
        for lbl in concept.labels:
            parts.append(lbl.value)
        for defn in concept.definitions:
            parts.append(defn.value)
        return "  ".join(parts)

    def _update_search(self) -> None:
        """Recompile pattern and recompute matching lines; jump cursor to first match."""
        q = self._search_query
        if not q:
            self._search_matches = []
            self._search_pattern = None
            self._search_idx     = 0
            return
        try:
            pat = re.compile(q, re.IGNORECASE)
        except re.error:
            pat = re.compile(re.escape(q), re.IGNORECASE)
        self._search_pattern = pat

        matches = [
            i for i, line in enumerate(self._flat)
            if pat.search(self._search_text(line.uri))
        ]
        self._search_matches = matches
        if matches:
            # Land on first match at-or-after current cursor
            for idx, m in enumerate(matches):
                if m >= self._cursor:
                    self._search_idx = idx
                    self._cursor     = m
                    return
            self._search_idx = 0
            self._cursor     = matches[0]
        else:
            self._search_idx = 0

    def _search_jump(self, delta: int) -> None:
        """Move to the next (+1) or previous (-1) search match."""
        if not self._search_matches:
            return
        self._search_idx = (self._search_idx + delta) % len(self._search_matches)
        self._cursor     = self._search_matches[self._search_idx]

    def _render_line_with_match(
        self,
        stdscr: "curses.window",
        y: int,
        x0: int,
        text: str,
        width: int,
        base_attr: int,
        is_current_match: bool = False,
    ) -> None:
        _render_line_with_match(stdscr, y, x0, text, width, base_attr, self._search_pattern)

    # ─────────────────────────── key reading ─────────────────────────────────

    def _getch_edit(self, stdscr: "curses.window") -> "int | str":
        """Read a key in edit mode; translate Alt/Ctrl+Arrow to action strings."""
        key = stdscr.getch()
        if key != 27:
            return key
        # ESC — peek ahead to detect Alt/Ctrl sequences
        stdscr.timeout(50)
        seq: list[int] = []
        while True:
            ch = stdscr.getch()
            if ch == -1:
                break
            seq.append(ch)
        stdscr.timeout(-1)
        if not seq:
            return 27  # plain Escape
        # Alt+b / Alt+f — Emacs-style word jump
        if seq == [ord("b")]:
            return "word_left"
        if seq == [ord("f")]:
            return "word_right"
        # Ctrl+Left: \033[1;5D or \033Od
        if seq in (
            [ord("["), ord("1"), ord(";"), ord("5"), ord("D")],
            [ord("O"), ord("d")],
        ):
            return "word_left"
        # Ctrl+Right: \033[1;5C or \033Oc
        if seq in (
            [ord("["), ord("1"), ord(";"), ord("5"), ord("C")],
            [ord("O"), ord("c")],
        ):
            return "word_right"
        return 27  # unknown sequence — treat as Escape

    # ─────────────────────────── TREE drawing ────────────────────────────────

    def _adjust_tree_scroll(self, rows: int) -> None:
        list_h = rows - 2
        if self._cursor < self._tree_scroll:
            self._tree_scroll = self._cursor
        elif self._cursor >= self._tree_scroll + list_h:
            self._tree_scroll = self._cursor - list_h + 1

    def _tree_footer(self, rows: int) -> str:
        n = len(self._flat)
        pos = f"[{self._cursor + 1}/{n}]" if n else "[0/0]"
        has_children = False
        is_action_row = False
        if 0 <= self._cursor < n:
            line = self._flat[self._cursor]
            if line.is_action:
                is_action_row = True
            else:
                concept = self.taxonomy.concepts.get(line.uri)
                has_children = bool(concept and concept.narrower)
        if is_action_row:
            enter_hint = "→/Enter: create scheme"
        elif has_children:
            enter_hint = "→/Enter: expand"
        else:
            enter_hint = "→/Enter: detail"
        at_top    = self._cursor == 0
        at_bottom = self._cursor == n - 1
        jump_hint = "G: last" if at_top else ("g: first" if at_bottom else "g/G: first/last")
        if self._search_matches:
            m_pos = f"[match {self._search_idx + 1}/{len(self._search_matches)}]"
            return (
                f" {pos}  {m_pos}  Tab/↓: next match  Shift+Tab/↑: prev  "
                f"Enter: open  /: new search  Esc: clear "
            )
        return (
            f" {pos}  ↑↓/j·k: move  {enter_hint}  ←/h: parent"
            f"   Spc: fold  +: add  ^D/^U: ½-page  {jump_hint}  /: search  ◉: scheme  q: quit "
        )

    def _draw_tree(self, stdscr: "curses.window", rows: int, cols: int) -> None:
        stdscr.erase()
        self._adjust_tree_scroll(rows)
        self._render_tree_col(stdscr, rows, 0, cols, self._cursor, highlight_uri=None)
        if self._status:
            _draw_bar(stdscr, rows - 1, 0, cols, f" {self._status} ", dim=False)
            self._status = ""
        elif self._search_active:
            self._draw_search_bar(stdscr, rows - 1, 0, cols)
        else:
            _draw_bar(stdscr, rows - 1, 0, cols, self._tree_footer(rows), dim=True)
        self._draw_help_hint(stdscr, cols)
        stdscr.refresh()

    def _draw_search_bar(
        self, stdscr: "curses.window", y: int, x0: int, width: int
    ) -> None:
        """Render the live search input bar."""
        q   = self._search_query
        n   = len(self._search_matches)
        if not q:
            status = "type to search  Esc: cancel"
        elif n == 0:
            status = "[bold red]no matches[/bold red]"  # plain text here
            status = "no matches"
        else:
            status = f"{n} match{'es' if n != 1 else ''}  Tab/↓: next  Shift+Tab/↑: prev  Enter: select  Esc: clear"
        bar = f" /{q}▌   {status} "
        attr = curses.color_pair(_C_SEARCH_BAR) | curses.A_BOLD
        try:
            stdscr.addstr(y, x0, bar[:width - 1].ljust(width - 1), attr)
        except curses.error:
            pass

    def _render_tree_col(
        self,
        stdscr: "curses.window",
        rows: int,
        x0: int,
        width: int,
        cursor_idx: int,
        highlight_uri: "str | None",
    ) -> None:
        """Render the tree list into column [x0, x0+width)."""
        scheme = self.taxonomy.primary_scheme()
        title  = ""
        if scheme:
            for lbl in scheme.labels:
                if lbl.lang == self.lang:
                    title = lbl.value
                    break
            if not title and scheme.labels:
                title = scheme.labels[0].value
        render_tree_col(
            stdscr, self._flat, self.taxonomy, self.lang,
            rows, x0, width, self._tree_scroll, cursor_idx,
            header_title=title,
            highlight_uri=highlight_uri,
            search_pattern=self._search_pattern,
            search_matches=self._search_matches,
        )

    # ─────────────────────────── TREE events ─────────────────────────────────

    def _on_tree(self, key: int, rows: int) -> bool:
        n      = len(self._flat)
        list_h = rows - 2

        # ── search: typing mode ───────────────────────────────────────────────
        if self._search_active:
            if key == 27:                              # Esc — clear search
                self._search_active   = False
                self._search_query    = ""
                self._search_matches  = []
                self._search_pattern  = None
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if self._search_query:
                    self._search_query = self._search_query[:-1]
                    self._update_search()
            elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                self._search_active = False           # commit, keep highlights
                self._open_detail()
            elif key in (9, curses.KEY_DOWN):         # Tab / ↓ — next match
                self._search_jump(+1)
            elif key in (curses.KEY_BTAB, curses.KEY_UP):  # Shift+Tab / ↑ — prev
                self._search_jump(-1)
            elif 32 <= key < 256:
                self._search_query += chr(key)
                self._update_search()
            return False

        # ── search: results-visible, navigate matches ─────────────────────────
        if self._search_matches:
            if key == 9:                              # Tab — next match
                self._search_jump(+1); return False
            if key == curses.KEY_BTAB:                # Shift+Tab — prev match
                self._search_jump(-1); return False
            if key == ord("n"):
                self._search_jump(+1); return False
            if key == ord("N"):
                self._search_jump(-1); return False
            if key == 27:                             # Esc — clear results
                self._search_matches = []
                self._search_pattern = None
                self._search_query   = ""
                return False

        # ── search trigger ────────────────────────────────────────────────────
        if key == ord("/"):
            self._search_active  = True
            self._search_query   = ""
            self._search_matches = []
            self._search_pattern = None
            self._search_idx     = 0
            return False

        # ── standard navigation ───────────────────────────────────────────────
        if key in (curses.KEY_UP, ord("k")):
            self._cursor = max(0, self._cursor - 1)

        elif key in (curses.KEY_DOWN, ord("j")):
            self._cursor = min(n - 1, self._cursor + 1)

        elif key in (curses.KEY_HOME, ord("g")):
            self._cursor = 0

        elif key in (curses.KEY_END, ord("G")):
            self._cursor = n - 1

        elif key == curses.KEY_PPAGE:
            self._cursor = max(0, self._cursor - list_h)

        elif key == curses.KEY_NPAGE:
            self._cursor = min(n - 1, self._cursor + list_h)

        elif key == 4:   # Ctrl+D — half-page down
            self._cursor = min(n - 1, self._cursor + list_h // 2)

        elif key == 21:  # Ctrl+U — half-page up
            self._cursor = max(0, self._cursor - list_h // 2)

        elif key == ord(" "):
            if 0 <= self._cursor < n:
                uri = self._flat[self._cursor].uri
                # Only fold/unfold nodes that have children
                line = self._flat[self._cursor]
                has_children = False
                if line.is_scheme:
                    s = self.taxonomy.schemes.get(uri)
                    has_children = bool(s and s.top_concepts)
                else:
                    c = self.taxonomy.concepts.get(uri)
                    has_children = bool(c and c.narrower)
                if has_children:
                    if uri in self._folded:
                        self._folded.discard(uri)
                    else:
                        self._folded.add(uri)
                    self._rebuild()
                    # Keep cursor on the same URI after rebuild
                    for i, tl in enumerate(self._flat):
                        if tl.uri == uri:
                            self._cursor = i
                            break

        elif key == ord("+"):
            # + on action row → add scheme; on scheme row → add top concept;
            # on concept row → add narrower concept
            if 0 <= self._cursor < n:
                line = self._flat[self._cursor]
                if line.is_action:
                    self._trigger_action("add_scheme")
                elif line.is_scheme:
                    self._detail_uri    = line.uri
                    self._detail_fields = build_scheme_fields(
                        self.taxonomy, self.lang, scheme_uri=line.uri
                    )
                    self._trigger_action("add_top_concept")
                else:
                    self._detail_uri    = line.uri
                    self._detail_fields = build_detail_fields(
                        self.taxonomy, line.uri, self.lang
                    )
                    self._trigger_action("add_narrower")

        elif key in (curses.KEY_RIGHT, curses.KEY_ENTER, ord("\n"), ord("\r"), ord("l")):
            if 0 <= self._cursor < n and self._flat[self._cursor].is_action:
                self._trigger_action("add_scheme")
            else:
                self._open_detail()

        elif key in (curses.KEY_LEFT, ord("h")):
            if 0 <= self._cursor < n:
                depth = self._flat[self._cursor].depth
                if depth > 0:
                    for i in range(self._cursor - 1, -1, -1):
                        if self._flat[i].depth == depth - 1:
                            self._cursor = i
                            break

        elif key == ord("?"):
            self._mode = self._WELCOME

        elif key in (ord("q"), ord("Q"), 27):
            return True

        return False

    # ─────────────────────────── DETAIL drawing ──────────────────────────────

    def _draw_split(self, stdscr: "curses.window", rows: int, cols: int) -> None:
        stdscr.erase()

        wide = cols >= self._SPLIT_MIN_COLS
        tree_w    = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w  = cols - tree_w

        if wide:
            # Sync tree scroll so detail concept is visible
            if self._detail_uri:
                for i, line in enumerate(self._flat):
                    if line.uri == self._detail_uri:
                        self._cursor = i
                        break
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr, rows, 0, tree_w,
                cursor_idx=self._cursor,
                highlight_uri=self._detail_uri,
            )
            # vertical separator
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass

        self._render_detail_col(stdscr, rows, detail_x0, detail_w)
        self._draw_help_hint(stdscr, cols)
        stdscr.refresh()

    def _render_detail_col(
        self, stdscr: "curses.window", rows: int, x0: int, width: int
    ) -> None:
        is_scheme_detail = bool(
            self._detail_uri and self._detail_uri in self.taxonomy.schemes
        )

        if is_scheme_detail:
            scheme = self.taxonomy.schemes[self._detail_uri]  # type: ignore[index]
            label  = scheme.title(self.lang)
            handle = None
        else:
            concept = (
                self.taxonomy.concepts.get(self._detail_uri) if self._detail_uri else None
            )
            if not concept:
                return
            handle = self.taxonomy.uri_to_handle(self._detail_uri) if self._detail_uri else "?"
            label  = concept.pref_label(self.lang) or self._detail_uri or ""
        n_fields = len(self._detail_fields)
        if self._mode == self._EDIT:
            title_bar = (
                " ^A:start  ^E:end  ^W:del-word  ^K:kill-end"
                "  Alt+←→/^←→:word-jump  Enter:save  Esc:cancel "
            )
        elif is_scheme_detail:
            counter = f" [{self._field_cursor + 1}/{n_fields}]" if n_fields else ""
            title_bar = f" ◉ {label}  [scheme settings]{counter} "
        else:
            counter = f" [{self._field_cursor + 1}/{n_fields}]" if n_fields else ""
            title_bar = f" [{handle}]  {label}{counter} "
        _draw_bar(stdscr, 0, x0, width, title_bar, dim=(self._mode == self._EDIT))

        list_h  = rows - 2
        n_fields = len(self._detail_fields)

        if self._field_cursor < self._detail_scroll:
            self._detail_scroll = self._field_cursor
        elif self._field_cursor >= self._detail_scroll + list_h:
            self._detail_scroll = self._field_cursor - list_h + 1

        lbl_w = 18
        for row in range(list_h):
            idx = self._detail_scroll + row
            if idx >= n_fields:
                break
            f   = self._detail_fields[idx]
            sel = idx == self._field_cursor

            is_narrower = (
                f.meta.get("type") == "relation" and f.key.startswith("narrower:")
            )
            # Actions use full label (not padded/truncated — some labels > lbl_w)
            fl = f.display if f.meta.get("type") == "action" else f.display[:lbl_w].ljust(lbl_w)
            fv  = f.value[:width - lbl_w - 5]
            y   = row + 1

            try:
                if sel:
                    line = f"  {fl}  {fv}"
                    stdscr.addstr(y, x0, line.ljust(width - 1)[:width - 1],
                                  curses.color_pair(_C_SEL_NAV) | curses.A_BOLD)
                elif f.meta.get("type") == "action":
                    stdscr.addstr(y, x0,   "  ")
                    stdscr.addstr(y, x0+2, fl, curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                elif f.editable:
                    stdscr.addstr(y, x0,   "  ")
                    stdscr.addstr(y, x0+2, fl, curses.color_pair(_C_FIELD_LABEL))
                    stdscr.addstr(y, x0+2+lbl_w+2, fv,
                                  curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD)
                elif is_narrower:
                    stdscr.addstr(y, x0,   "  ")
                    stdscr.addstr(y, x0+2, fl, curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                    stdscr.addstr(y, x0+2+lbl_w+2, fv,
                                  curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD)
                elif f.meta.get("type") == "scheme_base_uri":
                    # base URI — editable, shown with field label styling
                    stdscr.addstr(y, x0,   "  ")
                    stdscr.addstr(y, x0+2, fl, curses.color_pair(_C_FIELD_LABEL))
                    stdscr.addstr(y, x0+2+lbl_w+2, fv[:width - lbl_w - 5],
                                  curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD)
                elif f.meta.get("type") == "scheme_uri":
                    # URI — read-only but fully legible
                    stdscr.addstr(y, x0,   "  ")
                    stdscr.addstr(y, x0+2, fl, curses.color_pair(_C_DIM))
                    stdscr.addstr(y, x0+2+lbl_w+2, fv[:width - lbl_w - 5],
                                  curses.color_pair(_C_FIELD_VAL))
                else:
                    stdscr.addstr(y, x0,   "  ")
                    stdscr.addstr(y, x0+2, fl, curses.color_pair(_C_DIM) | curses.A_DIM)
                    stdscr.addstr(y, x0+2+lbl_w+2, fv, curses.color_pair(_C_DIM) | curses.A_DIM)
            except curses.error:
                pass

        if self._mode != self._EDIT:
            _draw_bar(stdscr, rows - 1, x0, width, self._detail_footer(), dim=True)

    # ─────────────────────────── DETAIL events ───────────────────────────────

    def _detail_footer(self) -> str:
        n = len(self._detail_fields)
        pos = f"[{self._field_cursor + 1}/{n}]" if n else "[0/0]"
        is_scheme_detail = bool(
            self._detail_uri and self._detail_uri in self.taxonomy.schemes
        )
        if 0 <= self._field_cursor < n:
            f = self._detail_fields[self._field_cursor]
            if f.meta.get("type") == "action":
                edit_hint = "Enter: execute"
            elif f.editable and not is_scheme_detail:
                edit_hint = "i/Enter: edit  -: delete val"
            elif f.editable:
                edit_hint = "i/Enter: edit"
            elif f.meta.get("type") == "relation" and f.key.startswith("narrower:"):
                edit_hint = "Enter: open concept"
            else:
                edit_hint = "(read-only)"
        else:
            edit_hint = ""
        at_top    = self._field_cursor == 0
        at_bottom = self._field_cursor == n - 1
        jump_hint = "G: last" if at_top else ("g: first" if at_bottom else "g/G: first/last")
        return (
            f" {pos}  ↑↓/j·k  {edit_hint}  {jump_hint}"
            f"  m: move  b: broader  -: delete  ^D/^U  ←/Esc: back  ?: help "
        )

    def _on_detail(self, key: int, rows: int) -> bool:
        n = len(self._detail_fields)
        list_h = rows - 2

        if key in (curses.KEY_UP, ord("k")):
            self._field_cursor = max(0, self._field_cursor - 1)

        elif key in (curses.KEY_DOWN, ord("j")):
            self._field_cursor = min(n - 1, self._field_cursor + 1)

        elif key in (curses.KEY_HOME, ord("g")):
            self._field_cursor = 0

        elif key in (curses.KEY_END, ord("G")):
            self._field_cursor = n - 1

        elif key == curses.KEY_PPAGE:
            self._field_cursor = max(0, self._field_cursor - list_h)

        elif key == curses.KEY_NPAGE:
            self._field_cursor = min(n - 1, self._field_cursor + list_h)

        elif key == 4:   # Ctrl+D — half-page down
            self._field_cursor = min(n - 1, self._field_cursor + list_h // 2)

        elif key == 21:  # Ctrl+U — half-page up
            self._field_cursor = max(0, self._field_cursor - list_h // 2)

        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r"), ord("i"), ord("e")):
            if 0 <= self._field_cursor < n:
                f = self._detail_fields[self._field_cursor]
                if f.meta.get("type") == "action":
                    self._trigger_action(f.meta.get("action", ""))
                elif f.editable:
                    self._edit_field       = f
                    self._edit_value       = f.value
                    self._edit_pos         = len(f.value)
                    self._edit_return_mode = self._DETAIL
                    self._mode             = self._EDIT
                elif f.meta.get("type") == "relation" and f.key.startswith("narrower:"):
                    child_uri = f.meta["uri"]
                    if child_uri in self.taxonomy.concepts:
                        self._push()
                        self._detail_uri    = child_uri
                        self._detail_fields = build_detail_fields(
                            self.taxonomy, child_uri, self.lang
                        )
                        self._field_cursor  = 0
                        self._detail_scroll = 0

        elif key == ord("-"):
            # Delete field value when on an editable field; delete concept when
            # on a non-editable / action field (mirrors ⊘ Delete action).
            if 0 <= self._field_cursor < n:
                f = self._detail_fields[self._field_cursor]
                if f.editable:
                    self._delete_field(f)
                else:
                    self._trigger_action("delete")

        elif key == ord("m"):
            # Move concept shortcut
            self._trigger_action("move")

        elif key == ord("b"):
            # Add broader link shortcut
            self._trigger_action("link_broader")

        elif key == ord("?"):
            self._mode = self._WELCOME

        elif key in (curses.KEY_LEFT, ord("h"), 27):
            self._back()

        return False

    # ─────────────────────────── EDIT drawing ────────────────────────────────

    def _draw_edit_bar(self, stdscr: "curses.window", rows: int, cols: int) -> None:
        if self._edit_field is None:
            return
        f       = self._edit_field
        prompt  = f" {f.display}: "
        before  = self._edit_value[:self._edit_pos]
        after   = self._edit_value[self._edit_pos:]
        bar     = f"{prompt}{before}▌{after}"
        try:
            stdscr.addstr(rows - 1, 0, bar[:cols - 1].ljust(cols - 1),
                          curses.color_pair(_C_EDIT_BAR) | curses.A_BOLD)
            stdscr.refresh()
        except curses.error:
            pass

    # ─────────────────────────── EDIT events ─────────────────────────────────

    @staticmethod
    def _word_start_left(v: str, p: int) -> int:
        """Return position of the start of the word to the left of p."""
        i = p
        while i > 0 and v[i - 1] == " ":
            i -= 1
        while i > 0 and v[i - 1] != " ":
            i -= 1
        return i

    @staticmethod
    def _word_start_right(v: str, p: int) -> int:
        """Return position just past the end of the word to the right of p."""
        i = p
        while i < len(v) and v[i] != " ":
            i += 1
        while i < len(v) and v[i] == " ":
            i += 1
        return i

    def _on_edit(self, key: "int | str") -> None:
        v, p = self._edit_value, self._edit_pos

        if key == 27:                           # Esc — cancel
            self._mode = self._edit_return_mode

        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            self._commit_edit()
            self._mode = self._edit_return_mode

        elif key == 1:                          # Ctrl+A — go to start
            self._edit_pos = 0

        elif key == 5:                          # Ctrl+E — go to end
            self._edit_pos = len(v)

        elif key == 11:                         # Ctrl+K — kill to end of line
            self._edit_value = v[:p]

        elif key == 23:                         # Ctrl+W — delete word backward
            i = self._word_start_left(v, p)
            self._edit_value = v[:i] + v[p:]
            self._edit_pos   = i

        elif key == "word_left":                # Alt+b / Ctrl+Left
            self._edit_pos = self._word_start_left(v, p)

        elif key == "word_right":               # Alt+f / Ctrl+Right
            self._edit_pos = self._word_start_right(v, p)

        elif key in (curses.KEY_BACKSPACE, 127):
            if p > 0:
                self._edit_value = v[:p-1] + v[p:]
                self._edit_pos   = p - 1

        elif key == curses.KEY_DC:
            if p < len(v):
                self._edit_value = v[:p] + v[p+1:]

        elif key == curses.KEY_LEFT:
            self._edit_pos = max(0, p - 1)

        elif key == curses.KEY_RIGHT:
            self._edit_pos = min(len(v), p + 1)

        elif key in (curses.KEY_HOME,):
            self._edit_pos = 0

        elif key in (curses.KEY_END,):
            self._edit_pos = len(v)

        elif isinstance(key, int) and 32 <= key < 256:
            ch = chr(key)
            self._edit_value = v[:p] + ch + v[p:]
            self._edit_pos   = p + 1

    def _commit_edit(self) -> None:
        if self._edit_return_mode == self._CREATE:
            if 0 <= self._create_cursor < len(self._create_fields):
                f = self._create_fields[self._create_cursor]
                if f.editable:
                    f.value = self._edit_value
            return
        if self._edit_return_mode == self._SCHEME_CREATE:
            if 0 <= self._scheme_create_cursor < len(self._scheme_create_fields):
                f = self._scheme_create_fields[self._scheme_create_cursor]
                if f.editable:
                    f.value = self._edit_value
            return
        if not self._detail_uri:
            return
        if not (0 <= self._field_cursor < len(self._detail_fields)):
            return
        f         = self._detail_fields[self._field_cursor]
        new_value = self._edit_value.strip()
        if not f.editable:
            return

        # ── scheme field editing ──────────────────────────────────────────────
        if self._detail_uri in self.taxonomy.schemes:
            self._commit_scheme_edit(f, new_value)
            return

        # ── concept field editing ─────────────────────────────────────────────
        if not new_value:
            return
        ftype = f.meta.get("type")
        lang  = f.meta.get("lang", "")
        try:
            if ftype == "pref":
                operations.set_label(
                    self.taxonomy, self._detail_uri, lang, new_value, LabelType.PREF
                )
            elif ftype == "alt":
                operations.set_label(
                    self.taxonomy, self._detail_uri, lang, new_value, LabelType.ALT
                )
            elif ftype == "def":
                operations.set_definition(
                    self.taxonomy, self._detail_uri, lang, new_value
                )
        except SkostaxError:
            return
        self._detail_fields = build_detail_fields(
            self.taxonomy, self._detail_uri, self.lang
        )
        self._save_file()

    def _commit_scheme_edit(self, f: DetailField, new_value: str) -> None:
        """Commit an edit to a ConceptScheme field."""
        scheme = self.taxonomy.schemes.get(self._detail_uri or "")
        if not scheme:
            return
        ftype = f.meta.get("type")
        lang  = f.meta.get("lang", "")

        if ftype == "scheme_base_uri":
            scheme.base_uri = new_value or None

        elif ftype == "scheme_title":
            for lbl in scheme.labels:
                if lbl.type == LabelType.PREF and lbl.lang == lang:
                    lbl.value = new_value
                    break
            else:
                scheme.labels.append(Label(lang=lang, value=new_value, type=LabelType.PREF))
        elif ftype == "scheme_desc":
            for desc in scheme.descriptions:
                if desc.lang == lang:
                    desc.value = new_value
                    break
            else:
                scheme.descriptions.append(Definition(lang=lang, value=new_value))
        elif ftype == "scheme_creator":
            scheme.creator = new_value
        elif ftype == "scheme_created":
            scheme.created = new_value
        elif ftype == "scheme_languages":
            scheme.languages = [lg.strip() for lg in new_value.split(",") if lg.strip()]

        self._detail_fields = build_scheme_fields(
            self.taxonomy, self.lang, scheme_uri=self._detail_uri
        )
        self._field_cursor = min(
            self._field_cursor, max(0, len(self._detail_fields) - 1)
        )
        self._save_file()

    def _delete_field(self, f: DetailField) -> None:
        if not self._detail_uri:
            return
        ftype = f.meta.get("type")
        lang  = f.meta.get("lang", "")
        try:
            if ftype in ("pref", "alt"):
                lt = LabelType.PREF if ftype == "pref" else LabelType.ALT
                operations.remove_label(
                    self.taxonomy, self._detail_uri, lang, f.value, lt
                )
            elif ftype == "def":
                concept = self.taxonomy.concepts.get(self._detail_uri)
                if concept:
                    concept.definitions = [
                        d for d in concept.definitions if d.lang != lang
                    ]
        except SkostaxError:
            return
        self._detail_fields = build_detail_fields(
            self.taxonomy, self._detail_uri, self.lang
        )
        self._field_cursor = min(
            self._field_cursor, max(0, len(self._detail_fields) - 1)
        )
        self._save_file()

    # ─────────────────────────── action dispatch ─────────────────────────────

    def _trigger_action(self, action: str) -> None:
        # Record where to return on cancel — if called from tree, return to tree
        self._create_return_mode = (
            self._TREE if self._mode in (self._TREE, self._WELCOME) else self._DETAIL
        )
        if action in ("add_narrower", "add_top_concept"):
            # add_narrower: parent is the current concept.
            # add_top_concept: parent is the scheme URI — add_concept treats a
            #   scheme URI as "add as top concept of that scheme".
            self._create_parent_uri = self._detail_uri
            self._create_fields     = self._build_create_fields()
            self._create_cursor     = 0
            self._create_scroll     = 0
            self._create_error      = ""
            self._mode              = self._CREATE
        elif action == "delete":
            self._mode = self._CONFIRM_DELETE
        elif action == "move":
            if self._detail_uri:
                self._move_source_uri = self._detail_uri
                self._move_candidates = self._build_move_candidates(self._detail_uri)
                self._move_filter     = ""
                self._move_cursor     = 0
                self._move_scroll     = 0
                self._mode            = self._MOVE_PICK
        elif action == "link_broader":
            if self._detail_uri:
                self._link_source_uri = self._detail_uri
                # Candidates: all concepts except the concept itself, its subtree,
                # and concepts already in its broader list (already linked)
                concept   = self.taxonomy.concepts.get(self._detail_uri)
                excluded  = operations._subtree_uris(self.taxonomy, self._detail_uri)
                already   = set(concept.broader) if concept else set()
                candidates: list[tuple[str, str]] = []
                for line in self._flat:
                    if line.is_scheme:
                        continue
                    if line.uri in excluded or line.uri in already:
                        continue
                    c = self.taxonomy.concepts.get(line.uri)
                    if c:
                        handle = self.taxonomy.uri_to_handle(line.uri) or "?"
                        label  = c.pref_label(self.lang) or line.uri
                        indent = "  " * line.depth
                        candidates.append((line.uri, f"{indent}[{handle}]  {label}"))
                self._move_candidates = candidates
                self._move_filter     = ""
                self._move_cursor     = 0
                self._move_scroll     = 0
                self._mode            = self._LINK_PICK

        elif action == "add_scheme":
            self._scheme_create_fields = self._build_scheme_create_fields()
            self._scheme_create_cursor = 0
            self._scheme_create_scroll = 0
            self._scheme_create_error  = ""
            self._mode = self._SCHEME_CREATE

        elif action == "pick_lang":
            options = _available_langs(self.taxonomy)
            if not options:
                options = ["en", "fr", "de", "es"]
            self._lang_options = options
            # Pre-select current language
            try:
                self._lang_cursor = options.index(self.lang)
            except ValueError:
                self._lang_cursor = 0
            self._lang_scroll = 0
            self._mode = self._LANG_PICK

    # ─────────────────────────── CREATE mode ─────────────────────────────────

    def _build_create_fields(self) -> "list[DetailField]":
        import re
        # Gather all languages currently used in the taxonomy
        langs: list[str] = []
        seen: set[str] = set()
        for concept in self.taxonomy.concepts.values():
            for lbl in concept.labels:
                if lbl.lang not in seen:
                    seen.add(lbl.lang)
                    langs.append(lbl.lang)
        if self.lang not in seen:
            langs.insert(0, self.lang)

        fields: list[DetailField] = [
            DetailField("form:name", "Concept name", "", editable=True,
                        meta={"type": "form", "field": "name"}),
        ]
        for lg in langs:
            fields.append(DetailField(
                f"form:pref:{lg}", f"prefLabel [{lg}]", "", editable=True,
                meta={"type": "form", "field": "pref", "lang": lg},
            ))
        fields.append(DetailField(
            f"form:def:{self.lang}", f"definition [{self.lang}]", "", editable=True,
            meta={"type": "form", "field": "def", "lang": self.lang},
        ))
        fields.append(DetailField(
            "form:submit", "✓  Create concept", "", editable=False,
            meta={"type": "form_action", "action": "submit"},
        ))
        fields.append(DetailField(
            "form:cancel", "✗  Cancel", "", editable=False,
            meta={"type": "form_action", "action": "cancel"},
        ))
        return fields

    def _draw_create(self, stdscr: "curses.window", rows: int, cols: int) -> None:
        stdscr.erase()
        wide      = cols >= self._SPLIT_MIN_COLS
        tree_w    = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w  = cols - tree_w
        if wide:
            if self._create_parent_uri:
                for i, line in enumerate(self._flat):
                    if line.uri == self._create_parent_uri:
                        self._cursor = i
                        break
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr, rows, 0, tree_w,
                cursor_idx=self._cursor,
                highlight_uri=self._create_parent_uri,
            )
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass
        self._render_create_col(stdscr, rows, detail_x0, detail_w)
        self._draw_help_hint(stdscr, cols)
        stdscr.refresh()

    def _render_create_col(
        self, stdscr: "curses.window", rows: int, x0: int, width: int
    ) -> None:
        if self._mode == self._EDIT:
            _draw_bar(
                stdscr, 0, x0, width,
                " ^A:start  ^E:end  ^W:del-word  ^K:kill-end"
                "  Alt+←→/^←→:word-jump  Enter:save  Esc:cancel ",
                dim=True,
            )
        else:
            if self._create_parent_uri in self.taxonomy.schemes:
                scheme     = self.taxonomy.schemes[self._create_parent_uri]
                scheme_lbl = scheme.title(self.lang) or self._create_parent_uri
                bar_title  = f" New top concept in «{scheme_lbl}» "
            elif self._create_parent_uri:
                ph        = self.taxonomy.uri_to_handle(self._create_parent_uri) or "?"
                bar_title = f" New concept under [{ph}] "
            else:
                bar_title = " New top concept "
            _draw_bar(stdscr, 0, x0, width, bar_title, dim=False)

        list_h = rows - 2
        n      = len(self._create_fields)

        if self._create_cursor < self._create_scroll:
            self._create_scroll = self._create_cursor
        elif self._create_cursor >= self._create_scroll + list_h:
            self._create_scroll = self._create_cursor - list_h + 1

        lbl_w  = 18
        # Use the target scheme's base_uri when creating a top concept
        if (self._create_parent_uri
                and self._create_parent_uri in self.taxonomy.schemes):
            s    = self.taxonomy.schemes[self._create_parent_uri]
            base = s.base_uri or self.taxonomy.base_uri()
        else:
            base = self.taxonomy.base_uri()
        for row in range(list_h):
            idx = self._create_scroll + row
            if idx >= n:
                break
            f   = self._create_fields[idx]
            sel = idx == self._create_cursor
            fl  = f.display[:lbl_w].ljust(lbl_w)
            fv  = f.value
            if f.meta.get("field") == "name":
                if fv:
                    preview = f"{base}{fv}" if base else fv
                    fv = f"{fv}  →  {preview}"
                else:
                    fv = "(required)"
            else:
                fv = fv[:width - lbl_w - 5]
            y   = row + 1
            ftype = f.meta.get("type")
            try:
                if sel:
                    line = f"  {fl}  {fv}"
                    stdscr.addstr(y, x0, line.ljust(width - 1)[:width - 1],
                                  curses.color_pair(_C_SEL_NAV) | curses.A_BOLD)
                elif ftype == "form_action":
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0+2, fl,
                                  curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                elif f.editable:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0+2, fl, curses.color_pair(_C_FIELD_LABEL))
                    val_text = f.value if f.value else "(empty — press Enter to edit)"
                    stdscr.addstr(y, x0+2+lbl_w+2, val_text[:width - lbl_w - 5],
                                  curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD)
                else:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0+2, fl, curses.color_pair(_C_DIM) | curses.A_DIM)
            except curses.error:
                pass

        if self._create_error and self._mode != self._EDIT:
            _draw_bar(stdscr, rows - 1, x0, width, f" ⚠  {self._create_error} ", dim=False)
        else:
            n_fields = len(self._create_fields)
            pos      = f"[{self._create_cursor + 1}/{n_fields}]"
            _draw_bar(
                stdscr, rows - 1, x0, width,
                f" {pos}  ↑↓/j·k  Enter: edit/select  Esc: cancel ",
                dim=True,
            )

    def _on_create(self, key: int, rows: int) -> None:
        n      = len(self._create_fields)
        list_h = rows - 2
        self._create_error = ""

        if key in (curses.KEY_UP, ord("k")):
            self._create_cursor = max(0, self._create_cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._create_cursor = min(n - 1, self._create_cursor + 1)
        elif key in (curses.KEY_HOME, ord("g")):
            self._create_cursor = 0
        elif key in (curses.KEY_END, ord("G")):
            self._create_cursor = n - 1
        elif key == 4:
            self._create_cursor = min(n - 1, self._create_cursor + list_h // 2)
        elif key == 21:
            self._create_cursor = max(0, self._create_cursor - list_h // 2)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= self._create_cursor < n:
                f = self._create_fields[self._create_cursor]
                if f.editable:
                    self._edit_field       = f
                    self._edit_value       = f.value
                    self._edit_pos         = len(f.value)
                    self._edit_return_mode = self._CREATE
                    self._mode             = self._EDIT
                elif f.meta.get("type") == "form_action":
                    act = f.meta.get("action")
                    if act == "submit":
                        self._submit_create()
                    elif act == "cancel":
                        self._mode = self._create_return_mode
        elif key == 27:   # Esc — cancel
            self._mode = self._create_return_mode

    def _submit_create(self) -> None:
        import re
        name         = ""
        pref_labels: dict[str, str] = {}
        definitions: dict[str, str] = {}

        for f in self._create_fields:
            fld = f.meta.get("field")
            if fld == "name":
                name = f.value.strip()
            elif fld == "pref" and f.value.strip():
                pref_labels[f.meta["lang"]] = f.value.strip()
            elif fld == "def" and f.value.strip():
                definitions[f.meta["lang"]] = f.value.strip()

        if not name:
            self._create_error = "Concept name is required"
            return

        if (self._create_parent_uri
                and self._create_parent_uri in self.taxonomy.schemes):
            s    = self.taxonomy.schemes[self._create_parent_uri]
            base = s.base_uri or self.taxonomy.base_uri()
        else:
            base = self.taxonomy.base_uri()
        new_uri = base + name

        if new_uri in self.taxonomy.concepts:
            self._create_error = f"'{name}' already exists"
            return

        if not pref_labels:
            label = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
            pref_labels[self.lang] = label

        parent_handle = None
        if self._create_parent_uri:
            parent_handle = (
                self.taxonomy.uri_to_handle(self._create_parent_uri)
                or self._create_parent_uri
            )

        try:
            operations.add_concept(
                self.taxonomy, new_uri, pref_labels,
                parent_handle=parent_handle,
                definitions=definitions if definitions else None,
            )
        except SkostaxError as exc:
            self._create_error = str(exc)
            return

        self._rebuild()
        self._save_file()

        # Navigate to the new concept detail
        for i, line in enumerate(self._flat):
            if line.uri == new_uri:
                self._cursor = i
                break
        self._detail_uri    = new_uri
        self._detail_fields = build_detail_fields(self.taxonomy, new_uri, self.lang)
        self._field_cursor  = 0
        self._detail_scroll = 0
        self._history.clear()
        self._mode = self._DETAIL

    # ─────────────────────────── SCHEME CREATE mode ──────────────────────────

    def _build_scheme_create_fields(self) -> "list[DetailField]":
        return [
            DetailField(
                "sc_form:title", f"title [{self.lang}]", "", editable=True,
                meta={"type": "sc_form", "field": "title"},
            ),
            DetailField(
                "sc_form:uri", "URI", "", editable=True,
                meta={"type": "sc_form", "field": "uri"},
            ),
            DetailField(
                "sc_form:base_uri", "base URI", "", editable=True,
                meta={"type": "sc_form", "field": "base_uri"},
            ),
            DetailField(
                "sc_form:submit", "✓  Create scheme", "", editable=False,
                meta={"type": "form_action", "action": "submit_scheme"},
            ),
            DetailField(
                "sc_form:cancel", "✗  Cancel", "", editable=False,
                meta={"type": "form_action", "action": "cancel"},
            ),
        ]

    def _draw_scheme_create(
        self, stdscr: "curses.window", rows: int, cols: int
    ) -> None:
        stdscr.erase()
        wide      = cols >= self._SPLIT_MIN_COLS
        tree_w    = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w  = cols - tree_w
        if wide:
            self._adjust_tree_scroll(rows)
            self._render_tree_col(stdscr, rows, 0, tree_w, cursor_idx=self._cursor)
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass
        self._render_scheme_create_col(stdscr, rows, detail_x0, detail_w)
        self._draw_help_hint(stdscr, cols)
        stdscr.refresh()

    def _render_scheme_create_col(
        self, stdscr: "curses.window", rows: int, x0: int, width: int
    ) -> None:
        if self._mode == self._EDIT:
            _draw_bar(stdscr, 0, x0, width,
                           " ^A:start  ^E:end  ^W:del-word  ^K:kill-end"
                           "  Enter:save  Esc:cancel ", dim=True)
        else:
            _draw_bar(stdscr, 0, x0, width, " ◉ New Concept Scheme ", dim=False)

        list_h = rows - 2
        n      = len(self._scheme_create_fields)

        if self._scheme_create_cursor < self._scheme_create_scroll:
            self._scheme_create_scroll = self._scheme_create_cursor
        elif self._scheme_create_cursor >= self._scheme_create_scroll + list_h:
            self._scheme_create_scroll = self._scheme_create_cursor - list_h + 1

        lbl_w = 18
        for row in range(list_h):
            idx = self._scheme_create_scroll + row
            if idx >= n:
                break
            f   = self._scheme_create_fields[idx]
            sel = idx == self._scheme_create_cursor
            fl  = f.display[:lbl_w].ljust(lbl_w)
            fv  = f.value
            ftype = f.meta.get("type")
            y   = row + 1
            try:
                if sel:
                    line = f"  {fl}  {fv}"
                    stdscr.addstr(y, x0, line.ljust(width - 1)[:width - 1],
                                  curses.color_pair(_C_SEL_NAV) | curses.A_BOLD)
                elif ftype == "form_action":
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl,
                                  curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                elif f.editable:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_FIELD_LABEL))
                    val_text = f.value if f.value else "(empty — press Enter to edit)"
                    stdscr.addstr(y, x0 + 2 + lbl_w + 2,
                                  val_text[:width - lbl_w - 5],
                                  curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD)
            except curses.error:
                pass

        if self._scheme_create_error and self._mode != self._EDIT:
            _draw_bar(stdscr, rows - 1, x0, width,
                           f" ⚠  {self._scheme_create_error} ", dim=False)
        else:
            pos = f"[{self._scheme_create_cursor + 1}/{n}]"
            _draw_bar(stdscr, rows - 1, x0, width,
                           f" {pos}  ↑↓/j·k  Enter: edit/select  Esc: cancel ",
                           dim=True)

    def _on_scheme_create(self, key: int, rows: int) -> None:
        n      = len(self._scheme_create_fields)
        list_h = rows - 2
        self._scheme_create_error = ""

        if key in (curses.KEY_UP, ord("k")):
            self._scheme_create_cursor = max(0, self._scheme_create_cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._scheme_create_cursor = min(n - 1, self._scheme_create_cursor + 1)
        elif key in (curses.KEY_HOME, ord("g")):
            self._scheme_create_cursor = 0
        elif key in (curses.KEY_END, ord("G")):
            self._scheme_create_cursor = n - 1
        elif key == 4:
            self._scheme_create_cursor = min(n - 1, self._scheme_create_cursor + list_h // 2)
        elif key == 21:
            self._scheme_create_cursor = max(0, self._scheme_create_cursor - list_h // 2)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= self._scheme_create_cursor < n:
                f = self._scheme_create_fields[self._scheme_create_cursor]
                if f.editable:
                    self._edit_field       = f
                    self._edit_value       = f.value
                    self._edit_pos         = len(f.value)
                    self._edit_return_mode = self._SCHEME_CREATE
                    self._mode             = self._EDIT
                elif f.meta.get("type") == "form_action":
                    act = f.meta.get("action")
                    if act == "submit_scheme":
                        self._submit_scheme_create()
                    elif act == "cancel":
                        self._mode = self._create_return_mode
        elif key == 27:  # Esc — cancel
            self._mode = self._create_return_mode

    def _submit_scheme_create(self) -> None:
        title    = ""
        uri      = ""
        base_uri = ""

        for f in self._scheme_create_fields:
            fld = f.meta.get("field")
            if fld == "title":
                title = f.value.strip()
            elif fld == "uri":
                uri = f.value.strip()
            elif fld == "base_uri":
                base_uri = f.value.strip()

        if not title:
            self._scheme_create_error = "Title is required"
            return
        if not uri:
            self._scheme_create_error = "URI is required"
            return
        if "://" not in uri:
            self._scheme_create_error = "URI must be a full URL (e.g. https://…)"
            return
        if uri in self.taxonomy.schemes:
            self._scheme_create_error = f"Scheme URI already exists"
            return

        if base_uri and not base_uri.endswith(("/", "#")):
            base_uri += "/"

        try:
            operations.create_scheme(
                self.taxonomy,
                uri,
                labels={self.lang: title},
                base_uri=base_uri,
                languages=[self.lang],
            )
        except SkostaxError as exc:
            self._scheme_create_error = str(exc)
            return

        self._rebuild()
        self._save_file()

        # Navigate to the new scheme detail
        for i, line in enumerate(self._flat):
            if line.uri == uri:
                self._cursor = i
                break
        self._detail_uri    = uri
        self._detail_fields = build_scheme_fields(
            self.taxonomy, self.lang, scheme_uri=uri
        )
        self._field_cursor  = 0
        self._detail_scroll = 0
        self._history.clear()
        self._mode = self._DETAIL

    # ─────────────────────────── CONFIRM DELETE mode ─────────────────────────

    def _draw_confirm(self, stdscr: "curses.window", rows: int, cols: int) -> None:
        stdscr.erase()
        wide      = cols >= self._SPLIT_MIN_COLS
        tree_w    = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w  = cols - tree_w
        if wide:
            if self._detail_uri:
                for i, line in enumerate(self._flat):
                    if line.uri == self._detail_uri:
                        self._cursor = i
                        break
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr, rows, 0, tree_w,
                cursor_idx=self._cursor,
                highlight_uri=self._detail_uri,
            )
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass
        self._render_confirm_col(stdscr, rows, detail_x0, detail_w)
        self._draw_help_hint(stdscr, cols)
        stdscr.refresh()

    def _render_confirm_col(
        self, stdscr: "curses.window", rows: int, x0: int, width: int
    ) -> None:
        concept = (
            self.taxonomy.concepts.get(self._detail_uri) if self._detail_uri else None
        )
        if not concept:
            return
        handle     = self.taxonomy.uri_to_handle(self._detail_uri) or "?"
        label      = concept.pref_label(self.lang) or self._detail_uri or ""
        n_children = len(concept.narrower)

        _draw_bar(stdscr, 0, x0, width, " ⊘ Confirm deletion ", dim=False)

        y = 2
        try:
            info = f"  [{handle}]  {label}"
            stdscr.addstr(y, x0, info[:width - 1],
                          curses.color_pair(_C_SEL) | curses.A_BOLD)
            y += 1
            uri_line = f"  {self._detail_uri}"
            stdscr.addstr(y, x0, uri_line[:width - 1],
                          curses.color_pair(_C_DIM) | curses.A_DIM)
            y += 2

            if n_children:
                total = len(operations._subtree_uris(self.taxonomy, self._detail_uri))
                sub   = f"subconcept{'s' if total != 1 else ''}"
                stdscr.addstr(
                    y, x0,
                    f"  This concept has {n_children} direct and {total} total {sub}."[:width-1],
                    curses.color_pair(_C_FIELD_VAL),
                )
                y += 1
                stdscr.addstr(
                    y, x0,
                    f"  All {total} {sub} will also be deleted."[:width-1],
                    curses.color_pair(_C_FIELD_VAL),
                )
                y += 2
                stdscr.addstr(y, x0,
                    "  y / Enter  — delete concept and all subconcepts"[:width-1],
                    curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
            else:
                stdscr.addstr(y, x0,
                    "  y / Enter  — confirm delete"[:width-1],
                    curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
            y += 1
            stdscr.addstr(y, x0,
                "  n / Esc    — cancel"[:width-1],
                curses.color_pair(_C_DIM))
        except curses.error:
            pass

        has_children = n_children > 0
        if has_children:
            footer = " y/Enter: delete with all subconcepts   n/Esc: cancel "
        else:
            footer = " y/Enter: confirm delete   n/Esc: cancel "
        _draw_bar(stdscr, rows - 1, x0, width, footer, dim=True)

    def _on_confirm_delete(self, key: int) -> None:
        if key in (ord("y"), curses.KEY_ENTER, ord("\n"), ord("\r")):
            concept     = self.taxonomy.concepts.get(self._detail_uri) if self._detail_uri else None
            has_children = bool(concept and concept.narrower)
            try:
                operations.remove_concept(
                    self.taxonomy, self._detail_uri, cascade=has_children
                )
            except SkostaxError as exc:
                self._status = str(exc)
                self._mode   = self._DETAIL
                return
            self._rebuild()
            self._save_file()
            self._history.clear()
            self._cursor = min(self._cursor, max(0, len(self._flat) - 1))
            self._mode   = self._TREE
        elif key in (ord("n"), 27):
            self._mode = self._DETAIL

    # ─────────────────────────── MOVE PICK mode ──────────────────────────────

    def _build_move_candidates(self, source_uri: str) -> "list[tuple[str,str]]":
        excluded   = operations._subtree_uris(self.taxonomy, source_uri)
        candidates: list[tuple[str, str]] = [("__TOP__", "↑  (top level)")]
        for line in self._flat:
            if line.uri not in excluded:
                concept = self.taxonomy.concepts.get(line.uri)
                if concept:
                    handle = self.taxonomy.uri_to_handle(line.uri) or "?"
                    label  = concept.pref_label(self.lang) or line.uri
                    indent = "  " * line.depth
                    candidates.append((line.uri, f"{indent}[{handle}]  {label}"))
        return candidates

    def _filtered_move_candidates(self) -> "list[tuple[str,str]]":
        flt = self._move_filter.lower()
        return [(u, d) for u, d in self._move_candidates
                if not flt or flt in d.lower()]

    def _draw_move(
        self, stdscr: "curses.window", rows: int, cols: int,
        title: str = "",
    ) -> None:
        stdscr.erase()
        wide      = cols >= self._SPLIT_MIN_COLS
        tree_w    = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w  = cols - tree_w
        highlight = self._move_source_uri or self._link_source_uri
        if wide:
            if highlight:
                for i, line in enumerate(self._flat):
                    if line.uri == highlight:
                        self._cursor = i
                        break
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr, rows, 0, tree_w,
                cursor_idx=self._cursor,
                highlight_uri=highlight,
            )
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass
        self._render_move_col(stdscr, rows, detail_x0, detail_w, title=title)
        self._draw_help_hint(stdscr, cols)
        stdscr.refresh()

    def _render_move_col(
        self, stdscr: "curses.window", rows: int, x0: int, width: int,
        title: str = "",
    ) -> None:
        source_uri    = self._move_source_uri or self._link_source_uri
        source_handle = self.taxonomy.uri_to_handle(source_uri) or "?"
        if not title:
            title = f" ↷ Move [{source_handle}] — select new parent "
        _draw_bar(stdscr, 0, x0, width, title, dim=False)

        # Filter bar at row 1
        filter_prompt = f" Filter: {self._move_filter}▌"
        try:
            stdscr.addstr(1, x0, filter_prompt[:width - 1].ljust(width - 1),
                          curses.color_pair(_C_EDIT_BAR) | curses.A_BOLD)
        except curses.error:
            pass

        filtered = self._filtered_move_candidates()
        list_h   = rows - 3  # title + filter + footer

        # Clamp + scroll
        if filtered:
            self._move_cursor = min(self._move_cursor, len(filtered) - 1)
        if self._move_cursor < self._move_scroll:
            self._move_scroll = self._move_cursor
        elif self._move_cursor >= self._move_scroll + list_h:
            self._move_scroll = self._move_cursor - list_h + 1

        for row in range(list_h):
            idx = self._move_scroll + row
            if idx >= len(filtered):
                break
            uri, display = filtered[idx]
            sel  = idx == self._move_cursor
            text = f"  {display}"
            y    = row + 2
            try:
                if sel:
                    stdscr.addstr(y, x0, text[:width - 1].ljust(width - 1),
                                  curses.color_pair(_C_SEL) | curses.A_BOLD)
                elif uri == "__TOP__":
                    stdscr.addstr(y, x0, text[:width - 1],
                                  curses.color_pair(_C_DIM) | curses.A_BOLD)
                else:
                    stdscr.addstr(y, x0, text[:width - 1])
            except curses.error:
                pass

        is_link = bool(self._link_source_uri) and self._mode == self._LINK_PICK
        source_uri = self._link_source_uri if is_link else self._move_source_uri
        source = self.taxonomy.concepts.get(source_uri)
        if not is_link and source and source.narrower:
            total    = len(operations._subtree_uris(self.taxonomy, source_uri))
            sub_note = f" — moves {total} subconcept{'s' if total != 1 else ''} too"
        else:
            sub_note = ""
        action_verb = "link here" if is_link else "move here"
        _draw_bar(
            stdscr, rows - 1, x0, width,
            f" ↑↓: navigate  Enter: {action_verb}{sub_note}  Esc: cancel  type to filter ",
            dim=True,
        )

    def _on_move_pick(self, key: int, rows: int) -> None:
        filtered = self._filtered_move_candidates()
        n        = len(filtered)
        list_h   = rows - 3

        if key == curses.KEY_UP:
            self._move_cursor = max(0, self._move_cursor - 1)
        elif key == curses.KEY_DOWN:
            self._move_cursor = min(n - 1, self._move_cursor + 1)
        elif key == curses.KEY_PPAGE:
            self._move_cursor = max(0, self._move_cursor - list_h)
        elif key == curses.KEY_NPAGE:
            self._move_cursor = min(n - 1, self._move_cursor + list_h)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= self._move_cursor < n:
                uri, _ = filtered[self._move_cursor]
                self._confirm_move(None if uri == "__TOP__" else uri)
        elif key == 27:  # Esc
            self._mode          = self._DETAIL
            self._detail_uri    = self._move_source_uri
            self._detail_fields = build_detail_fields(
                self.taxonomy, self._detail_uri, self.lang
            )
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if self._move_filter:
                self._move_filter = self._move_filter[:-1]
                self._move_cursor = 0
                self._move_scroll = 0
        elif 32 <= key < 256:
            self._move_filter += chr(key)
            self._move_cursor  = 0
            self._move_scroll  = 0

    def _confirm_move(self, target_uri: "str | None") -> None:
        try:
            operations.move_concept(self.taxonomy, self._move_source_uri, target_uri)
        except SkostaxError as exc:
            self._status        = str(exc)
            self._mode          = self._DETAIL
            self._detail_uri    = self._move_source_uri
            self._detail_fields = build_detail_fields(
                self.taxonomy, self._detail_uri, self.lang
            )
            return
        self._rebuild()
        self._save_file()
        for i, line in enumerate(self._flat):
            if line.uri == self._move_source_uri:
                self._cursor = i
                break
        self._detail_uri    = self._move_source_uri
        self._detail_fields = build_detail_fields(
            self.taxonomy, self._move_source_uri, self.lang
        )
        self._field_cursor  = 0
        self._history.clear()
        self._mode = self._DETAIL

    def _on_link_pick(self, key: int, rows: int) -> None:
        filtered = self._filtered_move_candidates()
        n        = len(filtered)
        list_h   = rows - 3

        if key == curses.KEY_UP:
            self._move_cursor = max(0, self._move_cursor - 1)
        elif key == curses.KEY_DOWN:
            self._move_cursor = min(n - 1, self._move_cursor + 1)
        elif key == curses.KEY_PPAGE:
            self._move_cursor = max(0, self._move_cursor - list_h)
        elif key == curses.KEY_NPAGE:
            self._move_cursor = min(n - 1, self._move_cursor + list_h)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= self._move_cursor < n:
                uri, _ = filtered[self._move_cursor]
                self._confirm_link(uri)
        elif key == 27:  # Esc
            back_uri = self._link_source_uri or self._detail_uri
            self._link_source_uri = ""
            self._mode          = self._DETAIL
            self._detail_uri    = back_uri
            if self._detail_uri:
                self._detail_fields = build_detail_fields(
                    self.taxonomy, self._detail_uri, self.lang
                )
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if self._move_filter:
                self._move_filter = self._move_filter[:-1]
                self._move_cursor = 0
                self._move_scroll = 0
        elif 32 <= key < 256:
            self._move_filter += chr(key)
            self._move_cursor  = 0
            self._move_scroll  = 0

    def _confirm_link(self, target_uri: str) -> None:
        src = self._link_source_uri
        self._link_source_uri = ""
        try:
            operations.add_broader_link(self.taxonomy, src, target_uri)
        except SkostaxError as exc:
            self._status        = str(exc)
            self._mode          = self._DETAIL
            self._detail_uri    = src
            self._detail_fields = build_detail_fields(self.taxonomy, src, self.lang)
            return
        self._rebuild()
        self._save_file()
        for i, line in enumerate(self._flat):
            if line.uri == src:
                self._cursor = i
                break
        self._detail_uri    = src
        self._detail_fields = build_detail_fields(self.taxonomy, src, self.lang)
        self._field_cursor  = 0
        self._history.clear()
        self._mode = self._DETAIL

    # ─────────────────────────── LANG PICK mode ──────────────────────────────

    def _draw_lang_pick(self, stdscr: "curses.window", rows: int, cols: int) -> None:
        stdscr.erase()
        self._render_lang_col(stdscr, rows, 0, cols)
        self._draw_help_hint(stdscr, cols)
        stdscr.refresh()

    def _render_lang_col(
        self, stdscr: "curses.window", rows: int, x0: int, width: int
    ) -> None:
        options  = self._lang_options
        n        = len(options)
        list_h   = rows - 2

        _draw_bar(stdscr, 0, x0, width,
                       " Select display language ", dim=False)

        # Scroll so cursor stays visible
        if self._lang_cursor < self._lang_scroll:
            self._lang_scroll = self._lang_cursor
        elif self._lang_cursor >= self._lang_scroll + list_h:
            self._lang_scroll = self._lang_cursor - list_h + 1

        for row in range(list_h):
            idx = self._lang_scroll + row
            if idx >= n:
                break
            code = options[idx]
            sel  = idx == self._lang_cursor
            is_current = code == self.lang
            marker = " ✓" if is_current else "  "
            text   = f"  {marker}  {code}"
            y      = row + 1
            if sel:
                attr = curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
            elif is_current:
                attr = curses.color_pair(_C_FIELD_LABEL) | curses.A_BOLD
            else:
                attr = curses.A_NORMAL
            try:
                stdscr.addstr(y, x0, text.ljust(width - 1)[:width - 1], attr)
            except curses.error:
                pass

        _draw_bar(stdscr, rows - 1, x0, width,
                       f" [{self._lang_cursor + 1}/{n}]  ↑↓: move  Enter: select  Esc: cancel ",
                       dim=True)

    def _on_lang_pick(self, key: int, rows: int) -> None:
        n      = len(self._lang_options)
        list_h = rows - 2

        if key in (curses.KEY_UP, ord("k")):
            self._lang_cursor = max(0, self._lang_cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._lang_cursor = min(n - 1, self._lang_cursor + 1)
        elif key in (curses.KEY_HOME, ord("g")):
            self._lang_cursor = 0
        elif key in (curses.KEY_END, ord("G")):
            self._lang_cursor = n - 1
        elif key == 4:   # Ctrl+D
            self._lang_cursor = min(n - 1, self._lang_cursor + list_h // 2)
        elif key == 21:  # Ctrl+U
            self._lang_cursor = max(0, self._lang_cursor - list_h // 2)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            chosen = self._lang_options[self._lang_cursor]
            self.lang = chosen
            _save_lang_pref(self.file_path, chosen)
            self._rebuild()
            self._status = f"Display language → {chosen}"
            # Refresh scheme detail fields so the value field updates
            if self._detail_uri and self._detail_uri in self.taxonomy.schemes:
                self._detail_fields = build_scheme_fields(self.taxonomy, self.lang)
                self._field_cursor  = 0
            self._mode = self._DETAIL
        elif key in (27, ord("q")):
            self._mode = self._DETAIL



# ──────────────────────────── TaxonomyShell (REPL) ───────────────────────────

class TaxonomyShell(Cmd):
    """Bash-like interactive REPL for taxonomy navigation and editing."""

    intro        = ""
    doc_header   = "Commands:"

    def __init__(self, taxonomy: Taxonomy, file_path: Path, lang: str = "en") -> None:
        super().__init__()
        self.taxonomy  = taxonomy
        self.file_path = file_path
        self.lang      = lang
        self._cwd: str | None = None
        self._update_prompt()
        try:
            import readline as rl
            rl.parse_and_bind("tab: complete")
        except ImportError:
            pass

    def _update_prompt(self) -> None:
        loc = "/" if self._cwd is None else f"[{self.taxonomy.uri_to_handle(self._cwd) or '?'}]"
        self.prompt = f"{loc} $ "

    def _save(self) -> None:
        try:
            store.save(self.taxonomy, self.file_path)
            console.print(f"[green]✓ Saved[/green]  {self.file_path}")
        except Exception as exc:
            err.print(f"[red]{exc}[/red]")

    def _run(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SkostaxError as exc:
            err.print(f"[red]{exc}[/red]")
            return None

    def _resolve(self, ref: str) -> str | None:
        try:
            return operations.resolve(self.taxonomy, ref)
        except SkostaxError:
            err.print(f"[red]Not found: {ref!r}[/red]")
            return None

    def _complete_handle(self, text: str) -> list[str]:
        return [h for h in self.taxonomy.handle_index if h.upper().startswith(text.upper())]

    # ── completions ───────────────────────────────────────────────────────────

    def complete_cd(self, text, line, begidx, endidx):
        extras = [".."] if not text or "..".startswith(text) else []
        return self._complete_handle(text) + extras

    def complete_ls(self, text, line, begidx, endidx):
        return self._complete_handle(text) + (["-l"] if not text or "-l".startswith(text) else [])

    def complete_info(self, t, l, b, e): return self._complete_handle(t)
    def complete_show(self, t, l, b, e): return self._complete_handle(t)
    def complete_rm(self, t, l, b, e):   return self._complete_handle(t)
    def complete_mv(self, t, l, b, e):   return self._complete_handle(t)
    def complete_label(self, t, l, b, e): return self._complete_handle(t)
    def complete_define(self, t, l, b, e): return self._complete_handle(t)

    # ── pwd ───────────────────────────────────────────────────────────────────

    def do_pwd(self, arg: str) -> None:
        """Show the current location.\n  pwd"""
        console.print(_breadcrumb(self.taxonomy, self._cwd))

    # ── ls ────────────────────────────────────────────────────────────────────

    def do_ls(self, arg: str) -> None:
        """List concepts at current location or a given handle.

  ls              list children of current location
  ls -l           detailed view
  ls HANDLE       list children of HANDLE
        """
        tokens  = arg.split()
        detailed = any(t in ("-l", "-la", "-al") for t in tokens)
        positional = [t for t in tokens if not t.startswith("-")]

        start = self._cwd
        if positional:
            uri = self._resolve(positional[0])
            if uri is None:
                return
            start = uri

        kids = _children(self.taxonomy, start)
        if not kids:
            console.print("[dim]No concepts here.[/dim]")
            return

        title = "/"
        if start:
            h = self.taxonomy.uri_to_handle(start) or "?"
            lbl = self.taxonomy.concepts[start].pref_label(self.lang)
            title = f"[{h}]  {lbl}"

        self._print_plain(kids, detailed, title)

    def _print_plain(self, uris: list[str], detailed: bool, title: str) -> None:
        console.print(f"\n[bold]{title}[/bold]\n")
        table = Table(box=None, padding=(0, 1))
        table.add_column("", no_wrap=True)
        table.add_column("Handle", style="dim cyan", no_wrap=True)
        table.add_column("Label")
        if detailed:
            table.add_column("↓", justify="right", style="cyan", no_wrap=True)
            table.add_column("↑", justify="right", style="dim",  no_wrap=True)
            table.add_column("~", justify="right", style="dim",  no_wrap=True)
            table.add_column("def", justify="center", style="dim", no_wrap=True)
        for uri in uris:
            c = self.taxonomy.concepts.get(uri)
            if not c:
                continue
            handle = self.taxonomy.uri_to_handle(uri) or "?"
            label  = c.pref_label(self.lang) or ""
            nav    = "▸" if c.narrower else " "
            lbl_cell = f"[bold cyan]{label}[/bold cyan]" if c.narrower else label
            if detailed:
                table.add_row(nav, f"[{handle}]", lbl_cell,
                              str(len(c.narrower)), str(len(c.broader)),
                              str(len(c.related)), "✓" if c.definitions else "·")
            else:
                table.add_row(nav, f"[{handle}]", lbl_cell)
        console.print(table)

    # ── cd ────────────────────────────────────────────────────────────────────

    def do_cd(self, arg: str) -> None:
        """Navigate to a concept.\n  cd HANDLE | cd .. | cd /"""
        target = arg.strip()
        if not target or target == "/":
            self._cwd = None
        elif target == "..":
            self._cwd = _parent_uri(self.taxonomy, self._cwd)
        else:
            uri = self._resolve(target)
            if uri is None:
                return
            if uri not in self.taxonomy.concepts:
                err.print(f"[red]Not a concept: {target!r}[/red]")
                return
            self._cwd = uri
        self._update_prompt()

    # ── show ──────────────────────────────────────────────────────────────────

    def do_show(self, arg: str) -> None:
        """Display the taxonomy tree.\n  show [HANDLE]"""
        target = arg.strip() or None
        root_h = None
        if target:
            uri = self._resolve(target)
            if uri is None:
                return
            root_h = self.taxonomy.uri_to_handle(uri) or target
        elif self._cwd:
            root_h = self.taxonomy.uri_to_handle(self._cwd)
        console.print(render_tree(self.taxonomy, root_handle=root_h, lang=self.lang))

    # ── info ──────────────────────────────────────────────────────────────────

    def do_info(self, arg: str) -> None:
        """Show full concept detail.\n  info [HANDLE]"""
        target = arg.strip()
        if not target:
            if self._cwd is None:
                err.print("[yellow]At root — specify a handle.[/yellow]")
                return
            uri = self._cwd
        else:
            uri = self._resolve(target)
            if uri is None:
                return
        console.print(render_concept_detail(self.taxonomy, uri, self.lang))

    # ── add ───────────────────────────────────────────────────────────────────

    def do_add(self, arg: str) -> None:
        """Add a concept (parent defaults to cwd).\n  add NAME [--en LABEL] [--fr LABEL] [--parent HANDLE]"""
        import shlex
        try:
            parts = shlex.split(arg)
        except ValueError as exc:
            err.print(f"[red]{exc}[/red]"); return

        if not parts:
            err.print("[yellow]Usage: add NAME [--en LABEL] [--parent HANDLE][/yellow]"); return

        name = parts[0]
        labels: dict[str, str] = {}
        parent_handle: str | None = None
        i = 1
        while i < len(parts):
            t = parts[i]
            if t in ("--en", "--fr") and i + 1 < len(parts):
                labels[t[2:]] = parts[i+1]; i += 2
            elif t == "--parent" and i + 1 < len(parts):
                parent_handle = parts[i+1]; i += 2
            else:
                i += 1

        if not labels:
            from .cli import _humanize
            labels[self.lang] = _humanize(name)
            console.print(f"[dim]No label — using default: {labels[self.lang]!r}[/dim]")

        if parent_handle is None and self._cwd is not None:
            parent_handle = self.taxonomy.uri_to_handle(self._cwd)

        uri = self._run(operations.expand_uri, self.taxonomy, name)
        if uri is None: return
        concept = self._run(operations.add_concept, self.taxonomy, uri, labels, parent_handle)
        if concept is None: return
        h = self.taxonomy.uri_to_handle(uri) or "?"
        console.print(f"[green]Added[/green]  [{h}]  {concept.pref_label(self.lang)}  [dim]({uri})[/dim]")
        self._save()

    # ── mv ────────────────────────────────────────────────────────────────────

    def do_mv(self, arg: str) -> None:
        """Move a concept.\n  mv HANDLE --parent NEW_PARENT | mv HANDLE /"""
        import shlex
        try:
            parts = shlex.split(arg)
        except ValueError as exc:
            err.print(f"[red]{exc}[/red]"); return

        if not parts:
            err.print("[yellow]Usage: mv HANDLE --parent NEW_PARENT[/yellow]"); return

        concept_ref = parts[0]
        new_parent_ref: str | None = None
        i = 1
        while i < len(parts):
            t = parts[i]
            if t == "--parent" and i + 1 < len(parts):
                new_parent_ref = parts[i+1]; i += 2
            elif t == "/":
                new_parent_ref = "/"; i += 1
            else:
                i += 1

        uri = self._resolve(concept_ref)
        if uri is None: return

        new_parent_uri: str | None = None
        if new_parent_ref and new_parent_ref != "/":
            new_parent_uri = self._resolve(new_parent_ref)
            if new_parent_uri is None: return

        self._run(operations.move_concept, self.taxonomy, uri, new_parent_uri)
        dest = (
            self.taxonomy.concepts[new_parent_uri].pref_label(self.lang)
            if new_parent_uri and new_parent_uri in self.taxonomy.concepts
            else "top level"
        )
        console.print(f"[green]Moved[/green]  {self.taxonomy.concepts[uri].pref_label(self.lang)}  →  {dest}")
        self._save()

    # ── rm ────────────────────────────────────────────────────────────────────

    def do_rm(self, arg: str) -> None:
        """Remove a concept.\n  rm HANDLE [--cascade] [-y]"""
        import shlex
        try:
            parts = shlex.split(arg)
        except ValueError as exc:
            err.print(f"[red]{exc}[/red]"); return

        if not parts:
            err.print("[yellow]Usage: rm HANDLE [--cascade] [-y][/yellow]"); return

        concept_ref = parts[0]
        cascade = "--cascade" in parts
        skip    = "-y" in parts or "--yes" in parts

        uri = self._resolve(concept_ref)
        if uri is None: return
        c = self.taxonomy.concepts.get(uri)
        if c is None:
            err.print(f"[red]Not found: {concept_ref!r}[/red]"); return

        if not skip:
            from rich.prompt import Confirm
            msg = f"Remove [bold]{c.pref_label(self.lang)}[/bold]"
            if cascade and c.narrower:
                msg += f" and its {len(c.narrower)} child(ren)"
            if not Confirm.ask(msg + "?"): return

        removed = self._run(operations.remove_concept, self.taxonomy, uri, cascade=cascade)
        if removed is None: return
        if self._cwd in removed:
            self._cwd = None
            self._update_prompt()
        console.print(f"[green]Removed[/green] {len(removed)} concept(s).")
        self._save()

    # ── label / define ────────────────────────────────────────────────────────

    def do_label(self, arg: str) -> None:
        """Set a label.\n  label HANDLE LANG \"Text\" [--alt]"""
        import shlex
        try:
            parts = shlex.split(arg)
        except ValueError as exc:
            err.print(f"[red]{exc}[/red]"); return

        alt   = "--alt" in parts
        parts = [p for p in parts if p != "--alt"]
        if len(parts) < 3:
            err.print("[yellow]Usage: label HANDLE LANG TEXT[/yellow]"); return
        uri = self._resolve(parts[0])
        if uri is None: return
        lang, text = parts[1], " ".join(parts[2:])
        self._run(operations.set_label, self.taxonomy, uri, lang, text,
                  LabelType.ALT if alt else LabelType.PREF)
        console.print(f"[green]Set {'alt' if alt else 'pref'} label[/green]  [{lang}]  {text}")
        self._save()

    def do_define(self, arg: str) -> None:
        """Set a definition.\n  define HANDLE LANG \"Text\"\""""
        import shlex
        try:
            parts = shlex.split(arg)
        except ValueError as exc:
            err.print(f"[red]{exc}[/red]"); return

        if len(parts) < 3:
            err.print("[yellow]Usage: define HANDLE LANG TEXT[/yellow]"); return
        uri = self._resolve(parts[0])
        if uri is None: return
        lang, text = parts[1], " ".join(parts[2:])
        self._run(operations.set_definition, self.taxonomy, uri, lang, text)
        console.print(f"[green]Set definition[/green]  [{lang}]")
        self._save()

    # ── quit ──────────────────────────────────────────────────────────────────

    def do_quit(self, arg: str) -> bool:
        """Exit the shell."""
        return True

    do_exit = do_quit
    do_q    = do_quit

    def do_EOF(self, arg: str) -> bool:
        print(); return True

    def default(self, line: str) -> None:
        cmd_ = line.split()[0] if line.split() else line
        err.print(f"[yellow]Unknown: {cmd_!r}  — type 'help' for commands.[/yellow]")

    def emptyline(self) -> None:
        pass
