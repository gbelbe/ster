"""Interactive taxonomy shell with bash-like navigation.

Commands mirror familiar shell tools:
  ls / ls -l      list concepts with arrow-key navigation
  cd HANDLE       navigate into a concept
  cd ..           go up
  cd /            go to root
  pwd             show breadcrumb path
  show [HANDLE]   ASCII tree
  info [HANDLE]   full concept detail
  add NAME        add concept (parent defaults to cwd)
  mv HANDLE       move concept
  rm HANDLE       remove concept
  label / define  edit metadata
  quit / exit     leave the shell
"""
from __future__ import annotations
import curses
import sys
from cmd import Cmd
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import operations, store
from .display import render_concept_detail, render_tree, console
from .exceptions import SkostaxError
from .model import Taxonomy

err = Console(stderr=True)


# ──────────────────────────── terminal helpers ────────────────────────────────

def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


# ──────────────────────────── taxonomy navigation helpers ────────────────────

def _children(taxonomy: Taxonomy, uri: str | None) -> list[str]:
    """Return direct child URIs (narrower), or top-level concepts when uri is None."""
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
    """Return a breadcrumb string like /[TOP]/[BC]/[RC]."""
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


# ──────────────────────────── curses interactive picker ──────────────────────

def _pick_interactive(
    taxonomy: Taxonomy,
    uris: list[str],
    lang: str = "en",
    detailed: bool = False,
    title: str = "",
) -> str | None:
    """
    Show a curses-based arrow-navigable list.

    Colors:
      cyan bold   — concept with narrower children (navigable, like a directory)
      white       — leaf concept
      blue bg     — currently selected row

    Keys:
      ↑ / k       — move up
      ↓ / j       — move down
      Enter       — select (open if navigable, show detail if leaf)
      q / ← / ESC — go back

    Returns the URI of the selected concept, or None if the user pressed q.
    """
    if not uris or not _is_tty():
        return None

    result: list[str | None] = [None]

    def _draw(stdscr: "curses.window", selected: int, scroll: int) -> None:
        stdscr.erase()
        rows, cols = stdscr.getmaxyx()
        list_h = rows - 2  # row 0 = title bar, last row = footer

        # ── title bar ────────────────────────────────────────────────────────
        t = f" {title} " if title else " / "
        try:
            stdscr.addstr(0, 0, t[: cols - 1], curses.A_REVERSE | curses.A_BOLD)
        except curses.error:
            pass

        # ── concept rows ─────────────────────────────────────────────────────
        for row in range(list_h):
            idx = scroll + row
            if idx >= len(uris):
                break
            uri = uris[idx]
            concept = taxonomy.concepts.get(uri)
            if concept is None:
                continue

            handle = taxonomy.uri_to_handle(uri) or "?"
            label = concept.pref_label(lang) or uri
            n = len(concept.narrower)
            nav = "▸" if n > 0 else " "

            if detailed:
                nb = len(concept.broader)
                nr = len(concept.related)
                d = "✓" if concept.definitions else "·"
                text = (
                    f" {nav} [{handle:<8}]  {label:<32}"
                    f"  {n:>3}↓  {nb:>2}↑  {nr:>2}~  def:{d}"
                )
            else:
                text = f" {nav} [{handle:<8}]  {label}"
                if n > 0:
                    text += f"  ({n})"

            text = text[: cols - 1].ljust(cols - 1)

            try:
                y = row + 1
                if idx == selected:
                    stdscr.addstr(y, 0, text, curses.color_pair(2) | curses.A_BOLD)
                elif n > 0:
                    stdscr.addstr(y, 0, text, curses.color_pair(1) | curses.A_BOLD)
                else:
                    stdscr.addstr(y, 0, text, curses.color_pair(3))
            except curses.error:
                pass

        # ── footer ────────────────────────────────────────────────────────────
        footer = " ↑↓ / j·k  navigate     Enter: open     q / ←: back "
        try:
            stdscr.addstr(rows - 1, 0, footer[: cols - 1], curses.A_DIM | curses.A_REVERSE)
        except curses.error:
            pass

        stdscr.refresh()

    def _inner(stdscr: "curses.window") -> None:
        curses.curs_set(0)
        try:
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)               # navigable
            curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)  # selected
            curses.init_pair(3, curses.COLOR_WHITE, -1)               # leaf
        except Exception:
            pass

        selected = 0
        scroll = 0

        while True:
            rows, _ = stdscr.getmaxyx()
            list_h = rows - 2

            # Adjust scroll window
            if selected < scroll:
                scroll = selected
            elif selected >= scroll + list_h:
                scroll = selected - list_h + 1

            _draw(stdscr, selected, scroll)

            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                selected = max(0, selected - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                selected = min(len(uris) - 1, selected + 1)
            elif key == curses.KEY_HOME:
                selected = 0
            elif key == curses.KEY_END:
                selected = len(uris) - 1
            elif key == curses.KEY_PPAGE:
                selected = max(0, selected - list_h)
            elif key == curses.KEY_NPAGE:
                selected = min(len(uris) - 1, selected + list_h)
            elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                result[0] = uris[selected]
                return
            elif key in (ord("q"), ord("Q"), 27, curses.KEY_LEFT):
                result[0] = None
                return

    try:
        curses.wrapper(_inner)
    except Exception:
        pass

    return result[0]


# ──────────────────────────── shell ──────────────────────────────────────────

class TaxonomyShell(Cmd):
    """Bash-like interactive shell for navigating and editing a SKOS taxonomy."""

    intro = ""
    doc_header = "Commands (type 'help <cmd>' for details):"

    def __init__(self, taxonomy: Taxonomy, file_path: Path, lang: str = "en") -> None:
        super().__init__()
        self.taxonomy = taxonomy
        self.file_path = file_path
        self.lang = lang
        self._cwd: str | None = None  # current concept URI; None = top level
        self._update_prompt()

        try:
            import readline as rl
            rl.parse_and_bind("tab: complete")
        except ImportError:
            pass

    # ── prompt ────────────────────────────────────────────────────────────────

    def _update_prompt(self) -> None:
        if self._cwd is None:
            loc = "/"
        else:
            h = self.taxonomy.uri_to_handle(self._cwd) or "?"
            loc = f"[{h}]"
        self.prompt = f"{loc} $ "

    # ── internal helpers ──────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            store.save(self.taxonomy, self.file_path)
            console.print(f"[green]✓ Saved[/green]  {self.file_path}")
        except Exception as exc:
            err.print(f"[red]Cannot save: {exc}[/red]")

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

    # ── readline completions ──────────────────────────────────────────────────

    def complete_cd(self, text, line, begidx, endidx):
        extras = [".."] if not text or "..".startswith(text) else []
        return self._complete_handle(text) + extras

    def complete_ls(self, text, line, begidx, endidx):
        flags = ["-l"] if not text or "-l".startswith(text) else []
        return self._complete_handle(text) + flags

    def complete_info(self, text, line, begidx, endidx): return self._complete_handle(text)
    def complete_show(self, text, line, begidx, endidx): return self._complete_handle(text)
    def complete_rm(self, text, line, begidx, endidx): return self._complete_handle(text)
    def complete_mv(self, text, line, begidx, endidx): return self._complete_handle(text)
    def complete_label(self, text, line, begidx, endidx): return self._complete_handle(text)
    def complete_define(self, text, line, begidx, endidx): return self._complete_handle(text)

    # ── pwd ───────────────────────────────────────────────────────────────────

    def do_pwd(self, arg: str) -> None:
        """Show the current location as a breadcrumb path.\n  pwd"""
        console.print(_breadcrumb(self.taxonomy, self._cwd))

    # ── ls ────────────────────────────────────────────────────────────────────

    def do_ls(self, arg: str) -> None:
        """List concepts. Use ↑↓ to navigate, Enter to open, q to go back.

  ls              list children of current location
  ls -l           detailed view (counts, definition flag)
  ls HANDLE       list children of HANDLE
  ls -l HANDLE    detailed view for HANDLE's children
        """
        tokens = arg.split()
        detailed = "-l" in tokens or "-la" in tokens or "-al" in tokens
        positional = [t for t in tokens if not t.startswith("-")]

        if positional:
            uri = self._resolve(positional[0])
            if uri is None:
                return
            start = uri
        else:
            start = self._cwd

        self._browse(start, detailed)

    def _browse(self, start: str | None, detailed: bool) -> None:
        """Interactive drill-down browser. Updates self._cwd on navigation."""
        current = start

        while True:
            kids = _children(self.taxonomy, current)
            if not kids:
                console.print("[dim]No concepts here.[/dim]")
                break

            if current is None:
                title = "/"
            else:
                h = self.taxonomy.uri_to_handle(current) or "?"
                lbl = self.taxonomy.concepts[current].pref_label(self.lang)
                title = f"[{h}]  {lbl}"

            if not _is_tty():
                self._print_plain(kids, detailed, title)
                break

            selected_uri = _pick_interactive(
                self.taxonomy, kids, self.lang, detailed, title
            )

            if selected_uri is None:
                # User pressed q — stop browsing, leave cwd as-is
                break

            concept = self.taxonomy.concepts.get(selected_uri)
            if concept and concept.narrower:
                # Navigate deeper
                self._cwd = selected_uri
                self._update_prompt()
                current = selected_uri
            else:
                # Leaf — show detail, exit browser
                console.print(render_concept_detail(self.taxonomy, selected_uri, self.lang))
                break

    def _print_plain(self, uris: list[str], detailed: bool, title: str) -> None:
        console.print(f"\n[bold]{title}[/bold]\n")
        table = Table(box=None, padding=(0, 1))
        table.add_column("", style="dim", no_wrap=True)        # nav marker
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
                    nav, f"[{handle}]", lbl_cell,
                    str(len(c.narrower)), str(len(c.broader)),
                    str(len(c.related)), "✓" if c.definitions else "·",
                )
            else:
                table.add_row(nav, f"[{handle}]", lbl_cell)
        console.print(table)

    # ── cd ────────────────────────────────────────────────────────────────────

    def do_cd(self, arg: str) -> None:
        """Navigate to a concept.

  cd HANDLE   navigate into concept
  cd ..       go up one level
  cd /        go to root
        """
        target = arg.strip()
        if not target or target == "/":
            self._cwd = None
            self._update_prompt()
            return

        if target == "..":
            self._cwd = _parent_uri(self.taxonomy, self._cwd)
            self._update_prompt()
            return

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
        """Display the taxonomy tree.

  show          tree from current location
  show HANDLE   tree from HANDLE
        """
        target = arg.strip() or None
        if target:
            uri = self._resolve(target)
            if uri is None:
                return
            root_h = self.taxonomy.uri_to_handle(uri) or target
        else:
            root_h = self.taxonomy.uri_to_handle(self._cwd) if self._cwd else None
        console.print(render_tree(self.taxonomy, root_handle=root_h, lang=self.lang))

    # ── info ──────────────────────────────────────────────────────────────────

    def do_info(self, arg: str) -> None:
        """Show full concept detail.

  info          current concept
  info HANDLE   given concept
        """
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
        """Add a new concept. Defaults parent to the current location.

  add NAME
  add NAME --en "Label" --fr "Libellé"
  add NAME --parent HANDLE --en "Label"
        """
        import shlex
        try:
            parts = shlex.split(arg)
        except ValueError as exc:
            err.print(f"[red]{exc}[/red]")
            return

        if not parts:
            err.print("[yellow]Usage: add NAME [--en LABEL] [--fr LABEL] [--parent HANDLE][/yellow]")
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
        console.print(f"[green]Added[/green]  [{h}]  {concept.pref_label(self.lang)}  [dim]({uri})[/dim]")
        self._save()

    # ── mv ────────────────────────────────────────────────────────────────────

    def do_mv(self, arg: str) -> None:
        """Move a concept to a new parent.

  mv HANDLE --parent NEW_PARENT
  mv HANDLE /                    promote to top level
        """
        import shlex
        try:
            parts = shlex.split(arg)
        except ValueError as exc:
            err.print(f"[red]{exc}[/red]")
            return

        if not parts:
            err.print("[yellow]Usage: mv HANDLE --parent NEW_PARENT  (or / for top level)[/yellow]")
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
            f"[green]Moved[/green]  "
            f"{self.taxonomy.concepts[uri].pref_label(self.lang)}  →  {dest}"
        )
        self._save()

    # ── rm ────────────────────────────────────────────────────────────────────

    def do_rm(self, arg: str) -> None:
        """Remove a concept.

  rm HANDLE
  rm HANDLE --cascade   also remove all descendants
  rm HANDLE -y          skip confirmation
        """
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

    # ── label ─────────────────────────────────────────────────────────────────

    def do_label(self, arg: str) -> None:
        """Set a preferred or alternative label.

  label HANDLE LANG "Text"
  label HANDLE LANG "Text" --alt
        """
        import shlex
        from .model import LabelType
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
        self._run(operations.set_label, self.taxonomy, uri, lang, text,
                  LabelType.ALT if alt else LabelType.PREF)
        console.print(f"[green]Set {'alt' if alt else 'pref'} label[/green]  [{lang}]  {text}")
        self._save()

    # ── define ────────────────────────────────────────────────────────────────

    def do_define(self, arg: str) -> None:
        """Set a definition.

  define HANDLE LANG "Text"
        """
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
        """Exit the taxonomy shell."""
        return True

    do_exit = do_quit
    do_q = do_quit

    def do_EOF(self, arg: str) -> bool:
        print()
        return True

    def default(self, line: str) -> None:
        cmd = line.split()[0] if line.split() else line
        err.print(f"[yellow]Unknown: {cmd!r}  — type 'help' for available commands.[/yellow]")

    def emptyline(self) -> None:
        pass
