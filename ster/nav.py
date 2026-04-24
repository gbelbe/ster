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
import os
import re
import signal
import sys
import threading
import traceback
from cmd import Cmd
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import analysis_cache, operations, store
from .display import console, render_concept_detail, render_tree
from .exceptions import SkostaxError
from .model import Definition, Label, LabelType, OWLIndividual, Taxonomy, is_builtin_uri
from .nav_logic import (  # noqa: F401
    _ACTION_ADD_SCHEME,
    _FILE_URI_PREFIX,
    _GLOBAL_URI,
    _OWL_ONTOLOGY_PREFIX,
    _OWL_SECTION_URI,
    _UNATTACHED_INDS_URI,
    DetailField,
    TreeLine,
    _available_langs,
    _breadcrumb,
    _children,
    _count_descendants,
    _effective_types,
    _file_sentinel,
    _flatten_taxonomy,
    _flatten_workspace,
    _is_ontology_sentinel,
    _ontology_sentinel,
    _parent_uri,
    _sep,
    build_concept_detail,
    build_detail_fields,
    build_file_fields,
    build_global_fields,
    build_individual_detail,
    build_ontology_overview_fields,
    build_promoted_detail,
    build_property_detail,
    build_rdf_class_detail,
    build_scheme_dashboard_fields,
    build_scheme_detail,
    build_scheme_fields,
    flatten_mixed_tree,
    flatten_ontology_tree,
    flatten_tree,
)
from .nav_state import (
    AiInstallState,
    AiSetupState,
    BatchConceptDraft,
    BatchCreateState,
    ClassToIndividualState,
    ConfirmDeleteState,
    CreateState,
    DetailState,
    EditState,
    IndividualToClassState,
    LangPickState,
    MapConceptPickState,
    MapSchemePickState,
    MovePickState,
    OntologySetupState,
    QueryState,
    SchemeCreateState,
    SearchState,
    TreeState,
    ViewerState,
    WelcomeState,
    navigate_detail,
    navigate_tree,
    search_update,
)
from .taxonomy_analysis import SchemeAnalysis
from .workspace import TaxonomyWorkspace

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
    stdscr.refresh()


# ──────────────────────────── TaxonomyViewer ─────────────────────────────────


