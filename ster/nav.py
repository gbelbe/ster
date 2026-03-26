"""Interactive taxonomy TUI (curses) and REPL shell (cmd.Cmd).

TaxonomyViewer — full-screen curses navigator
  Tree mode   ↑↓ navigate  →/Enter open detail  ← parent  Esc exit
  Detail mode ↑↓ fields    i/Enter edit          ← back    d delete
  Edit mode   text editing  Enter save            Esc cancel

TaxonomyShell — bash-like REPL (ster nav)
"""
from __future__ import annotations
import curses
import sys
from cmd import Cmd
from dataclasses import dataclass, field as dc_field
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import operations, store
from .display import render_concept_detail, render_tree, console
from .exceptions import SkostaxError
from .model import LabelType, Taxonomy

err = Console(stderr=True)


# ──────────────────────────── tree helpers ────────────────────────────────────

@dataclass
class TreeLine:
    uri: str
    depth: int
    prefix: str   # e.g. "│   ├── "


def flatten_tree(taxonomy: Taxonomy) -> list[TreeLine]:
    """Flatten the full taxonomy tree into a list of displayable lines."""
    result: list[TreeLine] = []
    scheme = taxonomy.primary_scheme()
    tops = list(scheme.top_concepts) if scheme else []

    def visit(uri: str, depth: int, prefix: str, is_last: bool) -> None:
        connector = "└── " if is_last else "├── "
        result.append(TreeLine(uri=uri, depth=depth, prefix=prefix + connector))
        concept = taxonomy.concepts.get(uri)
        if concept:
            ext = "    " if is_last else "│   "
            children = concept.narrower
            for i, child in enumerate(children):
                visit(child, depth + 1, prefix + ext, i == len(children) - 1)

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


def _init_colors() -> None:
    try:
        curses.use_default_colors()
        curses.init_pair(_C_NAVIGABLE,     curses.COLOR_CYAN,  -1)
        curses.init_pair(_C_SEL,           curses.COLOR_WHITE,  curses.COLOR_BLUE)
        curses.init_pair(_C_SEL_NAV,       curses.COLOR_CYAN,   curses.COLOR_BLUE)
        curses.init_pair(_C_DIM,           curses.COLOR_WHITE,  -1)
        curses.init_pair(_C_FIELD_LABEL,   curses.COLOR_GREEN,  -1)
        curses.init_pair(_C_FIELD_VAL,     curses.COLOR_WHITE,  -1)
        curses.init_pair(_C_EDIT_BAR,      curses.COLOR_BLACK,  curses.COLOR_GREEN)
        curses.init_pair(_C_DETAIL_CURSOR, curses.COLOR_BLACK,  curses.COLOR_CYAN)
    except Exception:
        pass


# ──────────────────────────── TaxonomyViewer ─────────────────────────────────

