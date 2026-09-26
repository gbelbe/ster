"""The semantic history of one ontology file, read as a drill-down.

Commits on the left, newest first, tagged releases marked. Choosing one shows
three things in order, each visibly separate: what the commit says it did, who
made it and when, and what it actually did to the vocabulary. The raw git hunk
sits below that, put away until asked for, because the text is the escape hatch
rather than the first thing to read.

Diffing a revision takes about a second on a large ontology, so it happens on a
worker thread: the list stays arrow-able while a commit is being read, and the
panel says it is working rather than freezing.
"""

from __future__ import annotations

from rich.console import Group
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from semanticdiff.render.rows import Row
from semanticdiff.vocabulary import ChangeKind
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import DataTable, Footer, Header, Static
from textual.worker import Worker, get_current_worker

from .history import FileHistory

_HIDDEN = "hidden-pane"

# The separator between the metadata fields, named once so the ratchet counts it once.
_DOT = ("  \u00b7  ", "dim")

# What each kind of change is called, and the colour it is called it in. Words
# rather than +/-/~ glyphs: a reader should not have to learn a key first.
_KINDS: dict[ChangeKind, tuple[str, str]] = {
    ChangeKind.ADDED: ("added", "green"),
    ChangeKind.REMOVED: ("removed", "red"),
    ChangeKind.MODIFIED: ("changed", "yellow"),
    ChangeKind.RENAMED: ("renamed", "cyan"),
    ChangeKind.DEPRECATED: ("deprecated", "magenta"),
}


class HistoryScreen(App[None]):
    """Commit list beside the change list, with the raw diff under it."""

    CSS = """
    Screen { background: $surface; }
    /* The commit list carries three things now — when, who, and what the commit
       says it did — and 44 columns truncated the subject to the point of
       uselessness. Both sides run the full height of the screen. */
    #commits { width: 52%; height: 1fr; border-right: solid $primary-darken-2; }
    #panes { width: 1fr; height: 1fr; }
    #detail { padding: 1 2; }
    #raw { height: 45%; border-top: solid $primary-darken-2; padding: 1 2; }
    #raw.hidden-pane { display: none; }
    """

    BINDINGS = [
        Binding("r", "toggle_raw", "Raw diff"),
        Binding("escape,q", "quit", "Close"),
    ]

    def __init__(self, history: FileHistory) -> None:
        super().__init__()
        self.history = history
        self.title = "Semantic history"
        self.sub_title = history.path
        self._sha = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield DataTable(id="commits", cursor_type="row", zebra_stripes=True)
            with Vertical(id="panes"):
                with VerticalScroll():
                    yield Static("", id="detail")
                with VerticalScroll(id="raw", classes=_HIDDEN):
                    yield Static("", id="raw-text")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#commits", DataTable)
        table.add_columns("when", "who", "commit")
        for row in self.history.rows:
            table.add_row(
                Text(row.when, style="dim"),
                Text(_short_author(row.author), style="cyan"),
                _commit_cell(row),
                key=row.sha,
            )
        table.focus()
        if self.history.rows:
            self._select(self.history.rows[0].sha)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None and event.row_key.value:
            self._select(str(event.row_key.value))

    def action_toggle_raw(self) -> None:
        """Show or put away the text under the summary."""
        pane = self.query_one("#raw")
        pane.toggle_class(_HIDDEN)
        if not pane.has_class(_HIDDEN):
            self._load_raw()

    # ── selection ─────────────────────────────────────────────────────────────

    def _select(self, sha: str) -> None:
        self._sha = sha
        row = next(r for r in self.history.rows if r.sha == sha)
        if self.history.is_ready(sha):
            self._render(row)
            return
        # Reading a revision is about a second: say so, and do it off the UI
        # thread, so the list stays arrow-able instead of locking up.
        self.query_one("#detail", Static).update(
            Group(_heading(row), Text("\nreading this revision…", style="italic dim"))
        )
        self._read(sha)

    def _read(self, sha: str) -> Worker:
        return self.run_worker(lambda: self._read_in_background(sha), thread=True, exclusive=True)

    def _read_in_background(self, sha: str) -> None:
        self.history.changes(sha)
        if get_current_worker().is_cancelled or self._sha != sha:
            return
        row = next(r for r in self.history.rows if r.sha == sha)
        self.call_from_thread(self._render, row)

    def _render(self, row) -> None:
        # A read can outlive the screen — the app may close while a revision is
        # still being diffed — so the panel is written only if it is still there.
        try:
            detail = self.query_one("#detail", Static)
        except NoMatches:
            return
        detail.update(Group(_heading(row), _changes(self.history, row.sha)))
        if not self.query_one("#raw").has_class(_HIDDEN):
            self._load_raw()

    def _load_raw(self) -> None:
        text = self.history.raw(self._sha) or "(no textual change)"
        self.query_one("#raw-text", Static).update(_diff_text(text))


