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
import traceback
from cmd import Cmd
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import analysis_cache, operations, store
from .display import console, render_concept_detail, render_tree
from .exceptions import SkostaxError
from .model import Definition, Label, LabelType, Taxonomy
from .nav_logic import (  # noqa: F401
    _ACTION_ADD_SCHEME,
    _FILE_URI_PREFIX,
    _GLOBAL_URI,
    DetailField,
    TreeLine,
    _available_langs,
    _breadcrumb,
    _children,
    _count_descendants,
    _file_sentinel,
    _flatten_taxonomy,
    _flatten_workspace,
    _parent_uri,
    _sep,
    build_concept_detail,
    build_detail_fields,
    build_file_fields,
    build_global_fields,
    build_scheme_dashboard_fields,
    build_scheme_detail,
    build_scheme_fields,
    flatten_tree,
)
from .nav_state import (
    AiInstallState,
    AiSetupState,
    ConfirmDeleteState,
    CreateState,
    DetailState,
    EditState,
    LangPickState,
    MapConceptPickState,
    MapSchemePickState,
    MovePickState,
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

        # ── scheme header row ─────────────────────────────────────────────
        if line.is_scheme:
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

        # ── normal concept row ────────────────────────────────────────────
        concept = taxonomy.concepts.get(line.uri)
        if not concept:
            continue

        handle = taxonomy.uri_to_handle(line.uri) or "?"
        label = concept.pref_label(lang) or line.uri
        n_children = len(concept.narrower)
        is_top = bool(concept.top_concept_of)
        d_status = diff_status.get(line.uri, "unchanged") if diff_status else "unchanged"
        has_map = bool(
            concept.exact_match
            or concept.close_match
            or concept.broad_match
            or concept.narrow_match
            or concept.related_match
        )

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
        map_tag = "  ⇔" if has_map else ""

        text = f"{line.prefix}{nav} [{handle}]  {label}{suffix}"
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
        # scheme_uri → SchemeAnalysis; populated on first run() call
        self._analysis: dict[str, SchemeAnalysis] | None = None
        # AI install threading state
        self._install_thread: object = None  # threading.Thread | None
        self._install_output: list[str] = []  # thread appends here (GIL-safe)
        self._install_returncode: int | None = None
        self._install_spinner: int = 0
        self._install_package: str = "llm"  # package passed to pip install

        self._rebuild()
        # Start with the global overview panel; cursor moves will update to item-specific detail
        self._detail_uri = _GLOBAL_URI
        self._detail_fields = self._bgf()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        self._flat = flatten_tree(self._workspace, folded=self._folded)
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
        if uri == self._detail_uri:
            return  # already previewing this concept
        self._detail_uri = uri
        if line.is_file and line.file_path:
            self._detail_fields = self._bff(line.file_path)
        elif line.is_scheme:
            self._detail_fields = self._bsf(uri)
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
        )

    def _sync_tree_state(self, ts: TreeState) -> None:
        """Write a TreeState back into the scattered tree attrs."""
        self._flat = ts.flat
        self._cursor = ts.cursor
        self._tree_scroll = ts.scroll
        self._folded = ts.folded
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
        except Exception as exc:
            self._status = f"Error saving: {exc}"

    def _open_detail(self) -> None:
        if not (0 <= self._cursor < len(self._flat)):
            return
        line = self._flat[self._cursor]
        self._push()
        if self._detail_uri != line.uri:
            self._detail_uri = line.uri
            if line.is_file and line.file_path:
                self._detail_fields = self._bff(line.file_path)
            elif line.is_scheme:
                self._detail_fields = self._bsf(line.uri)
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

        while True:
            rows, cols = stdscr.getmaxyx()

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
                    self._draw_create(stdscr, rows, cols)
                    self._run_generate(stdscr, self._create_ai_generate)
                else:
                    self._draw_create(stdscr, rows, cols)
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_create(key, rows)

            elif isinstance(self._state, ConfirmDeleteState):
                self._draw_confirm(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_confirm_delete(key)

            elif isinstance(self._state, MovePickState):
                ms = self._state
                if ms.pick_type == "add_related":
                    self._draw_move(stdscr, rows, cols, title=" ~ Add related concept ")
                    key = stdscr.getch()
                    if key == curses.KEY_RESIZE:
                        curses.update_lines_cols()
                        continue
                    self._on_related_pick(key, rows)
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
                if self._state.step == "install_plugin" and self._state.plugin_installing:
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
        return (
            f" ?: help  {pos}  ↑↓/j·k: move  {enter_hint}  ←/h: parent"
            f"   Space bar: fold/unfold  +: add  ^D/^U: ½-page  {jump_hint}  /: search  ◉: scheme  q: quit "
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
            header_title="Global Ster View",
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
                has_children = False
                if line.is_file:
                    has_children = True  # file nodes are always foldable
                elif line.is_scheme:
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

        if is_global_detail:
            label = "Global Ster View"
            handle = None
        elif is_file_detail:
            # Derive file path from the sentinel URI
            fp_str = self._detail_uri[len(_FILE_URI_PREFIX) :]  # type: ignore[index]
            label = Path(fp_str).name
            handle = None
        elif is_scheme_detail:
            scheme = self.taxonomy.schemes[self._detail_uri]  # type: ignore[index]
            label = scheme.title(self.lang)
            handle = None
        else:
            concept = self.taxonomy.concepts.get(self._detail_uri) if self._detail_uri else None
            if not concept:
                return
            handle = self.taxonomy.uri_to_handle(self._detail_uri) if self._detail_uri else "?"
            label = concept.pref_label(self.lang) or self._detail_uri or ""
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
        elif is_scheme_detail:
            counter = f" [{self._field_cursor + 1}/{n_fields}]" if n_fields else ""
            title_bar = f" ◉ {label}  [scheme settings]{counter} "
        else:
            counter = f" [{self._field_cursor + 1}/{n_fields}]" if n_fields else ""
            title_bar = f" [{handle}]  {label}{counter} "
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
            self._field_cursor = max(0, min(n - 1, self._field_cursor + direction))

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
                elif f.meta.get("nav"):
                    # broader / narrower / related / top_concept_of — navigate
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
            return

        # ── scheme field editing ──────────────────────────────────────────────
        if self._detail_uri in self.taxonomy.schemes:
            self._commit_scheme_edit(f, new_value)
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
        self._save_file()

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

    def _build_ai_context(self, cs: CreateState) -> tuple[str, str, str | None]:
        """Return (taxonomy_name, taxonomy_description, parent_label).

        parent_label is None when the parent is a scheme (top-concept context).
        """
        scheme = self.taxonomy.primary_scheme()
        taxonomy_name = scheme.title(self.lang) if scheme else self.file_path.stem

        taxonomy_description = ""
        if scheme and scheme.descriptions:
            for defn in scheme.descriptions:
                if defn.lang == self.lang:
                    taxonomy_description = defn.value
                    break
            if not taxonomy_description and scheme.descriptions:
                taxonomy_description = scheme.descriptions[0].value

        parent_label: str | None = None
        if cs.parent_uri and cs.parent_uri not in self.taxonomy.schemes:
            parent_concept = self.taxonomy.concepts.get(cs.parent_uri)
            if parent_concept:
                parent_label = parent_concept.pref_label(self.lang)

        return taxonomy_name, taxonomy_description, parent_label

    def _run_generate(self, stdscr: curses.window, fn) -> None:
        """Run an AI generate function, suspending curses first in copypaste mode."""
        from . import ai as _ai

        if _ai.is_copypaste():
            curses.endwin()
        try:
            fn()
        finally:
            if _ai.is_copypaste():
                stdscr.refresh()

    def _create_ai_generate(self) -> None:
        """Called from main loop when CreateState.ai_generating is True."""
        from . import ai as _ai

        if not isinstance(self._state, CreateState):
            return
        cs = self._state
        taxonomy_name, taxonomy_desc, parent_label = self._build_ai_context(cs)
        try:
            candidates = _ai.suggest_concept_names(
                taxonomy_name=taxonomy_name,
                taxonomy_description=taxonomy_desc,
                parent_label=parent_label,
                lang=self.lang,
                n=20,
                exclude=cs.ai_seen,
            )
        except Exception as exc:
            cs.error = str(exc)[:80]
            candidates = []
        cs.ai_candidates = candidates
        cs.ai_seen = cs.ai_seen + candidates
        cs.ai_generating = False
        cs.ai_cursor = 0
        cs.ai_scroll = 0

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

    def _draw_create_prompt_review(
        self, stdscr: curses.window, rows: int, x0: int, width: int, cs: CreateState
    ) -> None:
        """Render the prompt-review panel."""
        _draw_bar(
            stdscr, 0, x0, width, " Review AI prompt — Enter: generate   Esc: back ", dim=False
        )
        text_lines = cs.ai_prompt_preview.splitlines()
        list_h = rows - 2
        for i in range(list_h):
            idx = cs.ai_scroll + i
            y = 1 + i
            line = text_lines[idx][: width - 2] if idx < len(text_lines) else ""
            try:
                stdscr.addstr(y, x0 + 1, line.ljust(width - 2)[: width - 2])
            except curses.error:
                pass
        _draw_bar(
            stdscr, rows - 1, x0, width, "  ↑↓: scroll   Enter: generate   Esc: back  ", dim=True
        )

    def _draw_create_ai_pick(
        self, stdscr: curses.window, rows: int, x0: int, width: int, cs: CreateState
    ) -> None:
        """Render the AI suggestion pick list."""
        _draw_bar(stdscr, 0, x0, width, " AI suggestions — pick a name ", dim=False)

        if cs.ai_generating:
            spinner = self._SPINNER[self._install_spinner % 4]
            try:
                stdscr.addstr(rows // 2, x0 + 2, f"{spinner}  Generating suggestions…"[: width - 2])
            except curses.error:
                pass
            _draw_bar(stdscr, rows - 1, x0, width, "", dim=True)
            return

        if cs.error:
            try:
                stdscr.addstr(2, x0 + 2, f"Error: {cs.error}"[: width - 4])
            except curses.error:
                pass

        candidates = cs.ai_candidates
        actions = ["▶  Suggest more", "←  Back"]
        total = len(candidates) + len(actions)
        list_h = rows - 2

        for i in range(list_h):
            idx = cs.ai_scroll + i
            if idx >= total:
                break
            y = 1 + i
            sel = idx == cs.ai_cursor
            attr = curses.color_pair(_C_SEL_NAV) | curses.A_BOLD if sel else 0
            prefix = "▶ " if sel else "  "
            if idx < len(candidates):
                label = candidates[idx]
            else:
                label = actions[idx - len(candidates)]
            try:
                stdscr.addstr(y, x0, (prefix + label).ljust(width - 1)[: width - 1], attr)
            except curses.error:
                pass

        _draw_bar(stdscr, rows - 1, x0, width, "  ↑↓/jk: navigate   Enter: select  ", dim=True)

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
                # AI suggest — render prompt and show for review
                try:
                    from . import ai as _ai

                    taxonomy_name, taxonomy_desc, parent_label = self._build_ai_context(cs)
                    preview = _ai.render_suggest_concept_names_prompt(
                        taxonomy_name=taxonomy_name,
                        taxonomy_description=taxonomy_desc,
                        parent_label=parent_label,
                        lang=self.lang,
                        n=20,
                        exclude=cs.ai_seen,
                    )
                    cs.ai_prompt_preview = preview
                    cs.ai_scroll = 0
                    cs.step = "prompt_review"
                except Exception as exc:
                    cs.error = str(exc)[:120]
        elif key == 27:
            self._state = TreeState() if cs.came_from_tree else DetailState()

    def _on_create_prompt_review(self, key: int, cs: CreateState) -> None:
        KEY_UP, KEY_DOWN = curses.KEY_UP, curses.KEY_DOWN
        max_scroll = max(0, len(cs.ai_prompt_preview.splitlines()) - 3)
        if key in (KEY_UP, ord("k")):
            cs.ai_scroll = max(0, cs.ai_scroll - 1)
        elif key in (KEY_DOWN, ord("j")):
            cs.ai_scroll = min(max_scroll, cs.ai_scroll + 1)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            cs.ai_generating = True
            cs.step = "ai_pick"
        elif key == 27:
            cs.step = "choose"
            cs.ai_cursor = 1

    def _on_create_ai_pick(self, key: int, rows: int, cs: CreateState) -> None:
        if cs.ai_generating:
            return
        KEY_UP, KEY_DOWN = curses.KEY_UP, curses.KEY_DOWN
        candidates = cs.ai_candidates
        n_actions = 2
        total = len(candidates) + n_actions
        suggest_more_idx = len(candidates)
        back_idx = len(candidates) + 1
        list_h = rows - 2

        if key in (KEY_UP, ord("k")):
            cs.ai_cursor = max(0, cs.ai_cursor - 1)
            cs.ai_scroll = min(cs.ai_scroll, cs.ai_cursor)
        elif key in (KEY_DOWN, ord("j")):
            cs.ai_cursor = min(total - 1, cs.ai_cursor + 1)
            if cs.ai_cursor >= cs.ai_scroll + list_h:
                cs.ai_scroll = cs.ai_cursor - list_h + 1
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if cs.ai_cursor == suggest_more_idx:
                cs.ai_generating = True
            elif cs.ai_cursor == back_idx:
                cs.step = "choose"
                cs.ai_cursor = 1
            elif 0 <= cs.ai_cursor < len(candidates):
                chosen = candidates[cs.ai_cursor]
                cs.fields = self._build_create_fields()
                for f in cs.fields:
                    if f.meta.get("field") == "name":
                        f.value = chosen
                        break
                cs.step = "form"
                cs.cursor = 0
        elif key == 27:
            cs.step = "choose"
            cs.ai_cursor = 1

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

    # ─────────────────────────── MOVE PICK mode ──────────────────────────────

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
        return [(u, d) for u, d in ms.candidates if not flt or flt in d.lower()]

    def _draw_move(
        self,
        stdscr: curses.window,
        rows: int,
        cols: int,
        title: str = "",
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
        self._render_move_col(stdscr, rows, detail_x0, detail_w, title=title)
        stdscr.refresh()

    def _render_move_col(
        self,
        stdscr: curses.window,
        rows: int,
        x0: int,
        width: int,
        title: str = "",
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

        # Clamp + scroll
        if ms and filtered:
            ms.cursor = min(ms.cursor, len(filtered) - 1)
            cursor = ms.cursor
        if ms:
            if cursor < ms.scroll:
                ms.scroll = cursor
                scroll = cursor
            elif cursor >= ms.scroll + list_h:
                ms.scroll = cursor - list_h + 1
                scroll = ms.scroll

        for row in range(list_h):
            idx = scroll + row
            if idx >= len(filtered):
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
                elif uri == "__TOP__":
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
            ms.cursor = min(n - 1, ms.cursor + 1)
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = min(n - 1, ms.cursor + list_h)
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
            ms.cursor = min(n - 1, ms.cursor + 1)
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = min(n - 1, ms.cursor + list_h)
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
            ms.cursor = min(n - 1, ms.cursor + 1)
        elif key == curses.KEY_PPAGE:
            ms.cursor = max(0, ms.cursor - list_h)
        elif key == curses.KEY_NPAGE:
            ms.cursor = min(n - 1, ms.cursor + list_h)
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

    def _ai_install_worker(self) -> None:
        """Daemon thread: runs pip install and collects output."""
        import subprocess

        proc = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "--no-color", self._install_package],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if line:
                self._install_output.append(line)
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
        """Called each loop iteration while a plugin is installing."""
        import dataclasses
        import threading

        if not isinstance(self._state, AiSetupState):
            return
        st = self._state
        if st.step != "install_plugin" or not st.plugin_installing:
            return

        self._install_spinner += 1

        if self._install_thread is None:
            t = threading.Thread(target=self._ai_install_worker, daemon=True)
            self._install_thread = t
            t.start()

        current_lines = list(self._install_output)

        if self._install_returncode is not None:
            self._install_thread = None
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
                _put(3, "No models detected for this provider.")
            if st.error:
                _put(box_h - 3, st.error)
            _center(box_h - 2, "[↑↓] choose    [Enter] select    [Esc] back")

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
            if key == 27:
                self._state = _s(step="provider", error="")
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
