"""The semantic history of one ontology file, read as a drill-down.

Commits on the left, newest first, with release tags beside the ones they mark.
Selecting a commit shows what it did to the vocabulary; the raw git hunk sits
under it, collapsed, because the whole point is that the text is the escape
hatch rather than the first thing you read.

Diffing a revision costs about a second on a large ontology, so nothing is
computed until a row is selected, and :mod:`ster.history` keeps each result.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Static

from ster.history import FileHistory

_RAW_HIDDEN = "raw-hidden"


class HistoryScreen(App[None]):
    """Commit list beside the semantic view, with the raw diff under it."""

    CSS = """
    #commits { width: 46; border-right: solid $primary; }
    #panes { width: 1fr; }
    #semantic { height: 1fr; padding: 0 1; overflow-y: auto; }
    #raw { height: 40%; border-top: solid $primary; padding: 0 1; overflow: auto; }
    #raw.raw-hidden { display: none; }
    """

    BINDINGS = [
        Binding("r", "toggle_raw", "Raw diff"),
        Binding("escape,q", "quit", "Close"),
    ]

    def __init__(self, history: FileHistory) -> None:
        super().__init__()
        self.history = history
        self.title = f"Semantic history — {history.path}"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield DataTable(id="commits", cursor_type="row")
            with Vertical(id="panes"):
                yield Static("", id="semantic")
                yield Static("", id="raw", classes=_RAW_HIDDEN)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#commits", DataTable)
        table.add_columns("when", "commit")
        for row in self.history.rows:
            table.add_row(row.day, _label(row), key=row.sha)
        table.focus()
        if self.history.rows:
            self._show(self.history.rows[0].sha)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None and event.row_key.value:
            self._show(str(event.row_key.value))

    def action_toggle_raw(self) -> None:
        """Show or put away the text under the summary."""
        raw = self.query_one("#raw", Static)
        raw.toggle_class(_RAW_HIDDEN)
        if not raw.has_class(_RAW_HIDDEN):
            self._fill_raw()

    def _show(self, sha: str) -> None:
        self._sha = sha
        self.query_one("#semantic", Static).update(self.history.semantic(sha))
        if not self.query_one("#raw", Static).has_class(_RAW_HIDDEN):
            self._fill_raw()

    def _fill_raw(self) -> None:
        text = self.history.raw(self._sha)
        self.query_one("#raw", Static).update(text or "(no textual change)")


def _label(row) -> str:
    """The commit's subject, with any release tags it carries in front of it."""
    tags = " ".join(f"[{t}]" for t in row.tags)
    return f"{tags} {row.subject}".strip()


def run_history(history: FileHistory) -> None:  # pragma: no cover - interactive tty
    HistoryScreen(history).run()
