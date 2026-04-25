"""Interactive git commit history browser with taxonomy diff view.

Layout (wide terminal ≥ 90 cols):
  ┌─ git log ───────────────┬─ taxonomy diff ──────────────────────────────────┐
  │ 2024-01-15  Fix labels  │ ◉  My Taxonomy  ·  12 concepts                  │
  │   Alice                 │ ├── + [NEW]  Brand-new concept       (added)     │
  │ 2024-01-10  Add scheme  │ ├── ~ [CHG]  Renamed concept      ↵             │
  │   Bob                   │ └── » [OLD]  Unchanged parent  (+3)              │
  └─────────────────────────┴──────────────────────────────────────────────────┘
  [2/8]  ↑↓: commit  Tab/→: diff tree  r: revert  o: restore  ?: help  q: quit

Color legend in diff tree:
  green  = added concept        red   = removed concept
  yellow = concept with changes (press ↵ to view field-level diff)
  dim    = unchanged concept
"""

from __future__ import annotations

import curses
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import store
from ..model import Taxonomy
from ..nav import (
    TreeLine,
    flatten_tree,
    render_tree_col,
)
from ..nav import (
    _init_colors as _nav_init_colors,
)
from .log_logic import (
    ConceptChange,
    FieldDiff,
    LogEntry,
    _parse_log,
    build_diff_taxonomy,
    compute_auto_fold,
    compute_taxonomy_diff,
)

# ──────────────────────────── git log color pairs ─────────────────────────────
# Pairs 1-14 are owned by nav._init_colors (called in _loop).
# We add log-specific pairs in the 20+ range to avoid collisions.

_LC_SUBJECT = 20  # white bold — commit subject (highlighted)
_LC_DATE = 21  # cyan  dim  — commit date
_LC_AUTHOR = 22  # white dim  — author name
_LC_BAR = 23  # black on cyan — git-log title/footer bars
_LC_FD_ADD = 24  # green bold — added field value in detail overlay
_LC_FD_DEL = 25  # red   bold — removed field value in detail overlay
_LC_FD_KEY = 26  # cyan       — field label in detail overlay


def _git_init_colors() -> None:
    _nav_init_colors()
    try:
        curses.init_pair(_LC_SUBJECT, -1, -1)  # terminal default
        curses.init_pair(_LC_DATE, curses.COLOR_CYAN, -1)
        curses.init_pair(_LC_AUTHOR, -1, -1)  # terminal default
        curses.init_pair(_LC_BAR, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(_LC_FD_ADD, curses.COLOR_GREEN, -1)
        curses.init_pair(_LC_FD_DEL, curses.COLOR_RED, -1)
        curses.init_pair(_LC_FD_KEY, curses.COLOR_CYAN, -1)
    except Exception:
        pass


# ──────────────────────────── git helpers ────────────────────────────────────


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def find_repo_root(path: Path) -> Path | None:
    r = _git("rev-parse", "--show-toplevel", cwd=path)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def _fetch_diff(full_hash: str, file_path: Path | None, repo: Path) -> list[str]:
    """Return raw git-diff lines for one commit (kept for revert-preview use)."""
    hdr = _git(
        "show",
        "--no-patch",
        "--format=commit %H%nAuthor: %an <%ae>%nDate:   %ad%n%n    %s%n",
        "--date=format:%Y-%m-%d %H:%M",
        full_hash,
        cwd=repo,
    )
    lines: list[str] = hdr.stdout.rstrip().splitlines() if hdr.returncode == 0 else []
    diff_args = ["show", "--format=", "--stat", "-p", "-M", full_hash]
    if file_path:
        try:
            rel = file_path.relative_to(repo)
            diff_args += ["--", str(rel)]
        except ValueError:
            diff_args += ["--", str(file_path)]
    diff_r = _git(*diff_args, cwd=repo)
    if diff_r.returncode == 0:
        lines += [""] + diff_r.stdout.splitlines()
    return lines


def _do_revert(full_hash: str, repo: Path) -> tuple[bool, str]:
    r = _git("revert", "--no-edit", full_hash, cwd=repo)
    if r.returncode == 0:
        return True, f"Reverted {full_hash[:7]}"
    return False, (r.stderr or r.stdout).strip()


def _do_restore(full_hash: str, file_path: Path, repo: Path) -> tuple[bool, str]:
    try:
        rel = str(file_path.relative_to(repo))
    except ValueError:
        rel = str(file_path)
    r = _git("checkout", full_hash, "--", rel, cwd=repo)
    if r.returncode == 0:
        return True, f"Restored {rel} to {full_hash[:7]}"
    return False, (r.stderr or r.stdout).strip()


# ──────────────────────────── taxonomy diff helpers ──────────────────────────


def _get_file_at_commit(full_hash: str, file_path: Path, repo: Path) -> str | None:
    """Return file content at *full_hash*, or None if unavailable."""
    try:
        rel = str(file_path.relative_to(repo))
    except ValueError:
        rel = str(file_path)
    r = _git("show", f"{full_hash}:{rel}", cwd=repo)
    return r.stdout if r.returncode == 0 else None


def _load_taxonomy_safe(content: str, suffix: str = ".ttl") -> Taxonomy | None:
    """Parse taxonomy content from a string; return None on any error."""
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False) as f:
            f.write(content)
            tmp = Path(f.name)
        return store.load(tmp)
    except Exception:
        return None
    finally:
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)