class TaxonomyViewer:
    """Full-screen curses TUI for taxonomy navigation and inline editing."""

    _TREE   = "tree"
    _DETAIL = "detail"
    _EDIT   = "edit"

    # Minimum terminal width for side-by-side tree + detail
    _SPLIT_MIN_COLS = 120

    def __init__(self, taxonomy: Taxonomy, file_path: Path, lang: str = "en") -> None:
        self.taxonomy  = taxonomy
        self.file_path = file_path
        self.lang      = lang

        self._flat: list[TreeLine] = []
        self._cursor    = 0
        self._tree_scroll = 0

        self._detail_uri: str | None = None
        self._detail_fields: list[DetailField] = []
        self._field_cursor  = 0
        self._detail_scroll = 0

        self._edit_value = ""
        self._edit_pos   = 0

        self._mode    = self._TREE
        self._history: list[dict] = []
        self._status  = ""

        self._rebuild()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        self._flat = flatten_tree(self.taxonomy)

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
            self._detail_fields = build_detail_fields(
                self.taxonomy, self._detail_uri, self.lang
            )
        return True

    def _save_file(self) -> None:
        try:
            store.save(self.taxonomy, self.file_path)
            self._status = f"Saved  {self.file_path.name}"
        except Exception as exc:
            self._status = f"Error saving: {exc}"

    def _open_detail(self) -> None:
        if not (0 <= self._cursor < len(self._flat)):
            return
        self._push()
        self._detail_uri     = self._flat[self._cursor].uri
        self._detail_fields  = build_detail_fields(
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
                self._draw_split(stdscr, rows, cols)
                self._draw_edit_bar(stdscr, rows, cols)
                key = stdscr.getch()
                if key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                self._on_edit(key)

    # ─────────────────────────── TREE drawing ────────────────────────────────

    def _adjust_tree_scroll(self, rows: int) -> None:
        list_h = rows - 2
        if self._cursor < self._tree_scroll:
            self._tree_scroll = self._cursor
        elif self._cursor >= self._tree_scroll + list_h:
            self._tree_scroll = self._cursor - list_h + 1

    def _draw_tree(self, stdscr: "curses.window", rows: int, cols: int) -> None:
        stdscr.erase()
        self._adjust_tree_scroll(rows)
        self._render_tree_col(stdscr, rows, 0, cols, self._cursor, highlight_uri=None)
        footer = (
            " ↑↓ navigate   →/Enter: detail   ←: parent   "
            "j/k  h/l   Esc/q: exit "
        )
        self._draw_bar(stdscr, rows - 1, 0, cols, footer, dim=True)
        if self._status:
            self._draw_bar(stdscr, rows - 1, 0, cols, f" {self._status} ", dim=False)
            self._status = ""
        stdscr.refresh()

    def _render_tree_col(
        self,
        stdscr: "curses.window",
        rows: int,
        x0: int,
        width: int,
        cursor_idx: int,
        highlight_uri: str | None,
    ) -> None:
        """Render the tree list into column [x0, x0+width)."""
        list_h = rows - 2
        scheme = self.taxonomy.primary_scheme()
        title = ""
        if scheme:
            for lbl in scheme.labels:
                if lbl.lang == self.lang:
                    title = lbl.value
                    break
            if not title and scheme.labels:
                title = scheme.labels[0].value
        self._draw_bar(stdscr, 0, x0, width, f" {title} " if title else " Taxonomy ", dim=False)

        for row in range(list_h):
            idx = self._tree_scroll + row
            if idx >= len(self._flat):
                break
            line = self._flat[idx]
            concept = self.taxonomy.concepts.get(line.uri)
            if not concept:
                continue

            handle = self.taxonomy.uri_to_handle(line.uri) or "?"
            label  = concept.pref_label(self.lang) or line.uri
            n      = len(concept.narrower)
            nav    = "▸" if n else " "

            text = f"{line.prefix}{nav} [{handle}]  {label}"
            text = text[:width - 1]

            y  = row + 1
            is_cursor   = idx == cursor_idx
            is_detail   = line.uri == highlight_uri
            try:
                if is_cursor and n:
                    stdscr.addstr(y, x0, text.ljust(width - 1),
                                  curses.color_pair(_C_SEL_NAV) | curses.A_BOLD)
                elif is_cursor:
                    stdscr.addstr(y, x0, text.ljust(width - 1),
                                  curses.color_pair(_C_SEL) | curses.A_BOLD)
                elif is_detail:
                    stdscr.addstr(y, x0, text.ljust(width - 1),
                                  curses.color_pair(_C_SEL) | curses.A_DIM)
                elif n:
                    stdscr.addstr(y, x0, text,
                                  curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                else:
                    stdscr.addstr(y, x0, text)
            except curses.error:
                pass

    # ─────────────────────────── TREE events ─────────────────────────────────

    def _on_tree(self, key: int, rows: int) -> bool:
        n = len(self._flat)
        list_h = rows - 2

        if key in (curses.KEY_UP, ord("k")):
            self._cursor = max(0, self._cursor - 1)

        elif key in (curses.KEY_DOWN, ord("j")):
            self._cursor = min(n - 1, self._cursor + 1)

        elif key == curses.KEY_HOME:
            self._cursor = 0

        elif key == curses.KEY_END:
            self._cursor = n - 1

        elif key == curses.KEY_PPAGE:
            self._cursor = max(0, self._cursor - list_h)

        elif key == curses.KEY_NPAGE:
            self._cursor = min(n - 1, self._cursor + list_h)

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
        stdscr.refresh()

    def _render_detail_col(
        self, stdscr: "curses.window", rows: int, x0: int, width: int
    ) -> None:
        concept = (
            self.taxonomy.concepts.get(self._detail_uri) if self._detail_uri else None
        )
        if not concept:
            return

        handle = self.taxonomy.uri_to_handle(self._detail_uri) if self._detail_uri else "?"
        label  = concept.pref_label(self.lang) or self._detail_uri or ""
        self._draw_bar(stdscr, 0, x0, width, f" [{handle}]  {label} ", dim=False)

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

            fl  = f.display[:lbl_w].ljust(lbl_w)
            fv  = f.value[:width - lbl_w - 5]
            y   = row + 1

            try:
                if sel:
                    line = f"  {fl}  {fv}"
                    stdscr.addstr(y, x0, line.ljust(width - 1)[:width - 1],
                                  curses.color_pair(_C_DETAIL_CURSOR) | curses.A_BOLD)
                elif f.editable:
                    stdscr.addstr(y, x0,   "  ")
                    stdscr.addstr(y, x0+2, fl, curses.color_pair(_C_FIELD_LABEL))
                    stdscr.addstr(y, x0+2+lbl_w+2, fv,
                                  curses.color_pair(_C_FIELD_VAL) | curses.A_BOLD)
                else:
                    stdscr.addstr(y, x0,   "  ")
                    stdscr.addstr(y, x0+2, fl, curses.color_pair(_C_DIM) | curses.A_DIM)
                    stdscr.addstr(y, x0+2+lbl_w+2, fv, curses.color_pair(_C_DIM) | curses.A_DIM)
            except curses.error:
                pass

        if self._mode != self._EDIT:
            footer = " ↑↓ fields   i/Enter: edit   d: delete   ←/Esc: back "
            self._draw_bar(stdscr, rows - 1, x0, width, footer, dim=True)

    # ─────────────────────────── DETAIL events ───────────────────────────────

    def _on_detail(self, key: int, rows: int) -> bool:
        n = len(self._detail_fields)
        list_h = rows - 2

        if key in (curses.KEY_UP, ord("k")):
            self._field_cursor = max(0, self._field_cursor - 1)

        elif key in (curses.KEY_DOWN, ord("j")):
            self._field_cursor = min(n - 1, self._field_cursor + 1)

        elif key == curses.KEY_HOME:
            self._field_cursor = 0

        elif key == curses.KEY_END:
            self._field_cursor = n - 1

        elif key == curses.KEY_PPAGE:
            self._field_cursor = max(0, self._field_cursor - list_h)

        elif key == curses.KEY_NPAGE:
            self._field_cursor = min(n - 1, self._field_cursor + list_h)

        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r"), ord("i"), ord("e")):
            if 0 <= self._field_cursor < n:
                f = self._detail_fields[self._field_cursor]
                if f.editable:
                    self._edit_value = f.value
                    self._edit_pos   = len(f.value)
                    self._mode       = self._EDIT

        elif key == ord("d"):
            if 0 <= self._field_cursor < n:
                f = self._detail_fields[self._field_cursor]
                if f.editable:
                    self._delete_field(f)

        elif key in (curses.KEY_LEFT, ord("h"), 27):
            self._back()

        return False

    # ─────────────────────────── EDIT drawing ────────────────────────────────

    def _draw_edit_bar(self, stdscr: "curses.window", rows: int, cols: int) -> None:
        if not (0 <= self._field_cursor < len(self._detail_fields)):
            return
        f       = self._detail_fields[self._field_cursor]
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

    def _on_edit(self, key: int) -> None:
        v, p = self._edit_value, self._edit_pos

        if key == 27:                           # Esc — cancel
            self._mode = self._DETAIL

        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            self._commit_edit()
            self._mode = self._DETAIL

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

        elif key == curses.KEY_HOME:
            self._edit_pos = 0

        elif key == curses.KEY_END:
            self._edit_pos = len(v)

        elif 32 <= key < 256:
            ch = chr(key)
            self._edit_value = v[:p] + ch + v[p:]
            self._edit_pos   = p + 1

    def _commit_edit(self) -> None:
        if not self._detail_uri:
            return
        if not (0 <= self._field_cursor < len(self._detail_fields)):
            return
        f         = self._detail_fields[self._field_cursor]
        new_value = self._edit_value.strip()
        if not new_value or not f.editable:
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

    # ─────────────────────────── shared utility ──────────────────────────────

    @staticmethod
    def _draw_bar(
        stdscr: "curses.window",
        y: int,
        x0: int,
        width: int,
        text: str,
        dim: bool,
    ) -> None:
        t = text[:width - 1].ljust(width - 1)
        attr = (curses.A_DIM | curses.A_REVERSE) if dim else (curses.A_REVERSE | curses.A_BOLD)
        try:
            stdscr.addstr(y, x0, t, attr)
        except curses.error:
            pass


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