class TaxonomyViewer:
    """Full-screen curses TUI for taxonomy navigation and inline editing."""

    # Minimum terminal width for side-by-side tree + detail
    _SPLIT_MIN_COLS = 120

    def __init__(
        self,
        taxonomy: Taxonomy,
        file_path: Path,
        lang: str = "en",
        git_manager: object | None = None,
        workspace: TaxonomyWorkspace | None = None,
    ) -> None:
        # Store workspace; if none provided, create a single-file workspace.
        if workspace is not None:
            self._workspace = workspace
        else:
            self._workspace = TaxonomyWorkspace.from_taxonomy(taxonomy, file_path)

        # self.taxonomy / self.file_path are the "primary" file for single-file ops.
        self.taxonomy = taxonomy
        self.file_path = file_path
        # Load persisted language preference; fall back to argument
        self.lang = _load_lang_pref(file_path) or lang
        self._git_manager = git_manager

        # ── persistent tree/detail backing (available across all modes) ───────
        self._flat: list[TreeLine] = []
        self._cursor = 0
        self._tree_scroll = 0

        self._detail_uri: str | None = None
        self._detail_fields: list[DetailField] = []
        self._field_cursor = 0
        self._detail_scroll = 0

        # ── search (backed in tree attrs, bridged to SearchState) ─────────────
        self._search_query = ""
        self._search_active = False  # True while typing in the search bar
        self._search_matches: list[int] = []  # indices into self._flat
        self._search_idx = 0  # which match the cursor is on
        self._search_pattern: re.Pattern | None = None

        # ── typed mode state ──────────────────────────────────────────────────
        # self._state identifies the current mode and carries mode-specific data.
        # Tree/detail persistent attrs (above) are accessible from all modes for
        # split-view rendering; all other modal data lives inside self._state.
        prefs = _load_prefs()
        self._state: ViewerState = WelcomeState() if not prefs.get("help_seen") else TreeState()

        self._history: list[dict] = []
        self._status = ""
        self._folded: set[str] = set()
        self._overview_folded: set[str] = set()
        self._view_mode: str = "mixed"  # "mixed" | "taxonomy" | "ontology"
        # scheme_uri → SchemeAnalysis; populated on first run() call
        self._analysis: dict[str, SchemeAnalysis] | None = None
        # AI install threading state
        self._install_thread: object = None  # threading.Thread | None
        self._install_output: list[str] = []  # thread appends here (GIL-safe)
        self._install_returncode: int | None = None
        self._install_spinner: int = 0
        self._install_package: str = "llm"  # package passed to pip install
        self._install_command: list[str] | None = None  # if set, overrides pip install
        self._generate_elapsed: float = 0.0  # seconds since current generation started
        self._last_query_buffer: str = ""  # persist query across mode switches

        self._rebuild()
        # Start with the global overview panel; cursor moves will update to item-specific detail
        self._detail_uri = _GLOBAL_URI
        self._detail_fields = self._bgf()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        if self._view_mode == "ontology":
            self._flat = flatten_ontology_tree(self._workspace, folded=self._folded)
        elif self._view_mode == "taxonomy":
            self._flat = flatten_tree(self._workspace, folded=self._folded)
        else:
            self._flat = flatten_mixed_tree(self._workspace, folded=self._folded)
        # Always keep self.taxonomy in sync with the workspace so mutations
        # made on workspace taxonomy objects are immediately reflected.
        if self._workspace.multiple_schemes() or len(self._workspace.taxonomies) > 1:
            self.taxonomy = self._workspace.merged_taxonomy()
        else:
            # Single-file: point at the workspace's own taxonomy object
            prim = self._workspace.taxonomies.get(self.file_path)
            if prim is not None:
                self.taxonomy = prim

    def _update_tree_preview(self) -> None:
        """Sync detail preview to the current tree cursor (called on every cursor move)."""
        if not (0 <= self._cursor < len(self._flat)):
            return  # keep current panel (global or last item)
        line = self._flat[self._cursor]
        if line.is_action:
            return  # keep current panel
        uri = line.uri
        if uri in (_OWL_SECTION_URI, _UNATTACHED_INDS_URI):
            return  # synthetic header — no detail panel
        if uri == self._detail_uri:
            return  # already previewing this concept
        self._detail_uri = uri
        if line.is_file and line.file_path:
            self._detail_fields = self._bff(line.file_path)
        elif _is_ontology_sentinel(uri):
            self._detail_fields = self._boof(line.file_path)
        elif line.is_scheme:
            self._detail_fields = self._bsf(uri)
        elif line.node_type == "property":
            self._detail_fields = self._bpropf(uri)
        elif line.node_type == "individual":
            self._detail_fields = self._bidf(uri)
        elif line.node_type == "promoted":
            self._detail_fields = self._bpdf(uri)
        elif line.node_type == "class" or (
            self._view_mode == "ontology" and uri in self.taxonomy.owl_classes
        ):
            self._detail_fields = self._bcdf(uri)
        else:
            self._detail_fields = self._bdf(uri)
        self._reset_detail_cursor()

    def _bdf(self, uri: str) -> list[DetailField]:
        """Build detail fields, enabling mapping actions when multiple schemes open."""
        return build_detail_fields(
            self.taxonomy,
            uri,
            self.lang,
            show_mappings=self._workspace.multiple_schemes(),
        )

    def _bcdf(self, uri: str) -> list[DetailField]:
        """Build OWL class detail fields."""
        return build_rdf_class_detail(self.taxonomy, uri, self.lang)

    def _bpdf(self, uri: str) -> list[DetailField]:
        """Build promoted node (concept + OWL class) detail fields."""
        return build_promoted_detail(
            self.taxonomy, uri, self.lang, show_mappings=self._workspace.multiple_schemes()
        )

    def _bidf(self, uri: str) -> list[DetailField]:
        """Build individual detail fields."""
        return build_individual_detail(self.taxonomy, uri, self.lang)

    def _boof(self, file_path: Path | None) -> list[DetailField]:
        """Build ontology overview fields."""
        tax = (
            self._workspace.taxonomies.get(file_path, self.taxonomy) if file_path else self.taxonomy
        )
        return build_ontology_overview_fields(
            tax, file_path, self.lang, folded=self._overview_folded
        )

    def _bpropf(self, uri: str) -> list[DetailField]:
        """Build OWL property detail fields."""
        return build_property_detail(self.taxonomy, uri, self.lang)

    def _bsf(self, scheme_uri: str) -> list[DetailField]:
        """Build scheme dashboard fields (settings + stats + issues)."""
        return build_scheme_dashboard_fields(self.taxonomy, self._analysis, scheme_uri, self.lang)

    def _bff(self, file_path: Path) -> list[DetailField]:
        """Build file dashboard fields (overview + per-scheme stats + actions)."""
        tax = self._workspace.taxonomies.get(file_path, self.taxonomy)
        return build_file_fields(tax, file_path, self._analysis, self.lang)

    def _bgf(self) -> list[DetailField]:
        """Build global overview fields (setup + shortcuts + stats + quality)."""
        return build_global_fields(self._workspace, self._analysis, self.lang)

    def _load_analysis(self) -> None:
        """Load analysis from cache (or compute and cache) for all workspace files."""
        if self._analysis is None:
            self._analysis = {}
        for path, tax in self._workspace.taxonomies.items():
            by_scheme = analysis_cache.get_or_compute(tax, path)
            self._analysis.update(by_scheme)

    def _refresh_analysis(self, file_path: Path | None = None) -> None:
        """Invalidate cache for *file_path* and recompute. Call after every save."""
        path = file_path or self.file_path
        analysis_cache.invalidate(path)
        tax = self._workspace.taxonomies.get(path, self.taxonomy)
        by_scheme = analysis_cache.get_or_compute(tax, path)
        if self._analysis is None:
            self._analysis = {}
        self._analysis.update(by_scheme)
        # Refresh whichever detail panel is currently open
        if self._detail_uri == _GLOBAL_URI:
            self._detail_fields = self._bgf()
        elif self._detail_uri and self._detail_uri in self.taxonomy.schemes:
            self._detail_fields = self._bsf(self._detail_uri)
        elif self._detail_uri and self._detail_uri.startswith(_FILE_URI_PREFIX):
            fp_str = self._detail_uri[len(_FILE_URI_PREFIX) :]
            self._detail_fields = self._bff(Path(fp_str))

    # ── tree-state bridge (scattered attrs ↔ TreeState for pure functions) ────

    def _as_tree_state(self) -> TreeState:
        """Snapshot current tree attrs into a TreeState for pure-function calls."""
        return TreeState(
            flat=self._flat,
            cursor=self._cursor,
            scroll=self._tree_scroll,
            folded=self._folded,
            search=SearchState(
                query=self._search_query,
                active=self._search_active,
                matches=self._search_matches,
                current_idx=self._search_idx,
                pattern=self._search_pattern,
            ),
            view_mode=self._view_mode,
        )

    def _sync_tree_state(self, ts: TreeState) -> None:
        """Write a TreeState back into the scattered tree attrs."""
        self._flat = ts.flat
        self._cursor = ts.cursor
        self._tree_scroll = ts.scroll
        self._folded = ts.folded
        self._view_mode = ts.view_mode
        self._search_query = ts.search.query
        self._search_active = ts.search.active
        self._search_matches = ts.search.matches
        self._search_idx = ts.search.current_idx
        self._search_pattern = ts.search.pattern

    def _push(self) -> None:
        self._history.append(
            {
                "cursor": self._cursor,
                "tree_scroll": self._tree_scroll,
                "detail_uri": self._detail_uri,
                "field_cursor": self._field_cursor,
                "detail_scroll": self._detail_scroll,
                "was_tree_state": isinstance(self._state, TreeState),
            }
        )

    def _pop(self) -> bool:
        if not self._history:
            return False
        s = self._history.pop()
        self._cursor = s["cursor"]
        self._tree_scroll = s["tree_scroll"]
        self._detail_uri = s["detail_uri"]
        self._field_cursor = s["field_cursor"]
        self._detail_scroll = s["detail_scroll"]
        if s.get("was_tree_state", False):
            # Came from tree preview — restore tree state and refresh preview
            self._state = TreeState()
            self._update_tree_preview()
        elif self._detail_uri:
            if self._detail_uri in self.taxonomy.schemes:
                self._detail_fields = self._bsf(self._detail_uri)
            else:
                self._detail_fields = self._bdf(self._detail_uri)
            self._state = DetailState()
        else:
            self._state = TreeState()
        return True

    def _individual_taxonomy_for(self, uri: str | None) -> tuple[Taxonomy, Path]:
        """Return (individual_taxonomy, path) owning *uri*, or primary file as fallback."""
        if uri and self._workspace:
            for path, tax in self._workspace.taxonomies.items():
                if uri in tax.concepts or uri in tax.schemes:
                    return tax, path
        prim_tax = self._workspace.taxonomies.get(self.file_path, self.taxonomy)
        return prim_tax, self.file_path

    def _save_file(
        self,
        uri: str | None = None,
        path: Path | None = None,
    ) -> None:
        """Save the file that owns *uri*, or *path* explicitly, or the primary file."""
        try:
            if path is not None:
                target_path = path
            elif uri and self._workspace:
                target_path = self._workspace.uri_to_file(uri) or self.file_path
            else:
                target_path = self.file_path
            target_tax = self._workspace.taxonomies.get(target_path, self.taxonomy)
            store.save(target_tax, target_path)
            self._status = f"Saved  {target_path.name}"
            if self._git_manager:
                self._git_manager.stage_file()  # type: ignore[attr-defined]
            self._refresh_analysis(target_path)
            from . import viz as _viz

            _viz.push_update(target_tax)
        except Exception as exc:
            self._status = f"Error saving: {exc}"

    def _open_detail(self) -> None:
        if not (0 <= self._cursor < len(self._flat)):
            return
        line = self._flat[self._cursor]
        if line.uri in (_OWL_SECTION_URI, _UNATTACHED_INDS_URI):
            return  # synthetic header — no detail panel
        self._push()
        if self._detail_uri != line.uri:
            self._detail_uri = line.uri
            if line.is_file and line.file_path:
                self._detail_fields = self._bff(line.file_path)
            elif _is_ontology_sentinel(line.uri):
                self._detail_fields = self._boof(line.file_path)
            elif line.is_scheme:
                self._detail_fields = self._bsf(line.uri)
            elif line.node_type == "property":
                self._detail_fields = self._bpropf(line.uri)
            elif line.node_type == "individual":
                self._detail_fields = self._bidf(line.uri)
            elif line.node_type == "promoted":
                self._detail_fields = self._bpdf(line.uri)
            elif line.node_type == "class" or (
                self._view_mode == "ontology" and line.uri in self.taxonomy.owl_classes
            ):
                self._detail_fields = self._bcdf(line.uri)
            else:
                self._detail_fields = self._bdf(line.uri)
            self._reset_detail_cursor()
        self._state = DetailState()

    def _back(self) -> None:
        if not self._pop():
            self._state = TreeState()

    # ── entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            console.print(render_tree(self.taxonomy, lang=self.lang))
            return

        import os as _os

        def _flush_stdin() -> None:
            try:
                import termios

                termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
            except Exception:
                pass

        # Recognise lone Escape quickly so it doesn't linger in ncurses'
        # internal buffer and leak into the next session.
        _os.environ.setdefault("ESCDELAY", "25")

        # ── Freeze detector ───────────────────────────────────────────────────
        # SIGUSR1: dump all thread stacks to freeze.log (send from another
        #          terminal with: kill -USR1 $(cat ~/.cache/ster/ster.pid))
        freeze_log = Path.home() / ".cache" / "ster" / "freeze.log"
        pid_file = Path.home() / ".cache" / "ster" / "ster.pid"
        freeze_log.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))

        def _dump_freeze(signum: int, frame: object) -> None:  # type: ignore[type-arg]
            with freeze_log.open("a") as _f:
                _f.write(f"\n{'=' * 60}\nFreeze dump (PID {os.getpid()})\n{'=' * 60}\n")
                for tid, stack in sys._current_frames().items():
                    _f.write(f"\n--- Thread {tid} ---\n")
                    traceback.print_stack(stack, file=_f)

        _prev_handler = signal.signal(signal.SIGUSR1, _dump_freeze)

        # ── Watchdog thread ───────────────────────────────────────────────────
        # The main loop sets _heartbeat to True on every iteration.
        # The watchdog resets it every 5 s; if it's already False when the
        # watchdog wakes up, the loop has been stuck for ≥ 5 s → dump stacks.
        self._heartbeat = True
        self._watchdog_active = True

        def _watchdog() -> None:
            while self._watchdog_active:
                threading.Event().wait(5.0)
                if not self._watchdog_active:
                    break
                if not self._heartbeat:
                    with freeze_log.open("a") as _f:
                        _f.write(
                            f"\n{'=' * 60}\nWatchdog: loop unresponsive for ≥5 s "
                            f"(PID {os.getpid()})\n{'=' * 60}\n"
                        )
                        for tid, stack in sys._current_frames().items():
                            _f.write(f"\n--- Thread {tid} ---\n")
                            traceback.print_stack(stack, file=_f)
                self._heartbeat = False

        _wd = threading.Thread(target=_watchdog, daemon=True, name="ster-watchdog")
        _wd.start()

        # Discard stale input from the picker before curses starts.
        _flush_stdin()
        try:
            curses.wrapper(self._loop)
        except KeyboardInterrupt:
            pass
        except Exception:
            log = Path.home() / ".cache" / "ster" / "crash.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a") as f:
                f.write(f"\n{'=' * 60}\n")
                traceback.print_exc(file=f)
            raise
        finally:
            self._watchdog_active = False
            signal.signal(signal.SIGUSR1, _prev_handler)
            try:
                pid_file.unlink(missing_ok=True)
            except Exception:
                pass
            # ncurses calls endwin() on exit, which may push any internally
            # buffered bytes (e.g. a second Escape) back to the OS input queue.
            # Flush them now, before control returns to the home-screen picker.
            _flush_stdin()

    def _loop(self, stdscr: curses.window) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        _init_colors()
        stdscr.keypad(True)

        if self._analysis is None:
            rows, cols = stdscr.getmaxyx()
            stdscr.erase()
            _draw_bar(stdscr, rows // 2, 0, cols, " Analysing taxonomy… ", dim=True)
            stdscr.refresh()
            self._load_analysis()
            # Refresh global panel now that analysis is available
            if self._detail_uri == _GLOBAL_URI:
                self._detail_fields = self._bgf()

        # Prompt for ontology identity if the file has no URI pyLODE can use
        if not self.taxonomy.ontology_uri and not self.taxonomy.schemes:
            slug = re.sub(r"[^a-z0-9]+", "-", self.file_path.stem.lower()).strip("-")
            suggested_uri = f"https://example.org/ontology/{slug}"
            self._state = OntologySetupState(
                name_buf=self.file_path.stem.replace("_", " ").replace("-", " ").title(),
                name_pos=len(self.file_path.stem),
                uri_buf=suggested_uri,
                uri_pos=len(suggested_uri),
            )

        while True:
            self._heartbeat = True
            rows, cols = stdscr.getmaxyx()

            if isinstance(self._state, OntologySetupState):
                self._draw_ontology_setup(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_ontology_setup(key)
                continue

            if isinstance(self._state, WelcomeState):
                self._draw_welcome(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                _save_prefs({"help_seen": True})
                self._state = TreeState()
                continue

            if isinstance(self._state, TreeState):
                if cols >= self._SPLIT_MIN_COLS and self._detail_uri is not None:
                    self._draw_tree_preview(stdscr, rows, cols)
                else:
                    self._draw_tree(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                if self._on_tree(key, rows):
                    break

            elif isinstance(self._state, DetailState):
                self._draw_split(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                if self._on_detail(key, rows):
                    break

            elif isinstance(self._state, EditState):
                es = self._state
                if isinstance(es.return_to, CreateState):
                    self._draw_create(stdscr, rows, cols)
                elif isinstance(es.return_to, SchemeCreateState):
                    self._draw_scheme_create(stdscr, rows, cols)
                else:
                    self._draw_split(stdscr, rows, cols)
                self._draw_edit_bar(stdscr, rows, cols)
                action = self._getch_edit(stdscr)
                if action == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_edit(action)

            elif isinstance(self._state, CreateState):
                if self._state.ai_generating:
                    self._run_generate(
                        stdscr,
                        self._create_ai_generate,
                        lambda r=rows, c=cols: self._draw_create(stdscr, r, c),
                    )
                else:
                    self._draw_create(stdscr, rows, cols)
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_create(key, rows)

            elif isinstance(self._state, BatchCreateState):
                bcs = self._state
                draft = bcs.drafts[bcs.current] if bcs.drafts else None
                if draft and draft.alts_generating:
                    self._run_generate(
                        stdscr,
                        self._batch_generate_alts,
                        lambda r=rows, c=cols: self._draw_batch(stdscr, r, c),
                    )
                elif draft and draft.def_generating:
                    self._run_generate(
                        stdscr,
                        self._batch_generate_def,
                        lambda r=rows, c=cols: self._draw_batch(stdscr, r, c),
                    )
                else:
                    self._draw_batch(stdscr, rows, cols)
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_batch(key, rows)

            elif isinstance(self._state, ConfirmDeleteState):
                self._draw_confirm(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_confirm_delete(key)

            elif isinstance(self._state, ClassToIndividualState):
                self._draw_class_to_individual_confirm(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_class_to_individual_confirm(key)

            elif isinstance(self._state, IndividualToClassState):
                self._draw_individual_to_class_confirm(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_individual_to_class_confirm(key)

            elif isinstance(self._state, MovePickState):
                ms = self._state
                if ms.pick_type == "add_related":
                    self._draw_move(stdscr, rows, cols, title=" ~ Add related concept ")
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_related_pick(key, rows)
                elif ms.pick_type == "link_superclass":
                    self._draw_move(stdscr, rows, cols, title=" ↑ Add superclass (subClassOf) ")
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_owl_pick(key, rows, replace=False)
                elif ms.pick_type == "move_class":
                    self._draw_move(stdscr, rows, cols, title=" ↷ Move under different superclass ")
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_owl_pick(key, rows, replace=True)
                elif ms.pick_type == "add_prop_domain":
                    self._draw_move(stdscr, rows, cols, title=" → Add domain class ")
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_prop_class_pick(key, rows, "domain")
                elif ms.pick_type == "add_prop_range":
                    self._draw_move(stdscr, rows, cols, title=" → Add range class ")
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_prop_class_pick(key, rows, "range")
                elif ms.pick_type == "add_prop_value_step1":
                    self._draw_move(stdscr, rows, cols, title=" → Select property ")
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_prop_value_step1(key, rows)
                elif ms.pick_type == "add_prop_value_grouped":
                    self._draw_move(
                        stdscr,
                        rows,
                        cols,
                        title=" → Select individual ",
                        empty_msg="No individuals available for this property",
                    )
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_prop_value_grouped(key, rows)
                elif ms.pick_type == "add_prop_value_step2":
                    self._draw_move(stdscr, rows, cols, title=" → Select destination class ")
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_prop_value_step2(key, rows)
                elif ms.pick_type == "add_prop_value_step3":
                    self._draw_move(
                        stdscr,
                        rows,
                        cols,
                        title=" → Select target individual ",
                        empty_msg="No individual available for this class",
                    )
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_prop_value_step3(key, rows)
                elif ms.pick_type == "add_ind_type":
                    self._draw_move(stdscr, rows, cols, title=" ◈ Add class membership (rdf:type) ")
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_ind_type_pick(key, rows)
                elif ms.is_link:
                    self._draw_move(
                        stdscr, rows, cols, title=" ↗ Link to broader — pick new parent "
                    )
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_link_pick(key, rows)
                else:
                    self._draw_move(stdscr, rows, cols)
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_move_pick(key, rows)

            elif isinstance(self._state, LangPickState):
                self._draw_lang_pick(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_lang_pick(key, rows)

            elif isinstance(self._state, SchemeCreateState):
                self._draw_scheme_create(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_scheme_create(key, rows)

            elif isinstance(self._state, MapSchemePickState):
                self._draw_map_scheme_pick(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_map_scheme_pick(key)

            elif isinstance(self._state, MapConceptPickState):
                self._draw_map_concept_pick(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_map_concept_pick(key, rows)

            elif isinstance(self._state, AiInstallState):
                if self._state.installing:
                    self._draw_ai_install(stdscr, rows, cols)
                    self._ai_install_poll()
                    curses.napms(120)  # short sleep so we animate without spinning 100% CPU
                elif self._state.done:
                    self._draw_ai_install(stdscr, rows, cols)
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_ai_install(key)
                else:
                    self._draw_ai_install(stdscr, rows, cols)
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_ai_install(key)

            elif isinstance(self._state, AiSetupState):
                _had_pending = bool(self._state.pending_action)
                if (
                    self._state.step in ("install_plugin", "ollama_pull")
                    and self._state.plugin_installing
                ):
                    self._draw_ai_setup(stdscr, rows, cols)
                    self._ai_plugin_poll()
                    curses.napms(120)
                else:
                    self._draw_ai_setup(stdscr, rows, cols)
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_ai_setup(key)
                    if not _had_pending and not isinstance(self._state, AiSetupState):
                        break

            elif isinstance(self._state, QueryState):
                if self._state.ai_generating:
                    self._run_generate(
                        stdscr,
                        self._generate_sparql_query,
                        lambda r=rows, c=cols: self._draw_query(stdscr, r, c),
                    )
                elif self._state.running:
                    self._run_generate(
                        stdscr,
                        self._execute_sparql_query,
                        lambda r=rows, c=cols: self._draw_query(stdscr, r, c),
                    )
                else:
                    self._draw_query(stdscr, rows, cols)
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    if self._on_query(key, rows, cols):
                        break

    # ─────────────────────────── WELCOME screen ──────────────────────────────

    def _draw_welcome(self, stdscr: curses.window, rows: int, cols: int) -> None:
        """Draw a centred floating help overlay."""
        from .help import SECTIONS

        stdscr.erase()

        scheme = self.taxonomy.primary_scheme()
        title = scheme.title(self.lang) if scheme else self.file_path.stem
        n_concepts = len(self.taxonomy.concepts)

        KEY_W = 26  # key column width inside the box

        # Build content rows: list of (text, kind)
        # kind: "info" | "blank" | "header" | "entry"
        content: list[tuple[str, str]] = [
            (
                f"  {title}  ·  {n_concepts} concept{'s' if n_concepts != 1 else ''}  ·  lang: {self.lang}",
                "info",
            ),
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
        _draw_bar(stdscr, box_y, box_x, box_w, " ster — Keyboard Shortcuts & Help ", dim=False)

        # Row 1: hint (dim reverse)
        _draw_bar(
            stdscr,
            box_y + 1,
            box_x,
            box_w,
            "  Press any key to continue  ·  ? to re-open  ",
            dim=True,
        )

        # Content rows
        visible = box_h - 3  # rows available between hint and bottom bar
        for i, (text, kind) in enumerate(content[:visible]):
            y = box_y + 2 + i
            if y >= rows - 1:
                break
            clipped = text[: box_w - 1].ljust(box_w - 1)
            if kind == "header":
                try:
                    stdscr.addstr(
                        y, box_x, clipped, curses.color_pair(_C_HELP_SECTION) | curses.A_BOLD
                    )
                except curses.error:
                    pass
            elif kind == "info":
                try:
                    stdscr.addstr(
                        y, box_x, clipped, curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD
                    )
                except curses.error:
                    pass
            elif kind == "entry":
                key_end = 2 + KEY_W  # indent(2) + key column
                key_part = text[:key_end]
                desc_part = text[key_end : box_w - 1]
                try:
                    stdscr.addstr(
                        y,
                        box_x,
                        key_part[: box_w - 1],
                        curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD,
                    )
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
            self._search_idx = 0
            return
        try:
            pat = re.compile(q, re.IGNORECASE)
        except re.error:
            pat = re.compile(re.escape(q), re.IGNORECASE)
        self._search_pattern = pat

        matches = [
            i for i, line in enumerate(self._flat) if pat.search(self._search_text(line.uri))
        ]
        self._search_matches = matches
        if matches:
            # Land on first match at-or-after current cursor
            for idx, m in enumerate(matches):
                if m >= self._cursor:
                    self._search_idx = idx
                    self._cursor = m
                    return
            self._search_idx = 0
            self._cursor = matches[0]
        else:
            self._search_idx = 0

    def _search_jump(self, delta: int) -> None:
        """Move to the next (+1) or previous (-1) search match."""
        if not self._search_matches:
            return
        self._search_idx = (self._search_idx + delta) % len(self._search_matches)
        self._cursor = self._search_matches[self._search_idx]

    def _render_line_with_match(
        self,
        stdscr: curses.window,
        y: int,
        x0: int,
        text: str,
        width: int,
        base_attr: int,
        is_current_match: bool = False,
    ) -> None:
        _render_line_with_match(stdscr, y, x0, text, width, base_attr, self._search_pattern)

    # ─────────────────────────── key reading ─────────────────────────────────

    def _getch_edit(self, stdscr: curses.window) -> int | str:
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

    def _tree_footer(self, rows: int, preview: bool = False) -> str:
        n = len(self._flat)
        pos = f"[{self._cursor + 1}/{n}]" if n else "[0/0]"
        has_children = False
        if 0 <= self._cursor < n:
            line = self._flat[self._cursor]
            if line.is_file:
                # Return early — simplified footer for file nodes
                at_top = self._cursor == 0
                at_bottom = self._cursor == n - 1
                jump_hint = (
                    "G: last" if at_top else ("g: first" if at_bottom else "g/G: first/last")
                )
                enter_hint = "Enter: focus detail" if preview else "Enter: detail"
                return (
                    f" ?: help  {pos}  ↑↓/j·k: move  {enter_hint}"
                    f"   Space: fold/unfold  {jump_hint}  q: quit "
                )
            elif self._view_mode == "ontology" or (
                self._view_mode == "mixed" and line.node_type == "class"
            ):
                has_children = any(
                    line.uri in cls.sub_class_of for cls in self.taxonomy.owl_classes.values()
                )
            else:
                concept = self.taxonomy.concepts.get(line.uri)
                has_children = bool(concept and concept.narrower)
        if preview:
            enter_hint = "Enter: focus detail"
        elif has_children:
            enter_hint = "→/Enter: expand"
        else:
            enter_hint = "→/Enter: detail"
        at_top = self._cursor == 0
        at_bottom = self._cursor == n - 1
        jump_hint = "G: last" if at_top else ("g: first" if at_bottom else "g/G: first/last")
        if self._search_matches:
            m_pos = f"[match {self._search_idx + 1}/{len(self._search_matches)}]"
            return (
                f" {pos}  {m_pos}  Tab/↓: next match  Shift+Tab/↑: prev  "
                f"Enter: open  /: new search  Esc: clear "
            )
        if self._view_mode == "mixed":
            mode_hint = "[Mixed]  Tab: taxonomy"
        elif self._view_mode == "taxonomy":
            mode_hint = "[Taxonomy]  Tab: ontology"
        else:
            mode_hint = "[Ontology]  Tab: mixed"
        return (
            f" ?: help  {pos}  ↑↓/j·k: move  {enter_hint}  ←/h: parent"
            f"   Space: fold  +: add  {jump_hint}  /: search  {mode_hint}  q: quit "
        )

    def _draw_tree_preview(self, stdscr: curses.window, rows: int, cols: int) -> None:
        """Wide-terminal tree view: tree on left, read-only detail preview on right."""
        stdscr.erase()
        tree_w = cols // 3
        detail_x0 = tree_w
        detail_w = cols - tree_w

        self._adjust_tree_scroll(rows)
        self._render_tree_col(stdscr, rows, 0, tree_w, self._cursor, highlight_uri=self._detail_uri)

        # Vertical separator
        for y in range(rows):
            try:
                stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
            except curses.error:
                pass

        # Detail preview (no footer — we draw the tree footer below)
        if self._detail_uri:
            self._render_detail_col(stdscr, rows, detail_x0, detail_w, show_footer=False)

        # Tree footer across full width
        if self._status:
            _draw_bar(stdscr, rows - 1, 0, cols, f" {self._status} ", dim=False)
            self._status = ""
        elif self._search_active:
            self._draw_search_bar(stdscr, rows - 1, 0, cols)
        else:
            _draw_bar(stdscr, rows - 1, 0, cols, self._tree_footer(rows, preview=True), dim=True)
        stdscr.refresh()

    def _draw_tree(self, stdscr: curses.window, rows: int, cols: int) -> None:
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
        stdscr.refresh()

    def _draw_search_bar(self, stdscr: curses.window, y: int, x0: int, width: int) -> None:
        """Render the live search input bar."""
        q = self._search_query
        n = len(self._search_matches)
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
            stdscr.addstr(y, x0, bar[: width - 1].ljust(width - 1), attr)
        except curses.error:
            pass

    def _render_tree_col(
        self,
        stdscr: curses.window,
        rows: int,
        x0: int,
        width: int,
        cursor_idx: int,
        highlight_uri: str | None,
    ) -> None:
        """Render the tree list into column [x0, x0+width)."""
        if self._view_mode == "ontology":
            title = "Ontology View"
        elif self._view_mode == "taxonomy":
            title = "Taxonomy View"
        else:
            title = "Global Ster View"
        render_tree_col(
            stdscr,
            self._flat,
            self.taxonomy,
            self.lang,
            rows,
            x0,
            width,
            self._tree_scroll,
            cursor_idx,
            header_title=title,
            highlight_uri=highlight_uri,
            search_pattern=self._search_pattern,
            search_matches=self._search_matches,
        )

    # ─────────────────────────── TREE events ─────────────────────────────────

    def _on_tree(self, key: int, rows: int) -> bool:
        n = len(self._flat)
        list_h = rows - 2

        # ── search: typing mode — delegate to search_update() ─────────────────
        if self._search_active:
            ts = self._as_tree_state()
            if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                # Commit: deactivate search, then open detail
                new_ts = search_update(ts, key)
                self._sync_tree_state(new_ts)
                self._open_detail()
                return False
            new_ts = search_update(ts, key)
            if new_ts.search.query != ts.search.query:
                # Query changed — recompute matches
                self._sync_tree_state(new_ts)
                self._update_search()
            else:
                self._sync_tree_state(new_ts)
            return False

        # ── search: results-visible, navigate matches ─────────────────────────
        if self._search_matches:
            if key == 9:  # Tab — next match
                self._search_jump(+1)
                return False
            if key == curses.KEY_BTAB:  # Shift+Tab — prev match
                self._search_jump(-1)
                return False
            if key == ord("n"):
                self._search_jump(+1)
                return False
            if key == ord("N"):
                self._search_jump(-1)
                return False
            if key == 27:  # Esc — clear results
                self._search_matches = []
                self._search_pattern = None
                self._search_query = ""
                return False

        # ── view mode cycle (Tab when not navigating search results) ─────────
        if key == 9 and not self._search_matches:  # Tab
            _cycle = {"mixed": "taxonomy", "taxonomy": "ontology", "ontology": "mixed"}
            new_mode = _cycle.get(self._view_mode, "mixed")
            self._view_mode = new_mode
            self._folded = set()
            self._rebuild()
            self._cursor = 0
            self._tree_scroll = 0
            self._update_tree_preview()
            _labels = {"mixed": "Mixed", "taxonomy": "Taxonomy", "ontology": "Ontology"}
            self._status = f"Switched to {_labels[new_mode]} view"
            return False

        # ── search trigger ────────────────────────────────────────────────────
        if key == ord("/"):
            self._search_active = True
            self._search_query = ""
            self._search_matches = []
            self._search_pattern = None
            self._search_idx = 0
            return False

        # ── standard navigation — delegate to navigate_tree() ────────────────
        ts = self._as_tree_state()
        new_ts = navigate_tree(ts, key, list_h)
        if new_ts is not ts:
            self._sync_tree_state(new_ts)
            self._update_tree_preview()
            return False

        # ── unhandled by navigate_tree — action keys ──────────────────────────
        if key == ord(" "):
            if 0 <= self._cursor < n:
                uri = self._flat[self._cursor].uri
                line = self._flat[self._cursor]
                if uri == _OWL_SECTION_URI:
                    return False  # synthetic header, not foldable
                has_children = False
                if uri == _UNATTACHED_INDS_URI:
                    has_children = any(
                        not any(t in self.taxonomy.owl_classes for t in ind.types)
                        for ind in self.taxonomy.owl_individuals.values()
                    )
                elif line.is_file:
                    has_children = True  # file nodes are always foldable
                elif line.is_scheme:
                    s = self.taxonomy.schemes.get(uri)
                    has_children = bool(s and s.top_concepts)
                elif self._view_mode == "ontology" or (
                    self._view_mode == "mixed" and line.node_type == "class"
                ):
                    has_children = any(
                        uri in cls.sub_class_of for cls in self.taxonomy.owl_classes.values()
                    ) or any(uri in ind.types for ind in self.taxonomy.owl_individuals.values())
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
                    self._update_tree_preview()

        elif key == ord("+"):
            # + on scheme row → add top concept; on concept row → add narrower concept
            if 0 <= self._cursor < n:
                line = self._flat[self._cursor]
                if line.is_scheme:
                    self._detail_uri = line.uri
                    self._detail_fields = self._bsf(line.uri)
                    self._trigger_action("add_top_concept")
                elif not line.is_file and not line.is_action:
                    self._detail_uri = line.uri
                    self._detail_fields = self._bdf(line.uri)
                    self._trigger_action("add_narrower")

        elif key in (curses.KEY_RIGHT, curses.KEY_ENTER, ord("\n"), ord("\r"), ord("l")):
            self._open_detail()

        elif key in (curses.KEY_LEFT, ord("h")):
            if 0 <= self._cursor < n:
                depth = self._flat[self._cursor].depth
                if depth > 0:
                    for i in range(self._cursor - 1, -1, -1):
                        if self._flat[i].depth == depth - 1:
                            self._cursor = i
                            break

        elif key == ord("G"):
            from . import viz as _viz

            try:
                out = _viz.open_in_browser(self.taxonomy, self.file_path)
                self._status = f"Graph opened in browser — {out}"
            except Exception as exc:
                self._status = f"Error opening graph: {exc}"

        elif key == ord("?"):
            self._state = WelcomeState()

        elif key in (ord("q"), ord("Q"), 27):
            return True

        return False

    # ─────────────────────────── DETAIL drawing ──────────────────────────────

    def _draw_split(self, stdscr: curses.window, rows: int, cols: int) -> None:
        stdscr.erase()

        wide = cols >= self._SPLIT_MIN_COLS
        tree_w = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w = cols - tree_w

        if wide:
            # Sync tree scroll so detail concept is visible
            if self._detail_uri:
                for i, line in enumerate(self._flat):
                    if line.uri == self._detail_uri:
                        self._cursor = i
                        break
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr,
                rows,
                0,
                tree_w,
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
        stdscr.refresh()

    def _render_detail_col(
        self, stdscr: curses.window, rows: int, x0: int, width: int, show_footer: bool = True
    ) -> None:
        is_global_detail = self._detail_uri == _GLOBAL_URI
        is_file_detail = bool(self._detail_uri and self._detail_uri.startswith(_FILE_URI_PREFIX))
        is_scheme_detail = bool(self._detail_uri and self._detail_uri in self.taxonomy.schemes)
        is_ontology_detail = bool(self._detail_uri and _is_ontology_sentinel(self._detail_uri))
        is_property_detail = bool(
            self._detail_uri and self._detail_uri in self.taxonomy.owl_properties
        )

        if is_global_detail:
            label = "Global Ster View"
            handle = None
        elif is_file_detail:
            # Derive file path from the sentinel URI
            fp_str = self._detail_uri[len(_FILE_URI_PREFIX) :]  # type: ignore[index]
            label = Path(fp_str).name
            handle = None
        elif is_ontology_detail:
            label = self.taxonomy.ontology_label or self.taxonomy.ontology_uri or "OWL Ontology"
            handle = None
        elif is_scheme_detail:
            scheme = self.taxonomy.schemes[self._detail_uri]  # type: ignore[index]
            label = scheme.title(self.lang)
            handle = None
        elif is_property_detail:
            prop = self.taxonomy.owl_properties[self._detail_uri]  # type: ignore[index]
            handle = self.taxonomy.uri_to_handle(self._detail_uri) if self._detail_uri else "?"
            label = prop.label(self.lang) or self._detail_uri or ""
        else:
            concept = self.taxonomy.concepts.get(self._detail_uri) if self._detail_uri else None
            rdf_class = (
                self.taxonomy.owl_classes.get(self._detail_uri) if self._detail_uri else None
            )
            individual = (
                self.taxonomy.owl_individuals.get(self._detail_uri) if self._detail_uri else None
            )
            if not concept and not rdf_class and not individual:
                return
            if concept:
                handle = self.taxonomy.uri_to_handle(self._detail_uri) if self._detail_uri else "?"
                label = concept.pref_label(self.lang) or self._detail_uri or ""
            elif individual:
                handle = self.taxonomy.uri_to_handle(self._detail_uri) if self._detail_uri else "?"
                label = individual.label(self.lang) or self._detail_uri or ""
            else:
                # Pure OWL class — no SKOS concept counterpart
                assert rdf_class is not None
                handle = None
                label = rdf_class.label(self.lang) or self._detail_uri or ""
        n_fields = len(self._detail_fields)
        _in_edit = isinstance(self._state, EditState)
        if _in_edit:
            title_bar = (
                " ^A:start  ^E:end  ^W:del-word  ^K:kill-end"
                "  Alt+←→/^←→:word-jump  Enter:save  Esc:cancel "
            )
        elif is_global_detail:
            counter = f" [{self._field_cursor + 1}/{n_fields}]" if n_fields else ""
            title_bar = f" ★ Global Ster View{counter} "
        elif is_file_detail:
            counter = f" [{self._field_cursor + 1}/{n_fields}]" if n_fields else ""
            title_bar = f" 📄 {label}{counter} "
        elif is_ontology_detail:
            counter = f" [{self._field_cursor + 1}/{n_fields}]" if n_fields else ""
            title_bar = f" ◉ {label}  [ontology overview]{counter} "
        elif is_scheme_detail:
            counter = f" [{self._field_cursor + 1}/{n_fields}]" if n_fields else ""
            title_bar = f" ◉ {label}  [scheme settings]{counter} "
        elif handle:
            counter = f" [{self._field_cursor + 1}/{n_fields}]" if n_fields else ""
            title_bar = f" [{handle}]  {label}{counter} "
        else:
            counter = f" [{self._field_cursor + 1}/{n_fields}]" if n_fields else ""
            title_bar = f" ○ {label}{counter} "
        _draw_bar(stdscr, 0, x0, width, title_bar, dim=_in_edit)

        list_h = rows - 2
        n_fields = len(self._detail_fields)

        if self._field_cursor < self._detail_scroll:
            self._detail_scroll = self._field_cursor
        elif self._field_cursor >= self._detail_scroll + list_h:
            self._detail_scroll = self._field_cursor - list_h + 1

        lbl_w = 20
        for row in range(list_h):
            idx = self._detail_scroll + row
            if idx >= n_fields:
                break
            f = self._detail_fields[idx]
            sel = idx == self._field_cursor

            is_sep = f.meta.get("type") == "separator"
            is_mapping = f.meta.get("type") == "mapping"
            is_map_remove = f.meta.get("type") == "mapping_remove"
            is_navigable = f.meta.get("nav") is True and not is_mapping
            is_action = f.meta.get("type") == "action"
            # Actions and separator labels can exceed lbl_w — use full display
            fl = (
                f.display
                if (is_action or is_sep or is_map_remove)
                else f.display[:lbl_w].ljust(lbl_w)
            )
            fv = f.value[: width - lbl_w - 5]
            y = row + 1

            try:
                if is_sep:
                    # Section header: " ── Label ──────────"
                    hdr = f" ── {f.display} "
                    line = hdr + "─" * max(0, width - len(hdr) - 1)
                    stdscr.addstr(
                        y, x0, line[: width - 1], curses.color_pair(_C_DIM) | curses.A_DIM
                    )
                elif sel:
                    line = f"  {fl}  {fv}"
                    stdscr.addstr(
                        y,
                        x0,
                        line.ljust(width - 1)[: width - 1],
                        curses.color_pair(_C_SEL_NAV) | curses.A_BOLD,
                    )
                elif is_action:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                elif is_map_remove:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_DIFF_DEL))
                elif is_mapping:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(
                        y,
                        x0 + 2,
                        fl[:lbl_w].ljust(lbl_w),
                        curses.color_pair(_C_MAPPING_NAV) | curses.A_BOLD,
                    )
                    stdscr.addstr(y, x0 + 2 + lbl_w + 2, fv, curses.color_pair(_C_MAPPING_NAV))
                elif is_navigable:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(
                        y,
                        x0 + 2,
                        fl[:lbl_w].ljust(lbl_w),
                        curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD,
                    )
                    stdscr.addstr(
                        y, x0 + 2 + lbl_w + 2, fv, curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD
                    )
                elif f.editable:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_FIELD_LABEL))
                    stdscr.addstr(
                        y, x0 + 2 + lbl_w + 2, fv, curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD
                    )
                elif f.meta.get("type") == "scheme_base_uri":
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_FIELD_LABEL))
                    stdscr.addstr(
                        y,
                        x0 + 2 + lbl_w + 2,
                        fv[: width - lbl_w - 5],
                        curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD,
                    )
                elif f.meta.get("type") == "scheme_uri":
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_DIM))
                    stdscr.addstr(
                        y,
                        x0 + 2 + lbl_w + 2,
                        fv[: width - lbl_w - 5],
                        curses.color_pair(_C_FIELD_VAL),
                    )
                elif f.meta.get("type") == "stat":
                    # Read-only stat row: dim label, bold value
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl[:lbl_w].ljust(lbl_w), curses.color_pair(_C_DIM))
                    if fv:
                        stdscr.addstr(
                            y,
                            x0 + 2 + lbl_w + 2,
                            fv[: width - lbl_w - 5],
                            curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD,
                        )
                elif f.meta.get("type") == "repair_mapping":
                    # Dim red "remove broken link" repair row
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(
                        y,
                        x0 + 2,
                        fl[:lbl_w].ljust(lbl_w),
                        curses.color_pair(_C_DIFF_DEL) | curses.A_DIM,
                    )
                    if fv:
                        stdscr.addstr(
                            y,
                            x0 + 2 + lbl_w + 2,
                            fv[: width - lbl_w - 5],
                            curses.color_pair(_C_DIM) | curses.A_DIM,
                        )
                elif f.meta.get("type") == "issue_nav":
                    # Colour-coded by severity; clickable when concept_uri present
                    sev = f.meta.get("severity", "info")
                    if sev == "error":
                        label_attr = curses.color_pair(_C_DIFF_DEL) | curses.A_BOLD
                    elif sev == "warning":
                        label_attr = curses.color_pair(_C_DIFF_CHG) | curses.A_BOLD
                    else:
                        label_attr = curses.color_pair(_C_DIM)
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl[:lbl_w].ljust(lbl_w), label_attr)
                    if fv:
                        stdscr.addstr(
                            y,
                            x0 + 2 + lbl_w + 2,
                            fv[: width - lbl_w - 5],
                            curses.color_pair(_C_DIM),
                        )
                else:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_DIM) | curses.A_DIM)
                    stdscr.addstr(
                        y, x0 + 2 + lbl_w + 2, fv, curses.color_pair(_C_DIM) | curses.A_DIM
                    )
            except curses.error:
                pass

        if show_footer and not isinstance(self._state, EditState):
            if self._status:
                _draw_bar(stdscr, rows - 1, x0, width, f" {self._status} ", dim=False)
                self._status = ""
            else:
                _draw_bar(stdscr, rows - 1, x0, width, self._detail_footer(), dim=True)

    # ─────────────────────────── DETAIL events ───────────────────────────────

    def _detail_footer(self) -> str:
        n = len(self._detail_fields)
        pos = f"[{self._field_cursor + 1}/{n}]" if n else "[0/0]"
        is_scheme_detail = bool(self._detail_uri and self._detail_uri in self.taxonomy.schemes)
        if 0 <= self._field_cursor < n:
            f = self._detail_fields[self._field_cursor]
            if f.meta.get("type") == "action":
                edit_hint = "Enter: execute"
            elif f.editable and not is_scheme_detail:
                edit_hint = "i/Enter: edit  -: delete val"
            elif f.editable:
                edit_hint = "i/Enter: edit"
            elif f.meta.get("type") == "mapping" and f.meta.get("nav"):
                edit_hint = "Enter: open"
            elif f.meta.get("type") in ("mapping", "mapping_remove"):
                edit_hint = "Enter/-: remove link"
            elif f.meta.get("type") == "repair_mapping":
                edit_hint = "Enter/-: remove broken link"
            elif f.meta.get("type") == "ind_prop_val" and f.meta.get("nav"):
                edit_hint = "Enter: open  e: edit value"
            elif f.meta.get("nav"):
                edit_hint = "Enter: open concept"
            elif f.meta.get("type") == "separator":
                edit_hint = ""
            elif f.meta.get("type") == "issue_nav" and f.meta.get("uri"):
                edit_hint = "Enter: jump to concept"
            elif f.meta.get("type") in ("stat", "issue_nav"):
                edit_hint = "(read-only)"
            else:
                edit_hint = "(read-only)"
        else:
            edit_hint = ""
        at_top = self._field_cursor == 0
        at_bottom = self._field_cursor == n - 1
        jump_hint = "G: last" if at_top else ("g: first" if at_bottom else "g/G: first/last")
        return (
            f" ?: help  {pos}  ↑↓/j·k  {edit_hint}  {jump_hint}"
            f"  m: move  b: broader  -: delete  ^D/^U  ←/Esc: back "
        )

    def _skip_sep(self, direction: int) -> None:
        """Advance cursor past any separator rows in the given direction (+1/-1)."""
        n = len(self._detail_fields)
        while (
            0 <= self._field_cursor < n
            and self._detail_fields[self._field_cursor].meta.get("type") == "separator"
        ):
            new_cursor = max(0, min(n - 1, self._field_cursor + direction))
            if new_cursor == self._field_cursor:
                break  # hit the boundary — no non-separator row in this direction
            self._field_cursor = new_cursor

    def _reset_detail_cursor(self) -> None:
        """Reset field cursor to first non-separator row."""
        self._field_cursor = 0
        self._detail_scroll = 0
        self._skip_sep(+1)

    def _on_detail(self, key: int, rows: int) -> bool:
        n = len(self._detail_fields)
        list_h = rows - 2

        # ── cursor movement — delegate to navigate_detail() ───────────────────
        ds = DetailState(
            uri=self._detail_uri or "",
            fields=self._detail_fields,
            field_cursor=self._field_cursor,
            scroll=self._detail_scroll,
        )
        new_ds = navigate_detail(ds, key, list_h)
        if new_ds is not ds:
            self._field_cursor = new_ds.field_cursor
            self._detail_scroll = new_ds.scroll
            # Preserve skip-separator logic after cursor move
            if key in (curses.KEY_UP, ord("k"), curses.KEY_PPAGE, 21):
                self._skip_sep(-1)
            else:
                self._skip_sep(+1)
            return False

        # ── action keys ───────────────────────────────────────────────────────
        if key in (curses.KEY_ENTER, ord("\n"), ord("\r"), ord("i"), ord("e")):
            if 0 <= self._field_cursor < n:
                f = self._detail_fields[self._field_cursor]
                if f.meta.get("type") == "action":
                    self._trigger_action(f.meta.get("action", ""), f.meta)
                elif f.meta.get("type") == "repair_mapping":
                    self._repair_mapping_field(f)
                elif f.meta.get("type") == "mapping_remove":
                    self._remove_mapping_field(f)
                elif f.editable:
                    self._state = EditState(
                        buffer=f.value,
                        pos=len(f.value),
                        field=f,
                        return_to=None,  # return to detail mode
                    )
                elif f.meta.get("type") == "issue_nav" and f.meta.get("uri"):
                    # Quality issue pointing to a concept — navigate there
                    dest_uri = f.meta["uri"]
                    if dest_uri in self.taxonomy.concepts:
                        self._push()
                        self._detail_uri = dest_uri
                        self._detail_fields = self._bdf(dest_uri)
                        self._reset_detail_cursor()
                elif f.meta.get("type") == "ind_prop_val":
                    if key == ord("e"):
                        # 'e' on a property value row → open the edit flow
                        self._trigger_action("edit_prop_value", f.meta)
                    elif f.meta.get("nav"):
                        dest_uri = f.meta["val_uri"]
                        if dest_uri in self.taxonomy.owl_individuals:
                            self._push()
                            self._detail_uri = dest_uri
                            self._detail_fields = self._bidf(dest_uri)
                            self._reset_detail_cursor()
                elif f.meta.get("type") == "prop_nav" and f.meta.get("nav"):
                    dest_uri = f.meta["uri"]
                    if dest_uri in self.taxonomy.owl_properties:
                        self._push()
                        self._detail_uri = dest_uri
                        self._detail_fields = self._bpropf(dest_uri)
                        self._reset_detail_cursor()
                elif f.meta.get("nav"):
                    # broader / narrower / related / subClassOf / etc. — navigate
                    dest_uri = f.meta["uri"]
                    if dest_uri in self.taxonomy.concepts:
                        self._push()
                        self._detail_uri = dest_uri
                        self._detail_fields = self._bdf(dest_uri)
                        self._reset_detail_cursor()
                    elif dest_uri in self.taxonomy.schemes:
                        self._push()
                        self._detail_uri = dest_uri
                        self._detail_fields = self._bsf(dest_uri)
                        self._reset_detail_cursor()
                    elif dest_uri in self.taxonomy.owl_classes:
                        self._push()
                        self._detail_uri = dest_uri
                        node_t = self.taxonomy.node_type(dest_uri)
                        if node_t == "promoted":
                            self._detail_fields = self._bpdf(dest_uri)
                        else:
                            self._detail_fields = self._bcdf(dest_uri)
                        self._reset_detail_cursor()

        elif key == ord("-"):
            # Remove mapping link, delete field value, or delete concept.
            if 0 <= self._field_cursor < n:
                f = self._detail_fields[self._field_cursor]
                if f.meta.get("type") == "repair_mapping":
                    self._repair_mapping_field(f)
                elif f.meta.get("type") in ("mapping", "mapping_remove"):
                    self._remove_mapping_field(f)
                elif f.editable:
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
            self._state = WelcomeState()

        elif key in (curses.KEY_LEFT, ord("h"), 27):
            self._back()

        return False

    # ─────────────────────────── EDIT drawing ────────────────────────────────

    def _draw_edit_bar(self, stdscr: curses.window, rows: int, cols: int) -> None:
        if not isinstance(self._state, EditState):
            return
        es = self._state
        f = es.field
        if f is None:
            return
        prompt = f" {f.display}: "
        before = es.buffer[: es.pos]
        after = es.buffer[es.pos :]
        bar = f"{prompt}{before}▌{after}"
        try:
            stdscr.addstr(
                rows - 1,
                0,
                bar[: cols - 1].ljust(cols - 1),
                curses.color_pair(_C_EDIT_BAR) | curses.A_BOLD,
            )
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

    def _on_edit(self, key: int | str) -> None:
        if not isinstance(self._state, EditState):
            return
        es = self._state
        v, p = es.buffer, es.pos

        def _return_to_prev() -> None:
            ret = es.return_to
            if isinstance(ret, (CreateState, SchemeCreateState)):
                self._state = ret
            else:
                self._state = DetailState()

        if key == 27:  # Esc — cancel
            _return_to_prev()

        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            self._commit_edit()
            _return_to_prev()

        elif key == 1:  # Ctrl+A — go to start
            es.pos = 0

        elif key == 5:  # Ctrl+E — go to end
            es.pos = len(v)

        elif key == 11:  # Ctrl+K — kill to end of line
            es.buffer = v[:p]

        elif key == 23:  # Ctrl+W — delete word backward
            i = self._word_start_left(v, p)
            es.buffer = v[:i] + v[p:]
            es.pos = i

        elif key == "word_left":  # Alt+b / Ctrl+Left
            es.pos = self._word_start_left(v, p)

        elif key == "word_right":  # Alt+f / Ctrl+Right
            es.pos = self._word_start_right(v, p)

        elif key in (curses.KEY_BACKSPACE, 127):
            if p > 0:
                es.buffer = v[: p - 1] + v[p:]
                es.pos = p - 1

        elif key == curses.KEY_DC:
            if p < len(v):
                es.buffer = v[:p] + v[p + 1 :]

        elif key == curses.KEY_LEFT:
            es.pos = max(0, p - 1)

        elif key == curses.KEY_RIGHT:
            es.pos = min(len(v), p + 1)

        elif key in (curses.KEY_HOME,):
            es.pos = 0

        elif key in (curses.KEY_END,):
            es.pos = len(v)

        elif isinstance(key, int) and 32 <= key < 256:
            ch = chr(key)
            es.buffer = v[:p] + ch + v[p:]
            es.pos = p + 1

    def _commit_edit(self) -> None:
        if not isinstance(self._state, EditState):
            return
        es = self._state
        ret = es.return_to
        if isinstance(ret, CreateState):
            if 0 <= ret.cursor < len(ret.fields):
                f = ret.fields[ret.cursor]
                if f.editable:
                    f.value = es.buffer
            return
        if isinstance(ret, SchemeCreateState):
            if 0 <= ret.cursor < len(ret.fields):
                f = ret.fields[ret.cursor]
                if f.editable:
                    f.value = es.buffer
            return
        # return_to is None → editing from detail mode
        if not self._detail_uri:
            return
        if not (0 <= self._field_cursor < len(self._detail_fields)):
            return
        f = self._detail_fields[self._field_cursor]
        new_value = es.buffer.strip()
        if not f.editable:
            # The cursor is on an action row — the edit was action-triggered.
            # The synthetic editable field is stored in es.field.
            if es.field is not None and es.field.editable:
                f = es.field
            else:
                return

        # ── schema media (shared across all entity types) ─────────────────────
        if f.meta.get("type", "").endswith("_input") and f.meta["type"].startswith("schema_"):
            self._commit_schema_media(f, new_value)
            return

        # ── scheme field editing ──────────────────────────────────────────────
        if self._detail_uri in self.taxonomy.schemes:
            self._commit_scheme_edit(f, new_value)
            return

        # ── OWL class field editing ───────────────────────────────────────────
        if self._detail_uri in self.taxonomy.owl_classes:
            self._commit_owl_class_edit(f, new_value)
            return

        # ── OWL individual field editing ──────────────────────────────────────
        if self._detail_uri in self.taxonomy.owl_individuals:
            self._commit_individual_edit(f, new_value)
            return

        # ── OWL property field editing ────────────────────────────────────────
        if self._detail_uri in self.taxonomy.owl_properties:
            self._commit_property_edit(f, new_value)
            return

        # ── Ontology metadata editing ─────────────────────────────────────────
        if self._detail_uri and _is_ontology_sentinel(self._detail_uri):
            self._commit_ontology_edit(f, new_value)
            return

        # ── concept field editing ─────────────────────────────────────────────
        if not new_value:
            return
        ftype = f.meta.get("type")
        lang = f.meta.get("lang", "")
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
                operations.set_definition(self.taxonomy, self._detail_uri, lang, new_value)
            elif ftype == "scope_note":
                concept = self.taxonomy.concepts.get(self._detail_uri)
                if concept:
                    concept.scope_notes = [sn for sn in concept.scope_notes if sn.lang != lang]
                    concept.scope_notes.append(Definition(lang=lang, value=new_value))
        except SkostaxError:
            return
        self._detail_fields = self._bdf(self._detail_uri)
        self._save_file()

    def _commit_scheme_edit(self, f: DetailField, new_value: str) -> None:
        """Commit an edit to a ConceptScheme field."""
        scheme = self.taxonomy.schemes.get(self._detail_uri or "")
        if not scheme:
            return
        ftype = f.meta.get("type")
        lang = f.meta.get("lang", "")

        if ftype == "scheme_base_uri":
            scheme.base_uri = new_value or ""

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

        assert self._detail_uri is not None
        self._detail_fields = self._bsf(self._detail_uri)
        self._field_cursor = min(self._field_cursor, max(0, len(self._detail_fields) - 1))
        self._save_file(uri=self._detail_uri)

    def _commit_owl_class_edit(self, f: DetailField, new_value: str) -> None:
        """Commit an edit to an OWL/RDFS class field (rdfs:label or rdfs:comment)."""
        rdf_class = self.taxonomy.owl_classes.get(self._detail_uri or "")
        if not rdf_class or not new_value:
            return
        ftype = f.meta.get("type")
        lang = f.meta.get("lang", "")
        if ftype == "rdf_label":
            for lbl in rdf_class.labels:
                if lbl.lang == lang:
                    lbl.value = new_value
                    break
            else:
                rdf_class.labels.append(Label(lang=lang, value=new_value))
        elif ftype == "rdf_comment":
            for cmt in rdf_class.comments:
                if cmt.lang == lang:
                    cmt.value = new_value
                    break
            else:
                rdf_class.comments.append(Definition(lang=lang, value=new_value))
        else:
            return
        assert self._detail_uri is not None
        node_t = self.taxonomy.node_type(self._detail_uri)
        if node_t == "promoted":
            self._detail_fields = self._bpdf(self._detail_uri)
        else:
            self._detail_fields = self._bcdf(self._detail_uri)
        self._field_cursor = min(self._field_cursor, max(0, len(self._detail_fields) - 1))
        self._save_file()

    def _commit_individual_edit(self, f: DetailField, new_value: str) -> None:
        """Commit an edit to an OWL individual field (rdfs:label or rdfs:comment)."""
        individual = self.taxonomy.owl_individuals.get(self._detail_uri or "")
        if not individual:
            return
        ftype = f.meta.get("type")
        lang = f.meta.get("lang", "")
        if ftype == "ind_label":
            for lbl in individual.labels:
                if lbl.lang == lang:
                    lbl.value = new_value
                    break
            else:
                individual.labels.append(Label(lang=lang, value=new_value))
        elif ftype == "ind_comment":
            for cmt in individual.comments:
                if cmt.lang == lang:
                    cmt.value = new_value
                    break
            else:
                individual.comments.append(Definition(lang=lang, value=new_value))
        else:
            return
        assert self._detail_uri is not None
        self._detail_fields = self._bidf(self._detail_uri)
        self._field_cursor = min(self._field_cursor, max(0, len(self._detail_fields) - 1))
        self._save_file()

    def _commit_property_edit(self, f: DetailField, new_value: str) -> None:
        """Commit an edit to an OWL property field (rdfs:label or rdfs:comment)."""
        prop = self.taxonomy.owl_properties.get(self._detail_uri or "")
        if not prop or not new_value:
            return
        ftype = f.meta.get("type")
        lang = f.meta.get("lang", "")
        if ftype == "prop_label":
            for lbl in prop.labels:
                if lbl.lang == lang:
                    lbl.value = new_value
                    break
            else:
                prop.labels.append(Label(lang=lang, value=new_value))
        elif ftype == "prop_comment":
            for cmt in prop.comments:
                if cmt.lang == lang:
                    cmt.value = new_value
                    break
            else:
                prop.comments.append(Definition(lang=lang, value=new_value))
        else:
            return
        assert self._detail_uri is not None
        self._detail_fields = self._bpropf(self._detail_uri)
        self._field_cursor = min(self._field_cursor, max(0, len(self._detail_fields) - 1))
        self._save_file()

    def _commit_ontology_edit(self, f: DetailField, new_value: str) -> None:
        """Commit an edit to the ontology metadata or OWL creation prompt."""
        ftype = f.meta.get("type")
        assert self._detail_uri is not None
        fp_str = self._detail_uri[len(_OWL_ONTOLOGY_PREFIX) :]
        file_path: Path | None = Path(fp_str) if fp_str and fp_str != "__" else None

        if ftype == "ont_label":
            self.taxonomy.ontology_label = new_value or None
            self._detail_fields = self._boof(file_path)
            self._field_cursor = min(self._field_cursor, max(0, len(self._detail_fields) - 1))
            self._save_file()

        elif ftype == "new_owl_class_uri":
            if not new_value:
                return
            from .model import RDFClass

            if new_value not in self.taxonomy.owl_classes:
                self.taxonomy.owl_classes[new_value] = RDFClass(uri=new_value)
                from .handles import assign_handles

                assign_handles(self.taxonomy)
                self._rebuild()
                self._save_file()
            self._detail_uri = new_value
            self._detail_fields = self._bcdf(new_value)
            self._field_cursor = 0
            self._state = DetailState()

        elif ftype == "new_owl_property_uri":
            if not new_value:
                return
            from .model import OWLProperty

            if new_value not in self.taxonomy.owl_properties:
                self.taxonomy.owl_properties[new_value] = OWLProperty(uri=new_value)
                from .handles import assign_handles

                assign_handles(self.taxonomy)
                self._rebuild()
                self._save_file()
            self._detail_uri = new_value
            self._detail_fields = self._bpropf(new_value)
            self._field_cursor = 0
            self._state = DetailState()

        elif ftype == "new_owl_individual_uri":
            if not new_value:
                return
            class_uri = f.meta.get("class_uri", "")
            if new_value not in self.taxonomy.owl_individuals:
                self.taxonomy.owl_individuals[new_value] = OWLIndividual(
                    uri=new_value,
                    types=[class_uri] if class_uri else [],
                )
                from .handles import assign_handles

                assign_handles(self.taxonomy)
                self._rebuild()
                self._save_file()
            self._detail_uri = new_value
            self._detail_fields = self._bidf(new_value)
            self._field_cursor = 0
            self._state = DetailState()

    def _delete_field(self, f: DetailField) -> None:
        if not self._detail_uri:
            return
        ftype = f.meta.get("type")
        lang = f.meta.get("lang", "")
        try:
            if ftype in ("pref", "alt"):
                lt = LabelType.PREF if ftype == "pref" else LabelType.ALT
                operations.remove_label(self.taxonomy, self._detail_uri, lang, f.value, lt)
            elif ftype == "def":
                concept = self.taxonomy.concepts.get(self._detail_uri)
                if concept:
                    concept.definitions = [d for d in concept.definitions if d.lang != lang]
            elif ftype == "scope_note":
                concept = self.taxonomy.concepts.get(self._detail_uri)
                if concept:
                    concept.scope_notes = [
                        sn
                        for sn in concept.scope_notes
                        if not (sn.lang == lang and sn.value == f.value)
                    ]
        except SkostaxError:
            return
        self._detail_fields = self._bdf(self._detail_uri)
        self._field_cursor = min(self._field_cursor, max(0, len(self._detail_fields) - 1))
        self._save_file()

    _ATTR_TO_SKOS: dict[str, str] = {
        "exact_match": "exactMatch",
        "close_match": "closeMatch",
        "broad_match": "broadMatch",
        "narrow_match": "narrowMatch",
        "related_match": "relatedMatch",
    }

    def _remove_mapping_field(self, f: DetailField) -> None:
        """Remove a cross-scheme mapping link shown in the detail view."""
        attr = f.meta.get("attr", "")
        tgt_uri = f.meta.get("uri", "")
        skos_type = self._ATTR_TO_SKOS.get(attr)
        if not skos_type or not tgt_uri or not self._detail_uri:
            return

        src_tax, src_path = self._individual_taxonomy_for(self._detail_uri)
        src_concept = src_tax.concepts.get(self._detail_uri)
        if not src_concept:
            return

        # Remove from source side
        src_list: list = getattr(src_concept, attr)
        if tgt_uri in src_list:
            src_list.remove(tgt_uri)

        # Remove inverse from target side if it exists in the workspace
        tgt_info = self._workspace.concept_for(tgt_uri)
        if tgt_info is not None:
            tgt_path, tgt_concept = tgt_info
            from .workspace_ops import _ATTR, _INVERSE

            inv_list: list = getattr(tgt_concept, _ATTR[_INVERSE[skos_type]])
            if self._detail_uri in inv_list:
                inv_list.remove(self._detail_uri)
            self._workspace.save_file(tgt_path)
            if self._git_manager:
                self._git_manager.stage_path(tgt_path)  # type: ignore[attr-defined]

        self._workspace.save_file(src_path)
        if self._git_manager:
            self._git_manager.stage_path(src_path)  # type: ignore[attr-defined]
        src_h = self.taxonomy.uri_to_handle(self._detail_uri) or self._detail_uri
        tgt_h = self.taxonomy.uri_to_handle(tgt_uri) or tgt_uri
        self._status = f"Removed {skos_type}: {src_h} → {tgt_h}"
        self._rebuild()
        self._detail_fields = self._bdf(self._detail_uri)
        self._field_cursor = min(self._field_cursor, max(0, len(self._detail_fields) - 1))
        self._skip_sep(-1)

    def _repair_mapping_field(self, f: DetailField) -> None:
        """Remove a broken cross-scheme mapping link from the scheme dashboard."""
        src_uri = f.meta.get("source_uri", "")
        attr = f.meta.get("attr", "")
        tgt_uri = f.meta.get("target_uri", "")
        skos_type = self._ATTR_TO_SKOS.get(attr)
        if not skos_type or not src_uri or not tgt_uri:
            return

        src_tax, src_path = self._individual_taxonomy_for(src_uri)
        src_concept = src_tax.concepts.get(src_uri)
        if not src_concept:
            return

        src_list: list = getattr(src_concept, attr)
        if tgt_uri in src_list:
            src_list.remove(tgt_uri)

        self._workspace.save_file(src_path)
        if self._git_manager:
            self._git_manager.stage_path(src_path)  # type: ignore[attr-defined]
        src_h = self.taxonomy.uri_to_handle(src_uri) or src_uri
        self._status = f"Removed broken {skos_type}: {src_h} → {tgt_uri}"
        self._rebuild()
        self._refresh_analysis(src_path)
        # Rebuild the scheme dashboard (detail_uri is still the scheme)
        if self._detail_uri:
            self._detail_fields = self._bsf(self._detail_uri)
            self._field_cursor = min(self._field_cursor, max(0, len(self._detail_fields) - 1))
            self._skip_sep(-1)

    # ─────────────────────────── action dispatch ─────────────────────────────

    def _trigger_action(self, action: str, meta: dict | None = None) -> None:
        _came_from_tree = isinstance(self._state, (TreeState, WelcomeState))
        if action in ("add_narrower", "add_top_concept"):
            # add_narrower: parent is the current concept.
            # add_top_concept: parent is the scheme URI — add_concept treats a
            #   scheme URI as "add as top concept of that scheme".
            self._state = CreateState(
                parent_uri=self._detail_uri,
                fields=[],  # built when user picks "manual" in choose step
                cursor=0,
                scroll=0,
                error="",
                came_from_tree=_came_from_tree,
                step="choose",
            )
        elif action == "delete":
            self._state = ConfirmDeleteState(uri=self._detail_uri or "")
        elif action == "move":
            if self._detail_uri:
                self._state = MovePickState(
                    source_uri=self._detail_uri,
                    is_link=False,
                    candidates=self._build_move_candidates(self._detail_uri),
                    filter_text="",
                    cursor=0,
                    scroll=0,
                )
        elif action == "link_broader":
            if self._detail_uri:
                # Candidates: all concepts except the concept itself, its subtree,
                # and concepts already in its broader list (already linked)
                concept = self.taxonomy.concepts.get(self._detail_uri)
                excluded = operations._subtree_uris(self.taxonomy, self._detail_uri)
                already = set(concept.broader) if concept else set()
                candidates: list[tuple[str, str]] = []
                for line in self._flat:
                    if line.is_scheme:
                        continue
                    if line.uri in excluded or line.uri in already:
                        continue
                    c = self.taxonomy.concepts.get(line.uri)
                    if c:
                        handle = self.taxonomy.uri_to_handle(line.uri) or "?"
                        label = c.pref_label(self.lang) or line.uri
                        indent = "  " * line.depth
                        candidates.append((line.uri, f"{indent}[{handle}]  {label}"))
                self._state = MovePickState(
                    source_uri=self._detail_uri,
                    is_link=True,
                    candidates=candidates,
                    filter_text="",
                    cursor=0,
                    scroll=0,
                )

        elif action in ("add_rdf_label", "add_rdf_comment"):
            lang = (meta or {}).get("lang", self.lang)
            ftype = "rdf_label" if action == "add_rdf_label" else "rdf_comment"
            display = "rdfs:label" if action == "add_rdf_label" else "rdfs:comment"
            synthetic = DetailField(
                f"add:{ftype}:{lang}",
                f"{display} [{lang}]",
                "",
                editable=True,
                meta={"type": ftype, "lang": lang},
            )
            self._state = EditState(buffer="", pos=0, field=synthetic, return_to=None)

        elif action == "link_superclass":
            if self._detail_uri:
                self._state = MovePickState(
                    source_uri=self._detail_uri,
                    pick_type="link_superclass",
                    candidates=self._build_owl_class_candidates(self._detail_uri),
                )

        elif action == "move_class":
            if self._detail_uri:
                self._state = MovePickState(
                    source_uri=self._detail_uri,
                    pick_type="move_class",
                    candidates=self._build_owl_class_candidates(self._detail_uri),
                )

        elif action == "remove_superclass":
            if self._detail_uri:
                parent_uri = (meta or {}).get("parent_uri", "")
                rdf_class = self.taxonomy.owl_classes.get(self._detail_uri)
                if rdf_class and parent_uri in rdf_class.sub_class_of:
                    rdf_class.sub_class_of.remove(parent_uri)
                    self._rebuild()
                    self._save_file()
                    self._detail_fields = self._bcdf(self._detail_uri)
                    self._field_cursor = min(
                        self._field_cursor, max(0, len(self._detail_fields) - 1)
                    )

        elif action == "delete_class":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_classes:
                uri = self._detail_uri
                del self.taxonomy.owl_classes[uri]
                self._rebuild()
                self._save_file()
                self._cursor = min(self._cursor, max(0, len(self._flat) - 1))
                self._detail_uri = _GLOBAL_URI
                self._detail_fields = self._bgf()
                self._field_cursor = 0
                self._state = TreeState()

        elif action == "class_to_individual":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_classes:
                uri = self._detail_uri
                rdf_class = self.taxonomy.owl_classes[uri]
                affected = [
                    ind_uri
                    for ind_uri, ind in self.taxonomy.owl_individuals.items()
                    if uri in ind.types
                ]
                parent_uris = [p for p in rdf_class.sub_class_of if not is_builtin_uri(p)]
                if affected:
                    self._state = ClassToIndividualState(
                        class_uri=uri,
                        affected_uris=affected,
                        parent_uris=parent_uris,
                        cursor=0,
                    )
                else:
                    self._do_class_to_individual(uri)

        elif action == "individual_to_class":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_individuals:
                uri = self._detail_uri
                individual = self.taxonomy.owl_individuals[uri]

                # Collect outgoing relations (this individual's own property values)
                outgoing: list[tuple[str, str, str]] = []
                for prop_uri, val_uri in individual.property_values:
                    prop = self.taxonomy.owl_properties.get(prop_uri)
                    prop_lbl = prop.label(self.lang) if prop else prop_uri
                    target = self.taxonomy.owl_individuals.get(val_uri)
                    target_lbl = target.label(self.lang) if target else val_uri
                    outgoing.append((prop_uri, prop_lbl, target_lbl))

                # Collect incoming relations (other individuals pointing to this one)
                incoming: list[tuple[str, str, str]] = []
                for src_uri, src_ind in self.taxonomy.owl_individuals.items():
                    if src_uri == uri:
                        continue
                    for prop_uri, val_uri in src_ind.property_values:
                        if val_uri == uri:
                            src_lbl = src_ind.label(self.lang) or src_uri
                            prop = self.taxonomy.owl_properties.get(prop_uri)
                            prop_lbl = prop.label(self.lang) if prop else prop_uri
                            incoming.append((src_lbl, prop_uri, prop_lbl))

                if outgoing or incoming:
                    self._state = IndividualToClassState(
                        individual_uri=uri,
                        outgoing=outgoing,
                        incoming=incoming,
                        cursor=0,
                    )
                else:
                    self._do_individual_to_class(uri)

        elif action in ("add_ind_label", "add_ind_comment"):
            lang = (meta or {}).get("lang", self.lang)
            ftype = "ind_label" if action == "add_ind_label" else "ind_comment"
            display = "rdfs:label" if action == "add_ind_label" else "rdfs:comment"
            synthetic = DetailField(
                f"add:{ftype}:{lang}",
                f"{display} [{lang}]",
                "",
                editable=True,
                meta={"type": ftype, "lang": lang},
            )
            self._state = EditState(buffer="", pos=0, field=synthetic, return_to=None)

        elif action == "delete_individual":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_individuals:
                uri = self._detail_uri
                del self.taxonomy.owl_individuals[uri]
                self._rebuild()
                self._save_file()
                self._cursor = min(self._cursor, max(0, len(self._flat) - 1))
                self._detail_uri = _GLOBAL_URI
                self._detail_fields = self._bgf()
                self._field_cursor = 0
                self._state = TreeState()

        elif action == "add_prop_value":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_individuals:
                individual = self.taxonomy.owl_individuals[self._detail_uri]
                # Step 1: pick a property (object properties where this individual's class is domain)
                candidates: list[tuple[str, str]] = []  # type: ignore[no-redef]
                for p_uri, prop in sorted(
                    self.taxonomy.owl_properties.items(), key=lambda kv: kv[1].label(self.lang)
                ):
                    if prop.prop_type not in ("ObjectProperty", "Property"):
                        continue
                    eff = _effective_types(self.taxonomy, individual.types)
                    if prop.domains and not any(t in prop.domains for t in eff):
                        continue
                    h = self.taxonomy.uri_to_handle(p_uri) or "?"
                    lbl = prop.label(self.lang)
                    range_classes = [
                        self.taxonomy.owl_classes[r].label(self.lang)
                        if r in self.taxonomy.owl_classes
                        else r
                        for r in prop.ranges
                    ]
                    suffix = f"  ({', '.join(range_classes)})" if range_classes else ""
                    candidates.append((p_uri, f"[{h}]  {lbl}{suffix}"))
                self._state = MovePickState(
                    source_uri=self._detail_uri,
                    pick_type="add_prop_value_step1",
                    candidates=candidates,
                    filter_text="",
                    cursor=0,
                    scroll=0,
                )

        elif action == "remove_prop_value":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_individuals:
                prop_uri = (meta or {}).get("prop_uri", "")
                val_uri = (meta or {}).get("val_uri", "")
                individual = self.taxonomy.owl_individuals[self._detail_uri]
                pair = (prop_uri, val_uri)
                if pair in individual.property_values:
                    individual.property_values.remove(pair)
                    self._save_file()
                    self._detail_fields = self._bidf(self._detail_uri)
                    self._field_cursor = min(
                        self._field_cursor, max(0, len(self._detail_fields) - 1)
                    )

        elif action == "edit_prop_value":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_individuals:
                ind_uri = self._detail_uri
                prop_uri = (meta or {}).get("prop_uri", "")
                val_uri = (meta or {}).get("val_uri", "")
                edit_prop = self.taxonomy.owl_properties.get(prop_uri)
                self._state = self._make_class_or_individual_state(
                    ind_uri, prop_uri, edit_prop, replace_val_uri=val_uri
                )

        elif action == "remove_ind_type":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_individuals:
                type_uri = (meta or {}).get("type_uri", "")
                individual = self.taxonomy.owl_individuals[self._detail_uri]
                if type_uri in individual.types:
                    individual.types.remove(type_uri)
                    self._save_file()
                    self._rebuild()
                    self._detail_fields = self._bidf(self._detail_uri)
                    self._field_cursor = min(
                        self._field_cursor, max(0, len(self._detail_fields) - 1)
                    )

        elif action == "add_ind_type":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_individuals:
                ind_uri = self._detail_uri
                existing = set(self.taxonomy.owl_individuals[ind_uri].types)
                type_candidates: list[tuple[str, str]] = []
                for cls_uri, cls in sorted(
                    self.taxonomy.owl_classes.items(),
                    key=lambda kv: kv[1].label(self.lang),
                ):
                    if cls_uri in existing:
                        continue
                    h = self.taxonomy.uri_to_handle(cls_uri) or "?"
                    type_candidates.append((cls_uri, f"[{h}]  {cls.label(self.lang)}"))
                self._state = MovePickState(
                    source_uri=ind_uri,
                    pick_type="add_ind_type",
                    candidates=type_candidates,
                    filter_text="",
                    cursor=0,
                    scroll=0,
                )

        elif action in ("add_prop_label", "add_prop_comment"):
            lang = (meta or {}).get("lang", self.lang)
            ftype = "prop_label" if action == "add_prop_label" else "prop_comment"
            display = "rdfs:label" if action == "add_prop_label" else "rdfs:comment"
            synthetic = DetailField(
                f"add:{ftype}:{lang}",
                f"{display} [{lang}]",
                "",
                editable=True,
                meta={"type": ftype, "lang": lang},
            )
            self._state = EditState(buffer="", pos=0, field=synthetic, return_to=None)

        elif action in ("add_prop_domain", "add_prop_range"):
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_properties:
                prop = self.taxonomy.owl_properties[self._detail_uri]
                already = set(prop.domains if action == "add_prop_domain" else prop.ranges)
                candidates: list[tuple[str, str]] = []  # type: ignore[no-redef]
                for cls_uri in sorted(self.taxonomy.owl_classes):
                    if cls_uri in already:
                        continue
                    cls = self.taxonomy.owl_classes[cls_uri]
                    candidates.append((cls_uri, cls.label(self.lang)))
                self._state = MovePickState(
                    source_uri=self._detail_uri,
                    pick_type=action,
                    candidates=candidates,
                    filter_text="",
                    cursor=0,
                    scroll=0,
                )

        elif action == "remove_prop_domain":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_properties:
                d_uri = (meta or {}).get("domain_uri", "")
                prop = self.taxonomy.owl_properties[self._detail_uri]
                if d_uri in prop.domains:
                    prop.domains.remove(d_uri)
                    self._save_file()
                    self._detail_fields = self._bpropf(self._detail_uri)
                    self._field_cursor = min(
                        self._field_cursor, max(0, len(self._detail_fields) - 1)
                    )

        elif action == "remove_prop_range":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_properties:
                r_uri = (meta or {}).get("range_uri", "")
                prop = self.taxonomy.owl_properties[self._detail_uri]
                if r_uri in prop.ranges:
                    prop.ranges.remove(r_uri)
                    self._save_file()
                    self._detail_fields = self._bpropf(self._detail_uri)
                    self._field_cursor = min(
                        self._field_cursor, max(0, len(self._detail_fields) - 1)
                    )

        elif action == "delete_property":
            if self._detail_uri and self._detail_uri in self.taxonomy.owl_properties:
                uri = self._detail_uri
                del self.taxonomy.owl_properties[uri]
                self._rebuild()
                self._save_file()
                self._cursor = min(self._cursor, max(0, len(self._flat) - 1))
                self._detail_uri = _GLOBAL_URI
                self._detail_fields = self._bgf()
                self._field_cursor = 0
                self._state = TreeState()

        elif action in ("create_owl_class", "create_owl_property"):
            self._trigger_create_owl(action)

        elif action == "add_individual":
            if self._detail_uri:
                self._trigger_create_individual(self._detail_uri)

        elif action in ("add_schema_image", "add_schema_video", "add_schema_url"):
            kind = action[len("add_schema_") :]  # "image" | "video" | "url"
            label_map = {
                "image": "schema:image URL (photo)",
                "video": "schema:video URL (YouTube / Vimeo)",
                "url": "schema:url (external link)",
            }
            ftype = f"schema_{kind}_input"
            synthetic = DetailField(
                f"add:{ftype}",
                label_map.get(kind, kind),
                "https://",
                editable=True,
                meta={"type": ftype},
            )
            self._state = EditState(
                buffer="https://", pos=len("https://"), field=synthetic, return_to=None
            )

        elif action in ("remove_schema_image", "remove_schema_video", "remove_schema_url"):
            url = (meta or {}).get("url", "")
            entity = self._schema_entity()
            if url and entity is not None:
                kind = action[len("remove_schema_") :]  # "image" | "video" | "url"
                lst: list[str] = getattr(entity, f"schema_{kind}s")  # type: ignore[attr-defined]
                if url in lst:
                    lst.remove(url)
                    self._refresh_detail()
                    self._save_file()

        elif action == "view_ontology_graph":
            from . import viz as _viz

            try:
                out = _viz.open_in_browser(self.taxonomy, self.file_path)
                self._status = f"Graph opened in browser — {out}"
            except Exception as exc:
                self._status = f"Error opening graph: {exc}"

        elif action == "toggle_class_fold":
            uri = (meta or {}).get("uri", "")
            if uri:
                if uri in self._overview_folded:
                    self._overview_folded.discard(uri)
                else:
                    self._overview_folded.add(uri)
                # rebuild the ontology overview panel
                if self._detail_uri and _is_ontology_sentinel(self._detail_uri):
                    fp = self._detail_uri[len(_OWL_ONTOLOGY_PREFIX) :]
                    file_path = Path(fp) if fp and fp != "__" else self.file_path
                    self._detail_fields = self._boof(file_path)
                    self._field_cursor = min(
                        self._field_cursor, max(0, len(self._detail_fields) - 1)
                    )

        elif action in ("add_pref_label", "add_alt_label", "add_def", "add_scope_note"):
            lang = (meta or {}).get("lang", self.lang)
            _FTYPE = {
                "add_pref_label": ("pref", "pref"),
                "add_alt_label": ("alt", "alt"),
                "add_def": ("def", "def"),
                "add_scope_note": ("scope_note", "scopeNote"),
            }
            ftype, display_name = _FTYPE[action]
            synthetic = DetailField(
                f"add:{ftype}:{lang}",
                f"{display_name} [{lang}]",
                "",
                editable=True,
                meta={"type": ftype, "lang": lang},
            )
            self._state = EditState(buffer="", pos=0, field=synthetic, return_to=None)

        elif action == "add_related":
            if self._detail_uri:
                concept = self.taxonomy.concepts.get(self._detail_uri)
                already_related = set(concept.related) if concept else set()
                candidates: list[tuple[str, str]] = []  # type: ignore[no-redef]
                for line in self._flat:
                    if line.is_scheme or line.is_action or line.is_file:
                        continue
                    if line.uri == self._detail_uri or line.uri in already_related:
                        continue
                    c = self.taxonomy.concepts.get(line.uri)
                    if c:
                        handle = self.taxonomy.uri_to_handle(line.uri) or "?"
                        label = c.pref_label(self.lang) or line.uri
                        indent = "  " * line.depth
                        candidates.append((line.uri, f"{indent}[{handle}]  {label}"))
                self._state = MovePickState(
                    source_uri=self._detail_uri,
                    is_link=False,
                    pick_type="add_related",
                    candidates=candidates,
                    filter_text="",
                    cursor=0,
                    scroll=0,
                )

        elif action == "add_scheme":
            self._state = SchemeCreateState(
                fields=self._build_scheme_create_fields(),
                cursor=0,
                scroll=0,
                error="",
                came_from_tree=_came_from_tree,
            )

        elif action == "pick_lang":
            options = _available_langs(self.taxonomy) or ["en", "fr", "de", "es"]
            try:
                cursor = options.index(self.lang)
            except ValueError:
                cursor = 0
            self._state = LangPickState(options=options, cursor=cursor, scroll=0)

        elif action == "open_ai_config":
            from . import ai

            if not ai.is_available():
                self._state = AiInstallState(pending_action="open_ai_config")
            else:
                online, offline = ai.discover_models()
                cp_idx = (1 if online else 0) + (1 if offline else 0)
                self._state = AiSetupState(
                    online_providers=online,
                    offline_providers=offline,
                    provider_cursor=cp_idx if ai.is_copypaste() else 0,
                    pending_action="",  # no follow-up action after config
                )

        elif action == "open_query":
            self._state = QueryState(
                file_paths=list(self._workspace.taxonomies.keys()),
                query_buffer=self._last_query_buffer,
                query_pos=len(self._last_query_buffer),
            )

        elif action.startswith("map:"):
            mapping_type = action[4:]  # "broadMatch", "narrowMatch", …
            if self._detail_uri:
                cands = self._build_map_scheme_candidates(self._detail_uri)
                if not cands:
                    self._status = "No other scheme available for mapping"
                else:
                    self._state = MapSchemePickState(
                        source_uri=self._detail_uri,
                        map_type=mapping_type,
                        candidates=cands,
                        cursor=0,
                        scroll=0,
                    )

    def _build_create_fields(self) -> list[DetailField]:
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
            DetailField(
                "form:name",
                "Concept name",
                "",
                editable=True,
                meta={"type": "form", "field": "name"},
            ),
        ]
        for lg in langs:
            fields.append(
                DetailField(
                    f"form:pref:{lg}",
                    f"prefLabel [{lg}]",
                    "",
                    editable=True,
                    meta={"type": "form", "field": "pref", "lang": lg},
                )
            )
        fields.append(
            DetailField(
                f"form:def:{self.lang}",
                f"definition [{self.lang}]",
                "",
                editable=True,
                meta={"type": "form", "field": "def", "lang": self.lang},
            )
        )
        fields.append(
            DetailField(
                "form:submit",
                "✓  Create concept",
                "",
                editable=False,
                meta={"type": "form_action", "action": "submit"},
            )
        )
        fields.append(
            DetailField(
                "form:cancel",
                "✗  Cancel",
                "",
                editable=False,
                meta={"type": "form_action", "action": "cancel"},
            )
        )
        return fields

    def _draw_create(self, stdscr: curses.window, rows: int, cols: int) -> None:
        stdscr.erase()
        wide = cols >= self._SPLIT_MIN_COLS
        tree_w = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w = cols - tree_w
        cs = self._state if isinstance(self._state, CreateState) else None
        parent_uri = cs.parent_uri if cs else None
        if wide:
            if parent_uri:
                for i, line in enumerate(self._flat):
                    if line.uri == parent_uri:
                        self._cursor = i
                        break
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr,
                rows,
                0,
                tree_w,
                cursor_idx=self._cursor,
                highlight_uri=parent_uri,
            )
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass
        self._render_create_col(stdscr, rows, detail_x0, detail_w)
        stdscr.refresh()

    # ── Add-concept AI helpers ────────────────────────────────────────────────

    def _build_ai_context_from_uri(
        self, parent_uri: str | None
    ) -> tuple[str, str, str | None, str]:
        """Return (taxonomy_name, taxonomy_description, parent_label, parent_definition).

        For top-level concepts (parent is a scheme or None):
          parent_label = None, parent_definition = scheme description
        For narrower concepts (parent is a concept):
          parent_label = concept pref_label, parent_definition = concept skos:definition

        Uses the individual file taxonomy that owns *parent_uri* so that, in a
        multi-file workspace, the name and description reflect the correct scheme
        rather than the first scheme in the merged taxonomy.
        """
        target_tax, target_path = self._individual_taxonomy_for(parent_uri)

        # Resolve the relevant scheme: explicit when parent_uri IS a scheme URI,
        # otherwise fall back to the primary scheme of the owning file.
        if parent_uri and parent_uri in target_tax.schemes:
            scheme = target_tax.schemes[parent_uri]
        else:
            scheme = target_tax.primary_scheme()  # type: ignore[assignment]

        taxonomy_name = scheme.title(self.lang) if scheme else target_path.stem

        taxonomy_description = ""
        if scheme and scheme.descriptions:
            for defn in scheme.descriptions:
                if defn.lang == self.lang:
                    taxonomy_description = defn.value
                    break
            if not taxonomy_description and scheme.descriptions:
                taxonomy_description = scheme.descriptions[0].value

        parent_label: str | None = None
        parent_definition: str = ""
        if parent_uri and parent_uri not in target_tax.schemes:
            parent_concept = target_tax.concepts.get(parent_uri)
            if parent_concept:
                parent_label = parent_concept.pref_label(self.lang)
                parent_definition = parent_concept.definition(self.lang) or ""
        else:
            # Top-level: use scheme description as parent context for the AI
            parent_definition = taxonomy_description

        return taxonomy_name, taxonomy_description, parent_label, parent_definition

    def _build_ai_context(self, cs: CreateState) -> tuple[str, str, str | None, str]:
        """Return (taxonomy_name, taxonomy_description, parent_label, parent_definition) from a CreateState."""
        return self._build_ai_context_from_uri(cs.parent_uri)

    def _run_generate(self, stdscr: curses.window, fn, draw_fn=None) -> None:
        """Run an AI generate function with an animated spinner.

        In copy-paste mode curses is suspended around the interactive prompt.
        Otherwise the function runs in a background thread while the main loop
        redraws every 120 ms so the spinner character actually animates.
        *draw_fn* is called each poll tick; if omitted the last frame is kept.
        """
        import threading
        import time

        from . import ai as _ai

        if _ai.is_copypaste():
            curses.endwin()
            try:
                fn()
            finally:
                stdscr.refresh()
            return

        done: list[bool] = [False]
        exc_holder: list[BaseException | None] = [None]

        def _worker() -> None:
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                exc_holder[0] = e
            finally:
                done[0] = True

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t0 = time.monotonic()
        aborted = False
        stdscr.nodelay(True)  # non-blocking key check during poll
        try:
            while not done[0]:
                self._install_spinner += 1
                self._generate_elapsed = time.monotonic() - t0
                if draw_fn is not None:
                    draw_fn()
                else:
                    stdscr.refresh()
                key = stdscr.getch()
                if key == 27:  # Esc — abort
                    aborted = True
                    break
                curses.napms(120)
        finally:
            stdscr.nodelay(False)
            self._generate_elapsed = 0.0

        # Surface any exception from the worker as an error on the current state
        err = exc_holder[0]
        if aborted or err is not None:
            msg = "Cancelled." if aborted else f"Error: {err}"
            st = self._state
            if isinstance(st, BatchCreateState) and st.drafts:
                draft = st.drafts[st.current]
                draft.alts_error = msg
                draft.def_error = msg
                draft.alts_generating = False
                draft.def_generating = False
            elif isinstance(st, CreateState):
                st.error = msg
                st.ai_generating = False
            elif isinstance(st, QueryState):
                if st.ai_generating:
                    st.ai_generating = False
                    st.ai_step = ""
                    st.result_error = msg
                else:
                    st.result_error = msg
                    st.running = False

    def _create_ai_generate(self) -> None:
        """Called from main loop when CreateState.ai_generating is True."""
        from . import ai as _ai

        if not isinstance(self._state, CreateState):
            return
        cs = self._state
        try:
            # Use the (possibly user-edited) prompt_buffer directly
            candidates = _ai.suggest_concept_names_from_prompt(cs.prompt_buffer)
        except Exception as exc:
            cs.error = str(exc)[:80]
            candidates = []
        cs.ai_candidates = candidates
        cs.ai_checked = [False] * len(candidates)
        cs.ai_seen = cs.ai_seen + candidates
        cs.ai_generating = False
        cs.ai_cursor = 0
        cs.ai_scroll = 0

    # ── Batch concept creation wizard ────────────────────────────────────────

    def _launch_batch_create(self, cs: CreateState) -> None:
        """Build a BatchCreateState from checked candidates and enter the wizard."""
        selected = [name for name, chk in zip(cs.ai_candidates, cs.ai_checked, strict=False) if chk]
        drafts = [BatchConceptDraft(name=name, pref_label=name) for name in selected]
        self._state = BatchCreateState(
            parent_uri=cs.parent_uri,
            came_from_tree=cs.came_from_tree,
            drafts=drafts,
            current=0,
            step="label",
            label_buffer=drafts[0].pref_label if drafts else "",
            label_pos=len(drafts[0].pref_label) if drafts else 0,
        )

    @staticmethod
    def _apply_line_edit(buffer: str, pos: int, key: int) -> tuple[str, int]:
        """Apply one keystroke to a (buffer, pos) pair.

        Handles printable chars, backspace, Del, Ctrl+A/E/K/W, arrow keys.
        Returns unchanged (buffer, pos) for unrecognised keys.
        """
        if key == 1:  # Ctrl+A
            return buffer, 0
        if key == 5:  # Ctrl+E
            return buffer, len(buffer)
        if key == 11:  # Ctrl+K
            return buffer[:pos], pos
        if key == 23:  # Ctrl+W — delete word backward
            i = pos
            while i > 0 and buffer[i - 1] == " ":
                i -= 1
            while i > 0 and buffer[i - 1] != " ":
                i -= 1
            return buffer[:i] + buffer[pos:], i
        if key in (curses.KEY_BACKSPACE, 127):
            if pos > 0:
                return buffer[: pos - 1] + buffer[pos:], pos - 1
            return buffer, pos
        if key == curses.KEY_DC:
            if pos < len(buffer):
                return buffer[:pos] + buffer[pos + 1 :], pos
            return buffer, pos
        if key == curses.KEY_LEFT:
            return buffer, max(0, pos - 1)
        if key == curses.KEY_RIGHT:
            return buffer, min(len(buffer), pos + 1)
        if key == curses.KEY_HOME:
            return buffer, 0
        if key == curses.KEY_END:
            return buffer, len(buffer)
        if 32 <= key < 256:
            ch = chr(key)
            return buffer[:pos] + ch + buffer[pos:], pos + 1
        return buffer, pos

    def _batch_advance_or_recap(self, bcs: BatchCreateState) -> None:
        """Advance to the next concept or enter the recap step."""
        if bcs.current < len(bcs.drafts) - 1:
            bcs.current += 1
            draft = bcs.drafts[bcs.current]
            bcs.step = "label"
            bcs.label_buffer = draft.pref_label
            bcs.label_pos = len(draft.pref_label)
            bcs.alt_cursor = 0
            bcs.alt_scroll = 0
            bcs.error = ""
            if not draft.alt_labels and not draft.alts_generating:
                draft.alts_generating = True
        else:
            bcs.step = "recap"
            bcs.recap_cursor = 0
            bcs.recap_scroll = 0

    def _batch_generate_alts(self) -> None:
        """Called from main loop when draft.alts_generating is True."""
        from . import ai as _ai

        if not isinstance(self._state, BatchCreateState):
            return
        bcs = self._state
        draft = bcs.drafts[bcs.current]
        try:
            alts = _ai.suggest_alt_labels_from_prompt(bcs.alt_prompt_buffer)
        except Exception as exc:
            draft.alts_error = str(exc)[:80]
            alts = []
        draft.alt_labels = alts
        draft.alt_checked = [True] * len(alts)
        draft.alts_generating = False

    def _batch_generate_def(self) -> None:
        """Called from main loop when draft.def_generating is True."""
        from . import ai as _ai

        if not isinstance(self._state, BatchCreateState):
            return
        bcs = self._state
        draft = bcs.drafts[bcs.current]
        taxonomy_name, taxonomy_desc, parent_label, parent_def = self._build_ai_context_from_uri(
            bcs.parent_uri
        )
        try:
            defn = _ai.suggest_definition(
                pref_label=draft.pref_label,
                taxonomy_name=taxonomy_name,
                taxonomy_description=taxonomy_desc,
                parent_label=parent_label,
                parent_definition=parent_def,
                lang=self.lang,
            )
        except Exception as exc:
            draft.def_error = str(exc)[:80]
            defn = ""
        draft.definition = defn
        draft.def_generating = False

    def _draw_batch(self, stdscr: curses.window, rows: int, cols: int) -> None:
        """Top-level draw dispatcher for the batch creation wizard."""
        stdscr.erase()
        wide = cols >= self._SPLIT_MIN_COLS
        tree_w = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w = cols - tree_w
        bcs = self._state
        assert isinstance(bcs, BatchCreateState)
        if wide:
            parent_uri = bcs.parent_uri
            if parent_uri:
                for i, line in enumerate(self._flat):
                    if line.uri == parent_uri:
                        self._cursor = i
                        break
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr, rows, 0, tree_w, cursor_idx=self._cursor, highlight_uri=bcs.parent_uri
            )
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass
        if bcs.step == "recap":
            self._draw_batch_recap(stdscr, rows, detail_x0, detail_w, bcs)
        elif bcs.step == "confirm" and bcs.drafts:
            draft = bcs.drafts[bcs.current]
            self._draw_batch_confirm(stdscr, rows, detail_x0, detail_w, bcs, draft)
        elif bcs.drafts:
            draft = bcs.drafts[bcs.current]
            if bcs.step == "label":
                self._draw_batch_label(stdscr, rows, detail_x0, detail_w, bcs, draft)
            elif bcs.step == "definition":
                self._draw_batch_definition(stdscr, rows, detail_x0, detail_w, bcs, draft)
            elif bcs.step == "alt_prompt_review":
                self._draw_batch_alt_prompt_review(stdscr, rows, detail_x0, detail_w, bcs, draft)
            elif bcs.step == "alt_labels":
                self._draw_batch_alt_labels(stdscr, rows, detail_x0, detail_w, bcs, draft)
        stdscr.refresh()

    def _batch_header(self, bcs: BatchCreateState, step_title: str) -> str:
        n = len(bcs.drafts)
        idx = bcs.current + 1
        return f" Concept {idx}/{n} — {step_title} "

    def _draw_batch_label(
        self,
        stdscr: curses.window,
        rows: int,
        x0: int,
        width: int,
        bcs: BatchCreateState,
        draft: BatchConceptDraft,
    ) -> None:
        _draw_bar(stdscr, 0, x0, width, self._batch_header(bcs, "Preferred label"), dim=False)
        try:
            orig = f"  AI name: {draft.name}"
            stdscr.addstr(2, x0, orig[: width - 1], curses.color_pair(_C_DIM))
        except curses.error:
            pass
        # Inline edit bar for pref label
        buf, pos = bcs.label_buffer, bcs.label_pos
        max_w = width - 4
        offset = max(0, pos - max_w + 1)
        visible = buf[offset : offset + max_w]
        cursor_x = x0 + 2 + (pos - offset)
        try:
            stdscr.addstr(4, x0 + 1, f" {visible:<{max_w}} ", curses.color_pair(_C_EDIT_BAR))
            stdscr.move(4, min(cursor_x, x0 + width - 2))
        except curses.error:
            pass
        if draft.alts_generating:
            spinner = self._SPINNER[self._install_spinner % 4]
            elapsed = f"  {self._generate_elapsed:.0f}s" if self._generate_elapsed else ""
            try:
                stdscr.addstr(
                    6,
                    x0 + 2,
                    f"{spinner} Generating alt labels…{elapsed}"[: width - 4],
                    curses.color_pair(_C_DIM),
                )
                stdscr.addstr(7, x0 + 2, "  Esc to cancel"[: width - 4], curses.color_pair(_C_DIM))
            except curses.error:
                pass
        if bcs.error:
            try:
                stdscr.addstr(
                    rows - 2,
                    x0 + 1,
                    f"Error: {bcs.error}"[: width - 2],
                    curses.color_pair(_C_DIFF_DEL),
                )
            except curses.error:
                pass
        _draw_bar(stdscr, rows - 1, x0, width, "  Enter: confirm label   Esc: cancel  ", dim=True)

    def _draw_batch_alt_prompt_review(
        self,
        stdscr: curses.window,
        rows: int,
        x0: int,
        width: int,
        bcs: BatchCreateState,
        draft: BatchConceptDraft,
    ) -> None:
        """Render the editable alt-labels prompt review panel."""
        _draw_bar(
            stdscr,
            0,
            x0,
            width,
            self._batch_header(bcs, f"Alt-labels prompt — {draft.pref_label}"),
            dim=False,
        )
        # Display prompt buffer with ▌ cursor, word-split by lines
        buf = bcs.alt_prompt_buffer
        pos = bcs.alt_prompt_pos
        text_with_cursor = buf[:pos] + "▌" + buf[pos:]
        raw_lines = text_with_cursor.splitlines()
        display_lines: list[str] = []
        for raw in raw_lines:
            while len(raw) > width:
                display_lines.append(raw[:width])
                raw = raw[width:]
            display_lines.append(raw)
        list_h = rows - 2
        # scroll so the cursor line is visible
        cursor_line = len((buf[:pos] + "▌").splitlines()) - 1
        if bcs.alt_prompt_scroll > cursor_line:
            bcs.alt_prompt_scroll = cursor_line
        if cursor_line >= bcs.alt_prompt_scroll + list_h:
            bcs.alt_prompt_scroll = cursor_line - list_h + 1
        for i in range(list_h):
            idx = bcs.alt_prompt_scroll + i
            line = display_lines[idx] if idx < len(display_lines) else ""
            try:
                stdscr.addstr(1 + i, x0, line[:width])
            except curses.error:
                pass
        _draw_bar(
            stdscr,
            rows - 1,
            x0,
            width,
            "  ↑↓: scroll   type to edit   Enter: generate   Esc: back  ",
            dim=True,
        )

    def _draw_batch_alt_labels(
        self,
        stdscr: curses.window,
        rows: int,
        x0: int,
        width: int,
        bcs: BatchCreateState,
        draft: BatchConceptDraft,
    ) -> None:
        _draw_bar(stdscr, 0, x0, width, self._batch_header(bcs, "Alternative labels"), dim=False)
        if draft.alts_generating:
            spinner = self._SPINNER[self._install_spinner % 4]
            elapsed = f"  {self._generate_elapsed:.0f}s" if self._generate_elapsed else ""
            try:
                stdscr.addstr(
                    rows // 2,
                    x0 + 2,
                    f"{spinner}  Generating alt labels…{elapsed}"[: width - 2],
                    curses.color_pair(_C_DIM),
                )
                stdscr.addstr(
                    rows // 2 + 1, x0 + 2, "  Esc to cancel"[: width - 2], curses.color_pair(_C_DIM)
                )
            except curses.error:
                pass
            _draw_bar(stdscr, rows - 1, x0, width, "", dim=True)
            return
        if draft.alts_error:
            try:
                stdscr.addstr(
                    2,
                    x0 + 2,
                    f"Error: {draft.alts_error}"[: width - 4],
                    curses.color_pair(_C_DIFF_DEL),
                )
            except curses.error:
                pass
        items = draft.alt_labels + ["✓  Done"]
        list_h = rows - 2
        for i in range(list_h):
            idx = bcs.alt_scroll + i
            if idx >= len(items):
                break
            y = 1 + i
            sel = idx == bcs.alt_cursor
            attr = curses.color_pair(_C_SEL_NAV) | curses.A_BOLD if sel else 0
            if idx < len(draft.alt_labels):
                chk = "[✓]" if (idx < len(draft.alt_checked) and draft.alt_checked[idx]) else "[ ]"
                label = f"{chk} {draft.alt_labels[idx]}"
            else:
                label = items[idx]
                if not sel:
                    attr = curses.color_pair(_C_FIELD_LABEL)
            prefix = "▶ " if sel else "  "
            try:
                stdscr.addstr(y, x0, (prefix + label).ljust(width - 1)[: width - 1], attr)
            except curses.error:
                pass
        _draw_bar(
            stdscr,
            rows - 1,
            x0,
            width,
            "  ↑↓/jk: navigate   Space/Enter: toggle   Enter on Done: confirm  ",
            dim=True,
        )

    def _draw_batch_definition(
        self,
        stdscr: curses.window,
        rows: int,
        x0: int,
        width: int,
        bcs: BatchCreateState,
        draft: BatchConceptDraft,
    ) -> None:
        _draw_bar(stdscr, 0, x0, width, self._batch_header(bcs, "Definition"), dim=False)
        if draft.def_generating:
            spinner = self._SPINNER[self._install_spinner % 4]
            elapsed = f"  {self._generate_elapsed:.0f}s" if self._generate_elapsed else ""
            try:
                stdscr.addstr(
                    rows // 2,
                    x0 + 2,
                    f"{spinner}  Generating definition…{elapsed}"[: width - 2],
                    curses.color_pair(_C_DIM),
                )
                stdscr.addstr(
                    rows // 2 + 1, x0 + 2, "  Esc to cancel"[: width - 2], curses.color_pair(_C_DIM)
                )
            except curses.error:
                pass
            _draw_bar(stdscr, rows - 1, x0, width, "", dim=True)
            return
        if draft.def_error:
            try:
                stdscr.addstr(
                    2,
                    x0 + 2,
                    f"Error: {draft.def_error}"[: width - 4],
                    curses.color_pair(_C_DIFF_DEL),
                )
            except curses.error:
                pass
        # Wrap and render definition buffer with a visible ▌ cursor
        max_w = width - 4
        text = draft.definition
        pos = bcs.def_pos
        # Insert cursor marker into a copy of the text for wrapping
        text_with_cursor = text[:pos] + "▌" + text[pos:]
        lines: list[str] = []
        for word_line in (text_with_cursor or "").splitlines() or [""]:
            if not word_line:
                lines.append("")
                continue
            while len(word_line) > max_w:
                lines.append(word_line[:max_w])
                word_line = word_line[max_w:]
            lines.append(word_line)
        list_h = rows - 4
        for i, ln in enumerate(lines[:list_h]):
            try:
                stdscr.addstr(
                    2 + i, x0 + 2, ln.ljust(max_w)[:max_w], curses.color_pair(_C_EDIT_BAR)
                )
            except curses.error:
                pass
        if bcs.error:
            try:
                stdscr.addstr(
                    rows - 2,
                    x0 + 1,
                    f"Error: {bcs.error}"[: width - 2],
                    curses.color_pair(_C_DIFF_DEL),
                )
            except curses.error:
                pass
        _draw_bar(stdscr, rows - 1, x0, width, "  Enter: confirm   Esc: back  ", dim=True)

    def _draw_batch_confirm(
        self,
        stdscr: curses.window,
        rows: int,
        x0: int,
        width: int,
        bcs: BatchCreateState,
        draft: BatchConceptDraft,
    ) -> None:
        """Render the per-concept confirmation screen (shown after each concept is created)."""
        is_last = bcs.current >= len(bcs.drafts) - 1
        _draw_bar(stdscr, 0, x0, width, self._batch_header(bcs, "Created ✓"), dim=False)

        y = 2
        max_w = width - 4

        def _row(text: str, attr: int = 0) -> None:
            nonlocal y
            try:
                stdscr.addstr(y, x0 + 2, text[:max_w], attr)
            except curses.error:
                pass
            y += 1

        selected_alts = [
            alt for alt, chk in zip(draft.alt_labels, draft.alt_checked, strict=False) if chk
        ]
        _row(f'"{draft.pref_label}"', curses.A_BOLD)
        y += 1
        if selected_alts:
            _row(f"Alt labels:  {', '.join(selected_alts)}", curses.color_pair(_C_DIM))
        if draft.definition.strip():
            # Wrap long definition
            defn = draft.definition.strip()
            while defn:
                _row(f"Definition:  {defn[: max_w - 12]}", curses.color_pair(_C_DIM))
                defn = defn[max_w - 12 :]
                if defn:
                    _row(f"             {defn[: max_w - 13]}", curses.color_pair(_C_DIM))
                    defn = ""
        if bcs.error:
            y += 1
            _row(f"Warning: {bcs.error}", curses.color_pair(_C_DIFF_DEL))

        # Action rows
        actions = ["→  Continue to next concept", "■  Stop here"] if not is_last else ["■  Done"]
        y = max(y + 1, rows - len(actions) - 2)
        for i, action in enumerate(actions):
            sel = i == bcs.confirm_cursor
            attr = (
                curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
                if sel
                else curses.color_pair(_C_FIELD_LABEL)
            )
            prefix = "▶ " if sel else "  "
            try:
                stdscr.addstr(y + i, x0, (prefix + action).ljust(width - 1)[: width - 1], attr)
            except curses.error:
                pass

        _draw_bar(stdscr, rows - 1, x0, width, "  ↑↓: select   Enter: confirm  ", dim=True)

    def _draw_batch_recap(
        self,
        stdscr: curses.window,
        rows: int,
        x0: int,
        width: int,
        bcs: BatchCreateState,
    ) -> None:
        n = len(bcs.drafts)
        _draw_bar(
            stdscr,
            0,
            x0,
            width,
            f" Create {n} concept{'s' if n != 1 else ''} — confirm ",
            dim=False,
        )
        # Build display lines for all drafts
        lines: list[tuple[str, int]] = []  # (text, attr)
        for draft in bcs.drafts:
            lines.append((f"  {draft.pref_label}", curses.A_BOLD))
            selected_alts = [
                alt for alt, chk in zip(draft.alt_labels, draft.alt_checked, strict=False) if chk
            ]
            if selected_alts:
                lines.append((f"    alt: {', '.join(selected_alts)}", curses.color_pair(_C_DIM)))
            if draft.definition.strip():
                defn = draft.definition.strip()
                max_w = width - 6
                lines.append((f"    def: {defn[:max_w]}", curses.color_pair(_C_DIM)))
            lines.append(("", 0))
        action_rows = ["✓  Create all", "←  Back", "✕  Cancel"]
        list_h = rows - 2
        total = len(lines) + len(action_rows)

        for i in range(list_h):
            idx = bcs.recap_scroll + i
            if idx >= total:
                break
            y = 1 + i
            sel = idx == bcs.recap_cursor
            if idx < len(lines):
                text, attr = lines[idx]
                if sel:
                    attr = curses.color_pair(_C_SEL)
                try:
                    stdscr.addstr(y, x0, text.ljust(width - 1)[: width - 1], attr)
                except curses.error:
                    pass
            else:
                action = action_rows[idx - len(lines)]
                attr = (
                    curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
                    if sel
                    else curses.color_pair(_C_FIELD_LABEL)
                )
                prefix = "▶ " if sel else "  "
                try:
                    stdscr.addstr(y, x0, (prefix + action).ljust(width - 1)[: width - 1], attr)
                except curses.error:
                    pass
        if bcs.error:
            try:
                stdscr.addstr(
                    rows - 2,
                    x0 + 1,
                    f"Error: {bcs.error}"[: width - 2],
                    curses.color_pair(_C_DIFF_DEL),
                )
            except curses.error:
                pass
        _draw_bar(stdscr, rows - 1, x0, width, "  ↑↓: scroll   Enter: select  ", dim=True)

    def _on_batch(self, key: int, rows: int) -> None:
        if not isinstance(self._state, BatchCreateState):
            return
        bcs = self._state
        if bcs.step == "label":
            self._on_batch_label(key, rows, bcs)
        elif bcs.step == "definition":
            self._on_batch_definition(key, rows, bcs)
        elif bcs.step == "alt_prompt_review":
            self._on_batch_alt_prompt_review(key, rows, bcs)
        elif bcs.step == "alt_labels":
            self._on_batch_alt_labels(key, rows, bcs)
        elif bcs.step == "confirm":
            self._on_batch_confirm(key, rows, bcs)
        elif bcs.step == "recap":
            self._on_batch_recap(key, rows, bcs)

    def _on_batch_label(self, key: int, rows: int, bcs: BatchCreateState) -> None:  # noqa: ARG002
        draft = bcs.drafts[bcs.current]
        if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            draft.pref_label = bcs.label_buffer.strip() or draft.name
            draft.def_generating = True
            bcs.step = "definition"
            bcs.def_pos = 0
        elif key == 27:
            # Cancel entire batch — return to tree/detail
            self._state = TreeState() if bcs.came_from_tree else DetailState()
        else:
            bcs.label_buffer, bcs.label_pos = self._apply_line_edit(
                bcs.label_buffer, bcs.label_pos, key
            )

    def _on_batch_definition(self, key: int, rows: int, bcs: BatchCreateState) -> None:  # noqa: ARG002
        draft = bcs.drafts[bcs.current]
        if draft.def_generating:
            return
        if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            # Build the alt-labels prompt and go to review step
            from . import ai as _ai

            taxonomy_name, taxonomy_desc, _, _pd = self._build_ai_context_from_uri(bcs.parent_uri)
            bcs.alt_prompt_buffer = _ai.render_suggest_alt_labels_prompt(
                pref_label=draft.pref_label,
                taxonomy_name=taxonomy_name,
                taxonomy_description=taxonomy_desc,
                lang=self.lang,
                concept_definition=draft.definition.strip(),
            )
            bcs.alt_prompt_pos = len(bcs.alt_prompt_buffer)
            bcs.alt_prompt_scroll = 0
            bcs.step = "alt_prompt_review"
        elif key == 27:
            bcs.step = "label"
        else:
            draft.definition, bcs.def_pos = self._apply_line_edit(
                draft.definition, bcs.def_pos, key
            )

    def _on_batch_alt_prompt_review(
        self,
        key: int,
        rows: int,
        bcs: BatchCreateState,  # noqa: ARG002
    ) -> None:
        """Handle keys on the editable alt-labels prompt screen."""
        if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            bcs.drafts[bcs.current].alts_generating = True
            bcs.step = "alt_labels"
            bcs.alt_cursor = 0
            bcs.alt_scroll = 0
        elif key == 27:
            bcs.step = "definition"
        else:
            bcs.alt_prompt_buffer, bcs.alt_prompt_pos = self._apply_line_edit(
                bcs.alt_prompt_buffer, bcs.alt_prompt_pos, key
            )

    def _on_batch_alt_labels(self, key: int, rows: int, bcs: BatchCreateState) -> None:  # noqa: ARG002
        draft = bcs.drafts[bcs.current]
        if draft.alts_generating:
            return
        items_count = len(draft.alt_labels) + 1  # checkboxes + Done
        done_idx = len(draft.alt_labels)
        KEY_UP, KEY_DOWN = curses.KEY_UP, curses.KEY_DOWN

        if key in (KEY_UP, ord("k")):
            bcs.alt_cursor = max(0, bcs.alt_cursor - 1)
            bcs.alt_scroll = min(bcs.alt_scroll, bcs.alt_cursor)
        elif key in (KEY_DOWN, ord("j")):
            bcs.alt_cursor = min(items_count - 1, bcs.alt_cursor + 1)
            if bcs.alt_cursor >= bcs.alt_scroll + (rows - 2):
                bcs.alt_scroll = bcs.alt_cursor - (rows - 2) + 1
        elif key == ord(" ") and bcs.alt_cursor < len(draft.alt_labels):
            draft.alt_checked[bcs.alt_cursor] = not draft.alt_checked[bcs.alt_cursor]
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if bcs.alt_cursor == done_idx:
                self._batch_create_current_and_confirm(bcs)
            elif bcs.alt_cursor < len(draft.alt_labels):
                draft.alt_checked[bcs.alt_cursor] = not draft.alt_checked[bcs.alt_cursor]
        elif key == 27:
            bcs.step = "alt_prompt_review"

    def _batch_create_current_and_confirm(self, bcs: BatchCreateState) -> None:
        """Create the concept at bcs.current, then transition to the confirm step."""
        import re

        draft = bcs.drafts[bcs.current]
        target_tax, _target_path = self._individual_taxonomy_for(bcs.parent_uri)

        if bcs.parent_uri and bcs.parent_uri in target_tax.schemes:
            s = target_tax.schemes[bcs.parent_uri]
            base = s.base_uri or target_tax.base_uri()
        else:
            base = target_tax.base_uri()

        parent_handle = None
        if bcs.parent_uri:
            parent_handle = target_tax.uri_to_handle(bcs.parent_uri) or bcs.parent_uri

        slug = re.sub(r"[^A-Za-z0-9_-]", "", draft.name.replace(" ", ""))
        new_uri = base + (slug or draft.name)
        if new_uri in target_tax.concepts:
            bcs.error = f"'{draft.name}' already exists — skipped"
            bcs.step = "confirm"
            bcs.confirm_cursor = 0
            return

        pref_label = draft.pref_label.strip() or draft.name
        definitions = {self.lang: draft.definition.strip()} if draft.definition.strip() else None
        try:
            operations.add_concept(
                target_tax,
                new_uri,
                {self.lang: pref_label},
                parent_handle=parent_handle,
                definitions=definitions,
            )
        except SkostaxError as exc:
            bcs.error = str(exc)
            bcs.step = "confirm"
            bcs.confirm_cursor = 0
            return

        for alt, chk in zip(draft.alt_labels, draft.alt_checked, strict=False):
            if chk and alt.strip():
                operations.set_label(target_tax, new_uri, self.lang, alt.strip(), LabelType.ALT)

        self._rebuild()
        self._save_file(uri=new_uri)
        bcs.error = ""
        bcs.step = "confirm"
        bcs.confirm_cursor = 0

    def _on_batch_confirm(self, key: int, rows: int, bcs: BatchCreateState) -> None:  # noqa: ARG002
        """Handle key events on the per-concept confirmation screen."""
        is_last = bcs.current >= len(bcs.drafts) - 1
        n_actions = 1 if is_last else 2
        KEY_UP, KEY_DOWN = curses.KEY_UP, curses.KEY_DOWN

        if key in (KEY_UP, ord("k")):
            bcs.confirm_cursor = max(0, bcs.confirm_cursor - 1)
        elif key in (KEY_DOWN, ord("j")):
            bcs.confirm_cursor = min(n_actions - 1, bcs.confirm_cursor + 1)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if is_last or bcs.confirm_cursor == 1:
                # Stop / Done — navigate to last created concept or back
                self._navigate_after_batch(bcs)
            else:
                # Continue — advance to next concept
                next_idx = bcs.current + 1
                bcs.current = next_idx
                draft = bcs.drafts[bcs.current]
                bcs.step = "label"
                bcs.label_buffer = draft.pref_label
                bcs.label_pos = len(draft.pref_label)
                bcs.alt_cursor = 0
                bcs.alt_scroll = 0
                bcs.def_pos = 0
                bcs.error = ""
        elif key == 27 and is_last:
            self._navigate_after_batch(bcs)

    def _navigate_after_batch(self, bcs: BatchCreateState) -> None:
        """Navigate to the last created concept (or back to tree/detail)."""
        target_tax, _target_path = self._individual_taxonomy_for(bcs.parent_uri)
        # Find the last draft whose concept was successfully created
        last_uri: str | None = None
        import re

        for draft in reversed(bcs.drafts[: bcs.current + 1]):
            slug = re.sub(r"[^A-Za-z0-9_-]", "", draft.name.replace(" ", ""))
            base = target_tax.base_uri()
            uri = base + (slug or draft.name)
            if uri in target_tax.concepts:
                last_uri = uri
                break
        if last_uri:
            for i, line in enumerate(self._flat):
                if line.uri == last_uri:
                    self._cursor = i
                    break
            self._detail_uri = last_uri
            assert self._detail_uri is not None
            self._detail_fields = self._bdf(self._detail_uri)
            self._field_cursor = 0
            self._detail_scroll = 0
            self._history.clear()
            self._state = DetailState()
        else:
            self._state = TreeState() if bcs.came_from_tree else DetailState()

    def _on_batch_recap(self, key: int, rows: int, bcs: BatchCreateState) -> None:
        # Build the same line count as _draw_batch_recap
        lines_count = 0
        for draft in bcs.drafts:
            lines_count += 1  # pref label
            selected_alts = [
                a for a, c in zip(draft.alt_labels, draft.alt_checked, strict=False) if c
            ]
            if selected_alts:
                lines_count += 1
            if draft.definition.strip():
                lines_count += 1
            lines_count += 1  # blank separator
        action_rows_count = 3
        total = lines_count + action_rows_count
        create_idx = lines_count
        back_idx = lines_count + 1
        cancel_idx = lines_count + 2
        list_h = rows - 2
        KEY_UP, KEY_DOWN = curses.KEY_UP, curses.KEY_DOWN

        if key in (KEY_UP, ord("k")):
            bcs.recap_cursor = max(0, bcs.recap_cursor - 1)
            bcs.recap_scroll = min(bcs.recap_scroll, bcs.recap_cursor)
        elif key in (KEY_DOWN, ord("j")):
            bcs.recap_cursor = min(total - 1, bcs.recap_cursor + 1)
            if bcs.recap_cursor >= bcs.recap_scroll + list_h:
                bcs.recap_scroll = bcs.recap_cursor - list_h + 1
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if bcs.recap_cursor == create_idx:
                self._submit_batch_create(bcs)
            elif bcs.recap_cursor == back_idx:
                # Go back to definition step of last concept
                bcs.step = "definition"
                bcs.current = len(bcs.drafts) - 1
            elif bcs.recap_cursor == cancel_idx:
                self._state = TreeState() if bcs.came_from_tree else DetailState()
        elif key == 27:
            self._state = TreeState() if bcs.came_from_tree else DetailState()

    def _submit_batch_create(self, bcs: BatchCreateState) -> None:
        """Create all confirmed concepts from the batch wizard."""
        import re

        target_tax, _target_path = self._individual_taxonomy_for(bcs.parent_uri)

        if bcs.parent_uri and bcs.parent_uri in target_tax.schemes:
            s = target_tax.schemes[bcs.parent_uri]
            base = s.base_uri or target_tax.base_uri()
        else:
            base = target_tax.base_uri()

        parent_handle = None
        if bcs.parent_uri:
            parent_handle = target_tax.uri_to_handle(bcs.parent_uri) or bcs.parent_uri

        last_uri: str | None = None
        for draft in bcs.drafts:
            slug = re.sub(r"[^A-Za-z0-9_-]", "", draft.name.replace(" ", ""))
            new_uri = base + (slug or draft.name)
            if new_uri in target_tax.concepts:
                bcs.error = f"'{draft.name}' already exists — skipped"
                continue
            pref_label = draft.pref_label.strip() or draft.name
            definitions = (
                {self.lang: draft.definition.strip()} if draft.definition.strip() else None
            )
            try:
                operations.add_concept(
                    target_tax,
                    new_uri,
                    {self.lang: pref_label},
                    parent_handle=parent_handle,
                    definitions=definitions,
                )
            except SkostaxError as exc:
                bcs.error = str(exc)
                continue
            # Add selected alt labels
            for alt, chk in zip(draft.alt_labels, draft.alt_checked, strict=False):
                if chk and alt.strip():
                    operations.set_label(target_tax, new_uri, self.lang, alt.strip(), LabelType.ALT)
            last_uri = new_uri

        self._rebuild()
        self._save_file(uri=last_uri or bcs.parent_uri)

        # Navigate to the last created concept (or back to tree/detail)
        if last_uri and last_uri in target_tax.concepts:
            for i, line in enumerate(self._flat):
                if line.uri == last_uri:
                    self._cursor = i
                    break
            self._detail_uri = last_uri
            self._detail_fields = self._bdf(last_uri)
            self._field_cursor = 0
            self._detail_scroll = 0
            self._history.clear()
            self._state = DetailState()
        else:
            self._state = TreeState() if bcs.came_from_tree else DetailState()

    # ── Add-concept step drawing ──────────────────────────────────────────────

    def _draw_create_choose(
        self, stdscr: curses.window, rows: int, x0: int, width: int, cs: CreateState
    ) -> None:
        """Render the 'choose input method' screen."""
        if cs.parent_uri and cs.parent_uri in self.taxonomy.schemes:
            scheme = self.taxonomy.schemes[cs.parent_uri]
            bar_title = f" Add concept to «{scheme.title(self.lang) or cs.parent_uri}» "
        elif cs.parent_uri:
            ph = self.taxonomy.uri_to_handle(cs.parent_uri) or "?"
            bar_title = f" Add concept under [{ph}] "
        else:
            bar_title = " Add concept "
        _draw_bar(stdscr, 0, x0, width, bar_title, dim=False)

        options = [
            "  ✏   Enter name manually",
            "  ✦   AI Auto Suggest",
        ]
        for i, label in enumerate(options):
            sel = i == cs.ai_cursor
            y = 2 + i
            try:
                attr = (
                    curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
                    if sel
                    else curses.color_pair(_C_FIELD_LABEL)
                )
                prefix = "▶ " if sel else "  "
                stdscr.addstr(y, x0, (prefix + label).ljust(width - 1)[: width - 1], attr)
            except curses.error:
                pass

        if cs.error:
            try:
                stdscr.addstr(
                    rows - 2,
                    x0 + 1,
                    f"Error: {cs.error}"[: width - 2],
                    curses.color_pair(_C_DIFF_DEL),
                )
            except curses.error:
                pass
        _draw_bar(
            stdscr,
            rows - 1,
            x0,
            width,
            "  ↑↓/jk: navigate   Enter: select   Esc: cancel  ",
            dim=True,
        )

    def _draw_create_context_review(
        self, stdscr: curses.window, rows: int, x0: int, width: int, cs: CreateState
    ) -> None:
        """Show the scheme/parent name + editable description before prompt generation."""
        _draw_bar(stdscr, 0, x0, width, " Context for AI — edit description if needed ", dim=False)
        try:
            label = f"  Name:  {cs.context_name}"
            stdscr.addstr(2, x0, label[: width - 1], curses.color_pair(_C_FIELD_LABEL))
            stdscr.addstr(4, x0, "  Description:"[: width - 1], curses.color_pair(_C_FIELD_LABEL))
        except curses.error:
            pass
        # Editable definition with ▌ cursor, word-wrapped
        buf = cs.context_def_buffer
        pos = cs.context_def_pos
        text_with_cursor = buf[:pos] + "▌" + buf[pos:]
        raw_lines = text_with_cursor.splitlines() or ["▌"]
        display_lines: list[str] = []
        for raw in raw_lines:
            while len(raw) > width - 4:
                display_lines.append(raw[: width - 4])
                raw = raw[width - 4 :]
            display_lines.append(raw)
        list_h = rows - 7
        for i in range(list_h):
            line = display_lines[i] if i < len(display_lines) else ""
            try:
                stdscr.addstr(5 + i, x0 + 2, line[: width - 4].ljust(width - 4)[: width - 4])
            except curses.error:
                pass
        _draw_bar(
            stdscr,
            rows - 1,
            x0,
            width,
            "  type to edit description   Enter: review prompt   Esc: back  ",
            dim=True,
        )

    def _draw_create_prompt_review(
        self, stdscr: curses.window, rows: int, x0: int, width: int, cs: CreateState
    ) -> None:
        """Render the editable prompt-review panel."""
        _draw_bar(stdscr, 0, x0, width, " Review & edit AI prompt — Enter: generate ", dim=False)
        buf = cs.prompt_buffer
        pos = cs.prompt_pos
        text_with_cursor = buf[:pos] + "▌" + buf[pos:]
        raw_lines = text_with_cursor.splitlines() or ["▌"]
        display_lines: list[str] = []
        for raw in raw_lines:
            while len(raw) > width:
                display_lines.append(raw[:width])
                raw = raw[width:]
            display_lines.append(raw)
        list_h = rows - 2
        # scroll so cursor line is visible
        cursor_line = len((buf[:pos] + "▌").splitlines()) - 1
        if cs.ai_scroll > cursor_line:
            cs.ai_scroll = cursor_line
        if cursor_line >= cs.ai_scroll + list_h:
            cs.ai_scroll = cursor_line - list_h + 1
        for i in range(list_h):
            idx = cs.ai_scroll + i
            line = display_lines[idx] if idx < len(display_lines) else ""
            try:
                stdscr.addstr(1 + i, x0, line[:width])
            except curses.error:
                pass
        _draw_bar(
            stdscr,
            rows - 1,
            x0,
            width,
            "  ↑↓: scroll   type to edit   Enter: generate   Esc: back  ",
            dim=True,
        )

    def _draw_create_ai_pick(
        self, stdscr: curses.window, rows: int, x0: int, width: int, cs: CreateState
    ) -> None:
        """Render the AI suggestion pick list with multi-select checkboxes."""
        _draw_bar(stdscr, 0, x0, width, " AI suggestions — select concepts ", dim=False)

        if cs.ai_generating:
            spinner = self._SPINNER[self._install_spinner % 4]
            elapsed = f"  {self._generate_elapsed:.0f}s" if self._generate_elapsed else ""
            try:
                stdscr.addstr(
                    rows // 2,
                    x0 + 2,
                    f"{spinner}  Generating suggestions…{elapsed}"[: width - 2],
                    curses.color_pair(_C_DIM),
                )
                stdscr.addstr(
                    rows // 2 + 1, x0 + 2, "  Esc to cancel"[: width - 2], curses.color_pair(_C_DIM)
                )
            except curses.error:
                pass
            _draw_bar(stdscr, rows - 1, x0, width, "", dim=True)
            return

        if cs.error:
            try:
                stdscr.addstr(2, x0 + 2, f"Error: {cs.error}"[: width - 4])
            except curses.error:
                pass

        # Manual input overlay
        if cs.ai_manual_mode:
            mid = rows // 2
            box_w = min(width - 4, 60)
            bx = x0 + (width - box_w) // 2
            try:
                stdscr.addstr(
                    mid - 1, bx, " Add concept manually "[:box_w], curses.color_pair(_C_FIELD_LABEL)
                )
                buf = cs.ai_manual_input
                visible = buf[max(0, len(buf) - box_w + 3) :]
                stdscr.addstr(
                    mid,
                    bx,
                    f" {visible}▌"[:box_w].ljust(box_w)[:box_w],
                    curses.color_pair(_C_EDIT_BAR),
                )
                stdscr.addstr(
                    mid + 1, bx, " Enter: add   Esc: cancel "[:box_w], curses.color_pair(_C_DIM)
                )
            except curses.error:
                pass
            return

        candidates = cs.ai_candidates
        checked = cs.ai_checked
        n_checked = sum(checked) if checked else 0
        create_label = f"✓  Create selected ({n_checked})"
        actions = ["▶  Suggest more", "➕  Add manually", create_label, "←  Back"]
        total = len(candidates) + len(actions)
        list_h = rows - 2

        for i in range(list_h):
            idx = cs.ai_scroll + i
            if idx >= total:
                break
            y = 1 + i
            sel = idx == cs.ai_cursor
            if idx < len(candidates):
                is_checked = checked[idx] if idx < len(checked) else False
                box = "[✓]" if is_checked else "[ ]"
                label = f"{box} {candidates[idx]}"
                attr = curses.color_pair(_C_SEL_NAV) | curses.A_BOLD if sel else 0
            else:
                action_idx = idx - len(candidates)
                label = actions[action_idx]
                is_create = action_idx == 2
                if is_create and n_checked == 0:
                    attr = curses.color_pair(_C_DIM)
                elif sel:
                    attr = curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
                else:
                    attr = curses.color_pair(_C_FIELD_LABEL)
            prefix = "▶ " if sel else "  "
            try:
                stdscr.addstr(y, x0, (prefix + label).ljust(width - 1)[: width - 1], attr)
            except curses.error:
                pass

        _draw_bar(
            stdscr,
            rows - 1,
            x0,
            width,
            "  ↑↓/jk: navigate   Space: toggle   Enter: confirm  ",
            dim=True,
        )

    # ── Add-concept step input handlers ──────────────────────────────────────

    def _on_create_choose(self, key: int, cs: CreateState) -> None:
        KEY_UP, KEY_DOWN = curses.KEY_UP, curses.KEY_DOWN
        n = 2  # two options
        if key in (KEY_UP, ord("k")):
            cs.ai_cursor = (cs.ai_cursor - 1) % n
        elif key in (KEY_DOWN, ord("j")):
            cs.ai_cursor = (cs.ai_cursor + 1) % n
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if cs.ai_cursor == 0:
                # Manual entry
                cs.fields = self._build_create_fields()
                cs.step = "form"
                cs.cursor = 0
            else:
                # AI suggest — show context review first
                taxonomy_name, _taxonomy_desc, parent_label, parent_def = self._build_ai_context(cs)
                cs.context_name = parent_label or taxonomy_name
                cs.context_def_buffer = parent_def
                cs.context_def_pos = len(parent_def)
                cs.step = "context_review"
        elif key == 27:
            self._state = TreeState() if cs.came_from_tree else DetailState()

    def _on_create_context_review(self, key: int, cs: CreateState) -> None:
        """Handle keys on the context-review step (editable definition)."""
        if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            from . import ai as _ai
            from .model import Definition

            taxonomy_name, taxonomy_desc, parent_label, _orig_def = self._build_ai_context(cs)
            # Use the (possibly edited) definition from the buffer
            edited_def = cs.context_def_buffer.strip()
            if parent_label:
                # narrower: save edited definition back to the parent concept
                target_tax, _ = self._individual_taxonomy_for(cs.parent_uri)
                concept = target_tax.concepts.get(cs.parent_uri or "")
                if concept:
                    for d in concept.definitions:
                        if d.lang == self.lang:
                            d.value = edited_def
                            break
                    else:
                        if edited_def:
                            concept.definitions.append(Definition(lang=self.lang, value=edited_def))
                    self._save_file(uri=cs.parent_uri)
                parent_def = edited_def
            else:
                # top-level: save edited description back to the scheme
                target_tax, _ = self._individual_taxonomy_for(cs.parent_uri)
                scheme = (
                    target_tax.schemes.get(cs.parent_uri or "")
                    if cs.parent_uri
                    else target_tax.primary_scheme()
                )
                if scheme:
                    for d in scheme.descriptions:
                        if d.lang == self.lang:
                            d.value = edited_def
                            break
                    else:
                        if edited_def:
                            scheme.descriptions.append(Definition(lang=self.lang, value=edited_def))
                    self._save_file(uri=cs.parent_uri or (scheme.uri if scheme else None))
                taxonomy_desc = edited_def
                parent_def = edited_def
            preview = _ai.render_suggest_concept_names_prompt(
                taxonomy_name=taxonomy_name,
                taxonomy_description=taxonomy_desc,
                parent_label=parent_label,
                parent_definition=parent_def,
                lang=self.lang,
                n=20,
                exclude=cs.ai_seen,
            )
            cs.prompt_buffer = preview
            cs.prompt_pos = len(preview)
            cs.ai_scroll = 0
            cs.step = "prompt_review"
        elif key == 27:
            cs.step = "choose"
            cs.ai_cursor = 1
        else:
            cs.context_def_buffer, cs.context_def_pos = self._apply_line_edit(
                cs.context_def_buffer, cs.context_def_pos, key
            )

    def _on_create_prompt_review(self, key: int, cs: CreateState) -> None:
        if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            cs.ai_generating = True
            cs.step = "ai_pick"
        elif key == 27:
            cs.step = "context_review"
        else:
            cs.prompt_buffer, cs.prompt_pos = self._apply_line_edit(
                cs.prompt_buffer, cs.prompt_pos, key
            )
            # keep scroll tracking with cursor
            lines_before = cs.prompt_buffer[: cs.prompt_pos].count("\n")
            cs.ai_scroll = max(0, lines_before - 3)

    def _on_create_ai_pick(self, key: int, rows: int, cs: CreateState) -> None:
        if cs.ai_generating:
            return

        # Manual input mode: typing a new concept name
        if cs.ai_manual_mode:
            if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                name = cs.ai_manual_input.strip()
                if name:
                    cs.ai_candidates.append(name)
                    cs.ai_checked.append(True)
                    cs.ai_seen.append(name)
                cs.ai_manual_input = ""
                cs.ai_manual_mode = False
            elif key == 27:
                cs.ai_manual_input = ""
                cs.ai_manual_mode = False
            else:
                new_buf, _pos = self._apply_line_edit(
                    cs.ai_manual_input, len(cs.ai_manual_input), key
                )
                cs.ai_manual_input = new_buf
            return

        KEY_UP, KEY_DOWN = curses.KEY_UP, curses.KEY_DOWN
        candidates = cs.ai_candidates
        # Action indices: suggest_more | add_manually | create_selected | back
        suggest_more_idx = len(candidates)
        add_manual_idx = len(candidates) + 1
        create_selected_idx = len(candidates) + 2
        back_idx = len(candidates) + 3
        total = len(candidates) + 4
        list_h = rows - 2
        n_checked = sum(cs.ai_checked) if cs.ai_checked else 0

        if key in (KEY_UP, ord("k")):
            cs.ai_cursor = max(0, cs.ai_cursor - 1)
            cs.ai_scroll = min(cs.ai_scroll, cs.ai_cursor)
        elif key in (KEY_DOWN, ord("j")):
            cs.ai_cursor = min(total - 1, cs.ai_cursor + 1)
            if cs.ai_cursor >= cs.ai_scroll + list_h:
                cs.ai_scroll = cs.ai_cursor - list_h + 1
        elif key == ord(" ") and 0 <= cs.ai_cursor < len(candidates):
            if cs.ai_cursor < len(cs.ai_checked):
                cs.ai_checked[cs.ai_cursor] = not cs.ai_checked[cs.ai_cursor]
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if cs.ai_cursor == suggest_more_idx:
                cs.ai_generating = True
            elif cs.ai_cursor == add_manual_idx:
                cs.ai_manual_mode = True
                cs.ai_manual_input = ""
            elif cs.ai_cursor == create_selected_idx and n_checked > 0:
                self._launch_batch_create(cs)
            elif cs.ai_cursor == back_idx:
                cs.step = "context_review"
            elif 0 <= cs.ai_cursor < len(candidates):
                if n_checked == 0:
                    # No checkboxes checked: single-pick → go straight to form
                    chosen = candidates[cs.ai_cursor]
                    cs.fields = self._build_create_fields()
                    for f in cs.fields:
                        if f.meta.get("field") == "name":
                            f.value = chosen
                            break
                    cs.step = "form"
                    cs.cursor = 0
                else:
                    if cs.ai_cursor < len(cs.ai_checked):
                        cs.ai_checked[cs.ai_cursor] = not cs.ai_checked[cs.ai_cursor]
        elif key == 27:
            cs.step = "context_review"

    def _render_create_col(self, stdscr: curses.window, rows: int, x0: int, width: int) -> None:
        # Access CreateState from self._state directly, or from EditState.return_to
        if isinstance(self._state, CreateState):
            cs = self._state
            _in_edit = False
        elif isinstance(self._state, EditState) and isinstance(self._state.return_to, CreateState):
            cs = self._state.return_to
            _in_edit = True
        else:
            return

        # Dispatch non-form steps (not applicable when in edit mode)
        if not _in_edit:
            if cs.step == "choose":
                self._draw_create_choose(stdscr, rows, x0, width, cs)
                return
            elif cs.step == "context_review":
                self._draw_create_context_review(stdscr, rows, x0, width, cs)
                return
            elif cs.step == "prompt_review":
                self._draw_create_prompt_review(stdscr, rows, x0, width, cs)
                return
            elif cs.step == "ai_pick":
                self._draw_create_ai_pick(stdscr, rows, x0, width, cs)
                return

        if _in_edit:
            _draw_bar(
                stdscr,
                0,
                x0,
                width,
                " ^A:start  ^E:end  ^W:del-word  ^K:kill-end"
                "  Alt+←→/^←→:word-jump  Enter:save  Esc:cancel ",
                dim=True,
            )
        else:
            if cs.parent_uri in self.taxonomy.schemes:
                scheme = self.taxonomy.schemes[cs.parent_uri]
                scheme_lbl = scheme.title(self.lang) or cs.parent_uri
                bar_title = f" New top concept in «{scheme_lbl}» "
            elif cs.parent_uri:
                ph = self.taxonomy.uri_to_handle(cs.parent_uri) or "?"
                bar_title = f" New concept under [{ph}] "
            else:
                bar_title = " New top concept "
            _draw_bar(stdscr, 0, x0, width, bar_title, dim=False)

        list_h = rows - 2
        n = len(cs.fields)

        if cs.cursor < cs.scroll:
            cs.scroll = cs.cursor
        elif cs.cursor >= cs.scroll + list_h:
            cs.scroll = cs.cursor - list_h + 1

        lbl_w = 18
        # Use the target scheme's base_uri when creating a top concept
        if cs.parent_uri and cs.parent_uri in self.taxonomy.schemes:
            s = self.taxonomy.schemes[cs.parent_uri]
            base = s.base_uri or self.taxonomy.base_uri()
        else:
            base = self.taxonomy.base_uri()
        for row in range(list_h):
            idx = cs.scroll + row
            if idx >= n:
                break
            f = cs.fields[idx]
            sel = idx == cs.cursor
            fl = f.display[:lbl_w].ljust(lbl_w)
            fv = f.value
            if f.meta.get("field") == "name":
                if fv:
                    preview = f"{base}{fv}" if base else fv
                    fv = f"{fv}  →  {preview}"
                else:
                    fv = "(required)"
            else:
                fv = fv[: width - lbl_w - 5]
            y = row + 1
            ftype = f.meta.get("type")
            try:
                if sel:
                    line = f"  {fl}  {fv}"
                    stdscr.addstr(
                        y,
                        x0,
                        line.ljust(width - 1)[: width - 1],
                        curses.color_pair(_C_SEL_NAV) | curses.A_BOLD,
                    )
                elif ftype == "form_action":
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                elif f.editable:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_FIELD_LABEL))
                    val_text = f.value if f.value else "(empty — press Enter to edit)"
                    stdscr.addstr(
                        y,
                        x0 + 2 + lbl_w + 2,
                        val_text[: width - lbl_w - 5],
                        curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD,
                    )
                else:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_DIM) | curses.A_DIM)
            except curses.error:
                pass

        if cs.error and not _in_edit:
            _draw_bar(stdscr, rows - 1, x0, width, f" ⚠  {cs.error} ", dim=False)
        else:
            n_fields = len(cs.fields)
            pos = f"[{cs.cursor + 1}/{n_fields}]"
            _draw_bar(
                stdscr,
                rows - 1,
                x0,
                width,
                f" {pos}  ↑↓/j·k  Enter: edit/select  Esc: cancel ",
                dim=True,
            )

    def _on_create(self, key: int, rows: int) -> None:
        if not isinstance(self._state, CreateState):
            return
        cs = self._state

        if cs.step == "choose":
            cs.error = ""
            self._on_create_choose(key, cs)
            return
        elif cs.step == "context_review":
            self._on_create_context_review(key, cs)
            return
        elif cs.step == "prompt_review":
            self._on_create_prompt_review(key, cs)
            return
        elif cs.step == "ai_pick":
            self._on_create_ai_pick(key, rows, cs)
            return

        cs.error = ""

        # step == "form" — existing logic below
        n = len(cs.fields)
        list_h = rows - 2

        if key in (curses.KEY_UP, ord("k")):
            cs.cursor = max(0, cs.cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            cs.cursor = min(n - 1, cs.cursor + 1)
        elif key in (curses.KEY_HOME, ord("g")):
            cs.cursor = 0
        elif key in (curses.KEY_END, ord("G")):
            cs.cursor = n - 1
        elif key == 4:
            cs.cursor = min(n - 1, cs.cursor + list_h // 2)
        elif key == 21:
            cs.cursor = max(0, cs.cursor - list_h // 2)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= cs.cursor < n:
                f = cs.fields[cs.cursor]
                if f.editable:
                    self._state = EditState(
                        buffer=f.value,
                        pos=len(f.value),
                        field=f,
                        return_to=cs,  # save CreateState as return_to
                    )
                elif f.meta.get("type") == "form_action":
                    act = f.meta.get("action")
                    if act == "submit":
                        self._submit_create()
                    elif act == "cancel":
                        self._state = TreeState() if cs.came_from_tree else DetailState()
        elif key == 27:  # Esc — cancel
            self._state = TreeState() if cs.came_from_tree else DetailState()

    def _submit_create(self) -> None:
        import re

        if not isinstance(self._state, CreateState):
            return
        cs = self._state
        name = ""
        pref_labels: dict[str, str] = {}
        definitions: dict[str, str] = {}

        for f in cs.fields:
            fld = f.meta.get("field")
            if fld == "name":
                name = f.value.strip()
            elif fld == "pref" and f.value.strip():
                pref_labels[f.meta["lang"]] = f.value.strip()
            elif fld == "def" and f.value.strip():
                definitions[f.meta["lang"]] = f.value.strip()

        if not name:
            cs.error = "Concept name is required"
            return

        target_tax, target_path = self._individual_taxonomy_for(cs.parent_uri)

        if cs.parent_uri and cs.parent_uri in target_tax.schemes:
            s = target_tax.schemes[cs.parent_uri]
            base = s.base_uri or target_tax.base_uri()
        else:
            base = target_tax.base_uri()
        new_uri = base + name

        if new_uri in target_tax.concepts:
            cs.error = f"'{name}' already exists"
            return

        if not pref_labels:
            label = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
            pref_labels[self.lang] = label

        parent_handle = None
        if cs.parent_uri:
            parent_handle = target_tax.uri_to_handle(cs.parent_uri) or cs.parent_uri

        try:
            operations.add_concept(
                target_tax,
                new_uri,
                pref_labels,
                parent_handle=parent_handle,
                definitions=definitions if definitions else None,
            )
        except SkostaxError as exc:
            cs.error = str(exc)
            return

        self._rebuild()
        self._save_file(uri=new_uri)

        # Navigate to the new concept detail
        for i, line in enumerate(self._flat):
            if line.uri == new_uri:
                self._cursor = i
                break
        self._detail_uri = new_uri
        self._detail_fields = self._bdf(new_uri)
        self._field_cursor = 0
        self._detail_scroll = 0
        self._history.clear()
        self._state = DetailState()

    # ─────────────────────────── SCHEME CREATE mode ──────────────────────────

    def _build_scheme_create_fields(self) -> list[DetailField]:
        return [
            DetailField(
                "sc_form:title",
                f"title [{self.lang}]",
                "",
                editable=True,
                meta={"type": "sc_form", "field": "title"},
            ),
            DetailField(
                "sc_form:uri",
                "URI",
                "",
                editable=True,
                meta={"type": "sc_form", "field": "uri"},
            ),
            DetailField(
                "sc_form:base_uri",
                "base URI",
                "",
                editable=True,
                meta={"type": "sc_form", "field": "base_uri"},
            ),
            DetailField(
                "sc_form:submit",
                "✓  Create scheme",
                "",
                editable=False,
                meta={"type": "form_action", "action": "submit_scheme"},
            ),
            DetailField(
                "sc_form:cancel",
                "✗  Cancel",
                "",
                editable=False,
                meta={"type": "form_action", "action": "cancel"},
            ),
        ]

    def _draw_scheme_create(self, stdscr: curses.window, rows: int, cols: int) -> None:
        stdscr.erase()
        wide = cols >= self._SPLIT_MIN_COLS
        tree_w = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w = cols - tree_w
        if wide:
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr, rows, 0, tree_w, cursor_idx=self._cursor, highlight_uri=None
            )  # type: ignore[call-arg]
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass
        self._render_scheme_create_col(stdscr, rows, detail_x0, detail_w)
        stdscr.refresh()

    def _render_scheme_create_col(
        self, stdscr: curses.window, rows: int, x0: int, width: int
    ) -> None:
        # Access SchemeCreateState from self._state or from EditState.return_to
        if isinstance(self._state, SchemeCreateState):
            scs = self._state
            _in_edit = False
        elif isinstance(self._state, EditState) and isinstance(
            self._state.return_to, SchemeCreateState
        ):
            scs = self._state.return_to
            _in_edit = True
        else:
            return
        if _in_edit:
            _draw_bar(
                stdscr,
                0,
                x0,
                width,
                " ^A:start  ^E:end  ^W:del-word  ^K:kill-end  Enter:save  Esc:cancel ",
                dim=True,
            )
        else:
            _draw_bar(stdscr, 0, x0, width, " ◉ New Concept Scheme ", dim=False)

        list_h = rows - 2
        n = len(scs.fields)

        if scs.cursor < scs.scroll:
            scs.scroll = scs.cursor
        elif scs.cursor >= scs.scroll + list_h:
            scs.scroll = scs.cursor - list_h + 1

        lbl_w = 18
        for row in range(list_h):
            idx = scs.scroll + row
            if idx >= n:
                break
            f = scs.fields[idx]
            sel = idx == scs.cursor
            fl = f.display[:lbl_w].ljust(lbl_w)
            fv = f.value
            ftype = f.meta.get("type")
            y = row + 1
            try:
                if sel:
                    line = f"  {fl}  {fv}"
                    stdscr.addstr(
                        y,
                        x0,
                        line.ljust(width - 1)[: width - 1],
                        curses.color_pair(_C_SEL_NAV) | curses.A_BOLD,
                    )
                elif ftype == "form_action":
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                elif f.editable:
                    stdscr.addstr(y, x0, "  ")
                    stdscr.addstr(y, x0 + 2, fl, curses.color_pair(_C_FIELD_LABEL))
                    val_text = f.value if f.value else "(empty — press Enter to edit)"
                    stdscr.addstr(
                        y,
                        x0 + 2 + lbl_w + 2,
                        val_text[: width - lbl_w - 5],
                        curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD,
                    )
            except curses.error:
                pass

        if scs.error and not _in_edit:
            _draw_bar(stdscr, rows - 1, x0, width, f" ⚠  {scs.error} ", dim=False)
        else:
            pos = f"[{scs.cursor + 1}/{n}]"
            _draw_bar(
                stdscr,
                rows - 1,
                x0,
                width,
                f" {pos}  ↑↓/j·k  Enter: edit/select  Esc: cancel ",
                dim=True,
            )

    def _on_scheme_create(self, key: int, rows: int) -> None:
        if not isinstance(self._state, SchemeCreateState):
            return
        scs = self._state
        n = len(scs.fields)
        list_h = rows - 2
        scs.error = ""

        if key in (curses.KEY_UP, ord("k")):
            scs.cursor = max(0, scs.cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            scs.cursor = min(n - 1, scs.cursor + 1)
        elif key in (curses.KEY_HOME, ord("g")):
            scs.cursor = 0
        elif key in (curses.KEY_END, ord("G")):
            scs.cursor = n - 1
        elif key == 4:
            scs.cursor = min(n - 1, scs.cursor + list_h // 2)
        elif key == 21:
            scs.cursor = max(0, scs.cursor - list_h // 2)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= scs.cursor < n:
                f = scs.fields[scs.cursor]
                if f.editable:
                    self._state = EditState(
                        buffer=f.value,
                        pos=len(f.value),
                        field=f,
                        return_to=scs,  # save SchemeCreateState as return_to
                    )
                elif f.meta.get("type") == "form_action":
                    act = f.meta.get("action")
                    if act == "submit_scheme":
                        self._submit_scheme_create()
                    elif act == "cancel":
                        self._state = TreeState() if scs.came_from_tree else DetailState()
        elif key == 27:  # Esc — cancel
            self._state = TreeState() if scs.came_from_tree else DetailState()

    def _submit_scheme_create(self) -> None:
        if not isinstance(self._state, SchemeCreateState):
            return
        scs = self._state
        title = ""
        uri = ""
        base_uri = ""

        for f in scs.fields:
            fld = f.meta.get("field")
            if fld == "title":
                title = f.value.strip()
            elif fld == "uri":
                uri = f.value.strip()
            elif fld == "base_uri":
                base_uri = f.value.strip()

        if not title:
            scs.error = "Title is required"
            return
        if not uri:
            scs.error = "URI is required"
            return
        if "://" not in uri:
            scs.error = "URI must be a full URL (e.g. https://…)"
            return
        prim_tax = self._workspace.taxonomies.get(self.file_path, self.taxonomy)
        if uri in prim_tax.schemes:
            scs.error = "Scheme URI already exists"
            return

        if base_uri and not base_uri.endswith(("/", "#")):
            base_uri += "/"

        try:
            operations.create_scheme(
                prim_tax,
                uri,
                labels={self.lang: title},
                base_uri=base_uri,
                languages=[self.lang],
            )
        except SkostaxError as exc:
            scs.error = str(exc)
            return

        self._rebuild()
        self._save_file(path=self.file_path)

        # Navigate to the new scheme detail
        for i, line in enumerate(self._flat):
            if line.uri == uri:
                self._cursor = i
                break
        self._detail_uri = uri
        self._detail_fields = build_scheme_fields(self.taxonomy, self.lang, scheme_uri=uri)
        self._field_cursor = 0
        self._detail_scroll = 0
        self._history.clear()
        self._state = DetailState()

    # ──────────────────────── ONTOLOGY SETUP prompt ──────────────────────────

    def _draw_ontology_setup(self, stdscr: curses.window, rows: int, cols: int) -> None:
        stdscr.erase()
        if not isinstance(self._state, OntologySetupState):
            return
        st = self._state
        width = cols

        _draw_bar(stdscr, 0, 0, width, " ⚠  Ontology has no URI ", dim=False)

        y = 2
        try:
            stdscr.addstr(
                y,
                2,
                "This file has no owl:Ontology or skos:ConceptScheme URI."[: width - 3],
                curses.color_pair(_C_FIELD_VAL),
            )
            y += 1
            stdscr.addstr(
                y,
                2,
                "pyLODE and other tools need one to generate documentation."[: width - 3],
                curses.color_pair(_C_FIELD_VAL),
            )
            y += 2

            # Name field
            name_sel = st.active == 0
            name_attr = (
                curses.color_pair(_C_EDIT_BAR) | curses.A_BOLD
                if name_sel
                else curses.color_pair(_C_FIELD_LABEL)
            )
            stdscr.addstr(y, 2, "Name:"[: width - 3], curses.color_pair(_C_DIM))
            y += 1
            name_display = st.name_buf + ("▌" if name_sel else "")
            stdscr.addstr(y, 4, name_display[: width - 5].ljust(width - 5), name_attr)
            y += 2

            # URI field
            uri_sel = st.active == 1
            uri_attr = (
                curses.color_pair(_C_EDIT_BAR) | curses.A_BOLD
                if uri_sel
                else curses.color_pair(_C_FIELD_LABEL)
            )
            stdscr.addstr(y, 2, "URI:"[: width - 3], curses.color_pair(_C_DIM))
            y += 1
            uri_display = st.uri_buf + ("▌" if uri_sel else "")
            stdscr.addstr(y, 4, uri_display[: width - 5].ljust(width - 5), uri_attr)
            y += 2

            if st.error:
                stdscr.addstr(y, 2, st.error[: width - 3], curses.color_pair(_C_DIFF_DEL))
                y += 1
        except curses.error:
            pass

        _draw_bar(
            stdscr,
            rows - 1,
            0,
            width,
            " Tab/↑↓: switch field   Enter: confirm   Esc: skip ",
            dim=True,
        )
        stdscr.refresh()

    def _on_ontology_setup(self, key: int) -> None:
        if not isinstance(self._state, OntologySetupState):
            return
        st = self._state

        if key in (9, curses.KEY_DOWN, curses.KEY_UP):  # Tab / arrows switch field
            st.active = 1 - st.active
            st.error = ""
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            name = st.name_buf.strip()
            uri = st.uri_buf.strip()
            if not name:
                st.error = "Name is required."
                st.active = 0
            elif not uri:
                st.error = "URI is required."
                st.active = 1
            elif " " in uri:
                st.error = "URI must not contain spaces."
                st.active = 1
            else:
                self.taxonomy.ontology_uri = uri
                self.taxonomy.ontology_label = name
                self._save_file()
                self._rebuild()
                self._state = TreeState()
        elif key == 27:  # Esc — skip without saving
            self._state = TreeState()
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if st.active == 0 and st.name_buf:
                st.name_buf = st.name_buf[:-1]
                st.name_pos = len(st.name_buf)
            elif st.active == 1 and st.uri_buf:
                st.uri_buf = st.uri_buf[:-1]
                st.uri_pos = len(st.uri_buf)
        elif 32 <= key < 256:
            ch = chr(key)
            if st.active == 0:
                st.name_buf += ch
                st.name_pos = len(st.name_buf)
            else:
                st.uri_buf += ch
                st.uri_pos = len(st.uri_buf)

    # ─────────────────────────── CONFIRM DELETE mode ─────────────────────────

    def _draw_confirm(self, stdscr: curses.window, rows: int, cols: int) -> None:
        stdscr.erase()
        wide = cols >= self._SPLIT_MIN_COLS
        tree_w = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w = cols - tree_w
        if wide:
            if self._detail_uri:
                for i, line in enumerate(self._flat):
                    if line.uri == self._detail_uri:
                        self._cursor = i
                        break
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr,
                rows,
                0,
                tree_w,
                cursor_idx=self._cursor,
                highlight_uri=self._detail_uri,
            )
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass
        self._render_confirm_col(stdscr, rows, detail_x0, detail_w)
        stdscr.refresh()

    def _render_confirm_col(self, stdscr: curses.window, rows: int, x0: int, width: int) -> None:
        concept = self.taxonomy.concepts.get(self._detail_uri) if self._detail_uri else None
        if not concept:
            return
        handle = self.taxonomy.uri_to_handle(self._detail_uri or "") or "?"
        label = concept.pref_label(self.lang) or self._detail_uri or ""
        n_children = len(concept.narrower)

        _draw_bar(stdscr, 0, x0, width, " ⊘ Confirm deletion ", dim=False)

        y = 2
        try:
            info = f"  [{handle}]  {label}"
            stdscr.addstr(y, x0, info[: width - 1], curses.color_pair(_C_SEL) | curses.A_BOLD)
            y += 1
            uri_line = f"  {self._detail_uri}"
            stdscr.addstr(y, x0, uri_line[: width - 1], curses.color_pair(_C_DIM) | curses.A_DIM)
            y += 2

            if n_children:
                total = len(operations._subtree_uris(self.taxonomy, self._detail_uri or ""))
                sub = f"subconcept{'s' if total != 1 else ''}"
                stdscr.addstr(
                    y,
                    x0,
                    f"  This concept has {n_children} direct and {total} total {sub}."[: width - 1],
                    curses.color_pair(_C_FIELD_VAL),
                )
                y += 1
                stdscr.addstr(
                    y,
                    x0,
                    f"  All {total} {sub} will also be deleted."[: width - 1],
                    curses.color_pair(_C_FIELD_VAL),
                )
                y += 2
                stdscr.addstr(
                    y,
                    x0,
                    "  y / Enter  — delete concept and all subconcepts"[: width - 1],
                    curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD,
                )
            else:
                stdscr.addstr(
                    y,
                    x0,
                    "  y / Enter  — confirm delete"[: width - 1],
                    curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD,
                )
            y += 1
            stdscr.addstr(y, x0, "  n / Esc    — cancel"[: width - 1], curses.color_pair(_C_DIM))
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
            target_tax, target_path = self._individual_taxonomy_for(self._detail_uri)
            concept = target_tax.concepts.get(self._detail_uri) if self._detail_uri else None
            has_children = bool(concept and concept.narrower)
            try:
                operations.remove_concept(target_tax, self._detail_uri or "", cascade=has_children)
            except SkostaxError as exc:
                self._status = str(exc)
                self._state = DetailState()
                return
            self._save_file(path=target_path)
            self._rebuild()
            self._history.clear()
            self._cursor = min(self._cursor, max(0, len(self._flat) - 1))
            self._state = TreeState()
        elif key in (ord("n"), 27):
            self._state = DetailState()

    # ──────────────── CLASS → INDIVIDUAL confirmation ────────────────────────

    def _do_class_to_individual(self, uri: str, reattach_to: list[str] | None = None) -> None:
        """Perform the class→individual conversion.

        *reattach_to*: if given, re-type affected individuals to these classes
        instead of deleting them.
        """
        rdf_class = self.taxonomy.owl_classes.get(uri)
        if not rdf_class:
            self._state = DetailState()
            return

        # Collect individuals currently typed as this class before we mutate
        affected = [
            ind_uri for ind_uri, ind in self.taxonomy.owl_individuals.items() if uri in ind.types
        ]

        individual = OWLIndividual(
            uri=uri,
            labels=list(rdf_class.labels),
            comments=list(rdf_class.comments),
            types=[p for p in rdf_class.sub_class_of if not is_builtin_uri(p)],
        )
        del self.taxonomy.owl_classes[uri]
        self.taxonomy.owl_individuals[uri] = individual

        # Scrub class-only references
        for cls in self.taxonomy.owl_classes.values():
            for lst in (cls.sub_class_of, cls.equivalent_class, cls.disjoint_with):
                if uri in lst:
                    lst.remove(uri)
        for prop in self.taxonomy.owl_properties.values():
            for lst in (prop.domains, prop.ranges):
                if uri in lst:
                    lst.remove(uri)

        for ind_uri in affected:
            ind = self.taxonomy.owl_individuals.get(ind_uri)
            if not ind:
                continue
            if uri in ind.types:
                ind.types.remove(uri)
            if reattach_to is not None:
                for parent in reattach_to:
                    if parent not in ind.types:
                        ind.types.append(parent)
            else:
                # Delete the individual entirely
                del self.taxonomy.owl_individuals[ind_uri]

        self._rebuild()
        self._save_file()
        self._detail_uri = uri
        self._detail_fields = self._bidf(uri)
        self._field_cursor = 0
        self._state = DetailState()

    def _draw_class_to_individual_confirm(
        self, stdscr: curses.window, rows: int, cols: int
    ) -> None:
        stdscr.erase()
        wide = cols >= self._SPLIT_MIN_COLS
        tree_w = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w = cols - tree_w
        if wide:
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr,
                rows,
                0,
                tree_w,
                cursor_idx=self._cursor,
                highlight_uri=None,
            )
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass
        self._render_class_to_individual_col(stdscr, rows, detail_x0, detail_w)
        stdscr.refresh()

    def _render_class_to_individual_col(
        self, stdscr: curses.window, rows: int, x0: int, width: int
    ) -> None:
        if not isinstance(self._state, ClassToIndividualState):
            return
        cs = self._state

        rdf_class = self.taxonomy.owl_classes.get(cs.class_uri)
        label = (rdf_class.label(self.lang) if rdf_class else None) or cs.class_uri
        handle = self.taxonomy.uri_to_handle(cs.class_uri) or "?"

        _draw_bar(stdscr, 0, x0, width, " ⚠  Class has typed individuals ", dim=False)

        y = 2
        try:
            stdscr.addstr(
                y,
                x0,
                f"  [{handle}]  {label}"[: width - 1],
                curses.color_pair(_C_SEL) | curses.A_BOLD,
            )
            y += 2
            n = len(cs.affected_uris)
            noun = "individual" if n == 1 else "individuals"
            stdscr.addstr(
                y,
                x0,
                f"  {n} {noun} will lose their class membership:"[: width - 1],
                curses.color_pair(_C_FIELD_VAL),
            )
            y += 1
            for ind_uri in cs.affected_uris[:5]:
                ind = self.taxonomy.owl_individuals.get(ind_uri)
                ind_lbl = (ind.label(self.lang) if ind else None) or ind_uri
                ind_h = self.taxonomy.uri_to_handle(ind_uri) or "?"
                stdscr.addstr(
                    y,
                    x0,
                    f"    • [{ind_h}]  {ind_lbl}"[: width - 1],
                    curses.color_pair(_C_DIM),
                )
                y += 1
            if n > 5:
                stdscr.addstr(
                    y, x0, f"    … and {n - 5} more"[: width - 1], curses.color_pair(_C_DIM)
                )
                y += 1
            y += 1

            has_parent = bool(cs.parent_uris)
            if has_parent:
                parent_labels = []
                for p in cs.parent_uris[:2]:
                    pc = self.taxonomy.owl_classes.get(p)
                    parent_labels.append((pc.label(self.lang) if pc else None) or p)
                parent_str = ", ".join(parent_labels)
            else:
                parent_str = ""

            options: list[str] = []
            options.append(f"  ⊘  Delete the {noun}")
            if has_parent:
                options.append(f"  ⇢  Re-attach {noun} to superclass ({parent_str})")
            options.append("  ✕  Cancel")

            for i, opt in enumerate(options):
                sel = i == cs.cursor
                attr = (
                    curses.color_pair(_C_SEL) | curses.A_BOLD
                    if sel
                    else curses.color_pair(_C_FIELD_VAL)
                )
                prefix = "▶" if sel else " "
                try:
                    stdscr.addstr(y, x0, f"{prefix}{opt}"[: width - 1], attr)
                except curses.error:
                    pass
                y += 1
        except curses.error:
            pass

        _draw_bar(
            stdscr,
            rows - 1,
            x0,
            width,
            " ↑↓: choose   Enter: confirm   Esc: cancel ",
            dim=True,
        )

    def _on_class_to_individual_confirm(self, key: int) -> None:
        if not isinstance(self._state, ClassToIndividualState):
            return
        cs = self._state
        has_parent = bool(cs.parent_uris)
        n_options = 3 if has_parent else 2  # delete / [re-attach] / cancel

        if key in (curses.KEY_UP, ord("k")):
            cs.cursor = max(0, cs.cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            cs.cursor = min(n_options - 1, cs.cursor + 1)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if cs.cursor == 0:
                # Delete individuals
                self._do_class_to_individual(cs.class_uri, reattach_to=None)
            elif has_parent and cs.cursor == 1:
                # Re-attach to superclass(es)
                self._do_class_to_individual(cs.class_uri, reattach_to=cs.parent_uris)
            else:
                # Cancel
                self._state = DetailState()
        elif key == 27:  # Esc
            self._state = DetailState()

    # ──────────────── INDIVIDUAL → CLASS confirmation ────────────────────────

    def _do_individual_to_class(self, uri: str) -> None:
        from .model import RDFClass

        individual = self.taxonomy.owl_individuals.get(uri)
        if not individual:
            self._state = DetailState()
            return

        rdf_class = RDFClass(
            uri=uri,
            labels=list(individual.labels),
            comments=list(individual.comments),
            sub_class_of=[t for t in individual.types if not is_builtin_uri(t)],
        )
        del self.taxonomy.owl_individuals[uri]
        self.taxonomy.owl_classes[uri] = rdf_class

        for ind in self.taxonomy.owl_individuals.values():
            ind.property_values = [(p, v) for p, v in ind.property_values if v != uri]

        self._rebuild()
        self._save_file()
        self._detail_uri = uri
        self._detail_fields = self._bcdf(uri)
        self._field_cursor = 0
        self._state = DetailState()

    def _draw_individual_to_class_confirm(
        self, stdscr: curses.window, rows: int, cols: int
    ) -> None:
        stdscr.erase()
        wide = cols >= self._SPLIT_MIN_COLS
        tree_w = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w = cols - tree_w
        if wide:
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr,
                rows,
                0,
                tree_w,
                cursor_idx=self._cursor,
                highlight_uri=None,
            )
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass
        self._render_individual_to_class_col(stdscr, rows, detail_x0, detail_w)
        stdscr.refresh()

    def _render_individual_to_class_col(
        self, stdscr: curses.window, rows: int, x0: int, width: int
    ) -> None:
        if not isinstance(self._state, IndividualToClassState):
            return
        cs = self._state

        individual = self.taxonomy.owl_individuals.get(cs.individual_uri)
        label = (individual.label(self.lang) if individual else None) or cs.individual_uri
        handle = self.taxonomy.uri_to_handle(cs.individual_uri) or "?"

        _draw_bar(stdscr, 0, x0, width, " ⚠  Individual has property relations ", dim=False)

        y = 2
        try:
            stdscr.addstr(
                y,
                x0,
                f"  [{handle}]  {label}"[: width - 1],
                curses.color_pair(_C_SEL) | curses.A_BOLD,
            )
            y += 2
            stdscr.addstr(
                y,
                x0,
                "  The following relations will be deleted:"[: width - 1],
                curses.color_pair(_C_FIELD_VAL),
            )
            y += 1

            shown = 0
            max_rows = rows - 8  # leave room for options + footer

            for _prop_uri, prop_lbl, target_lbl in cs.outgoing:
                if shown >= max_rows:
                    break
                stdscr.addstr(
                    y,
                    x0,
                    f"    → {prop_lbl}: {target_lbl}"[: width - 1],
                    curses.color_pair(_C_DIM),
                )
                y += 1
                shown += 1

            for src_lbl, _prop_uri, prop_lbl in cs.incoming:
                if shown >= max_rows:
                    break
                stdscr.addstr(
                    y,
                    x0,
                    f"    ← {src_lbl} ({prop_lbl})"[: width - 1],
                    curses.color_pair(_C_DIM),
                )
                y += 1
                shown += 1

            total = len(cs.outgoing) + len(cs.incoming)
            if shown < total:
                stdscr.addstr(
                    y,
                    x0,
                    f"    … and {total - shown} more"[: width - 1],
                    curses.color_pair(_C_DIM),
                )
                y += 1

            y += 1
            options = ["  ✓  Proceed (delete all relations)", "  ✕  Cancel"]
            for i, opt in enumerate(options):
                sel = i == cs.cursor
                attr = (
                    curses.color_pair(_C_SEL) | curses.A_BOLD
                    if sel
                    else curses.color_pair(_C_FIELD_VAL)
                )
                prefix = "▶" if sel else " "
                try:
                    stdscr.addstr(y, x0, f"{prefix}{opt}"[: width - 1], attr)
                except curses.error:
                    pass
                y += 1
        except curses.error:
            pass

        _draw_bar(
            stdscr,
            rows - 1,
            x0,
            width,
            " ↑↓: choose   Enter: confirm   Esc: cancel ",
            dim=True,
        )

    def _on_individual_to_class_confirm(self, key: int) -> None:
        if not isinstance(self._state, IndividualToClassState):
            return
        cs = self._state

        if key in (curses.KEY_UP, ord("k")):
            cs.cursor = max(0, cs.cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            cs.cursor = min(1, cs.cursor + 1)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if cs.cursor == 0:
                self._do_individual_to_class(cs.individual_uri)
            else:
                self._state = DetailState()
        elif key == 27:  # Esc
            self._state = DetailState()

    # ─────────────────────────── MOVE PICK mode ──────────────────────────────

    def _build_owl_class_candidates(
        self,
        source_uri: str,
        exclude_self: bool = True,
    ) -> list[tuple[str, str]]:
        """All OWL classes except *source_uri* and its subclass descendants."""
        # Descendants to exclude (to avoid cycles)
        excluded: set[str] = set()
        if exclude_self:
            excluded.add(source_uri)
            queue = [source_uri]
            while queue:
                u = queue.pop()
                for uri, cls in self.taxonomy.owl_classes.items():
                    if u in cls.sub_class_of and uri not in excluded:
                        excluded.add(uri)
                        queue.append(uri)

        candidates: list[tuple[str, str]] = [("__TOP__", "↑  (root — no superclass)")]
        for line in self._flat:
            if line.uri in excluded or line.is_scheme or line.is_file or line.is_action:
                continue
            owl_cls = self.taxonomy.owl_classes.get(line.uri)
            if owl_cls is not None:
                handle = self.taxonomy.uri_to_handle(line.uri) or "?"
                label = owl_cls.label(self.lang) or line.uri
                indent = "  " * line.depth
                candidates.append((line.uri, f"{indent}[{handle}]  {label}"))
        return candidates

    def _confirm_owl_reparent(self, new_parent_uri: str | None, replace: bool) -> None:
        """Set (or add) subClassOf for the source OWL class, then return to detail."""
        if not isinstance(self._state, MovePickState):
            return
        source_uri = self._state.source_uri
        rdf_class = self.taxonomy.owl_classes.get(source_uri)
        if not rdf_class:
            self._state = DetailState()
            return
        if replace:
            rdf_class.sub_class_of = [new_parent_uri] if new_parent_uri else []
        else:
            if new_parent_uri and new_parent_uri not in rdf_class.sub_class_of:
                rdf_class.sub_class_of.append(new_parent_uri)
        self._rebuild()
        self._save_file()
        for i, line in enumerate(self._flat):
            if line.uri == source_uri:
                self._cursor = i
                break
        self._detail_uri = source_uri
        self._detail_fields = self._bcdf(source_uri)
        self._field_cursor = 0
        self._history.clear()
        self._state = DetailState()

    def _build_move_candidates(self, source_uri: str) -> list[tuple[str, str]]:
        excluded = operations._subtree_uris(self.taxonomy, source_uri)
        candidates: list[tuple[str, str]] = [("__TOP__", "↑  (top level)")]
        for line in self._flat:
            if line.uri not in excluded:
                concept = self.taxonomy.concepts.get(line.uri)
                if concept:
                    handle = self.taxonomy.uri_to_handle(line.uri) or "?"
                    label = concept.pref_label(self.lang) or line.uri
                    indent = "  " * line.depth
                    candidates.append((line.uri, f"{indent}[{handle}]  {label}"))
        return candidates

    def _filtered_move_candidates(self) -> list[tuple[str, str]]:
        ms = self._state
        if not isinstance(ms, MovePickState):
            return []
        flt = ms.filter_text.lower()
        if not flt:
            return list(ms.candidates)
        # When filtering, drop class-header rows and match on display text only
        return [
            (u, d) for u, d in ms.candidates if not u.startswith("__HDR__:") and flt in d.lower()
        ]

    def _draw_move(
        self,
        stdscr: curses.window,
        rows: int,
        cols: int,
        title: str = "",
        empty_msg: str = "",
    ) -> None:
        stdscr.erase()
        wide = cols >= self._SPLIT_MIN_COLS
        tree_w = cols // 3 if wide else 0
        detail_x0 = tree_w
        detail_w = cols - tree_w
        ms = self._state if isinstance(self._state, MovePickState) else None
        highlight = ms.source_uri if ms else ""
        if wide:
            if highlight:
                for i, line in enumerate(self._flat):
                    if line.uri == highlight:
                        self._cursor = i
                        break
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr,
                rows,
                0,
                tree_w,
                cursor_idx=self._cursor,
                highlight_uri=highlight,
            )
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass
        self._render_move_col(stdscr, rows, detail_x0, detail_w, title=title, empty_msg=empty_msg)
        stdscr.refresh()

    def _render_move_col(
        self,
        stdscr: curses.window,
        rows: int,
        x0: int,
        width: int,
        title: str = "",
        empty_msg: str = "",
    ) -> None:
        ms = self._state if isinstance(self._state, MovePickState) else None
        source_uri = ms.source_uri if ms else ""
        source_handle = self.taxonomy.uri_to_handle(source_uri) or "?"
        if not title:
            title = f" ↷ Move [{source_handle}] — select new parent "
        _draw_bar(stdscr, 0, x0, width, title, dim=False)

        # Filter bar at row 1
        filter_text = ms.filter_text if ms else ""
        filter_prompt = f" Filter: {filter_text}▌"
        try:
            stdscr.addstr(
                1,
                x0,
                filter_prompt[: width - 1].ljust(width - 1),
                curses.color_pair(_C_EDIT_BAR) | curses.A_BOLD,
            )
        except curses.error:
            pass

        filtered = self._filtered_move_candidates()
        list_h = rows - 3  # title + filter + footer
        cursor = ms.cursor if ms else 0
        scroll = ms.scroll if ms else 0

        # Clamp cursor and scroll — always keep both non-negative so that
        # `idx = scroll + row` is never negative (negative indices silently
        # wrap in Python and would bypass the `idx >= len(filtered)` guard).
        if ms:
            n_flt = len(filtered)
            ms.cursor = max(0, min(ms.cursor, n_flt - 1) if n_flt else 0)
            cursor = ms.cursor
            ms.scroll = max(0, ms.scroll)
            if cursor < ms.scroll:
                ms.scroll = cursor
            elif list_h > 0 and cursor >= ms.scroll + list_h:
                ms.scroll = max(0, cursor - list_h + 1)
            scroll = ms.scroll

        if not filtered and empty_msg:
            try:
                stdscr.addstr(2, x0, f"  {empty_msg}"[: width - 1], curses.color_pair(_C_DIM))
            except curses.error:
                pass

        for row in range(list_h):
            idx = scroll + row
            if idx < 0 or idx >= len(filtered):
                break
            uri, display = filtered[idx]
            sel = idx == cursor
            text = f"  {display}"
            y = row + 2
            try:
                if sel:
                    stdscr.addstr(
                        y,
                        x0,
                        text[: width - 1].ljust(width - 1),
                        curses.color_pair(_C_SEL) | curses.A_BOLD,
                    )
                elif uri == "__TOP__" or uri.startswith("__HDR__:"):
                    stdscr.addstr(
                        y, x0, text[: width - 1], curses.color_pair(_C_DIM) | curses.A_BOLD
                    )
                else:
                    stdscr.addstr(y, x0, text[: width - 1])
            except curses.error:
                pass

        is_link = ms.is_link if ms else False
        source = self.taxonomy.concepts.get(source_uri)
        if not is_link and source and source.narrower:
            total = len(operations._subtree_uris(self.taxonomy, source_uri))
            sub_note = f" — moves {total} subconcept{'s' if total != 1 else ''} too"
        else:
            sub_note = ""
        action_verb = "link here" if is_link else "move here"
        _draw_bar(
            stdscr,
            rows - 1,
            x0,
            width,
            f" ↑↓: navigate  Enter: {action_verb}{sub_note}  Esc: cancel  type to filter ",
            dim=True,
        )

    def _on_move_pick(self, key: int, rows: int) -> None:
        if not isinstance(self._state, MovePickState):
            return
        ms = self._state
        filtered = self._filtered_move_candidates()
        n = len(filtered)
        list_h = rows - 3

        if key == curses.KEY_UP:
            ms.cursor = max(0, ms.cursor - 1)
        elif key == curses.KEY_DOWN:
            ms.cursor = max(0, min(n - 1, ms.cursor + 1))
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = max(0, min(n - 1, ms.cursor + list_h))
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= ms.cursor < n:
                uri, _ = filtered[ms.cursor]
                self._confirm_move(None if uri == "__TOP__" else uri)
        elif key == 27:  # Esc
            self._detail_uri = ms.source_uri
            self._detail_fields = self._bdf(self._detail_uri)
            self._state = DetailState()
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if ms.filter_text:
                ms.filter_text = ms.filter_text[:-1]
                ms.cursor = 0
                ms.scroll = 0
        elif 32 <= key < 256:
            ms.filter_text += chr(key)
            ms.cursor = 0
            ms.scroll = 0

    def _confirm_move(self, target_uri: str | None) -> None:
        if not isinstance(self._state, MovePickState):
            return
        source_uri = self._state.source_uri
        try:
            operations.move_concept(self.taxonomy, source_uri, target_uri)
        except SkostaxError as exc:
            self._status = str(exc)
            self._detail_uri = source_uri
            self._detail_fields = self._bdf(self._detail_uri)
            self._state = DetailState()
            return
        self._rebuild()
        self._save_file()
        for i, line in enumerate(self._flat):
            if line.uri == source_uri:
                self._cursor = i
                break
        self._detail_uri = source_uri
        self._detail_fields = self._bdf(source_uri)
        self._field_cursor = 0
        self._history.clear()
        self._state = DetailState()

    def _on_link_pick(self, key: int, rows: int) -> None:
        if not isinstance(self._state, MovePickState):
            return
        ms = self._state
        filtered = self._filtered_move_candidates()
        n = len(filtered)
        list_h = rows - 3

        if key == curses.KEY_UP:
            ms.cursor = max(0, ms.cursor - 1)
        elif key == curses.KEY_DOWN:
            ms.cursor = max(0, min(n - 1, ms.cursor + 1))
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = max(0, min(n - 1, ms.cursor + list_h))
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= ms.cursor < n:
                uri, _ = filtered[ms.cursor]
                self._confirm_link(uri)
        elif key == 27:  # Esc
            back_uri = ms.source_uri or self._detail_uri
            self._detail_uri = back_uri
            if self._detail_uri:
                self._detail_fields = self._bdf(self._detail_uri)
            self._state = DetailState()
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if ms.filter_text:
                ms.filter_text = ms.filter_text[:-1]
                ms.cursor = 0
                ms.scroll = 0
        elif 32 <= key < 256:
            ms.filter_text += chr(key)
            ms.cursor = 0
            ms.scroll = 0

    def _on_owl_pick(self, key: int, rows: int, replace: bool) -> None:
        """Handle keypresses in OWL superclass pickers (link_superclass / move_class)."""
        if not isinstance(self._state, MovePickState):
            return
        ms = self._state
        filtered = self._filtered_move_candidates()
        n = len(filtered)
        list_h = rows - 3

        if key == curses.KEY_UP:
            ms.cursor = max(0, ms.cursor - 1)
        elif key == curses.KEY_DOWN:
            ms.cursor = max(0, min(n - 1, ms.cursor + 1))
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = max(0, min(n - 1, ms.cursor + list_h))
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= ms.cursor < n:
                uri, _ = filtered[ms.cursor]
                self._confirm_owl_reparent(None if uri == "__TOP__" else uri, replace=replace)
        elif key == 27:  # Esc
            self._detail_uri = ms.source_uri
            self._detail_fields = self._bcdf(self._detail_uri) if self._detail_uri else []
            self._state = DetailState()
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if ms.filter_text:
                ms.filter_text = ms.filter_text[:-1]
                ms.cursor = 0
                ms.scroll = 0
        elif 32 <= key < 256:
            ms.filter_text += chr(key)
            ms.cursor = 0
            ms.scroll = 0

    def _on_related_pick(self, key: int, rows: int) -> None:
        """Handle keypresses in the 'add related' picker."""
        if not isinstance(self._state, MovePickState):
            return
        ms = self._state
        filtered = self._filtered_move_candidates()
        n = len(filtered)
        list_h = rows - 3

        if key == curses.KEY_UP:
            ms.cursor = max(0, ms.cursor - 1)
        elif key == curses.KEY_DOWN:
            ms.cursor = max(0, min(n - 1, ms.cursor + 1))
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = max(0, min(n - 1, ms.cursor + list_h))
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= ms.cursor < n:
                uri, _ = filtered[ms.cursor]
                self._confirm_related(uri)
        elif key == 27:  # Esc
            back_uri = ms.source_uri or self._detail_uri
            self._detail_uri = back_uri
            if self._detail_uri:
                self._detail_fields = self._bdf(self._detail_uri)
            self._state = DetailState()
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if ms.filter_text:
                ms.filter_text = ms.filter_text[:-1]
                ms.cursor = 0
                ms.scroll = 0
        elif 32 <= key < 256:
            ms.filter_text += chr(key)
            ms.cursor = 0
            ms.scroll = 0

    def _build_range_class_candidates(self, prop: object) -> list[tuple[str, str]]:
        """Build a hierarchically-indented class list for the range of *prop*.

        If prop has no declared ranges, all known OWL classes are offered.
        Subclasses are indented under their parent with two spaces per level.
        The root class is always shown even if not explicitly in owl_classes.
        """
        from .model import OWLProperty as _OWLProp

        range_roots: list[str] = (
            list(prop.ranges)
            if isinstance(prop, _OWLProp) and prop.ranges
            else sorted(self.taxonomy.owl_classes)
        )

        seen: set[str] = set()
        candidates: list[tuple[str, str]] = []

        def visit(cls_uri: str, depth: int) -> None:
            if cls_uri in seen:
                return
            seen.add(cls_uri)
            cls = self.taxonomy.owl_classes.get(cls_uri)
            lbl = cls.label(self.lang) if cls else cls_uri
            candidates.append((cls_uri, "  " * depth + lbl))
            for sub_uri in sorted(
                u for u, c in self.taxonomy.owl_classes.items() if cls_uri in c.sub_class_of
            ):
                visit(sub_uri, depth + 1)

        for root in range_roots:
            visit(root, 0)  # always visit — visit() handles missing owl_classes entry

        return candidates

    def _make_class_or_individual_state(
        self,
        ind_uri: str,
        prop_uri: str,
        prop: object,
        replace_val_uri: str = "",
    ) -> MovePickState:
        """Return a grouped individual picker: all range-class instances grouped by class."""
        return MovePickState(
            source_uri=f"{ind_uri}::{prop_uri}",
            pick_type="add_prop_value_grouped",
            candidates=self._build_individual_candidates_grouped(prop, ind_uri),
            filter_text="",
            cursor=0,
            scroll=0,
            replace_val_uri=replace_val_uri,
        )

    def _build_individual_candidates_for_class(
        self, class_uri: str, exclude_uri: str
    ) -> list[tuple[str, str]]:
        """Build individual candidates typed as *class_uri* or any of its subclasses."""
        candidates: list[tuple[str, str]] = []
        for i_uri, ind in sorted(
            self.taxonomy.owl_individuals.items(), key=lambda kv: kv[1].label(self.lang)
        ):
            if i_uri == exclude_uri:
                continue
            if class_uri not in _effective_types(self.taxonomy, ind.types):
                continue
            h = self.taxonomy.uri_to_handle(i_uri) or "?"
            lbl = ind.label(self.lang)
            type_lbls = [
                self.taxonomy.owl_classes[t].label(self.lang)
                if t in self.taxonomy.owl_classes
                else t
                for t in ind.types
            ]
            type_str = f"  ({', '.join(type_lbls)})" if type_lbls else ""
            candidates.append((i_uri, f"[{h}]  {lbl}{type_str}"))
        return candidates

    def _build_individual_candidates_grouped(
        self, prop: object, exclude_uri: str
    ) -> list[tuple[str, str]]:
        """Build grouped candidates: class headers with indented individuals underneath.

        Traverses the range class hierarchy depth-first.  Each class gets a bold
        header row (URI prefix ``__HDR__:``) followed by its direct instances,
        then its subclass groups recursively.  Individuals that belong to multiple
        classes only appear under their most-specific (deepest) class.
        """
        from .model import OWLProperty as _OWLProp

        range_roots: list[str] = (
            list(prop.ranges)  # type: ignore[union-attr]
            if isinstance(prop, _OWLProp) and prop.ranges  # type: ignore[union-attr]
            else sorted(self.taxonomy.owl_classes)
        )

        candidates: list[tuple[str, str]] = []
        added_ind_uris: set[str] = set()
        seen_class_uris: set[str] = set()

        def add_group(class_uri: str, depth: int) -> None:
            if class_uri in seen_class_uris:
                return
            seen_class_uris.add(class_uri)

            cls = self.taxonomy.owl_classes.get(class_uri)
            cls_lbl = cls.label(self.lang) if cls else class_uri
            indent = "  " * depth

            sub_uris = sorted(
                u for u, c in self.taxonomy.owl_classes.items() if class_uri in c.sub_class_of
            )
            direct_inds = sorted(
                [
                    (uri, ind)
                    for uri, ind in self.taxonomy.owl_individuals.items()
                    if uri != exclude_uri and uri not in added_ind_uris and class_uri in ind.types
                ],
                key=lambda kv: kv[1].label(self.lang),
            )

            if not sub_uris and not direct_inds:
                return

            candidates.append((f"__HDR__:{class_uri}", f"{indent}▸ {cls_lbl}"))

            for sub_uri in sub_uris:
                add_group(sub_uri, depth + 1)

            for i_uri, ind in direct_inds:
                if i_uri not in added_ind_uris:
                    h = self.taxonomy.uri_to_handle(i_uri) or "?"
                    lbl = ind.label(self.lang)
                    candidates.append((i_uri, f"{indent}  [{h}]  {lbl}"))
                    added_ind_uris.add(i_uri)

        for root in range_roots:
            add_group(root, 0)

        return candidates

    def _on_prop_value_grouped(self, key: int, rows: int) -> None:
        """Handle grouped individual picker (class headers + individuals)."""
        if not isinstance(self._state, MovePickState):
            return
        ms = self._state
        filtered = self._filtered_move_candidates()
        n = len(filtered)
        list_h = rows - 3

        parts = ms.source_uri.split("::", 1)
        if len(parts) != 2:
            self._state = DetailState()
            return
        ind_uri, prop_uri = parts

        def skip_headers(direction: int) -> None:
            while 0 <= ms.cursor < n and filtered[ms.cursor][0].startswith("__HDR__:"):
                ms.cursor += direction
            if n > 0:
                ms.cursor = max(0, min(n - 1, ms.cursor))

        # Ensure cursor starts on a selectable row (not a header)
        skip_headers(1)

        if key == curses.KEY_UP:
            ms.cursor = max(0, ms.cursor - 1)
            skip_headers(-1)
        elif key == curses.KEY_DOWN:
            ms.cursor = max(0, min(n - 1, ms.cursor + 1))
            skip_headers(1)
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
            skip_headers(-1)
        elif key == curses.KEY_NPAGE:
            ms.cursor = max(0, min(n - 1, ms.cursor + list_h))
            skip_headers(1)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= ms.cursor < n:
                val_uri, _ = filtered[ms.cursor]
                if not val_uri.startswith("__HDR__:"):
                    individual = self.taxonomy.owl_individuals.get(ind_uri)
                    if individual:
                        new_pair = (prop_uri, val_uri)
                        if ms.replace_val_uri:
                            old_pair = (prop_uri, ms.replace_val_uri)
                            if old_pair in individual.property_values:
                                idx = individual.property_values.index(old_pair)
                                individual.property_values[idx] = new_pair
                            elif new_pair not in individual.property_values:
                                individual.property_values.append(new_pair)
                        elif new_pair not in individual.property_values:
                            individual.property_values.append(new_pair)
                        self._save_file()
                    self._detail_uri = ind_uri
                    self._detail_fields = self._bidf(ind_uri)
                    self._field_cursor = 0
                    self._state = DetailState()
        elif key == 27:  # Esc — go back to property selection (step 1)
            individual = self.taxonomy.owl_individuals.get(ind_uri)
            ind_types = individual.types if individual else []
            eff = _effective_types(self.taxonomy, ind_types)
            applicable_props = [
                (p_uri, prop)
                for p_uri, prop in self.taxonomy.owl_properties.items()
                if prop.prop_type in ("ObjectProperty", "Property")
                and (not prop.domains or any(t in prop.domains for t in eff))
            ]
            step1_candidates: list[tuple[str, str]] = []
            for p_uri, prop in sorted(applicable_props, key=lambda kv: kv[1].label(self.lang)):
                h = self.taxonomy.uri_to_handle(p_uri) or "?"
                lbl = prop.label(self.lang)
                range_cls_lbls = [
                    self.taxonomy.owl_classes[r].label(self.lang)
                    if r in self.taxonomy.owl_classes
                    else r
                    for r in prop.ranges
                ]
                suffix = f"  ({', '.join(range_cls_lbls)})" if range_cls_lbls else ""
                step1_candidates.append((p_uri, f"[{h}]  {lbl}{suffix}"))
            self._state = MovePickState(
                source_uri=ind_uri,
                pick_type="add_prop_value_step1",
                candidates=step1_candidates,
                filter_text="",
                cursor=0,
                scroll=0,
                replace_val_uri=ms.replace_val_uri,
            )
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if ms.filter_text:
                ms.filter_text = ms.filter_text[:-1]
                ms.cursor = 0
                ms.scroll = 0
        elif 32 <= key < 256:
            ms.filter_text += chr(key)
            ms.cursor = 0
            ms.scroll = 0

    def _on_prop_value_step1(self, key: int, rows: int) -> None:
        """Handle property selection (step 1 of add-property-value flow)."""
        if not isinstance(self._state, MovePickState):
            return
        ms = self._state
        filtered = self._filtered_move_candidates()
        n = len(filtered)
        list_h = rows - 3

        if key == curses.KEY_UP:
            ms.cursor = max(0, ms.cursor - 1)
        elif key == curses.KEY_DOWN:
            ms.cursor = max(0, min(n - 1, ms.cursor + 1))
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = max(0, min(n - 1, ms.cursor + list_h))
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= ms.cursor < n:
                prop_uri, _ = filtered[ms.cursor]
                ind_uri = ms.source_uri
                prop = self.taxonomy.owl_properties.get(prop_uri)
                self._state = self._make_class_or_individual_state(
                    ind_uri, prop_uri, prop, ms.replace_val_uri
                )
        elif key == 27:  # Esc
            self._detail_uri = ms.source_uri
            self._detail_fields = self._bidf(ms.source_uri)
            self._state = DetailState()
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if ms.filter_text:
                ms.filter_text = ms.filter_text[:-1]
                ms.cursor = 0
                ms.scroll = 0
        elif 32 <= key < 256:
            ms.filter_text += chr(key)
            ms.cursor = 0
            ms.scroll = 0

    def _on_prop_value_step2(self, key: int, rows: int) -> None:
        """Handle range-class selection (step 2 of add-property-value flow)."""
        if not isinstance(self._state, MovePickState):
            return
        ms = self._state
        filtered = self._filtered_move_candidates()
        n = len(filtered)
        list_h = rows - 3

        # source_uri is "<individual_uri>::<prop_uri>"
        parts = ms.source_uri.split("::", 1)
        if len(parts) != 2:
            self._state = DetailState()
            return
        ind_uri, prop_uri = parts

        if key == curses.KEY_UP:
            ms.cursor = max(0, ms.cursor - 1)
        elif key == curses.KEY_DOWN:
            ms.cursor = max(0, min(n - 1, ms.cursor + 1))
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = max(0, min(n - 1, ms.cursor + list_h))
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= ms.cursor < n:
                class_uri, _ = filtered[ms.cursor]
                # Step 3: pick an individual of that class
                self._state = MovePickState(
                    source_uri=f"{ind_uri}::{prop_uri}::{class_uri}",
                    pick_type="add_prop_value_step3",
                    candidates=self._build_individual_candidates_for_class(class_uri, ind_uri),
                    filter_text="",
                    cursor=0,
                    scroll=0,
                    replace_val_uri=ms.replace_val_uri,
                )
        elif key == 27:  # Esc — go back to step 1
            individual = self.taxonomy.owl_individuals.get(ind_uri)
            ind_types = individual.types if individual else []
            eff = _effective_types(self.taxonomy, ind_types)
            applicable_props = [
                (p_uri, prop)
                for p_uri, prop in self.taxonomy.owl_properties.items()
                if prop.prop_type in ("ObjectProperty", "Property")
                and (not prop.domains or any(t in prop.domains for t in eff))
            ]
            candidates: list[tuple[str, str]] = []
            for p_uri, prop in sorted(applicable_props, key=lambda kv: kv[1].label(self.lang)):
                h = self.taxonomy.uri_to_handle(p_uri) or "?"
                lbl = prop.label(self.lang)
                range_cls_lbls = [
                    self.taxonomy.owl_classes[r].label(self.lang)
                    if r in self.taxonomy.owl_classes
                    else r
                    for r in prop.ranges
                ]
                suffix = f"  ({', '.join(range_cls_lbls)})" if range_cls_lbls else ""
                candidates.append((p_uri, f"[{h}]  {lbl}{suffix}"))
            self._state = MovePickState(
                source_uri=ind_uri,
                pick_type="add_prop_value_step1",
                candidates=candidates,
                filter_text="",
                cursor=0,
                scroll=0,
                replace_val_uri=ms.replace_val_uri,
            )
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if ms.filter_text:
                ms.filter_text = ms.filter_text[:-1]
                ms.cursor = 0
                ms.scroll = 0
        elif 32 <= key < 256:
            ms.filter_text += chr(key)
            ms.cursor = 0
            ms.scroll = 0

    def _on_prop_value_step3(self, key: int, rows: int) -> None:
        """Handle target-individual selection (step 3 of add-property-value flow)."""
        if not isinstance(self._state, MovePickState):
            return
        ms = self._state
        filtered = self._filtered_move_candidates()
        n = len(filtered)
        list_h = rows - 3

        # source_uri is "<individual_uri>::<prop_uri>::<class_uri>"
        parts = ms.source_uri.split("::", 2)
        if len(parts) != 3:
            self._state = DetailState()
            return
        ind_uri, prop_uri, class_uri = parts

        if key == curses.KEY_UP:
            ms.cursor = max(0, ms.cursor - 1)
        elif key == curses.KEY_DOWN:
            ms.cursor = max(0, min(n - 1, ms.cursor + 1))
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = max(0, min(n - 1, ms.cursor + list_h))
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= ms.cursor < n:
                val_uri, _ = filtered[ms.cursor]
                individual = self.taxonomy.owl_individuals.get(ind_uri)
                if individual:
                    new_pair = (prop_uri, val_uri)
                    if ms.replace_val_uri:
                        old_pair = (prop_uri, ms.replace_val_uri)
                        if old_pair in individual.property_values:
                            idx = individual.property_values.index(old_pair)
                            individual.property_values[idx] = new_pair
                        elif new_pair not in individual.property_values:
                            individual.property_values.append(new_pair)
                    elif new_pair not in individual.property_values:
                        individual.property_values.append(new_pair)
                    self._save_file()
                self._detail_uri = ind_uri
                self._detail_fields = self._bidf(ind_uri)
                self._field_cursor = 0
                self._state = DetailState()
        elif key == 27:  # Esc — go back to step 2 (or step 1 if step 2 was skipped)
            prop = self.taxonomy.owl_properties.get(prop_uri)
            back = self._make_class_or_individual_state(ind_uri, prop_uri, prop)
            if back.pick_type == "add_prop_value_step3":
                # Step 2 was auto-skipped (single class); go all the way to step 1
                self._detail_uri = ind_uri
                self._detail_fields = self._bidf(ind_uri)
                self._field_cursor = 0
                self._state = DetailState()
            else:
                self._state = back
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if ms.filter_text:
                ms.filter_text = ms.filter_text[:-1]
                ms.cursor = 0
                ms.scroll = 0
        elif 32 <= key < 256:
            ms.filter_text += chr(key)
            ms.cursor = 0
            ms.scroll = 0

    def _on_ind_type_pick(self, key: int, rows: int) -> None:
        """Handle class selection in the add-rdf:type flow."""
        if not isinstance(self._state, MovePickState):
            return
        ms = self._state
        filtered = self._filtered_move_candidates()
        n = len(filtered)
        list_h = rows - 3
        ind_uri = ms.source_uri

        if key == curses.KEY_UP:
            ms.cursor = max(0, ms.cursor - 1)
        elif key == curses.KEY_DOWN:
            ms.cursor = max(0, min(n - 1, ms.cursor + 1))
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = max(0, min(n - 1, ms.cursor + list_h))
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= ms.cursor < n:
                cls_uri, _ = filtered[ms.cursor]
                individual = self.taxonomy.owl_individuals.get(ind_uri)
                if individual and cls_uri not in individual.types:
                    individual.types.append(cls_uri)
                    self._save_file()
                    self._rebuild()
                self._detail_uri = ind_uri
                self._detail_fields = self._bidf(ind_uri)
                self._field_cursor = 0
                self._state = DetailState()
        elif key == 27:  # Esc
            self._detail_uri = ind_uri
            self._detail_fields = self._bidf(ind_uri)
            self._field_cursor = 0
            self._state = DetailState()
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if ms.filter_text:
                ms.filter_text = ms.filter_text[:-1]
                ms.cursor = 0
                ms.scroll = 0
        elif 32 <= key < 256:
            ms.filter_text += chr(key)
            ms.cursor = 0
            ms.scroll = 0

    def _on_prop_class_pick(self, key: int, rows: int, slot: str) -> None:
        """Handle keypresses in the add-domain / add-range class pickers."""
        if not isinstance(self._state, MovePickState):
            return
        ms = self._state
        filtered = self._filtered_move_candidates()
        n = len(filtered)
        list_h = rows - 3

        if key == curses.KEY_UP:
            ms.cursor = max(0, ms.cursor - 1)
        elif key == curses.KEY_DOWN:
            ms.cursor = max(0, min(n - 1, ms.cursor + 1))
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = max(0, min(n - 1, ms.cursor + list_h))
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= ms.cursor < n:
                cls_uri, _ = filtered[ms.cursor]
                prop = self.taxonomy.owl_properties.get(ms.source_uri or "")
                if prop:
                    if slot == "domain" and cls_uri not in prop.domains:
                        prop.domains.append(cls_uri)
                    elif slot == "range" and cls_uri not in prop.ranges:
                        prop.ranges.append(cls_uri)
                    self._save_file()
                self._detail_uri = ms.source_uri
                self._detail_fields = self._bpropf(ms.source_uri or "")
                self._field_cursor = 0
                self._state = DetailState()
        elif key == 27:  # Esc
            self._detail_uri = ms.source_uri
            self._detail_fields = self._bpropf(ms.source_uri or "")
            self._state = DetailState()
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if ms.filter_text:
                ms.filter_text = ms.filter_text[:-1]
                ms.cursor = 0
                ms.scroll = 0
        elif 32 <= key < 256:
            ms.filter_text += chr(key)
            ms.cursor = 0
            ms.scroll = 0

    def _trigger_create_owl(self, action: str) -> None:
        """Prompt for a URI, then create a new OWL class or property."""
        base_uri = self.taxonomy.base_uri()
        slot = "class" if action == "create_owl_class" else "property"
        ftype = f"new_owl_{slot}_uri"
        synthetic = DetailField(
            f"new:owl_{slot}",
            f"New {slot} URI",
            base_uri,
            editable=True,
            meta={"type": ftype},
        )
        self._state = EditState(buffer=base_uri, pos=len(base_uri), field=synthetic, return_to=None)

    def _trigger_create_individual(self, class_uri: str) -> None:
        """Prompt for a URI, then create a new owl:NamedIndividual typed as *class_uri*."""
        base_uri = self.taxonomy.base_uri()
        synthetic = DetailField(
            "new:owl_individual",
            "New individual URI",
            base_uri,
            editable=True,
            meta={"type": "new_owl_individual_uri", "class_uri": class_uri},
        )
        self._state = EditState(buffer=base_uri, pos=len(base_uri), field=synthetic, return_to=None)

    # ─── schema media helpers ─────────────────────────────────────────────────

    def _schema_entity(self) -> object | None:
        """Return the concept/class/individual currently shown in the detail panel."""
        if not self._detail_uri:
            return None
        uri = self._detail_uri
        return (
            self.taxonomy.concepts.get(uri)
            or self.taxonomy.owl_classes.get(uri)
            or self.taxonomy.owl_individuals.get(uri)
        )

    def _refresh_detail(self) -> None:
        """Rebuild the detail field list for the current detail_uri."""
        if not self._detail_uri:
            return
        uri = self._detail_uri
        if uri in self.taxonomy.concepts:
            self._detail_fields = self._bdf(uri)
        elif uri in self.taxonomy.owl_classes:
            self._detail_fields = self._bcdf(uri)
        elif uri in self.taxonomy.owl_individuals:
            self._detail_fields = self._bidf(uri)
        self._field_cursor = min(self._field_cursor, max(0, len(self._detail_fields) - 1))

    def _commit_schema_media(self, f: DetailField, new_value: str) -> None:
        """Append a schema:image / schema:video / schema:url URL to the current entity."""
        if not new_value or not self._detail_uri:
            return
        ftype = f.meta.get("type", "")
        entity = self._schema_entity()
        if entity is None:
            return
        if ftype == "schema_image_input":
            lst: list[str] = entity.schema_images  # type: ignore[attr-defined]
            if new_value not in lst:
                lst.append(new_value)
        elif ftype == "schema_video_input":
            lst = entity.schema_videos  # type: ignore[attr-defined]
            if new_value not in lst:
                lst.append(new_value)
        elif ftype == "schema_url_input":
            lst = entity.schema_urls  # type: ignore[attr-defined]
            if new_value not in lst:
                lst.append(new_value)
        else:
            return
        self._refresh_detail()
        self._save_file()

    def _confirm_related(self, target_uri: str) -> None:
        if not isinstance(self._state, MovePickState):
            return
        src = self._state.source_uri
        try:
            operations.add_related(self.taxonomy, src, target_uri)
        except SkostaxError as exc:
            self._status = str(exc)
            self._detail_uri = src
            self._detail_fields = self._bdf(self._detail_uri)
            self._state = DetailState()
            return
        self._rebuild()
        self._save_file()
        for i, line in enumerate(self._flat):
            if line.uri == src:
                self._cursor = i
                break
        self._detail_uri = src
        self._detail_fields = self._bdf(src)
        self._field_cursor = 0
        self._history.clear()
        self._state = DetailState()

    def _confirm_link(self, target_uri: str) -> None:
        if not isinstance(self._state, MovePickState):
            return
        src = self._state.source_uri
        try:
            operations.add_broader_link(self.taxonomy, src, target_uri)
        except SkostaxError as exc:
            self._status = str(exc)
            self._detail_uri = src
            self._detail_fields = self._bdf(src)
            self._state = DetailState()
            return
        self._rebuild()
        self._save_file()
        for i, line in enumerate(self._flat):
            if line.uri == src:
                self._cursor = i
                break
        self._detail_uri = src
        self._detail_fields = self._bdf(src)
        self._field_cursor = 0
        self._history.clear()
        self._state = DetailState()

    # ─────────────────── MAPPING (cross-scheme) pickers ─────────────────────

    _MAP_TYPE_LABELS: dict[str, str] = {
        "exactMatch": "⟺ exactMatch",
        "closeMatch": "≈  closeMatch",
        "broadMatch": "↗ broadMatch",
        "narrowMatch": "↙ narrowMatch",
        "relatedMatch": "↔ relatedMatch",
    }

    def _build_map_scheme_candidates(self, source_uri: str = "") -> list[tuple[str, str]]:
        """All schemes in the workspace except the one owning the source concept."""
        src_scheme = self._workspace.concept_scheme_uri(source_uri)
        result: list[tuple[str, str]] = []
        for path, t in self._workspace.taxonomies.items():
            for s_uri, scheme in t.schemes.items():
                if s_uri == src_scheme:
                    continue
                title = scheme.title(self.lang) or s_uri
                result.append((s_uri, f"{title}  [{path.name}]"))
        return result

    def _build_map_concept_candidates(self, scheme_uri: str) -> list[tuple[str, str]]:
        """All concepts in *scheme_uri*, in tree order."""
        t = self._workspace.taxonomy_for_uri(scheme_uri)
        if not t:
            return []
        scheme = t.schemes.get(scheme_uri)
        if not scheme:
            return []
        result: list[tuple[str, str]] = []
        seen: set[str] = set()

        def walk(uri: str, depth: int) -> None:
            if uri in seen:
                return
            seen.add(uri)
            c = t.concepts.get(uri)
            if not c:
                return
            label = c.pref_label(self.lang) or uri
            handle = t.uri_to_handle(uri) or "?"
            result.append((uri, f"{'  ' * depth}[{handle}]  {label}"))
            for child in c.narrower:
                walk(child, depth + 1)

        for tc in scheme.top_concepts:
            walk(tc, 0)
        return result

    # ── Step 1: scheme picker ─────────────────────────────────────────────────

    def _draw_map_scheme_pick(self, stdscr: curses.window, rows: int, cols: int) -> None:
        stdscr.erase()
        wide = cols >= self._SPLIT_MIN_COLS
        tree_w = cols // 3 if wide else 0
        detail_x = tree_w
        detail_w = cols - tree_w
        msp = self._state if isinstance(self._state, MapSchemePickState) else None
        source_uri = msp.source_uri if msp else ""
        if wide:
            if source_uri:
                for i, line in enumerate(self._flat):
                    if line.uri == source_uri:
                        self._cursor = i
                        break
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr,
                rows,
                0,
                tree_w,
                cursor_idx=self._cursor,
                highlight_uri=source_uri,
            )
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass

        src_handle = self.taxonomy.uri_to_handle(source_uri) or "?"
        map_type = msp.map_type if msp else ""
        type_label = self._MAP_TYPE_LABELS.get(map_type, map_type)
        _draw_bar(
            stdscr,
            0,
            detail_x,
            detail_w,
            f" {type_label} for [{src_handle}] — pick target scheme ",
        )

        cands = msp.candidates if msp else []
        list_h = rows - 2
        if msp and cands:
            msp.cursor = min(msp.cursor, len(cands) - 1)
        if msp:
            if msp.cursor < msp.scroll:
                msp.scroll = msp.cursor
            elif msp.cursor >= msp.scroll + list_h:
                msp.scroll = msp.cursor - list_h + 1
        cursor = msp.cursor if msp else 0
        scroll = msp.scroll if msp else 0

        for row in range(list_h):
            idx = scroll + row
            if idx >= len(cands):
                break
            _, display = cands[idx]
            sel = idx == cursor
            text = f"  ◉  {display}"
            y = row + 1
            try:
                if sel:
                    stdscr.addstr(
                        y,
                        detail_x,
                        text[: detail_w - 1].ljust(detail_w - 1),
                        curses.color_pair(_C_SEL) | curses.A_BOLD,
                    )
                else:
                    stdscr.addstr(
                        y, detail_x, text[: detail_w - 1], curses.color_pair(_C_NAVIGABLE)
                    )
            except curses.error:
                pass

        _draw_bar(
            stdscr,
            rows - 1,
            detail_x,
            detail_w,
            " ↑↓: navigate  Enter: select scheme  Esc: cancel ",
            dim=True,
        )
        stdscr.refresh()

    def _on_map_scheme_pick(self, key: int) -> None:
        if not isinstance(self._state, MapSchemePickState):
            return
        msp = self._state
        n = len(msp.candidates)
        if key == curses.KEY_UP:
            msp.cursor = max(0, msp.cursor - 1)
        elif key == curses.KEY_DOWN:
            msp.cursor = min(n - 1, msp.cursor + 1)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= msp.cursor < n:
                chosen_scheme, _ = msp.candidates[msp.cursor]
                concept_cands = self._build_map_concept_candidates(chosen_scheme)
                if not concept_cands:
                    self._status = "This scheme has no concepts to map to"
                else:
                    self._state = MapConceptPickState(
                        source_uri=msp.source_uri,
                        map_type=msp.map_type,
                        target_scheme=chosen_scheme,
                        candidates=concept_cands,
                        filter_text="",
                        cursor=0,
                        scroll=0,
                    )
        elif key == 27:  # Esc
            self._detail_uri = msp.source_uri
            self._detail_fields = self._bdf(msp.source_uri)
            self._state = DetailState()

    # ── Step 2: concept picker inside chosen scheme ───────────────────────────

    def _filtered_map_concept_cands(self) -> list[tuple[str, str]]:
        mcp = self._state if isinstance(self._state, MapConceptPickState) else None
        if not mcp:
            return []
        flt = mcp.filter_text.lower()
        return [(u, d) for u, d in mcp.candidates if not flt or flt in d.lower()]

    def _draw_map_concept_pick(self, stdscr: curses.window, rows: int, cols: int) -> None:
        stdscr.erase()
        wide = cols >= self._SPLIT_MIN_COLS
        tree_w = cols // 3 if wide else 0
        detail_x = tree_w
        detail_w = cols - tree_w
        mcp = self._state if isinstance(self._state, MapConceptPickState) else None
        source_uri = mcp.source_uri if mcp else ""
        if wide:
            if source_uri:
                for i, line in enumerate(self._flat):
                    if line.uri == source_uri:
                        self._cursor = i
                        break
            self._adjust_tree_scroll(rows)
            self._render_tree_col(
                stdscr,
                rows,
                0,
                tree_w,
                cursor_idx=self._cursor,
                highlight_uri=source_uri,
            )
            for y in range(rows):
                try:
                    stdscr.addch(y, tree_w - 1, curses.ACS_VLINE)
                except curses.error:
                    pass

        src_handle = self.taxonomy.uri_to_handle(source_uri) or "?"
        map_type = mcp.map_type if mcp else ""
        type_label = self._MAP_TYPE_LABELS.get(map_type, map_type)
        target_scheme = mcp.target_scheme if mcp else ""
        t = self._workspace.taxonomy_for_uri(target_scheme)
        scheme_obj = t.schemes.get(target_scheme) if t else None
        scheme_title = scheme_obj.title(self.lang) if scheme_obj else target_scheme
        _draw_bar(
            stdscr,
            0,
            detail_x,
            detail_w,
            f" {type_label} [{src_handle}] → {scheme_title} — pick concept ",
        )

        # Filter bar
        filter_text = mcp.filter_text if mcp else ""
        filter_prompt = f" Filter: {filter_text}▌"
        try:
            stdscr.addstr(
                1,
                detail_x,
                filter_prompt[: detail_w - 1].ljust(detail_w - 1),
                curses.color_pair(_C_EDIT_BAR) | curses.A_BOLD,
            )
        except curses.error:
            pass

        filtered = self._filtered_map_concept_cands()
        list_h = rows - 3
        cursor = mcp.cursor if mcp else 0
        scroll = mcp.scroll if mcp else 0
        if mcp and filtered:
            mcp.cursor = min(mcp.cursor, len(filtered) - 1)
            cursor = mcp.cursor
        if mcp:
            if cursor < mcp.scroll:
                mcp.scroll = cursor
                scroll = cursor
            elif cursor >= mcp.scroll + list_h:
                mcp.scroll = cursor - list_h + 1
                scroll = mcp.scroll

        for row in range(list_h):
            idx = scroll + row
            if idx >= len(filtered):
                break
            _, display = filtered[idx]
            sel = idx == cursor
            text = f"  {display}"
            y = row + 2
            try:
                if sel:
                    stdscr.addstr(
                        y,
                        detail_x,
                        text[: detail_w - 1].ljust(detail_w - 1),
                        curses.color_pair(_C_SEL) | curses.A_BOLD,
                    )
                else:
                    stdscr.addstr(y, detail_x, text[: detail_w - 1])
            except curses.error:
                pass

        _draw_bar(
            stdscr,
            rows - 1,
            detail_x,
            detail_w,
            " ↑↓: navigate  Enter: confirm  Esc: back to schemes  type to filter ",
            dim=True,
        )
        stdscr.refresh()

    def _on_map_concept_pick(self, key: int, rows: int) -> None:
        if not isinstance(self._state, MapConceptPickState):
            return
        mcp = self._state
        filtered = self._filtered_map_concept_cands()
        n = len(filtered)
        list_h = rows - 3

        if key == curses.KEY_UP:
            mcp.cursor = max(0, mcp.cursor - 1)
        elif key == curses.KEY_DOWN:
            mcp.cursor = min(n - 1, mcp.cursor + 1)
        elif key == curses.KEY_PPAGE:
            mcp.cursor = max(0, mcp.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            mcp.cursor = min(n - 1, mcp.cursor + list_h)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if 0 <= mcp.cursor < n:
                target_uri, _ = filtered[mcp.cursor]
                self._confirm_mapping(target_uri)
        elif key == 27:  # Esc → back to scheme picker
            scheme_cands = self._build_map_scheme_candidates(mcp.source_uri)
            self._state = MapSchemePickState(
                source_uri=mcp.source_uri,
                map_type=mcp.map_type,
                candidates=scheme_cands,
                cursor=0,
                scroll=0,
            )
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if mcp.filter_text:
                mcp.filter_text = mcp.filter_text[:-1]
                mcp.cursor = 0
                mcp.scroll = 0
        elif 32 <= key < 256:
            mcp.filter_text += chr(key)
            mcp.cursor = 0
            mcp.scroll = 0

    def _confirm_mapping(self, target_uri: str) -> None:
        from .workspace_ops import add_mapping

        if not isinstance(self._state, MapConceptPickState):
            return
        src = self._state.source_uri
        map_type = self._state.map_type
        try:
            src_file, tgt_file = add_mapping(
                self._workspace,
                src,
                target_uri,
                map_type,  # type: ignore[arg-type]
            )
        except Exception as exc:
            self._status = str(exc)
            self._detail_uri = src
            self._detail_fields = self._bdf(src)
            self._state = DetailState()
            return
        # Save both affected files and stage them in git
        self._workspace.save_file(src_file)
        self._workspace.save_file(tgt_file)
        if self._git_manager:
            self._git_manager.stage_path(src_file)  # type: ignore[attr-defined]
            if tgt_file != src_file:
                self._git_manager.stage_path(tgt_file)  # type: ignore[attr-defined]
        self._status = (
            f"Added {map_type}: {self.taxonomy.uri_to_handle(src) or src}"
            f" → {self.taxonomy.uri_to_handle(target_uri) or target_uri}"
        )
        self._rebuild()
        for i, line in enumerate(self._flat):
            if line.uri == src:
                self._cursor = i
                break
        self._detail_uri = src
        self._detail_fields = self._bdf(src)
        self._field_cursor = 0
        self._history.clear()
        self._state = DetailState()

    # ─────────────────────────── LANG PICK mode ──────────────────────────────

    def _draw_lang_pick(self, stdscr: curses.window, rows: int, cols: int) -> None:
        stdscr.erase()
        self._render_lang_col(stdscr, rows, 0, cols)
        stdscr.refresh()

    def _render_lang_col(self, stdscr: curses.window, rows: int, x0: int, width: int) -> None:
        lp = self._state if isinstance(self._state, LangPickState) else None
        options = lp.options if lp else []
        n = len(options)
        list_h = rows - 2

        _draw_bar(stdscr, 0, x0, width, " Select display language ", dim=False)

        # Scroll so cursor stays visible
        if lp:
            if lp.cursor < lp.scroll:
                lp.scroll = lp.cursor
            elif lp.cursor >= lp.scroll + list_h:
                lp.scroll = lp.cursor - list_h + 1
        cursor = lp.cursor if lp else 0
        scroll = lp.scroll if lp else 0

        for row in range(list_h):
            idx = scroll + row
            if idx >= n:
                break
            code = options[idx]
            sel = idx == cursor
            is_current = code == self.lang
            marker = " ✓" if is_current else "  "
            text = f"  {marker}  {code}"
            y = row + 1
            if sel:
                attr = curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
            elif is_current:
                attr = curses.color_pair(_C_FIELD_LABEL) | curses.A_BOLD
            else:
                attr = curses.A_NORMAL
            try:
                stdscr.addstr(y, x0, text.ljust(width - 1)[: width - 1], attr)
            except curses.error:
                pass

        _draw_bar(
            stdscr,
            rows - 1,
            x0,
            width,
            f" [{cursor + 1}/{n}]  ↑↓: move  Enter: select  Esc: cancel ",
            dim=True,
        )

    # ──────────────────────────── AI install overlay ─────────────────────────────

    _SPINNER = "|/-\\"

    def _draw_ai_install(self, stdscr: curses.window, rows: int, cols: int) -> None:
        """Install confirmation / progress overlay."""
        if not isinstance(self._state, AiInstallState):
            return
        st = self._state
        stdscr.erase()
        box_w = min(72, cols - 4)
        # height: title + blank + body lines + blank + progress bar + blank + hint
        body_lines = 3  # output lines shown during install
        box_h = body_lines + 6
        y0 = max(0, (rows - box_h) // 2)
        x0 = max(0, (cols - box_w) // 2)
        attr = curses.color_pair(_C_SEL)
        for i in range(box_h):
            try:
                stdscr.addstr(y0 + i, x0, " " * box_w, attr)
            except curses.error:
                pass

        def _put(row: int, text: str, bold: bool = False) -> None:
            a = attr | (curses.A_BOLD if bold else 0)
            try:
                stdscr.addstr(y0 + row, x0 + 2, text[: box_w - 4], a)
            except curses.error:
                pass

        def _center(row: int, text: str, bold: bool = False) -> None:
            a = attr | (curses.A_BOLD if bold else 0)
            pad = max(0, (box_w - len(text)) // 2)
            try:
                stdscr.addstr(y0 + row, x0 + pad, text[:box_w], a)
            except curses.error:
                pass

        if st.done:
            _center(0, " ✓  AI dependency installed ", bold=True)
            _center(2, "llm is ready to use.")
            _center(box_h - 2, "[Enter] continue to model setup    [Esc] cancel")
        elif st.error:
            _center(0, " Installation failed ", bold=True)
            _put(2, st.error)
            _center(box_h - 2, "[Esc] close")
        elif st.installing:
            spinner = self._SPINNER[self._install_spinner % 4]
            _center(0, f" {spinner}  Installing llm… ", bold=True)
            # Show last `body_lines` output lines
            recent = st.lines[-(body_lines):]
            for i, line in enumerate(recent):
                _put(2 + i, line)
            # Progress bar: pulse based on number of lines received
            bar_w = box_w - 6
            pos = (len(st.lines) * 4) % (bar_w * 2)
            filled = min(pos, bar_w - pos) if pos > bar_w else pos
            filled = max(2, filled)
            bar = "█" * filled + "░" * (bar_w - filled)
            _put(2 + body_lines + 1, f"[{bar}]")
            _center(box_h - 1, "")
        else:
            _center(0, " Install AI dependency ", bold=True)
            _center(2, "The 'llm' package is required for AI features.")
            _center(4, "It will be installed into the current Python environment.")
            _center(box_h - 2, "[Enter] install now    [Esc] cancel")
        stdscr.refresh()

    def _on_ai_install(self, key: int) -> None:
        if not isinstance(self._state, AiInstallState):
            return
        st = self._state
        if st.done:
            # Proceed to model setup — discover models fresh after install
            from . import ai

            pending = st.pending_action
            online, offline = ai.discover_models()
            self._state = AiSetupState(
                online_providers=online,
                offline_providers=offline,
                pending_action=pending,
            )
        elif st.error:
            if key == 27:
                self._state = TreeState()
        elif key == 27:
            self._state = TreeState()
        elif key in (ord("\n"), ord("\r"), 343):
            self._install_thread = None
            self._install_output = []
            self._install_returncode = None
            self._install_spinner = 0
            self._state = AiInstallState(
                pending_action=st.pending_action,
                installing=True,
            )

    @staticmethod
    def _strip_ansi(data: bytes) -> bytes:
        """Remove ANSI/VT100 escape sequences from a byte string."""
        import re

        return re.sub(rb"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", b"", data)

    def _ai_install_worker(self) -> None:
        """Daemon thread: runs a subprocess command and collects output.

        Uses self._install_command if set, otherwise falls back to
        ``pip install self._install_package``.

        Uses a PTY on Unix so the subprocess flushes output immediately
        (pipe mode causes block-buffering in many programs, e.g. ollama).
        Falls back to a plain pipe if pty is unavailable (Windows).
        Handles both \\n-terminated lines (pip) and \\r progress-bar lines
        (ollama) so the display updates live.
        """
        import os
        import subprocess

        cmd = self._install_command or [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-color",
            self._install_package,
        ]

        # --- open a PTY so the child sees a TTY and flushes promptly ----------
        try:
            import pty

            master_fd, slave_fd = pty.openpty()
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    close_fds=True,
                )
            except Exception:
                os.close(slave_fd)
                raise
            os.close(slave_fd)
            use_pty = True
        except FileNotFoundError:
            self._install_output.append(f"Command not found: {cmd[0]}")
            self._install_returncode = 127
            return
        except (ImportError, OSError):
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
            except FileNotFoundError:
                self._install_output.append(f"Command not found: {cmd[0]}")
                self._install_returncode = 127
                return
            use_pty = False

        # --- byte-by-byte reader: \r overwrites last line, \n appends ----------
        buf = b""

        def _flush(sep: bytes) -> None:
            nonlocal buf
            raw = self._strip_ansi(buf).decode("utf-8", errors="replace").strip()
            buf = b""
            if not raw:
                return
            if sep == b"\r":
                if self._install_output:
                    self._install_output[-1] = raw
                else:
                    self._install_output.append(raw)
            else:
                self._install_output.append(raw)

        if use_pty:
            while True:
                try:
                    chunk = os.read(master_fd, 256)
                except OSError:
                    break
                if not chunk:
                    break
                for byte in chunk:
                    b = bytes([byte])
                    if b in (b"\r", b"\n"):
                        _flush(b)
                    else:
                        buf += b
            try:
                os.close(master_fd)
            except OSError:
                pass
        else:
            assert proc.stdout is not None
            while True:
                b = proc.stdout.read(1)
                if not b:
                    break
                if b in (b"\r", b"\n"):
                    _flush(b)
                else:
                    buf += b

        _flush(b"\n")  # flush any remaining buffer
        proc.wait()
        self._install_returncode = proc.returncode

    def _ai_install_poll(self) -> None:
        """Called each loop iteration while installing. Starts thread, polls result."""
        import threading

        if not isinstance(self._state, AiInstallState):
            return
        st = self._state
        self._install_spinner += 1

        # Start thread once
        if self._install_thread is None:
            t = threading.Thread(target=self._ai_install_worker, daemon=True)
            self._install_thread = t
            t.start()

        # Snapshot output for display
        current_lines = list(self._install_output)

        # Check completion
        if self._install_returncode is not None:
            self._install_thread = None
            if self._install_returncode == 0:
                self._state = AiInstallState(
                    pending_action=st.pending_action,
                    done=True,
                    lines=current_lines,
                )
            else:
                err = current_lines[-1] if current_lines else "Installation failed"
                self._state = AiInstallState(
                    pending_action=st.pending_action,
                    error=err,
                    lines=current_lines,
                )
            return

        self._state = AiInstallState(
            pending_action=st.pending_action,
            installing=True,
            lines=current_lines,
        )

    def _ai_plugin_poll(self) -> None:
        """Called each loop iteration while a plugin is installing or a model is pulling."""
        import dataclasses
        import threading

        if not isinstance(self._state, AiSetupState):
            return
        st = self._state
        if st.step not in ("install_plugin", "ollama_pull") or not st.plugin_installing:
            return

        self._install_spinner += 1

        if self._install_thread is None:
            t = threading.Thread(target=self._ai_install_worker, daemon=True)
            self._install_thread = t
            t.start()

        current_lines = list(self._install_output)

        if self._install_returncode is not None:
            self._install_thread = None
            self._install_command = None  # reset so next pip install is unaffected
            if self._install_returncode == 0:
                self._state = dataclasses.replace(
                    st,
                    plugin_installing=False,
                    plugin_done=True,
                    plugin_lines=current_lines,
                )
            else:
                err = current_lines[-1] if current_lines else "Installation failed"
                self._state = dataclasses.replace(
                    st,
                    plugin_installing=False,
                    plugin_error=err,
                    plugin_lines=current_lines,
                )
        else:
            self._state = dataclasses.replace(st, plugin_lines=current_lines)

    # ──────────────────────────── AI setup wizard ─────────────────────────────────

    def _draw_ai_setup(self, stdscr: curses.window, rows: int, cols: int) -> None:
        """Guided AI model setup: mode → provider → model → key? → done."""
        if not isinstance(self._state, AiSetupState):
            return
        st = self._state
        stdscr.erase()
        box_w = min(72, cols - 4)
        list_h = max(4, rows - 10)
        box_h = min(rows - 2, list_h + 8)
        y0 = max(0, (rows - box_h) // 2)
        x0 = max(0, (cols - box_w) // 2)
        attr = curses.color_pair(_C_SEL)
        for i in range(box_h):
            try:
                stdscr.addstr(y0 + i, x0, " " * box_w, attr)
            except curses.error:
                pass

        def _put(row: int, text: str, bold: bool = False, hl: bool = False) -> None:
            a = (
                (curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                if hl
                else (attr | (curses.A_BOLD if bold else 0))
            )
            try:
                stdscr.addstr(y0 + row, x0 + 2, text[: box_w - 4], a)
            except curses.error:
                pass

        def _center(row: int, text: str, bold: bool = False) -> None:
            a = attr | (curses.A_BOLD if bold else 0)
            pad = max(0, (box_w - len(text)) // 2)
            try:
                stdscr.addstr(y0 + row, x0 + pad, text[:box_w], a)
            except curses.error:
                pass

        def _draw_list(
            items: list[tuple[str, str]], cursor: int, scroll: int, row_start: int
        ) -> None:
            for i in range(list_h):
                idx = scroll + i
                if idx >= len(items) or row_start + i >= box_h - 2:
                    break
                _, lbl = items[idx]
                _put(row_start + i, ("▶ " if idx == cursor else "  ") + lbl, hl=(idx == cursor))

        providers = st.online_providers if st.mode == "online" else st.offline_providers

        if st.step == "mode":
            _center(0, " Configure AI model ", bold=True)
            _put(2, "How do you want to run the AI?")
            has_online = bool(st.online_providers)
            has_offline = bool(st.offline_providers)
            modes = []
            if has_online:
                modes.append("☁  Online  — cloud API (requires an API key)")
            if has_offline:
                modes.append("⬛  Offline — local model (no key, runs on your machine)")
            modes.append("📋  Copy-paste — display prompt, paste response from any web AI")
            if not modes:
                _put(4, "No models found. Install llm plugins first:")
                _put(5, "  pip install llm-anthropic   # Claude")
                _put(6, "  pip install llm-ollama      # Ollama (local)")
                _put(7, "  pip install llm-gemini      # Gemini")
            else:
                for i, lbl in enumerate(modes):
                    _put(
                        4 + i,
                        ("▶ " if i == st.provider_cursor else "  ") + lbl,
                        hl=(i == st.provider_cursor),
                    )
            _center(box_h - 2, "[↑↓] choose    [Enter] select    [Esc] cancel")

        elif st.step == "provider":
            mode_label = (
                "Online providers  (API key required)"
                if st.mode == "online"
                else "Local / offline providers"
            )
            _center(0, f" {mode_label} ", bold=True)
            # Build items: providers + install entry
            items = [(p[0], p[1]) for p in providers] + [
                ("__install__", "+ Install more providers…")
            ]
            _draw_list(items, st.provider_cursor, st.provider_scroll, 2)
            if st.error:
                _put(box_h - 3, st.error)
            _center(box_h - 2, "[↑↓] choose    [Enter] select    [Esc] back")

        elif st.step == "ollama_pull":
            if st.plugin_installing:
                spinner = self._SPINNER[self._install_spinner % 4]
                _center(0, f" {spinner}  Pulling {st.selected_plugin_label}… ", bold=True)
                recent = st.plugin_lines[-(list_h - 4) :]
                for i, line in enumerate(recent):
                    _put(2 + i, line)
            elif st.plugin_done:
                _center(0, f" ✓  {st.selected_plugin_label} pulled ", bold=True)
                _center(box_h - 2, "[Enter / Esc] continue")
            elif st.plugin_error:
                _center(0, " Pull failed ", bold=True)
                _put(2, st.plugin_error[: box_w - 4])
                _put(3, "Check that the Ollama daemon is running.")
                _center(box_h - 2, "[Esc] back")
            else:
                # Input step: choose model name to pull
                _center(0, " Pull an Ollama model ", bold=True)
                _put(2, "Enter the model name to pull (e.g. llama3, mistral, phi3):")
                buf, pos = st.buffer, st.pos
                bar_w = box_w - 8
                offset = max(0, pos - bar_w + 1)
                visible = buf[offset : offset + bar_w]
                cursor_rel = pos - offset
                display = visible[:cursor_rel] + "▌" + visible[cursor_rel:]
                _put(4, f"Model:  {display[: bar_w + 1]}", bold=True)
                if st.plugin_error:
                    _put(6, st.plugin_error[: box_w - 4])
                _center(box_h - 2, "[Enter] pull    [Esc] back")

        elif st.step == "install_plugin":
            if st.plugin_installing:
                spinner = self._SPINNER[self._install_spinner % 4]
                _center(0, f" {spinner}  Installing {st.selected_plugin_label}… ", bold=True)
                recent = st.plugin_lines[-(list_h - 4) :]
                for i, line in enumerate(recent):
                    _put(2 + i, line)
                bar_w = box_w - 6
                pos = (len(st.plugin_lines) * 4) % (bar_w * 2)
                filled = min(pos, bar_w - pos) if pos > bar_w else pos
                bar = "█" * max(2, filled) + "░" * (bar_w - max(2, filled))
                _put(min(box_h - 3, 2 + len(recent) + 1), f"[{bar}]")
            elif st.plugin_done:
                _center(0, f" ✓  {st.selected_plugin_label} installed ", bold=True)
                _center(box_h - 2, "[Enter / Esc] back to provider list")
            elif st.plugin_error:
                _center(0, " Installation failed ", bold=True)
                _put(2, st.plugin_error[: box_w - 4])
                _center(box_h - 2, "[Esc] back")
            else:
                _center(0, " Install a provider plugin ", bold=True)
                plugins = st.available_plugins
                if plugins:
                    _draw_list(
                        [(p[0], p[1]) for p in plugins], st.plugin_cursor, st.plugin_scroll, 2
                    )
                else:
                    _put(3, "All known providers are already installed.")
                _center(box_h - 2, "[↑↓] choose    [Enter] install    [Esc] back")

        elif st.step == "model":
            provider = next((p for p in providers if p[0] == st.selected_provider_id), None)
            pname = provider[1].split("  ")[0] if provider else st.selected_provider_id
            _center(0, f" {pname} — choose a model ", bold=True)
            models = provider[2] if provider else []
            if models:
                _draw_list(models, st.model_cursor, st.model_scroll, 2)
            else:
                _put(2, "No models detected for this provider.")
                hint_row = 4
                is_ollama = st.selected_provider_id == "llm_ollama"
                if is_ollama:
                    _put(hint_row, "Ollama must be installed and running:")
                    _put(hint_row + 1, "    https://ollama.com/download")
                    hint_row += 3
                else:
                    _put(hint_row, "Start the provider service or configure it,")
                    _put(hint_row + 1, "then press [R] to refresh.")
                    hint_row += 3
                action_row = min(hint_row, box_h - 5)
                actions = (
                    [
                        "↺  Refresh model list",
                        "⬇  Pull a model (ollama pull…)",
                        "✏  Enter model ID manually",
                    ]
                    if is_ollama
                    else ["↺  Refresh model list", "✏  Enter model ID manually"]
                )
                for i, action in enumerate(actions):
                    sel = st.model_cursor == i
                    _put(action_row + i, ("▶ " if sel else "  ") + action, hl=sel)
            if st.error:
                _put(box_h - 3, st.error)
            _center(box_h - 2, "[↑↓] choose    [R] refresh    [Enter] select    [Esc] back")

        elif st.step == "model_input":
            provider = next((p for p in providers if p[0] == st.selected_provider_id), None)
            pname = provider[1].split("  ")[0] if provider else st.selected_provider_id
            _center(0, f" {pname} — enter model ID ", bold=True)
            _put(2, "Type the model ID exactly as shown by the provider.")
            if st.selected_provider_id == "llm_ollama":
                _put(3, "Example:  llama3    mistral    phi3")
            # Inline edit bar with ▌ cursor
            buf, pos = st.buffer, st.pos
            bar_w = box_w - 8
            offset = max(0, pos - bar_w + 1)
            visible = buf[offset : offset + bar_w]
            cursor_rel = pos - offset
            display = visible[:cursor_rel] + "▌" + visible[cursor_rel:]
            _put(5, f"Model ID:  {display[: bar_w + 1]}", bold=True)
            if st.error:
                _put(7, st.error)
            _center(box_h - 2, "[Enter] confirm    [Esc] back")

        elif st.step == "key":
            _center(0, f" API key for '{st.selected_model_id}' ", bold=True)
            _put(2, f"This model requires an API key  (key name: '{st.key_name}').")
            _put(3, "Get your key from the provider's website or developer console.")
            _put(5, f"Key: {'*' * len(st.buffer)}█")
            if st.error:
                _put(7, st.error)
            _center(box_h - 2, "[Enter] save & continue    [Esc] skip (configure later)")

        elif st.step == "done":
            if st.mode == "copypaste":
                _center(0, " ✓  Copy-paste mode enabled ", bold=True)
                _center(2, "Prompts will be shown and copied to your clipboard.")
                _center(3, "Paste the model response back to continue.")
            else:
                _center(0, " ✓  AI model configured ", bold=True)
                _center(2, f"Model: {st.selected_model_id}")
            if st.pending_action:
                _center(box_h - 2, "[Enter] start wizard    [Esc] close")
            else:
                _center(box_h - 2, "[Enter / Esc] close")

        stdscr.refresh()

    def _on_ai_setup(self, key: int) -> None:  # noqa: C901
        from . import ai as _ai

        if not isinstance(self._state, AiSetupState):
            return
        st = self._state
        KEY_UP, KEY_DOWN = 259, 258

        def _s(**kw: object) -> AiSetupState:
            d = {
                "step": st.step,
                "mode": st.mode,
                "online_providers": st.online_providers,
                "offline_providers": st.offline_providers,
                "provider_cursor": st.provider_cursor,
                "provider_scroll": st.provider_scroll,
                "model_cursor": st.model_cursor,
                "model_scroll": st.model_scroll,
                "selected_provider_id": st.selected_provider_id,
                "selected_model_id": st.selected_model_id,
                "key_name": st.key_name,
                "buffer": st.buffer,
                "pos": st.pos,
                "error": st.error,
                "pending_action": st.pending_action,
                "available_plugins": st.available_plugins,
                "plugin_cursor": st.plugin_cursor,
                "plugin_scroll": st.plugin_scroll,
                "plugin_installing": st.plugin_installing,
                "plugin_done": st.plugin_done,
                "plugin_error": st.plugin_error,
                "plugin_lines": st.plugin_lines,
                "selected_plugin_pkg": st.selected_plugin_pkg,
                "selected_plugin_label": st.selected_plugin_label,
            }
            d.update(kw)
            return AiSetupState(**d)  # type: ignore[arg-type]

        providers = st.online_providers if st.mode == "online" else st.offline_providers

        if st.step == "mode":
            # Build available mode list same as draw
            avail = []
            if st.online_providers:
                avail.append("online")
            if st.offline_providers:
                avail.append("offline")
            avail.append("copypaste")
            n = len(avail)
            if key == 27:
                self._state = TreeState()
            elif n > 0 and key in (KEY_UP, ord("k")):
                self._state = _s(provider_cursor=(st.provider_cursor - 1) % n)
            elif n > 0 and key in (KEY_DOWN, ord("j")):
                self._state = _s(provider_cursor=(st.provider_cursor + 1) % n)
            elif n > 0 and key in (ord("\n"), ord("\r"), 343):
                mode = avail[st.provider_cursor]
                if mode == "copypaste":
                    _ai.save_copypaste(True)
                    self._state = _s(step="done", mode="copypaste")
                else:
                    _ai.save_copypaste(False)
                    self._state = _s(
                        step="provider", mode=mode, provider_cursor=0, provider_scroll=0
                    )

        elif st.step == "provider":
            # Items = providers + install entry
            n = len(providers) + 1
            install_idx = len(providers)
            if key == 27:
                self._state = _s(step="mode", provider_cursor=0)
            elif key in (KEY_UP, ord("k")):
                c = max(0, st.provider_cursor - 1)
                self._state = _s(provider_cursor=c, provider_scroll=min(st.provider_scroll, c))
            elif key in (KEY_DOWN, ord("j")):
                c = min(n - 1, st.provider_cursor + 1)
                self._state = _s(provider_cursor=c, provider_scroll=max(st.provider_scroll, c - 3))
            elif key in (ord("\n"), ord("\r"), 343):
                if st.provider_cursor == install_idx:
                    from . import ai as _ai_mod

                    installed = {p[0] for p in st.online_providers + st.offline_providers}
                    plugins = _ai_mod.available_plugins(installed)
                    self._state = _s(
                        step="install_plugin",
                        available_plugins=plugins,
                        plugin_cursor=0,
                        plugin_scroll=0,
                        plugin_installing=False,
                        plugin_done=False,
                        plugin_error="",
                        plugin_lines=[],
                        selected_plugin_pkg="",
                        selected_plugin_label="",
                    )
                else:
                    pid, _, _ = providers[st.provider_cursor]
                    self._state = _s(
                        step="model",
                        selected_provider_id=pid,
                        model_cursor=0,
                        model_scroll=0,
                        error="",
                    )

        elif st.step == "install_plugin":
            if st.plugin_done:
                if key in (27, ord("\n"), ord("\r"), 343):
                    from . import ai as _ai_mod

                    online, offline = _ai_mod.discover_models()
                    self._state = _s(
                        step="provider",
                        online_providers=online,
                        offline_providers=offline,
                        provider_cursor=0,
                        provider_scroll=0,
                        plugin_installing=False,
                        plugin_done=False,
                        plugin_error="",
                        plugin_lines=[],
                        selected_plugin_pkg="",
                        selected_plugin_label="",
                    )
            elif st.plugin_error:
                if key == 27:
                    self._state = _s(
                        plugin_error="", selected_plugin_pkg="", selected_plugin_label=""
                    )
            elif not st.plugin_installing:
                plugins = st.available_plugins
                n = len(plugins)
                if key == 27:
                    self._state = _s(step="provider", provider_cursor=0, provider_scroll=0)
                elif n > 0 and key in (KEY_UP, ord("k")):
                    c = max(0, st.plugin_cursor - 1)
                    self._state = _s(plugin_cursor=c, plugin_scroll=min(st.plugin_scroll, c))
                elif n > 0 and key in (KEY_DOWN, ord("j")):
                    c = min(n - 1, st.plugin_cursor + 1)
                    self._state = _s(plugin_cursor=c, plugin_scroll=max(st.plugin_scroll, c - 3))
                elif n > 0 and key in (ord("\n"), ord("\r"), 343):
                    _, lbl, pkg = plugins[st.plugin_cursor]
                    self._install_package = pkg
                    self._install_output = []
                    self._install_returncode = None
                    self._install_spinner = 0
                    self._install_thread = None
                    self._state = _s(
                        plugin_installing=True,
                        selected_plugin_pkg=pkg,
                        selected_plugin_label=lbl,
                        plugin_lines=[],
                    )

        elif st.step == "model":
            provider = next((p for p in providers if p[0] == st.selected_provider_id), None)
            models = provider[2] if provider else []
            n = len(models)
            if key in (ord("r"), ord("R")):
                # R always refreshes
                online, offline = _ai.discover_models()
                self._state = _s(
                    online_providers=online,
                    offline_providers=offline,
                    model_cursor=0,
                    model_scroll=0,
                    error="",
                )
            elif key == 27:
                self._state = _s(step="provider", error="")
            elif n == 0 and key in (KEY_UP, ord("k")):
                is_ollama = st.selected_provider_id == "llm_ollama"
                self._state = _s(model_cursor=max(0, st.model_cursor - 1))
            elif n == 0 and key in (KEY_DOWN, ord("j")):
                is_ollama = st.selected_provider_id == "llm_ollama"
                n_actions = 3 if is_ollama else 2
                self._state = _s(model_cursor=min(n_actions - 1, st.model_cursor + 1))
            elif n == 0 and key in (ord("\n"), ord("\r"), 343):
                is_ollama = st.selected_provider_id == "llm_ollama"
                if st.model_cursor == 0:
                    # Refresh
                    online, offline = _ai.discover_models()
                    self._state = _s(
                        online_providers=online,
                        offline_providers=offline,
                        model_cursor=0,
                        model_scroll=0,
                        error="",
                    )
                elif is_ollama and st.model_cursor == 1:
                    # Pull a model
                    self._state = _s(
                        step="ollama_pull",
                        buffer="llama3",
                        pos=len("llama3"),
                        plugin_installing=False,
                        plugin_done=False,
                        plugin_error="",
                        plugin_lines=[],
                        selected_plugin_label="",
                    )
                else:
                    # Enter model ID manually
                    self._state = _s(step="model_input", buffer="", pos=0, error="")
            elif n > 0 and key in (KEY_UP, ord("k")):
                c = max(0, st.model_cursor - 1)
                self._state = _s(model_cursor=c, model_scroll=min(st.model_scroll, c))
            elif n > 0 and key in (KEY_DOWN, ord("j")):
                c = min(n - 1, st.model_cursor + 1)
                self._state = _s(model_cursor=c, model_scroll=max(st.model_scroll, c - 3))
            elif n > 0 and key in (ord("\n"), ord("\r"), 343):
                mid = models[st.model_cursor][0]
                key_name = _ai.model_needs_key(mid)
                if key_name:
                    self._state = _s(
                        step="key",
                        selected_model_id=mid,
                        key_name=key_name,
                        buffer="",
                        pos=0,
                        error="",
                    )
                else:
                    _ai.save_model(mid)
                    self._state = _s(step="done", selected_model_id=mid)

        elif st.step == "ollama_pull":
            if st.plugin_done:
                if key in (27, ord("\n"), ord("\r"), 343):
                    # Done — refresh model list and return to model step
                    online, offline = _ai.discover_models()
                    self._state = _s(
                        step="model",
                        online_providers=online,
                        offline_providers=offline,
                        model_cursor=0,
                        model_scroll=0,
                        plugin_installing=False,
                        plugin_done=False,
                        plugin_error="",
                        plugin_lines=[],
                        error="",
                    )
            elif st.plugin_error:
                if key == 27:
                    self._state = _s(
                        plugin_error="",
                        plugin_installing=False,
                        plugin_done=False,
                        plugin_lines=[],
                        buffer="llama3",
                        pos=len("llama3"),
                    )
            elif st.plugin_installing:
                pass  # wait for poll to finish
            else:
                # Input step: edit model name then confirm
                if key == 27:
                    self._state = _s(step="model", model_cursor=1, error="")
                elif key in (ord("\n"), ord("\r"), 343):
                    import shutil

                    model_name = st.buffer.strip()
                    if not model_name:
                        self._state = _s(plugin_error="Please enter a model name.")
                    else:
                        ollama_path = shutil.which("ollama")
                        if not ollama_path:
                            self._state = _s(
                                plugin_error="'ollama' not found. Install from https://ollama.com/download"
                            )
                        else:
                            self._install_command = [ollama_path, "pull", model_name]
                            self._install_output = []
                            self._install_returncode = None
                            self._install_spinner = 0
                            self._install_thread = None
                            self._state = _s(
                                plugin_installing=True,
                                selected_plugin_label=model_name,
                                plugin_lines=[],
                                plugin_error="",
                            )
                else:
                    buf, pos = st.buffer, st.pos
                    KEY_BS = curses.KEY_BACKSPACE
                    if key in (KEY_BS, 127, 8):
                        buf, pos = buf[: pos - 1] + buf[pos:], max(0, pos - 1)
                    elif key == curses.KEY_LEFT:
                        pos = max(0, pos - 1)
                    elif key == curses.KEY_RIGHT:
                        pos = min(len(buf), pos + 1)
                    elif key == 1:
                        pos = 0
                    elif key == 5:
                        pos = len(buf)
                    elif key == 11:
                        buf, pos = buf[:pos], pos
                    elif 32 <= key < 256:
                        buf = buf[:pos] + chr(key) + buf[pos:]
                        pos += 1
                    self._state = _s(buffer=buf, pos=pos, plugin_error="")

        elif st.step == "model_input":
            if key == 27:
                self._state = _s(step="model", model_cursor=2, error="")
            elif key in (ord("\n"), ord("\r"), 343):
                mid = st.buffer.strip()
                if not mid:
                    self._state = _s(error="Please enter a model ID.")
                else:
                    key_name = _ai.model_needs_key(mid)
                    if key_name:
                        self._state = _s(
                            step="key",
                            selected_model_id=mid,
                            key_name=key_name,
                            buffer="",
                            pos=0,
                            error="",
                        )
                    else:
                        _ai.save_model(mid)
                        self._state = _s(step="done", selected_model_id=mid)
            else:
                # Text editing — reuse the same logic as key step
                buf, pos = st.buffer, st.pos
                KEY_BS = curses.KEY_BACKSPACE
                if key in (KEY_BS, 127, 8):
                    buf, pos = buf[: pos - 1] + buf[pos:], max(0, pos - 1)
                elif key == curses.KEY_LEFT:
                    pos = max(0, pos - 1)
                elif key == curses.KEY_RIGHT:
                    pos = min(len(buf), pos + 1)
                elif key == 1:  # Ctrl+A
                    pos = 0
                elif key == 5:  # Ctrl+E
                    pos = len(buf)
                elif key == 11:  # Ctrl+K
                    buf, pos = buf[:pos], pos
                elif 32 <= key < 256:
                    buf = buf[:pos] + chr(key) + buf[pos:]
                    pos += 1
                self._state = _s(buffer=buf, pos=pos, error="")

        elif st.step == "key":
            if key == 27:
                _ai.save_model(st.selected_model_id)
                self._state = _s(step="done", error="")
            elif key in (ord("\n"), ord("\r"), 343):
                if st.buffer.strip():
                    _ai.save_key(st.key_name, st.buffer.strip())
                    _ai.save_model(st.selected_model_id)
                    self._state = _s(step="done", error="")
                else:
                    self._state = _s(error="Enter a key value or press Esc to skip")
            elif key in (263, 127, 8):
                self._state = _s(buffer=st.buffer[:-1], pos=max(0, st.pos - 1))
            elif 32 <= key < 256:
                self._state = _s(buffer=st.buffer + chr(key), pos=st.pos + 1)

        elif st.step == "done":
            if key in (27, ord("q")):
                self._state = TreeState()
            elif key in (ord("\n"), ord("\r"), 343):
                self._state = TreeState()
                if st.pending_action:
                    self._trigger_action(st.pending_action)

    def _on_lang_pick(self, key: int, rows: int) -> None:
        if not isinstance(self._state, LangPickState):
            return
        lp = self._state
        n = len(lp.options)
        list_h = rows - 2

        if key in (curses.KEY_UP, ord("k")):
            lp.cursor = max(0, lp.cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            lp.cursor = min(n - 1, lp.cursor + 1)
        elif key in (curses.KEY_HOME, ord("g")):
            lp.cursor = 0
        elif key in (curses.KEY_END, ord("G")):
            lp.cursor = n - 1
        elif key == 4:  # Ctrl+D
            lp.cursor = min(n - 1, lp.cursor + list_h // 2)
        elif key == 21:  # Ctrl+U
            lp.cursor = max(0, lp.cursor - list_h // 2)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            chosen = lp.options[lp.cursor]
            self.lang = chosen
            _save_lang_pref(self.file_path, chosen)
            self._rebuild()
            self._status = f"Display language → {chosen}"
            # Refresh scheme detail fields so the value field updates
            if self._detail_uri and self._detail_uri in self.taxonomy.schemes:
                self._detail_fields = build_scheme_fields(self.taxonomy, self.lang)
                self._field_cursor = 0
            self._state = DetailState()
        elif key in (27, ord("q")):
            self._state = DetailState()

    # ─────────────────────────── SPARQL QUERY mode ───────────────────────────

    # Layout constants
    _QUERY_EDIT_RATIO = 3  # editor takes ~1/3 of available rows

    def _draw_query(self, stdscr: curses.window, rows: int, cols: int) -> None:
        """Render the SPARQL query interface (editor + results + optional presets)."""
        from . import sparql_query as _sq

        qs = self._state
        if not isinstance(qs, QueryState):
            return

        # AI sub-flow screens take over the full display
        if qs.ai_step == "prompt_review" or qs.ai_generating:
            self._draw_query_ai_prompt_review(stdscr, rows, cols, qs)
            return

        stdscr.erase()

        # ── Dimensions ────────────────────────────────────────────────────────
        edit_h = max(5, (rows - 2) // self._QUERY_EDIT_RATIO)
        div_row = edit_h + 1
        res_start = div_row + 1
        res_h = max(0, rows - res_start - 1)

        # ── Header ────────────────────────────────────────────────────────────
        file_names = ", ".join(p.name for p in qs.file_paths) or "—"
        _draw_bar(stdscr, 0, 0, cols, f" ❯ SPARQL Query — {file_names} ", dim=False)

        # ── Editor ────────────────────────────────────────────────────────────
        is_edit = qs.panel == "editor"
        buf = qs.query_buffer
        pos = qs.query_pos
        default_attr = curses.color_pair(_C_FIELD_VAL) if is_edit else curses.color_pair(_C_DIM)

        # Build display lines tracking buffer offsets (no cursor injection)
        display_lines: list[str] = []
        display_buf_starts: list[int] = []
        buf_off = 0
        for raw_line in buf.split("\n") if buf else [""]:
            chunk_start = buf_off
            remaining = raw_line
            while len(remaining) > cols:
                display_lines.append(remaining[:cols])
                display_buf_starts.append(chunk_start)
                chunk_start += cols
                remaining = remaining[cols:]
            display_lines.append(remaining)
            display_buf_starts.append(chunk_start)
            buf_off += len(raw_line) + 1  # +1 for \n

        # Find which display line the cursor is on
        cursor_display_line = 0
        cursor_col_on_screen = 0
        for di in range(len(display_lines) - 1, -1, -1):
            if display_buf_starts[di] <= pos:
                cursor_display_line = di
                cursor_col_on_screen = pos - display_buf_starts[di]
                break

        # Scroll so cursor stays visible
        if qs.query_scroll > cursor_display_line:
            qs.query_scroll = cursor_display_line
        if cursor_display_line >= qs.query_scroll + edit_h:
            qs.query_scroll = cursor_display_line - edit_h + 1

        # Per-character syntax-highlight attrs
        char_attrs = _sparql_hl_attrs(buf, is_edit)

        for i in range(edit_h):
            idx = qs.query_scroll + i
            screen_y = 1 + i
            if idx >= len(display_lines):
                try:
                    stdscr.addstr(screen_y, 0, " " * cols, default_attr)
                except curses.error:
                    pass
                continue

            line_text = display_lines[idx]
            buf_start = display_buf_starts[idx]
            is_cursor_line = idx == cursor_display_line

            # Build coloured segments
            segments: list[tuple[str, int]] = []
            for ci, ch in enumerate(line_text):
                bp = buf_start + ci
                is_cur = is_cursor_line and ci == cursor_col_on_screen
                attr = (
                    curses.A_REVERSE
                    if is_cur
                    else (char_attrs[bp] if bp < len(char_attrs) else default_attr)
                )
                if segments and segments[-1][1] == attr and not is_cur:
                    segments[-1] = (segments[-1][0] + ch, attr)
                else:
                    segments.append((ch, attr))

            # Cursor at end-of-line
            if is_cursor_line and cursor_col_on_screen >= len(line_text):
                segments.append((" ", curses.A_REVERSE))

            # Render
            xcol = 0
            for seg_text, seg_attr in segments:
                if xcol >= cols:
                    break
                clip = seg_text[: cols - xcol]
                try:
                    stdscr.addstr(screen_y, xcol, clip, seg_attr)
                except curses.error:
                    pass
                xcol += len(clip)
            if xcol < cols:
                try:
                    stdscr.addstr(screen_y, xcol, " " * (cols - xcol), default_attr)
                except curses.error:
                    pass

        # ── Divider ───────────────────────────────────────────────────────────
        n_rows = len(qs.rows)
        if qs.running:
            sp = self._SPINNER[self._install_spinner % 4]
            div_label = f"  {sp} Running…  "
        elif qs.result_error:
            div_label = "  ✗ Error  "
        elif qs.columns:
            div_label = f"  Results — {n_rows} row{'s' if n_rows != 1 else ''}  "
        else:
            div_label = "  Results  "
        _draw_bar(stdscr, div_row, 0, cols, div_label, dim=qs.panel != "results")

        # ── Results area ──────────────────────────────────────────────────────
        is_res = qs.panel == "results"

        if qs.running:
            try:
                stdscr.addstr(
                    res_start + res_h // 2,
                    2,
                    "Executing query…",
                    curses.color_pair(_C_DIM),
                )
            except curses.error:
                pass
        elif qs.result_error:
            lines = qs.result_error.splitlines()
            for i, ln in enumerate(lines[: max(1, res_h)]):
                try:
                    stdscr.addstr(res_start + i, 1, ln[: cols - 2], curses.color_pair(_C_DIFF_DEL))
                except curses.error:
                    pass
        elif qs.columns:
            widths = _sq.compute_col_widths(qs.columns, qs.rows, cols - 1)
            # Header row
            hdr = ""
            for i, col in enumerate(qs.columns):
                hdr += col[: widths[i]].ljust(widths[i])
                if i < len(qs.columns) - 1:
                    hdr += " │ "
            try:
                stdscr.addstr(res_start, 0, hdr[:cols], curses.color_pair(_C_FIELD_LABEL))
            except curses.error:
                pass
            # Separator
            sep_line = "─" * (cols - 1)
            try:
                stdscr.addstr(res_start + 1, 0, sep_line[:cols], curses.color_pair(_C_DIM))
            except curses.error:
                pass
            # Data rows
            data_start = res_start + 2
            data_h = max(0, rows - data_start - 1)
            # Clamp scroll
            if qs.result_scroll + data_h > n_rows:
                qs.result_scroll = max(0, n_rows - data_h)
            for i in range(data_h):
                row_idx = qs.result_scroll + i
                if row_idx >= n_rows:
                    break
                row = qs.rows[row_idx]
                sel = is_res and row_idx == qs.result_cursor
                cell_text = ""
                for ci, val in enumerate(row):
                    if ci >= len(widths):
                        break
                    cell_text += val[: widths[ci]].ljust(widths[ci])
                    if ci < len(row) - 1:
                        cell_text += " │ "
                attr = curses.color_pair(_C_SEL) | curses.A_BOLD if sel else curses.A_NORMAL
                try:
                    stdscr.addstr(data_start + i, 0, cell_text[:cols].ljust(cols)[:cols], attr)
                except curses.error:
                    pass
        else:
            hint = "Ctrl+R or F5 to run query   P for presets   Tab to switch panel"
            try:
                stdscr.addstr(
                    res_start + res_h // 2,
                    max(0, (cols - len(hint)) // 2),
                    hint[:cols],
                    curses.color_pair(_C_DIM),
                )
            except curses.error:
                pass

        # ── Presets overlay ───────────────────────────────────────────────────
        if qs.show_presets:
            self._draw_query_presets(stdscr, rows, cols, qs)

        # ── AI ask overlay (drawn on top of everything) ───────────────────────
        if qs.ai_step == "ask":
            self._draw_query_ai_ask(stdscr, rows, cols, qs)

        # ── @ autocomplete overlay ────────────────────────────────────────────
        if qs.ac_active and qs.panel == "editor":
            self._draw_query_ac(stdscr, rows, cols, qs)

        # ── Keyword autocomplete popup (when editor focused and no @ AC) ──────
        if qs.panel == "editor" and not qs.ac_active and not qs.show_presets:
            kw_word, _kw_start = _sparql_current_word(qs.query_buffer, qs.query_pos)
            kw_cands = _sparql_kw_candidates(kw_word)
            if kw_cands:
                self._draw_query_kw_popup(
                    stdscr, rows, cols, qs, kw_cands, cursor_display_line, cursor_col_on_screen
                )

        # ── Footer ────────────────────────────────────────────────────────────
        if qs.show_presets:
            hint_text = "  ↑↓: navigate   Enter: load preset   Ctrl+L/Esc: close  "
        elif qs.ai_step == "ask":
            hint_text = ""
        elif qs.ac_active:
            if qs.ac_level == 1:
                hint_text = "  ↑↓: navigate   Tab/Enter: select scheme   Esc: cancel  "
            else:
                hint_text = "  ↑↓: navigate   Tab/Enter: insert URI   Esc: back  "
        elif qs.panel == "editor":
            hint_text = "  Ctrl+R/F5: run   Ctrl+G: AI   @: URI   Tab: complete/results   Ctrl+L: presets   Esc: back  "
        else:
            hint_text = (
                "  Tab: editor   Enter: go to concept   A: AI   Ctrl+L: presets   Esc: back  "
            )
        _draw_bar(stdscr, rows - 1, 0, cols, hint_text, dim=True)

    def _draw_query_presets(
        self,
        stdscr: curses.window,
        rows: int,
        cols: int,
        qs: QueryState,
    ) -> None:
        """Draw the presets overlay on the right side of the screen."""
        from . import sparql_query as _sq

        presets = _sq.PRESET_QUERIES
        ov_w = min(42, cols - 2)
        ov_h = min(len(presets) + 4, rows - 2)
        ov_x = cols - ov_w - 1
        ov_y = 1

        # Clamp preset cursor/scroll
        n = len(presets)
        qs.preset_cursor = max(0, min(qs.preset_cursor, n - 1))
        if qs.preset_scroll > qs.preset_cursor:
            qs.preset_scroll = qs.preset_cursor
        list_h = ov_h - 3  # title + footer
        if qs.preset_cursor >= qs.preset_scroll + list_h:
            qs.preset_scroll = qs.preset_cursor - list_h + 1

        # Draw box background
        for y in range(ov_h):
            try:
                stdscr.addstr(ov_y + y, ov_x, " " * ov_w, curses.color_pair(_C_FIELD_VAL))
            except curses.error:
                pass

        # Title
        title = " Presets "
        try:
            stdscr.addstr(
                ov_y,
                ov_x,
                title.center(ov_w)[:ov_w],
                curses.color_pair(_C_EDIT_BAR) | curses.A_BOLD,
            )
        except curses.error:
            pass

        # List
        for i in range(list_h):
            idx = qs.preset_scroll + i
            if idx >= n:
                break
            sel = idx == qs.preset_cursor
            p = presets[idx]
            prefix = "▶ " if sel else "  "
            label = (prefix + p.label)[: ov_w - 1]
            attr = (
                curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
                if sel
                else curses.color_pair(_C_FIELD_VAL)
            )
            try:
                stdscr.addstr(ov_y + 1 + i, ov_x, label.ljust(ov_w)[:ov_w], attr)
            except curses.error:
                pass

        # Description of selected preset
        if 0 <= qs.preset_cursor < n:
            desc = presets[qs.preset_cursor].description[: ov_w - 1]
            try:
                stdscr.addstr(
                    ov_y + ov_h - 2, ov_x, desc.ljust(ov_w)[:ov_w], curses.color_pair(_C_DIM)
                )
            except curses.error:
                pass

        # Hint
        hint = " Enter: load  P/Esc: close "
        try:
            stdscr.addstr(
                ov_y + ov_h - 1, ov_x, hint.center(ov_w)[:ov_w], curses.color_pair(_C_DIM)
            )
        except curses.error:
            pass

    def _draw_query_kw_popup(
        self,
        stdscr: curses.window,
        rows: int,
        cols: int,
        qs: QueryState,
        candidates: list[str],
        cursor_display_line: int,
        cursor_col: int,
    ) -> None:
        """Draw the SPARQL keyword autocomplete popup below the cursor."""
        n = len(candidates)
        popup_w = min(max(len(c) for c in candidates) + 4, 40, cols - 2)
        popup_h = min(n + 1, 10, rows - 3)  # items + footer hint
        if popup_h < 2:
            return

        screen_row = 1 + (cursor_display_line - qs.query_scroll)
        popup_y = screen_row + 1
        popup_x = max(0, min(cursor_col, cols - popup_w - 1))

        if popup_y + popup_h > rows - 1:
            popup_y = max(1, screen_row - popup_h)

        list_h = popup_h - 1  # reserve last row for hint

        for y in range(popup_h):
            try:
                stdscr.addstr(popup_y + y, popup_x, " " * popup_w, curses.color_pair(_C_FIELD_VAL))
            except curses.error:
                pass

        kw_cur = max(0, min(qs.kw_cursor, n - 1))
        for i in range(list_h):
            if i >= n:
                break
            sel = i == kw_cur
            text = f" {candidates[i]} "
            attr = (
                curses.color_pair(_C_SH_KEYWORD) | curses.A_BOLD | curses.A_REVERSE
                if sel
                else curses.color_pair(_C_SH_KEYWORD)
            )
            try:
                stdscr.addstr(popup_y + i, popup_x, text[:popup_w].ljust(popup_w)[:popup_w], attr)
            except curses.error:
                pass

        hint = " ↑↓: select   Tab: insert "
        try:
            stdscr.addstr(
                popup_y + popup_h - 1,
                popup_x,
                hint.center(popup_w)[:popup_w],
                curses.color_pair(_C_DIM),
            )
        except curses.error:
            pass

    def _on_query(self, key: int, rows: int, cols: int) -> bool:
        """Handle a keypress in SPARQL query mode. Returns True to quit the viewer."""
        qs = self._state
        if not isinstance(qs, QueryState):
            return False

        # ── AI sub-flow ───────────────────────────────────────────────────────
        if qs.ai_step == "ask":
            self._on_query_ai_ask(key, rows, cols, qs)
            return False
        if qs.ai_step == "prompt_review":
            self._on_query_ai_prompt_review(key, qs)
            return False

        # ── Presets overlay is open ───────────────────────────────────────────
        if qs.show_presets:
            from . import sparql_query as _sq

            n = len(_sq.PRESET_QUERIES)
            if key in (curses.KEY_UP, ord("k")):
                qs.preset_cursor = max(0, qs.preset_cursor - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                qs.preset_cursor = min(n - 1, qs.preset_cursor + 1)
            elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                if 0 <= qs.preset_cursor < n:
                    qs.query_buffer = _sq.PRESET_QUERIES[qs.preset_cursor].sparql
                    qs.query_pos = len(qs.query_buffer)
                    qs.query_scroll = 0
                qs.show_presets = False
                qs.panel = "editor"
            elif key in (27, 12):  # Esc or Ctrl+L → close
                qs.show_presets = False
            return False

        # ── Editor panel ──────────────────────────────────────────────────────
        # Only Ctrl/function keys here — all printable chars pass to the editor.
        if qs.panel == "editor":
            # ── @ autocomplete intercept ──────────────────────────────────────
            if qs.ac_active:
                candidates = self._query_ac_candidates(
                    qs.query_buffer[qs.ac_trigger_pos : qs.query_pos],
                    qs.ac_level,
                    qs.ac_scheme_uri,
                )
                if key == 27:  # Esc
                    if qs.ac_level == 2:
                        # Back to scheme selection
                        self._query_ac_clear_filter(qs)
                        qs.ac_level = 1
                        qs.ac_scheme_uri = ""
                        qs.ac_scheme_label = ""
                        qs.ac_cursor = 0
                        qs.ac_scroll = 0
                    else:
                        # Remove @ and filter text so it doesn't corrupt the query
                        self._query_ac_cancel(qs)
                    return False
                if key in (9, curses.KEY_ENTER, ord("\n"), ord("\r")):  # Tab/Enter
                    if qs.ac_level == 1:
                        # Select scheme → enter level 2
                        if candidates:
                            s_label, s_uri, _k, _sl = candidates[qs.ac_cursor]
                            self._query_ac_clear_filter(qs)
                            qs.ac_level = 2
                            qs.ac_scheme_uri = s_uri
                            qs.ac_scheme_label = s_label
                            qs.ac_cursor = 0
                            qs.ac_scroll = 0
                        else:
                            qs.ac_active = False
                    else:
                        # Insert concept URI
                        if candidates:
                            self._query_ac_insert(qs, candidates[qs.ac_cursor])
                        else:
                            qs.ac_active = False
                    return False
                if key == curses.KEY_UP:
                    qs.ac_cursor = max(0, qs.ac_cursor - 1)
                    return False
                if key == curses.KEY_DOWN:
                    qs.ac_cursor = min(max(0, len(candidates) - 1), qs.ac_cursor + 1)
                    return False
                # All other keys pass through to the editor, then re-check AC state
                qs.query_buffer, qs.query_pos = self._apply_line_edit(
                    qs.query_buffer, qs.query_pos, key
                )
                # Close AC if cursor moved before trigger or '@' was deleted
                if qs.query_pos < qs.ac_trigger_pos or (
                    qs.ac_trigger_pos > 0
                    and qs.query_buffer[qs.ac_trigger_pos - 1 : qs.ac_trigger_pos] != "@"
                ):
                    qs.ac_active = False
                    qs.ac_cursor = 0
                    qs.ac_scroll = 0
                    qs.ac_level = 1
                    qs.ac_scheme_uri = ""
                    qs.ac_scheme_label = ""
                else:
                    qs.ac_cursor = 0  # reset so best match shows first
                return False

            # ── Keyword popup navigation (intercepts ↑↓ and Tab) ─────────────
            kw_word, _ = _sparql_current_word(qs.query_buffer, qs.query_pos)
            kw_cands = _sparql_kw_candidates(kw_word)
            if kw_cands:
                qs.kw_cursor = max(0, min(qs.kw_cursor, len(kw_cands) - 1))
                if key == curses.KEY_UP:
                    qs.kw_cursor = max(0, qs.kw_cursor - 1)
                    return False
                if key == curses.KEY_DOWN:
                    qs.kw_cursor = min(len(kw_cands) - 1, qs.kw_cursor + 1)
                    return False
                if key in (9, curses.KEY_ENTER, ord("\n"), ord("\r")):
                    _sparql_kw_insert(qs, kw_cands[qs.kw_cursor])
                    qs.kw_cursor = 0
                    return False

            if key in (18, 269):  # Ctrl+R or F5 → run
                if qs.query_buffer.strip():
                    self._last_query_buffer = qs.query_buffer
                    qs.running = True
            elif key == 7:  # Ctrl+G → AI generate
                qs.ai_step = "ask"
                qs.ai_question = ""
                qs.ai_question_pos = 0
            elif key == 9:  # Tab → results (no kw popup active)
                qs.panel = "results"
            elif key == 12:  # Ctrl+L → presets
                qs.show_presets = True
            elif key == 27:  # Esc → back to tree
                self._last_query_buffer = qs.query_buffer
                self._state = TreeState()
            elif key == curses.KEY_UP:
                qs.query_pos = _query_pos_up(qs.query_buffer, qs.query_pos)
            elif key == curses.KEY_DOWN:
                qs.query_pos = _query_pos_down(qs.query_buffer, qs.query_pos)
            elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                qs.query_buffer = (
                    qs.query_buffer[: qs.query_pos] + "\n" + qs.query_buffer[qs.query_pos :]
                )
                qs.query_pos += 1
            else:
                qs.query_buffer, qs.query_pos = self._apply_line_edit(
                    qs.query_buffer, qs.query_pos, key
                )
                qs.kw_cursor = 0  # reset popup selection when word changes
                # Trigger @ autocomplete when '@' is typed
                if key == ord("@"):
                    qs.ac_active = True
                    qs.ac_context = "editor"
                    qs.ac_trigger_pos = qs.query_pos  # pos is now right after '@'
                    qs.ac_cursor = 0
                    qs.ac_scroll = 0
                    qs.ac_level = 1
                    qs.ac_scheme_uri = ""
                    qs.ac_scheme_label = ""
            return False

        # ── Results panel ─────────────────────────────────────────────────────
        if qs.panel == "results":
            edit_h = max(5, (rows - 2) // self._QUERY_EDIT_RATIO)
            data_start_row = edit_h + 3  # header + sep above data rows
            data_h = max(0, rows - data_start_row - 1)
            n_rows = len(qs.rows)

            if key in (curses.KEY_UP, ord("k")):
                qs.result_cursor = max(0, qs.result_cursor - 1)
                if qs.result_cursor < qs.result_scroll:
                    qs.result_scroll = qs.result_cursor
            elif key in (curses.KEY_DOWN, ord("j")):
                qs.result_cursor = min(max(0, n_rows - 1), qs.result_cursor + 1)
                if qs.result_cursor >= qs.result_scroll + data_h:
                    qs.result_scroll = qs.result_cursor - data_h + 1
            elif key in (curses.KEY_HOME, ord("g")):
                qs.result_cursor = 0
                qs.result_scroll = 0
            elif key in (curses.KEY_END, ord("G")):
                qs.result_cursor = max(0, n_rows - 1)
                qs.result_scroll = max(0, n_rows - data_h)
            elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                self._query_navigate_to_concept(qs)
            elif key == 9:  # Tab → editor
                qs.panel = "editor"
            elif key in (18, 269):  # Ctrl+R or F5 — re-run
                if qs.query_buffer.strip():
                    self._last_query_buffer = qs.query_buffer
                    qs.running = True
            elif key == 12:  # Ctrl+L → presets
                qs.show_presets = True
            elif key in (ord("a"), ord("A"), 7):  # A or Ctrl+G → AI generate
                qs.ai_step = "ask"
                qs.ai_question = ""
                qs.ai_question_pos = 0
            elif key == 27:  # Esc → back to editor first
                qs.panel = "editor"

        return False

    def _query_navigate_to_concept(self, qs: QueryState) -> None:
        """If the selected result row contains a known concept/scheme URI, jump to it."""
        from . import sparql_query as _sq

        if not qs.rows or qs.result_cursor >= len(qs.rows):
            return
        row = qs.rows[qs.result_cursor]
        uri_col = _sq.find_uri_column(_sq.QueryResult(columns=qs.columns, rows=qs.rows))
        uri = row[uri_col] if uri_col is not None and uri_col < len(row) else None
        if not uri:
            return
        # Check if URI is in the taxonomy
        if uri in self.taxonomy.concepts or uri in self.taxonomy.schemes:
            self._last_query_buffer = qs.query_buffer
            self._detail_uri = uri
            if uri in self.taxonomy.schemes:
                self._detail_fields = self._bsf(uri)
            else:
                self._detail_fields = build_concept_detail(self.taxonomy, uri, self.lang)
            self._field_cursor = 0
            self._detail_scroll = 0
            # Jump tree cursor to this URI
            for i, line in enumerate(self._flat):
                if line.uri == uri:
                    self._cursor = i
                    break
            self._state = DetailState(
                uri=uri,
                fields=self._detail_fields,
                field_cursor=0,
                scroll=0,
            )

    def _execute_sparql_query(self) -> None:
        """Run the SPARQL query stored in QueryState, update result fields."""
        from . import sparql_query as _sq

        qs = self._state
        if not isinstance(qs, QueryState):
            return
        result = _sq.run_query(qs.file_paths, qs.query_buffer)
        qs.columns = result.columns
        qs.rows = result.rows
        qs.result_error = result.error
        qs.result_scroll = 0
        qs.result_cursor = 0
        qs.running = False
        if not result.error:
            qs.panel = "results"

    def _generate_sparql_query(self) -> None:
        """Background worker: call the LLM to generate a SPARQL query.

        Reads ``qs.ai_prompt_buffer`` (possibly user-edited), calls
        ``ai.generate_sparql_from_prompt``, and places the resulting SPARQL
        into ``qs.query_buffer`` so the user can inspect/run/edit it.
        """
        from . import ai as _ai

        qs = self._state
        if not isinstance(qs, QueryState):
            return
        sparql = _ai.generate_sparql_from_prompt(qs.ai_prompt_buffer)
        qs.query_buffer = sparql
        qs.query_pos = len(sparql)
        qs.query_scroll = 0
        qs.ai_generating = False
        qs.ai_step = ""
        qs.panel = "editor"

    def _draw_query_ai_ask(
        self, stdscr: curses.window, rows: int, cols: int, qs: QueryState
    ) -> None:
        """Overlay: single-line natural language question input."""
        box_h = 5
        box_w = min(cols - 4, 70)
        by = (rows - box_h) // 2
        bx = (cols - box_w) // 2

        for y in range(box_h):
            try:
                stdscr.addstr(by + y, bx, " " * box_w, curses.color_pair(_C_FIELD_VAL))
            except curses.error:
                pass

        title = " ✦ Ask AI — describe what you want to query "
        try:
            stdscr.addstr(
                by, bx, title.center(box_w)[:box_w], curses.color_pair(_C_EDIT_BAR) | curses.A_BOLD
            )
        except curses.error:
            pass

        buf = qs.ai_question
        pos = qs.ai_question_pos
        visible_w = box_w - 2
        start = max(0, pos - visible_w + 1)
        visible = buf[start : start + visible_w]
        cursor_col = pos - start
        display = visible[:cursor_col] + "▌" + visible[cursor_col:]
        try:
            stdscr.addstr(
                by + 2,
                bx + 1,
                display[:visible_w].ljust(visible_w)[:visible_w],
                curses.color_pair(_C_EDIT_BAR),
            )
        except curses.error:
            pass

        if qs.ac_active:
            if qs.ac_level == 1:
                hint = " ↑↓: navigate   Tab/Enter: select scheme   Esc: cancel "
            else:
                hint = (
                    f" In {qs.ac_scheme_label} — ↑↓: navigate   Tab/Enter: insert URI   Esc: back "
                )
        else:
            hint = " Enter: review prompt   @: autocomplete   Esc: cancel "
        try:
            stdscr.addstr(by + 4, bx, hint.center(box_w)[:box_w], curses.color_pair(_C_DIM))
        except curses.error:
            pass

        # AC popup anchored just below the dialog box
        if qs.ac_active:
            self._draw_query_ac(stdscr, rows, cols, qs, anchor_y=by + box_h, anchor_x=bx + 1)

    def _draw_query_ai_prompt_review(
        self, stdscr: curses.window, rows: int, cols: int, qs: QueryState
    ) -> None:
        """Full-screen: editable AI prompt before submission."""
        stdscr.erase()
        _draw_bar(
            stdscr,
            0,
            0,
            cols,
            " ✦ AI SPARQL — review & edit prompt — Enter: generate   Esc: back ",
            dim=False,
        )

        if qs.ai_generating:
            sp = self._SPINNER[self._install_spinner % 4]
            try:
                stdscr.addstr(
                    rows // 2,
                    2,
                    f"{sp}  Generating SPARQL query…",
                    curses.color_pair(_C_DIM),
                )
            except curses.error:
                pass
            _draw_bar(stdscr, rows - 1, 0, cols, "", dim=True)
            return

        buf = qs.ai_prompt_buffer
        pos = qs.ai_prompt_pos
        text_with_cursor = buf[:pos] + "▌" + buf[pos:]
        raw_lines = text_with_cursor.splitlines() or ["▌"]
        display_lines: list[str] = []
        for raw in raw_lines:
            while len(raw) > cols:
                display_lines.append(raw[:cols])
                raw = raw[cols:]
            display_lines.append(raw)

        list_h = rows - 2
        cursor_line = len((buf[:pos] + "▌").splitlines()) - 1
        if qs.ai_prompt_scroll > cursor_line:
            qs.ai_prompt_scroll = cursor_line
        if cursor_line >= qs.ai_prompt_scroll + list_h:
            qs.ai_prompt_scroll = cursor_line - list_h + 1

        for i in range(list_h):
            idx = qs.ai_prompt_scroll + i
            line = display_lines[idx] if idx < len(display_lines) else ""
            try:
                stdscr.addstr(1 + i, 0, line[:cols])
            except curses.error:
                pass

        _draw_bar(
            stdscr,
            rows - 1,
            0,
            cols,
            "  ↑↓: scroll   type to edit   Enter: generate   Esc: back  ",
            dim=True,
        )

    def _on_query_ai_ask(self, key: int, rows: int, cols: int, qs: QueryState) -> None:
        """Handle keypresses in the AI question input overlay."""
        from . import ai as _ai

        # ── @ autocomplete intercept ──────────────────────────────────────────
        if qs.ac_active:
            candidates = self._query_ac_candidates(
                qs.ai_question[qs.ac_trigger_pos : qs.ai_question_pos],
                qs.ac_level,
                qs.ac_scheme_uri,
            )
            if key == 27:  # Esc
                if qs.ac_level == 2:
                    # Back to scheme selection (don't cancel the ask dialog)
                    self._query_ac_clear_filter(qs)
                    qs.ac_level = 1
                    qs.ac_scheme_uri = ""
                    qs.ac_scheme_label = ""
                    qs.ac_cursor = 0
                    qs.ac_scroll = 0
                else:
                    # Remove @ and filter text, but keep the ask dialog open
                    self._query_ac_cancel(qs)
                return
            if key in (9, curses.KEY_ENTER, ord("\n"), ord("\r")):  # Tab/Enter
                if qs.ac_level == 1:
                    if candidates:
                        s_label, s_uri, _k, _sl = candidates[qs.ac_cursor]
                        self._query_ac_clear_filter(qs)
                        qs.ac_level = 2
                        qs.ac_scheme_uri = s_uri
                        qs.ac_scheme_label = s_label
                        qs.ac_cursor = 0
                        qs.ac_scroll = 0
                    else:
                        qs.ac_active = False
                else:
                    if candidates:
                        self._query_ac_insert(qs, candidates[qs.ac_cursor])
                    else:
                        qs.ac_active = False
                return
            if key == curses.KEY_UP:
                qs.ac_cursor = max(0, qs.ac_cursor - 1)
                return
            if key == curses.KEY_DOWN:
                qs.ac_cursor = min(max(0, len(candidates) - 1), qs.ac_cursor + 1)
                return
            # Pass other keys through to the input, then re-check AC state
            qs.ai_question, qs.ai_question_pos = self._apply_line_edit(
                qs.ai_question, qs.ai_question_pos, key
            )
            if qs.ai_question_pos < qs.ac_trigger_pos or (
                qs.ac_trigger_pos > 0
                and qs.ai_question[qs.ac_trigger_pos - 1 : qs.ac_trigger_pos] != "@"
            ):
                qs.ac_active = False
                qs.ac_cursor = 0
                qs.ac_scroll = 0
                qs.ac_level = 1
                qs.ac_scheme_uri = ""
                qs.ac_scheme_label = ""
            else:
                qs.ac_cursor = 0
            return

        if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if not qs.ai_question.strip():
                return
            if not _ai.is_configured():
                qs.result_error = "AI not configured. Press ⚙ from the main menu."
                qs.ai_step = ""
                return
            # Build taxonomy context from current taxonomy
            scheme = self.taxonomy.primary_scheme()
            taxonomy_name = scheme.title(self.lang) if scheme else self.file_path.stem
            taxonomy_description = ""
            if scheme and scheme.descriptions:
                for d in scheme.descriptions:
                    if d.lang == self.lang:
                        taxonomy_description = d.value
                        break
                if not taxonomy_description and scheme.descriptions:
                    taxonomy_description = scheme.descriptions[0].value
            scheme_uris = list(self.taxonomy.schemes.keys())
            prompt = _ai.render_generate_sparql_prompt(
                taxonomy_name, taxonomy_description, scheme_uris, qs.ai_question
            )
            qs.ai_prompt_buffer = prompt
            qs.ai_prompt_pos = len(prompt)
            qs.ai_prompt_scroll = 0
            qs.ai_step = "prompt_review"
        elif key == 27:
            qs.ai_step = ""
        else:
            qs.ai_question, qs.ai_question_pos = self._apply_line_edit(
                qs.ai_question, qs.ai_question_pos, key
            )
            # Trigger @ autocomplete when '@' is typed
            if key == ord("@"):
                qs.ac_active = True
                qs.ac_context = "ai_ask"
                qs.ac_trigger_pos = qs.ai_question_pos  # pos is now right after '@'
                qs.ac_cursor = 0
                qs.ac_scroll = 0
                qs.ac_level = 1
                qs.ac_scheme_uri = ""
                qs.ac_scheme_label = ""

    def _on_query_ai_prompt_review(self, key: int, qs: QueryState) -> None:
        """Handle keypresses in the AI prompt review screen."""
        if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            qs.ai_generating = True
        elif key == 27:
            qs.ai_step = "ask"
        elif key == curses.KEY_UP:
            qs.ai_prompt_pos = _query_pos_up(qs.ai_prompt_buffer, qs.ai_prompt_pos)
        elif key == curses.KEY_DOWN:
            qs.ai_prompt_pos = _query_pos_down(qs.ai_prompt_buffer, qs.ai_prompt_pos)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            qs.ai_prompt_buffer = (
                qs.ai_prompt_buffer[: qs.ai_prompt_pos]
                + "\n"
                + qs.ai_prompt_buffer[qs.ai_prompt_pos :]
            )
            qs.ai_prompt_pos += 1
        else:
            qs.ai_prompt_buffer, qs.ai_prompt_pos = self._apply_line_edit(
                qs.ai_prompt_buffer, qs.ai_prompt_pos, key
            )

    # ── @ autocomplete ────────────────────────────────────────────────────────

    def _query_ac_candidates(
        self, ac_query: str, level: int = 1, scheme_uri: str = ""
    ) -> list[tuple[str, str, str, str]]:
        """Return (label, uri, kind, scheme_label) tuples for @ autocomplete.

        Level 1: schemes only, filtered by *ac_query*.
        Level 2: concepts within *scheme_uri* only, filtered by *ac_query*.
        """
        q = ac_query.lower()

        if level == 1:
            rows: list[tuple[str, str, str, str]] = []
            for uri, scheme in self.taxonomy.schemes.items():
                label = scheme.title(self.lang)
                if _ac_matches(label, q):
                    rows.append((label, uri, "SCH", ""))
            rows.sort(key=lambda t: t[0].lower())
            return rows[:50]

        # Level 2: BFS from scheme's top_concepts
        scheme_obj = self.taxonomy.schemes.get(scheme_uri)
        if not scheme_obj:
            return []
        scheme = scheme_obj
        scheme_concepts: set[str] = set()
        queue = list(scheme.top_concepts)
        seen: set[str] = set()
        while queue:
            curi = queue.pop(0)
            if curi in seen:
                continue
            seen.add(curi)
            scheme_concepts.add(curi)
            c = self.taxonomy.concepts.get(curi)
            if c:
                queue.extend(c.narrower)
        rows2: list[tuple[str, str, str, str]] = []
        for curi in scheme_concepts:
            concept = self.taxonomy.concepts.get(curi)
            if not concept:
                continue
            label = concept.pref_label(self.lang)
            if _ac_matches(label, q):
                rows2.append((label, curi, "CON", ""))
        rows2.sort(key=lambda t: t[0].lower())
        return rows2[:50]

    def _query_ac_insert(self, qs: QueryState, candidate: tuple[str, str, str, str]) -> None:
        """Replace @filter_text at the current cursor position with <uri>."""
        _label, uri, _kind, _scheme = candidate
        start = qs.ac_trigger_pos - 1  # include the '@' itself
        replacement = f"<{uri}>"
        if qs.ac_context == "ai_ask":
            end = qs.ai_question_pos
            qs.ai_question = qs.ai_question[:start] + replacement + qs.ai_question[end:]
            qs.ai_question_pos = start + len(replacement)
        else:
            end = qs.query_pos
            qs.query_buffer = qs.query_buffer[:start] + replacement + qs.query_buffer[end:]
            qs.query_pos = start + len(replacement)
        qs.ac_active = False
        qs.ac_cursor = 0
        qs.ac_scroll = 0
        qs.ac_level = 1
        qs.ac_scheme_uri = ""
        qs.ac_scheme_label = ""

    def _query_ac_clear_filter(self, qs: QueryState) -> None:
        """Remove filter text typed after '@' (used when transitioning AC levels)."""
        start = qs.ac_trigger_pos
        if qs.ac_context == "ai_ask":
            end = qs.ai_question_pos
            qs.ai_question = qs.ai_question[:start] + qs.ai_question[end:]
            qs.ai_question_pos = start
        else:
            end = qs.query_pos
            qs.query_buffer = qs.query_buffer[:start] + qs.query_buffer[end:]
            qs.query_pos = start

    def _query_ac_cancel(self, qs: QueryState) -> None:
        """Remove the '@' trigger character and any filter text, then close AC."""
        start = qs.ac_trigger_pos - 1  # include the '@' itself
        if qs.ac_context == "ai_ask":
            end = qs.ai_question_pos
            qs.ai_question = qs.ai_question[:start] + qs.ai_question[end:]
            qs.ai_question_pos = start
        else:
            end = qs.query_pos
            qs.query_buffer = qs.query_buffer[:start] + qs.query_buffer[end:]
            qs.query_pos = start
        qs.ac_active = False
        qs.ac_cursor = 0
        qs.ac_scroll = 0
        qs.ac_level = 1
        qs.ac_scheme_uri = ""
        qs.ac_scheme_label = ""

    def _draw_query_ac(
        self,
        stdscr: curses.window,
        rows: int,
        cols: int,
        qs: QueryState,
        anchor_y: int | None = None,
        anchor_x: int = 0,
    ) -> None:
        """Draw the @ autocomplete popup.

        When *anchor_y* is given the popup is anchored at that screen row (used
        by the AI-ask overlay). Otherwise the popup is positioned below the
        cursor line in the editor area.
        """
        if qs.ac_context == "ai_ask":
            ac_q = qs.ai_question[qs.ac_trigger_pos : qs.ai_question_pos]
        else:
            ac_q = qs.query_buffer[qs.ac_trigger_pos : qs.query_pos]
        candidates = self._query_ac_candidates(ac_q, qs.ac_level, qs.ac_scheme_uri)

        n_cands = len(candidates)

        if anchor_y is not None:
            screen_row = anchor_y - 1  # popup_y will be anchor_y
            cur_col = anchor_x
        else:
            # Determine cursor screen position (row within the editor area)
            buf = qs.query_buffer
            pos = qs.query_pos
            lines_before = (buf[:pos] + "▌").splitlines() or ["▌"]
            cur_line = len(lines_before) - 1  # 0-based logical line index
            cur_col = len(lines_before[-1]) - 1  # column of cursor char
            screen_row = 1 + (cur_line - qs.query_scroll)  # 1 = header offset

        # Popup dimensions (flat list — no section headers)
        popup_w = min(60, cols - 2)
        popup_x = max(0, min(cur_col, cols - popup_w - 1))
        popup_y = screen_row + 1
        if popup_y + 3 > rows - 1:
            popup_y = max(1, screen_row - 3)
        avail_h = (rows - 1) - popup_y - 1  # subtract footer row
        popup_h = min(n_cands + 2, 16, max(3, avail_h))  # title + items + footer
        list_h = popup_h - 2

        # If no room below, show above
        if popup_y + popup_h > rows - 1:
            popup_y = max(1, screen_row - popup_h)

        if popup_h < 3:
            return

        # Clamp AC cursor and scroll
        if n_cands > 0:
            qs.ac_cursor = max(0, min(qs.ac_cursor, n_cands - 1))
            if qs.ac_scroll > qs.ac_cursor:
                qs.ac_scroll = qs.ac_cursor
            if qs.ac_cursor >= qs.ac_scroll + list_h:
                qs.ac_scroll = qs.ac_cursor - list_h + 1
        qs.ac_scroll = max(0, min(qs.ac_scroll, max(0, n_cands - list_h)))

        # Background
        for y in range(popup_h):
            try:
                stdscr.addstr(popup_y + y, popup_x, " " * popup_w, curses.color_pair(_C_FIELD_VAL))
            except curses.error:
                pass

        # Title bar
        if qs.ac_level == 1:
            if n_cands == 0:
                title = f" @{ac_q} — no schemes match "
            else:
                title = f" @{ac_q} — {n_cands} scheme{'s' if n_cands != 1 else ''} "
        else:
            sl = qs.ac_scheme_label
            if n_cands == 0:
                title = f" {sl}: no matches "
            else:
                title = f" {sl}: {n_cands} concept{'s' if n_cands != 1 else ''} "
        try:
            stdscr.addstr(
                popup_y,
                popup_x,
                title[:popup_w].ljust(popup_w)[:popup_w],
                curses.color_pair(_C_EDIT_BAR) | curses.A_BOLD,
            )
        except curses.error:
            pass

        # List rows (flat)
        for i in range(list_h):
            idx = qs.ac_scroll + i
            if idx >= n_cands:
                break
            label, _uri, kind, _sl = candidates[idx]
            sel = idx == qs.ac_cursor
            if qs.ac_level == 1:
                text = f" \u25b6 {label}"  # ▶ scheme
            else:
                text = f"   {label}"
            attr = (
                curses.color_pair(_C_SEL_NAV) | curses.A_BOLD
                if sel
                else curses.color_pair(_C_FIELD_VAL)
            )
            try:
                stdscr.addstr(
                    popup_y + 1 + i, popup_x, text[:popup_w].ljust(popup_w)[:popup_w], attr
                )
            except curses.error:
                pass

        # Footer hint
        if qs.ac_level == 1:
            footer = " Tab/Enter: select scheme   ↑↓: navigate   Esc: cancel "
        else:
            footer = " Tab/Enter: insert URI   ↑↓: navigate   Esc: back "
        try:
            stdscr.addstr(
                popup_y + popup_h - 1,
                popup_x,
                footer.center(popup_w)[:popup_w],
                curses.color_pair(_C_DIM),
            )
        except curses.error:
            pass


# ──────────────────────────── module-level helpers for query editor ───────────


def _sparql_hl_attrs(buffer: str, is_edit: bool) -> list[int]:
    """Tokenize *buffer* with pygments and return a per-character curses attr list.

    Falls back to a uniform default attr when pygments is unavailable or the
    buffer is empty so the caller never has to guard against ImportError.
    """
    default = curses.color_pair(_C_FIELD_VAL) if is_edit else curses.color_pair(_C_DIM)
    if not buffer:
        return []
    attrs = [default] * len(buffer)
    try:
        from pygments import lex
        from pygments.lexers.rdf import SparqlLexer
        from pygments.token import Token
    except ImportError:
        return attrs

    _MAP: list[tuple[object, int]] = [
        (Token.Keyword, curses.color_pair(_C_SH_KEYWORD) | curses.A_BOLD),
        (Token.Name.Function, curses.color_pair(_C_SH_FUNCTION) | curses.A_BOLD),
        (Token.Name.Variable, curses.color_pair(_C_SH_VAR)),
        (Token.Name.Label, curses.color_pair(_C_SH_URI) | curses.A_BOLD),
        (Token.Name.Tag, curses.color_pair(_C_SH_NS)),
        (Token.Name.Namespace, curses.color_pair(_C_SH_NS) | curses.A_BOLD),
        (Token.Literal.String, curses.color_pair(_C_SH_STRING)),
        (Token.Literal.Number, curses.color_pair(_C_SH_FUNCTION)),
        (Token.Comment, curses.color_pair(_C_DIM) | curses.A_DIM),
        (Token.Operator, curses.color_pair(_C_SH_KEYWORD)),
    ]

    char_pos = 0
    for ttype, value in lex(buffer, SparqlLexer()):
        attr = default
        for pattern, a in _MAP:
            if ttype in pattern:  # type: ignore[operator]
                attr = a
                break
        for _ in value:
            if char_pos < len(attrs):
                attrs[char_pos] = attr
            char_pos += 1
    return attrs


_SPARQL_WORD_SEPS = frozenset(" \t\n\r{}()<>,;|@?$\"'=!*+/#^&[]\\")


def _sparql_current_word(buffer: str, pos: int) -> tuple[str, int]:
    """Return *(word, word_start)* for the identifier ending at *pos*."""
    i = pos
    while i > 0 and buffer[i - 1] not in _SPARQL_WORD_SEPS:
        i -= 1
    return buffer[i:pos], i


def _sparql_kw_candidates(word: str) -> list[str]:
    """Return SPARQL keywords whose uppercase form starts with *word* (max 9)."""
    from . import sparql_query as _sq

    if not word:
        return []
    wu = word.upper()
    return [kw for kw in _sq.SPARQL_KEYWORDS if kw.startswith(wu)][:9]


def _sparql_kw_insert(qs: QueryState, keyword: str) -> None:
    """Replace the partial word before the cursor with *keyword*."""
    _word, word_start = _sparql_current_word(qs.query_buffer, qs.query_pos)
    qs.query_buffer = qs.query_buffer[:word_start] + keyword + qs.query_buffer[qs.query_pos :]
    qs.query_pos = word_start + len(keyword)


def _ac_matches(label: str, q: str) -> bool:
    """Return True if *q* is a prefix of *label* or of any word in *label*.

    Empty query matches everything. Comparison is case-insensitive.
    """
    if not q:
        return True
    q_lower = q.lower()
    label_lower = label.lower()
    if label_lower.startswith(q_lower):
        return True
    return any(word.startswith(q_lower) for word in label_lower.split())


def _query_pos_up(buffer: str, pos: int) -> int:
    """Move cursor position up one logical line, preserving column."""
    before = buffer[:pos]
    lines_before = before.split("\n")
    col = len(lines_before[-1])
    if len(lines_before) <= 1:
        return 0
    prev_line = lines_before[-2]
    prefix_len = sum(len(ln) + 1 for ln in lines_before[:-2])
    return prefix_len + min(col, len(prev_line))


def _query_pos_down(buffer: str, pos: int) -> int:
    """Move cursor position down one logical line, preserving column."""
    before = buffer[:pos]
    lines_before = before.split("\n")
    col = len(lines_before[-1])
    rest = buffer[pos:]
    nl_idx = rest.find("\n")
    if nl_idx == -1:
        return len(buffer)  # already on last line
    next_start = pos + nl_idx + 1
    nl_end = buffer.find("\n", next_start)
    next_line_len = (nl_end - next_start) if nl_end >= 0 else (len(buffer) - next_start)
    return next_start + min(col, next_line_len)


# ──────────────────────────── TaxonomyShell (REPL) ───────────────────────────


class TaxonomyShell(Cmd):
    """Bash-like interactive REPL for taxonomy navigation and editing."""

    intro = ""
    doc_header = "Commands:"

    def __init__(self, taxonomy: Taxonomy, file_path: Path, lang: str = "en") -> None:
        super().__init__()
        self.taxonomy = taxonomy
        self.file_path = file_path
        self.lang = lang
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

    def complete_info(self, t, l, b, e):
        return self._complete_handle(t)

    def complete_show(self, t, l, b, e):
        return self._complete_handle(t)

    def complete_rm(self, t, l, b, e):
        return self._complete_handle(t)

    def complete_mv(self, t, l, b, e):
        return self._complete_handle(t)

    def complete_label(self, t, l, b, e):
        return self._complete_handle(t)

    def complete_define(self, t, l, b, e):
        return self._complete_handle(t)

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
        tokens = arg.split()
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
            table.add_column("↑", justify="right", style="dim", no_wrap=True)
            table.add_column("~", justify="right", style="dim", no_wrap=True)
            table.add_column("def", justify="center", style="dim", no_wrap=True)
        for uri in uris:
            c = self.taxonomy.concepts.get(uri)
            if not c:
                continue
            handle = self.taxonomy.uri_to_handle(uri) or "?"
            label = c.pref_label(self.lang) or ""
            nav = "▸" if c.narrower else " "
            lbl_cell = f"[bold cyan]{label}[/bold cyan]" if c.narrower else label
            if detailed:
                table.add_row(
                    nav,
                    f"[{handle}]",
                    lbl_cell,
                    str(len(c.narrower)),
                    str(len(c.broader)),
                    str(len(c.related)),
                    "✓" if c.definitions else "·",
                )
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
            uri = self._resolve(target)  # type: ignore[assignment]
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
            err.print(f"[red]{exc}[/red]")
            return

        if not parts:
            err.print("[yellow]Usage: add NAME [--en LABEL] [--parent HANDLE][/yellow]")
            return

        name = parts[0]
        labels: dict[str, str] = {}
        parent_handle: str | None = None
        i = 1
        while i < len(parts):
            t = parts[i]
            if t in ("--en", "--fr") and i + 1 < len(parts):
                labels[t[2:]] = parts[i + 1]
                i += 2
            elif t == "--parent" and i + 1 < len(parts):
                parent_handle = parts[i + 1]
                i += 2
            else:
                i += 1

        if not labels:
            from .cli import _humanize

            labels[self.lang] = _humanize(name)
            console.print(f"[dim]No label — using default: {labels[self.lang]!r}[/dim]")

        if parent_handle is None and self._cwd is not None:
            parent_handle = self.taxonomy.uri_to_handle(self._cwd)

        uri = self._run(operations.expand_uri, self.taxonomy, name)
        if uri is None:
            return
        concept = self._run(operations.add_concept, self.taxonomy, uri, labels, parent_handle)
        if concept is None:
            return
        h = self.taxonomy.uri_to_handle(uri) or "?"
        console.print(
            f"[green]Added[/green]  [{h}]  {concept.pref_label(self.lang)}  [dim]({uri})[/dim]"
        )
        self._save()

    # ── mv ────────────────────────────────────────────────────────────────────

    def do_mv(self, arg: str) -> None:
        """Move a concept.\n  mv HANDLE --parent NEW_PARENT | mv HANDLE /"""
        import shlex

        try:
            parts = shlex.split(arg)
        except ValueError as exc:
            err.print(f"[red]{exc}[/red]")
            return

        if not parts:
            err.print("[yellow]Usage: mv HANDLE --parent NEW_PARENT[/yellow]")
            return

        concept_ref = parts[0]
        new_parent_ref: str | None = None
        i = 1
        while i < len(parts):
            t = parts[i]
            if t == "--parent" and i + 1 < len(parts):
                new_parent_ref = parts[i + 1]
                i += 2
            elif t == "/":
                new_parent_ref = "/"
                i += 1
            else:
                i += 1

        uri = self._resolve(concept_ref)
        if uri is None:
            return

        new_parent_uri: str | None = None
        if new_parent_ref and new_parent_ref != "/":
            new_parent_uri = self._resolve(new_parent_ref)
            if new_parent_uri is None:
                return

        self._run(operations.move_concept, self.taxonomy, uri, new_parent_uri)
        dest = (
            self.taxonomy.concepts[new_parent_uri].pref_label(self.lang)
            if new_parent_uri and new_parent_uri in self.taxonomy.concepts
            else "top level"
        )
        console.print(
            f"[green]Moved[/green]  {self.taxonomy.concepts[uri].pref_label(self.lang)}  →  {dest}"
        )
        self._save()

    # ── rm ────────────────────────────────────────────────────────────────────

    def do_rm(self, arg: str) -> None:
        """Remove a concept.\n  rm HANDLE [--cascade] [-y]"""
        import shlex

        try:
            parts = shlex.split(arg)
        except ValueError as exc:
            err.print(f"[red]{exc}[/red]")
            return

        if not parts:
            err.print("[yellow]Usage: rm HANDLE [--cascade] [-y][/yellow]")
            return

        concept_ref = parts[0]
        cascade = "--cascade" in parts
        skip = "-y" in parts or "--yes" in parts

        uri = self._resolve(concept_ref)
        if uri is None:
            return
        c = self.taxonomy.concepts.get(uri)
        if c is None:
            err.print(f"[red]Not found: {concept_ref!r}[/red]")
            return

        if not skip:
            from rich.prompt import Confirm

            msg = f"Remove [bold]{c.pref_label(self.lang)}[/bold]"
            if cascade and c.narrower:
                msg += f" and its {len(c.narrower)} child(ren)"
            if not Confirm.ask(msg + "?"):
                return

        removed = self._run(operations.remove_concept, self.taxonomy, uri, cascade=cascade)
        if removed is None:
            return
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
            err.print(f"[red]{exc}[/red]")
            return

        alt = "--alt" in parts
        parts = [p for p in parts if p != "--alt"]
        if len(parts) < 3:
            err.print("[yellow]Usage: label HANDLE LANG TEXT[/yellow]")
            return
        uri = self._resolve(parts[0])
        if uri is None:
            return
        lang, text = parts[1], " ".join(parts[2:])
        self._run(
            operations.set_label,
            self.taxonomy,
            uri,
            lang,
            text,
            LabelType.ALT if alt else LabelType.PREF,
        )
        console.print(f"[green]Set {'alt' if alt else 'pref'} label[/green]  [{lang}]  {text}")
        self._save()

    def do_define(self, arg: str) -> None:
        """Set a definition.\n  define HANDLE LANG \"Text\"\""""
        import shlex

        try:
            parts = shlex.split(arg)
        except ValueError as exc:
            err.print(f"[red]{exc}[/red]")
            return

        if len(parts) < 3:
            err.print("[yellow]Usage: define HANDLE LANG TEXT[/yellow]")
            return
        uri = self._resolve(parts[0])
        if uri is None:
            return
        lang, text = parts[1], " ".join(parts[2:])
        self._run(operations.set_definition, self.taxonomy, uri, lang, text)
        console.print(f"[green]Set definition[/green]  [{lang}]")
        self._save()

    # ── quit ──────────────────────────────────────────────────────────────────

    def do_quit(self, arg: str) -> bool:
        """Exit the shell."""
        return True

    do_exit = do_quit
    do_q = do_quit

    def do_EOF(self, arg: str) -> bool:
        print()
        return True

    def default(self, line: str) -> None:
        cmd_ = line.split()[0] if line.split() else line
        err.print(f"[yellow]Unknown: {cmd_!r}  — type 'help' for commands.[/yellow]")

    def emptyline(self) -> bool:  # type: ignore[override]
        return False