# ── rendering ─────────────────────────────────────────────────────────────────


def _short_author(author: str) -> str:
    """A committer as a column can show them: first name, or initials for a
    long one. The full name is on the detail panel, where there is room."""
    name = author.strip()
    if len(name) <= 14:
        return name
    first, _, rest = name.partition(" ")
    return f"{first} {rest[0]}." if rest else first[:14]


def _commit_cell(row) -> Text:
    """The subject, with any release tags in front of it."""
    cell = Text()
    for tag in row.tags:
        cell.append(f" {tag} ", style="bold black on yellow")
        cell.append(" ")
    cell.append(row.subject)
    return cell


def _heading(row) -> Group:
    """What the commit says it did, then who did it — separated from each other."""
    return Group(
        Text(row.subject, style="bold"),
        Text.assemble(
            (row.author, "cyan"),
            _DOT,
            (row.day, "dim"),
            _DOT,
            (row.short_sha, "dim"),
            *((_DOT, (" ".join(row.tags), "bold yellow")) if row.tags else ()),
        ),
        Rule(style="dim"),
    )


def _changes(history: FileHistory, sha: str) -> Table | Text:
    """The vocabulary changes, one per line, each kind named and coloured."""
    if history.is_unreadable(sha):
        return Text("The ontology does not parse at this revision.", style="italic red")
    rows = history.changes(sha)
    if not rows:
        return Text(
            "No semantic change — the file was reformatted, not edited.",
            style="italic green",
        )
    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", width=11)
    table.add_column(width=11)
    table.add_column(ratio=1)
    for row in rows:
        word, colour = _KINDS[row.kind]
        table.add_row(
            Text(word, style=f"bold {colour}"),
            Text(row.entity.value, style="dim"),
            _change_name(row),
        )
    return table


def _change_name(row: Row) -> Text:
    """The readable name, the identifier beside it, and what moved."""
    if row.counted:
        where = f"  in {row.of_class}" if row.of_class else ""
        return Text.assemble((row.name, "bold"), (where, "dim"))
    if row.kind is ChangeKind.RENAMED:
        return Text.assemble((str(row.previous), "dim"), (" → ", "dim"), (row.name, "bold"))
    name = Text(row.name, style="bold")
    if row.curie and row.curie != row.name:
        name.append(f"  {row.curie}", style="dim")
    if row.detail:
        name.append(f"\n{' · '.join(row.detail)}", style="italic")
    return name


def _diff_text(text: str) -> Text:
    """The git hunk, with added and removed lines told apart by colour."""
    out = Text()
    for line in text.splitlines():
        style = ""
        if line.startswith("+") and not line.startswith("+++"):
            style = "green"
        elif line.startswith("-") and not line.startswith("---"):
            style = "red"
        elif line.startswith("@@"):
            style = "cyan"
        elif line.startswith(("diff ", "index ", "+++", "---")):
            style = "dim"
        out.append(line + "\n", style=style)
    return out


def run_history(history: FileHistory) -> None:  # pragma: no cover - interactive tty
    from ._run import run_app  # noqa: PLC0415

    run_app(HistoryScreen(history))