# ──────────────────────────── viewer ─────────────────────────────────────────


class GitLogViewer:
    """Full-screen curses git log browser with taxonomy diff tree."""

    _NORMAL = "normal"
    _DIFF_FOCUS = "diff_focus"
    _CONCEPT_DETAIL = "concept_detail"
    _CONFIRM = "confirm_revert"
    _HELP = "help"

    _SPLIT_MIN = 80  # minimum cols for side-by-side layout

    def __init__(self, repo: Path, file_path: Path | None = None) -> None:
        self._repo = repo
        self._file_path = file_path

        # Left panel — commit list
        self._entries: list[LogEntry] = []
        self._cursor = 0
        self._list_scroll = 0

        # Right panel — taxonomy diff tree
        self._diff_taxonomy: Taxonomy | None = None
        self._diff_status: dict[str, ConceptChange] = {}
        self._diff_flat: list[TreeLine] = []
        self._diff_cursor = 0
        self._diff_scroll = 0
        self._diff_folded: set[str] = set()

        # Concept detail overlay (field-level diff)
        self._detail_diffs: list[FieldDiff] = []
        self._detail_uri: str | None = None
        self._detail_scroll = 0

        # Cache: full_hash → (diff_taxonomy, diff_status)
        self._diff_cache: dict[str, tuple[Taxonomy, dict[str, ConceptChange]]] = {}

        self._mode = self._NORMAL
        self._status = ""

        # Raw diff lines kept for fallback / revert context
        self._raw_diff: list[str] = []

    # ── public ────────────────────────────────────────────────────────────────

    def run(self) -> None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            for e in self._entries:
                print(f"{e.date}  {e.subject}  {e.author}")
            return
        try:
            curses.wrapper(self._loop)
        except KeyboardInterrupt:
            pass

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_log(self) -> None:
        SEP = "\x1f"
        fmt = f"{SEP}%H{SEP}%h{SEP}%s{SEP}%an{SEP}%ad{SEP}%D"
        args = [
            "log",
            "--color=never",
            f"--pretty=tformat:{fmt}",
            "--date=format:%Y-%m-%d",
            "--max-count=300",
        ]
        if self._file_path:
            try:
                rel = str(self._file_path.relative_to(self._repo))
            except ValueError:
                rel = str(self._file_path)
            args += ["--follow", "--", rel]
        r = _git(*args, cwd=self._repo)
        if r.returncode != 0:
            self._status = f"git log: {(r.stderr or r.stdout).strip()}"
            return
        self._entries = _parse_log(r.stdout)
        if self._entries:
            self._load_diff_tree(0)

    def _load_diff_tree(self, idx: int) -> None:
        """Load taxonomy diff for entry *idx* into right-panel state."""
        if not (0 <= idx < len(self._entries)):
            return
        if not self._file_path:
            self._diff_taxonomy = None
            self._diff_status = {}
            self._diff_flat = []
            return

        h = self._entries[idx].full_hash
        if h in self._diff_cache:
            self._diff_taxonomy, self._diff_status = self._diff_cache[h]
        else:
            suffix = self._file_path.suffix or ".ttl"

            after_raw = _get_file_at_commit(h, self._file_path, self._repo)
            parent_raw = _get_file_at_commit(f"{h}^", self._file_path, self._repo)

            # _load_taxonomy_safe returns None on parse failure — treat as empty
            after_tax = (
                _load_taxonomy_safe(after_raw, suffix) if after_raw else None
            ) or Taxonomy()
            before_tax = (
                _load_taxonomy_safe(parent_raw, suffix) if parent_raw else None
            ) or Taxonomy()

            diff_status = compute_taxonomy_diff(before_tax, after_tax)
            diff_taxonomy = build_diff_taxonomy(before_tax, after_tax)

            self._diff_cache[h] = (diff_taxonomy, diff_status)
            self._diff_taxonomy = diff_taxonomy
            self._diff_status = diff_status

        self._diff_folded = compute_auto_fold(self._diff_taxonomy, self._diff_status)
        self._diff_flat = flatten_tree(self._diff_taxonomy, folded=self._diff_folded)
        self._diff_cursor = 0
        self._diff_scroll = 0

    def _diff_status_str(self) -> dict[str, str]:
        """Convert ConceptChange map to the string-status dict render_tree_col expects."""
        return {uri: ch.status for uri, ch in self._diff_status.items()}

    # ── main loop ─────────────────────────────────────────────────────────────

    def _loop(self, stdscr: curses.window) -> None:
        curses.curs_set(0)
        _git_init_colors()
        stdscr.keypad(True)
        self._load_log()

        while True:
            rows, cols = stdscr.getmaxyx()
            self._draw(stdscr, rows, cols)
            key = stdscr.getch()
            if key == curses.KEY_RESIZE:
                curses.update_lines_cols()
                continue
            if self._mode == self._HELP:
                self._mode = self._NORMAL
                continue
            if self._mode == self._CONFIRM:
                if self._on_confirm(key):
                    break
                continue
            if self._on_key(key, rows, cols):
                break

    # ── drawing ───────────────────────────────────────────────────────────────

    def _log_bar(self, stdscr: curses.window, y: int, x: int, w: int, text: str) -> None:
        attr = curses.color_pair(_LC_BAR) | curses.A_BOLD
        try:
            stdscr.addstr(y, x, text[: w - 1].ljust(w - 1), attr)
        except curses.error:
            pass

    def _draw(self, stdscr: curses.window, rows: int, cols: int) -> None:
        stdscr.erase()
        if self._mode == self._HELP:
            self._draw_help(stdscr, rows, cols)
            stdscr.refresh()
            return

        wide = cols >= self._SPLIT_MIN
        if wide:
            list_w = max(24, cols * 3 // 10)
            diff_x = list_w + 1
            diff_w = cols - diff_x
            self._draw_list(stdscr, rows, 0, list_w)
            for y in range(rows - 1):
                try:
                    stdscr.addch(y, list_w, curses.ACS_VLINE)
                except curses.error:
                    pass
            self._draw_diff_tree(stdscr, rows, diff_x, diff_w)
        else:
            if self._mode == self._DIFF_FOCUS:
                self._draw_diff_tree(stdscr, rows, 0, cols)
            else:
                self._draw_list(stdscr, rows, 0, cols)

        if self._mode == self._CONCEPT_DETAIL:
            self._draw_concept_detail(stdscr, rows, cols)

        if self._mode == self._CONFIRM:
            self._draw_confirm(stdscr, rows, cols)

        self._draw_footer(stdscr, rows, cols)
        stdscr.refresh()

    # ── list panel ────────────────────────────────────────────────────────────

    def _draw_list(self, stdscr: curses.window, rows: int, x0: int, w: int) -> None:
        n = len(self._entries)
        name = self._file_path.name if self._file_path else self._repo.name
        pos = f"  [{self._cursor + 1}/{n}]" if n else ""
        self._log_bar(stdscr, 0, x0, w, f" ⎇  {name}{pos} ")

        list_h = rows - 2
        # Each entry takes 2 rows: line 1 = date + subject, line 2 = author
        # But with limited width we use 1 row per entry for compactness:
        # "YYYY-MM-DD  Subject…  Author"
        self._list_scroll = max(0, min(self._list_scroll, max(0, n - list_h)))
        if self._cursor < self._list_scroll:
            self._list_scroll = self._cursor
        elif self._cursor >= self._list_scroll + list_h:
            self._list_scroll = self._cursor - list_h + 1

        for row in range(list_h):
            idx = self._list_scroll + row
            if idx >= n:
                break
            e = self._entries[idx]
            y = row + 1
            is_sel = idx == self._cursor

            if is_sel:
                attr_date = curses.color_pair(_LC_BAR) | curses.A_BOLD
                attr_subject = curses.color_pair(_LC_BAR) | curses.A_BOLD
                attr_author = curses.color_pair(_LC_BAR) | curses.A_DIM
                # clear whole row
                try:
                    stdscr.addstr(y, x0, " " * (w - 1), attr_date)
                except curses.error:
                    pass
            else:
                attr_date = curses.color_pair(_LC_DATE) | curses.A_DIM
                attr_subject = curses.color_pair(_LC_SUBJECT) | curses.A_BOLD
                attr_author = curses.color_pair(_LC_AUTHOR) | curses.A_DIM

            col = x0
            rem = w - 1

            def _put(text: str, attr: int, _row: int = y) -> None:
                nonlocal col, rem
                t = text[:rem]
                if not t:
                    return
                try:
                    stdscr.addstr(_row, col, t, attr)
                except curses.error:
                    pass
                col += len(t)
                rem -= len(t)

            _put(e.date, attr_date)
            _put("  ", attr_subject)
            # Subject: fill most of the remaining width, then author at end
            author_field = f"  {e.author}"
            subject_max = max(0, rem - len(author_field))
            subject_text = e.subject[:subject_max].ljust(subject_max) if subject_max else ""
            _put(subject_text, attr_subject)
            _put(author_field, attr_author)

    # ── diff-tree panel ───────────────────────────────────────────────────────

    def _draw_diff_tree(self, stdscr: curses.window, rows: int, x0: int, w: int) -> None:
        if not self._diff_taxonomy:
            self._log_bar(stdscr, 0, x0, w, " taxonomy diff ")
            if not self._file_path:
                msg = " No file scope — run: ster log <file.ttl> "
            elif not self._entries:
                msg = " No commits found for this file "
            else:
                msg = " Loading… "
            try:
                stdscr.addstr(2, x0 + 2, msg[: w - 3], curses.A_DIM)
            except curses.error:
                pass
            return

        e = self._entries[self._cursor] if self._entries else None
        focus_mark = " [DIFF]" if self._mode == self._DIFF_FOCUS else ""
        title = f" {e.date}: {e.subject}{focus_mark} " if e else " taxonomy diff "
        n_changed = sum(1 for ch in self._diff_status.values() if ch.status != "unchanged")
        if n_changed:
            title = title.rstrip(" ") + f"  {n_changed} change{'s' if n_changed != 1 else ''} "

        cursor = self._diff_cursor if self._mode == self._DIFF_FOCUS else -1

        # Clamp scroll
        list_h = rows - 2
        n = len(self._diff_flat)
        if cursor >= 0:
            if cursor < self._diff_scroll:
                self._diff_scroll = cursor
            elif cursor >= self._diff_scroll + list_h:
                self._diff_scroll = cursor - list_h + 1
        self._diff_scroll = max(0, min(self._diff_scroll, max(0, n - list_h)))

        render_tree_col(
            stdscr,
            self._diff_flat,
            self._diff_taxonomy,
            "en",
            rows,
            x0,
            w,
            self._diff_scroll,
            cursor,
            header_title=title.strip(),
            diff_status=self._diff_status_str(),
        )

    # ── concept detail overlay ────────────────────────────────────────────────

    def _draw_concept_detail(self, stdscr: curses.window, rows: int, cols: int) -> None:
        if not self._detail_diffs and self._detail_uri is None:
            return

        # Draw as full-width overlay panel on the right two-thirds
        wide = cols >= self._SPLIT_MIN
        list_w = max(24, cols * 3 // 10) if wide else 0
        x0 = list_w + 1 if wide else 0
        w = cols - x0
        list_h = rows - 2

        # Concept name from taxonomy
        concept_label = self._detail_uri or ""
        if self._diff_taxonomy and self._detail_uri:
            c = self._diff_taxonomy.concepts.get(self._detail_uri)
            if c:
                concept_label = c.pref_label("en") or self._detail_uri

        ch = self._diff_status.get(self._detail_uri or "")
        status_tag = f" [{ch.status}]" if ch else ""
        self._log_bar(stdscr, 0, x0, w, f" ◈ {concept_label}{status_tag}  ←/Esc: back ")

        # Build display lines
        diffs = self._detail_diffs
        scroll = max(0, min(self._detail_scroll, max(0, len(diffs) - list_h)))
        self._detail_scroll = scroll

        for row in range(list_h):
            di = scroll + row
            if di >= len(diffs):
                break
            fd = diffs[di]
            y = row + 1

            col = x0 + 1
            rem = w - 2

            def _put(text: str, attr: int, _row: int = y) -> None:
                nonlocal col, rem
                t = text[:rem]
                if not t:
                    return
                try:
                    stdscr.addstr(_row, col, t, attr)
                except curses.error:
                    pass
                col += len(t)
                rem -= len(t)

            lbl_attr = curses.color_pair(_LC_FD_KEY)
            _put(f"{fd.label:<24} ", lbl_attr)

            def _one(v: str) -> str:
                v = v.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
                return v

            if fd.status == "added":
                _put(f"+ {_one(fd.after)}", curses.color_pair(_LC_FD_ADD) | curses.A_BOLD)
            elif fd.status == "removed":
                _put(f"− {_one(fd.before)}", curses.color_pair(_LC_FD_DEL) | curses.A_BOLD)
            else:  # changed
                _put(f"− {_one(fd.before)}", curses.color_pair(_LC_FD_DEL))
                _put("  →  ", curses.A_DIM)
                _put(f"+ {_one(fd.after)}", curses.color_pair(_LC_FD_ADD))

        if not diffs:
            try:
                stdscr.addstr(
                    2, x0 + 2, " (no field-level changes recorded) "[: w - 3], curses.A_DIM
                )
            except curses.error:
                pass

    # ── footer / confirm / help ───────────────────────────────────────────────

    def _draw_footer(self, stdscr: curses.window, rows: int, cols: int) -> None:
        if self._status:
            text = f" {self._status} "
            self._status = ""
        elif self._mode == self._CONCEPT_DETAIL:
            text = " ↑↓: scroll fields  ←/Esc: back to diff tree  q: quit "
        elif self._mode == self._DIFF_FOCUS:
            text = (
                " ↑↓/jk: navigate  Space: fold/unfold  ↵/→: view changes"
                "  ←/Tab: back to list  q: quit "
            )
        else:
            n = len(self._entries)
            pos = f"[{self._cursor + 1}/{n}]" if n else "[0/0]"
            resto = "  o: restore" if self._file_path else ""
            text = f" {pos}  ↑↓/jk: commit  Tab/→: diff tree  r: revert{resto}  ?: help  q: quit "
        self._log_bar(stdscr, rows - 1, 0, cols, text)

    def _draw_confirm(self, stdscr: curses.window, rows: int, cols: int) -> None:
        if not self._entries:
            return
        e = self._entries[self._cursor]
        msg = f' Revert commit {e.short_hash}? "{e.subject}" '
        hint = "  [y] yes   [n / Esc] cancel  "
        bw = min(cols - 4, max(len(msg), len(hint)) + 4)
        by = rows // 2 - 1
        bx = (cols - bw) // 2
        attr = curses.color_pair(_LC_BAR) | curses.A_BOLD
        try:
            stdscr.addstr(by, bx, msg[: bw - 1].center(bw - 1), attr)
            stdscr.addstr(by + 1, bx, hint[: bw - 1].center(bw - 1), attr)
        except curses.error:
            pass

    def _draw_help(self, stdscr: curses.window, rows: int, cols: int) -> None:
        lines = [
            " git log browser — keyboard shortcuts ",
            "",
            "  COMMIT LIST (left panel)",
            "  ↑↓ / j·k          select commit",
            "  g / G             first / last commit",
            "  Ctrl+D / Ctrl+U   half-page down / up",
            "  Tab / →           focus diff tree",
            "",
            "  TAXONOMY DIFF TREE (right panel)",
            "  ↑↓ / j·k          navigate tree",
            "  Space             fold / unfold",
            "  ↵ / →             view field-level changes for modified concept",
            "  ← / Tab           back to commit list",
            "",
            "  COLOR LEGEND",
            "  green  added concept        red    removed concept",
            "  yellow changed concept      dim    unchanged concept",
            "",
            "  ACTIONS",
            "  r                 revert selected commit",
            "  o                 restore file to this version  (file scope only)",
            "  ? / h             show this help",
            "  q / Esc           quit",
            "",
            "  Press any key to return …",
        ]
        bw = min(cols - 4, 66)
        bh = min(rows - 2, len(lines) + 2)
        by = max(0, (rows - bh) // 2)
        bx = max(0, (cols - bw) // 2)
        self._log_bar(stdscr, by, bx, bw, " git log — help ")
        for i, text in enumerate(lines[: bh - 2]):
            y = by + 1 + i
            if y >= rows - 1:
                break
            stripped = text.strip()
            if stripped.isupper() or stripped.endswith("panel)") or stripped.endswith("legend"):
                attr = curses.color_pair(_LC_DATE) | curses.A_BOLD
            else:
                attr = curses.A_NORMAL
            try:
                stdscr.addstr(y, bx, text[: bw - 1].ljust(bw - 1), attr)
            except curses.error:
                pass
        self._log_bar(stdscr, by + bh - 1, bx, bw, "  Press any key to return … ")

    # ── key handlers ─────────────────────────────────────────────────────────

    def _on_key(self, key: int, rows: int, cols: int) -> bool:
        list_h = rows - 2

        # ── concept detail mode ───────────────────────────────────────────────
        if self._mode == self._CONCEPT_DETAIL:
            if key in (curses.KEY_DOWN, ord("j")):
                self._detail_scroll += 1
            elif key in (curses.KEY_UP, ord("k")):
                self._detail_scroll = max(0, self._detail_scroll - 1)
            elif key in (curses.KEY_LEFT, 27, ord("q"), ord("Q")):
                if key in (ord("q"), ord("Q")):
                    return True
                self._mode = self._DIFF_FOCUS
            return False

        # ── diff tree focus ───────────────────────────────────────────────────
        if self._mode == self._DIFF_FOCUS:
            n = len(self._diff_flat)
            if key in (curses.KEY_UP, ord("k")):
                self._diff_cursor = max(0, self._diff_cursor - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                self._diff_cursor = min(n - 1, self._diff_cursor + 1)
            elif key in (curses.KEY_HOME, ord("g")):
                self._diff_cursor = 0
            elif key in (curses.KEY_END, ord("G")):
                self._diff_cursor = max(0, n - 1)
            elif key == 4:  # Ctrl+D
                self._diff_cursor = min(n - 1, self._diff_cursor + list_h // 2)
            elif key == 21:  # Ctrl+U
                self._diff_cursor = max(0, self._diff_cursor - list_h // 2)
            elif key == ord(" "):
                self._toggle_diff_fold()
            elif key in (curses.KEY_RIGHT, curses.KEY_ENTER, ord("\n"), ord("\r")):
                self._open_concept_detail()
            elif key in (curses.KEY_LEFT, 9, ord("h")):  # ← or Tab
                self._mode = self._NORMAL
            elif key in (ord("q"), ord("Q"), 27):
                return True
            return False

        # ── list focus (normal) ───────────────────────────────────────────────
        if key in (curses.KEY_UP, ord("k")):
            if self._cursor > 0:
                self._cursor -= 1
                self._load_diff_tree(self._cursor)
        elif key in (curses.KEY_DOWN, ord("j")):
            if self._cursor < len(self._entries) - 1:
                self._cursor += 1
                self._load_diff_tree(self._cursor)
        elif key in (curses.KEY_HOME, ord("g")):
            self._cursor = 0
            self._list_scroll = 0
            self._load_diff_tree(0)
        elif key in (curses.KEY_END, ord("G")):
            self._cursor = max(0, len(self._entries) - 1)
            self._load_diff_tree(self._cursor)
        elif key == 4:  # Ctrl+D
            self._cursor = min(len(self._entries) - 1, self._cursor + list_h // 2)
            self._load_diff_tree(self._cursor)
        elif key == 21:  # Ctrl+U
            self._cursor = max(0, self._cursor - list_h // 2)
            self._load_diff_tree(self._cursor)
        elif key in (9, curses.KEY_RIGHT):  # Tab / →
            if self._diff_flat:
                self._mode = self._DIFF_FOCUS
        elif key == ord("r"):
            if self._entries:
                self._mode = self._CONFIRM
        elif key == ord("o"):
            if self._file_path and self._entries:
                e = self._entries[self._cursor]
                ok, msg = _do_restore(e.full_hash, self._file_path, self._repo)
                self._status = msg
            else:
                self._status = "'o' only when launched with a specific file"
        elif key in (ord("?"), ord("h")):
            self._mode = self._HELP
        elif key in (ord("q"), ord("Q"), 27):
            return True

        return False

    def _toggle_diff_fold(self) -> None:
        if not (0 <= self._diff_cursor < len(self._diff_flat)):
            return
        line = self._diff_flat[self._diff_cursor]
        uri = line.uri
        # Check has children
        has_children = False
        if line.is_scheme:
            s = self._diff_taxonomy.schemes.get(uri) if self._diff_taxonomy else None
            has_children = bool(s and s.top_concepts)
        else:
            if self._diff_taxonomy:
                c = self._diff_taxonomy.concepts.get(uri)
                has_children = bool(c and c.narrower)
        if not has_children:
            return
        if uri in self._diff_folded:
            self._diff_folded.discard(uri)
        else:
            self._diff_folded.add(uri)
        if self._diff_taxonomy:
            self._diff_flat = flatten_tree(self._diff_taxonomy, folded=self._diff_folded)
        # Keep cursor on same URI
        for i, tl in enumerate(self._diff_flat):
            if tl.uri == uri:
                self._diff_cursor = i
                break

    def _open_concept_detail(self) -> None:
        if not (0 <= self._diff_cursor < len(self._diff_flat)):
            return
        line = self._diff_flat[self._diff_cursor]
        if line.is_scheme:
            return
        uri = line.uri
        ch = self._diff_status.get(uri)
        if ch is None or ch.status == "unchanged":
            return
        self._detail_uri = uri
        self._detail_diffs = ch.field_diffs
        self._detail_scroll = 0
        self._mode = self._CONCEPT_DETAIL

    def _on_confirm(self, key: int) -> bool:
        if key in (ord("y"), ord("Y")):
            e = self._entries[self._cursor]
            ok, msg = _do_revert(e.full_hash, self._repo)
            self._status = msg
            self._mode = self._NORMAL
            if ok:
                self._diff_cache.clear()
                self._load_log()
        else:
            self._mode = self._NORMAL
        return False


# ──────────────────────────── public entry point ─────────────────────────────


def launch_git_log(
    path: Path | None = None,
    repo: Path | None = None,
) -> None:
    from rich.console import Console

    err = Console(stderr=True)

    target = path or Path.cwd()
    file_scope: Path | None = None

    if target.is_file():
        file_scope = target.resolve()
        search_from = target.parent
    else:
        search_from = target

    if repo is None:
        repo = find_repo_root(search_from)

    if repo is None:
        err.print("[red]Not inside a git repository.[/red]")
        return

    viewer = GitLogViewer(repo=repo, file_path=file_scope)
    viewer.run()
