"""A SPARQL query workspace for the New-TUI.

An editor above a results table. Ctrl+R runs the query against the *in-memory*
taxonomy (so unsaved edits are reflected), Ctrl+P loads a built-in preset, Esc
closes. The engine is reached only through :mod:`ster.tui.query`.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Static, TextArea

from ster.model import Taxonomy
from ster.sparql_query import QueryResult

from . import query
from .picker_modal import PickerModal


class QueryScreen(Screen[None]):
    """SPARQL editor over a results table. Runs against the live taxonomy."""

    DEFAULT_CSS = """
    QueryScreen { background: $surface; }
    #query-box { padding: 1 2; }
    #query-editor { height: 45%; border: round $primary; }
    #query-status { height: 1; color: $text-muted; padding: 0 1; }
    #query-results { height: 1fr; border: round $primary; }
    """

    BINDINGS = [
        Binding("ctrl+r", "run", "Run"),
        Binding("ctrl+p", "presets", "Presets"),
        Binding("escape", "close", "Close"),
    ]

    def __init__(self, tax: Taxonomy) -> None:
        super().__init__()
        self._tax = tax
        self._last_result: QueryResult | None = None  # last run, for tests/introspection

    def compose(self) -> ComposeResult:
        with Vertical(id="query-box"):
            yield TextArea(query.DEFAULT_QUERY, id="query-editor")
            yield Static("", id="query-status")
            yield DataTable(id="query-results")
        yield Footer()

    def on_mount(self) -> None:
        editor = self.query_one("#query-editor", TextArea)
        editor.border_title = "SPARQL  (ctrl+r run · ctrl+p presets · esc close)"
        self.query_one("#query-results", DataTable).border_title = "Results"
        editor.focus()

    def action_run(self) -> None:
        """Execute the editor's query and render its result (inline — small ontologies)."""
        text = self.query_one("#query-editor", TextArea).text
        self._show_result(query.run(self._tax, text))

    def _show_result(self, result: QueryResult) -> None:
        self._last_result = result
        table = self.query_one("#query-results", DataTable)
        table.clear(columns=True)
        status = self.query_one("#query-status", Static)
        if result.error:
            status.update(f"[red]{result.error}[/red]")
            return
        if result.columns:
            table.add_columns(*result.columns)
        for row in result.rows:
            table.add_row(*row)
        status.update(f"{result.query_type} · {len(result.rows)} row(s)")

    def action_presets(self) -> None:
        presets = query.presets()
        options = [(p.label, str(i)) for i, p in enumerate(presets)]

        def _on_pick(value: str | None) -> None:
            if value is not None:
                self._apply_preset(presets[int(value)].sparql)

        self.app.push_screen(PickerModal("Preset queries", options), _on_pick)

    def _apply_preset(self, sparql: str) -> None:
        self.query_one("#query-editor", TextArea).text = sparql

    def action_close(self) -> None:
        self.dismiss()
