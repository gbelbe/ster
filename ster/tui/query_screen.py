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
from ster.sparql_query import SPARQL_KEYWORDS, QueryResult

from . import query
from .picker_modal import PickerModal
from .sparql_complete import Completion, replace_start, suggest
from .sparql_editor import SparqlEditor


class QueryScreen(Screen[None]):
    """SPARQL editor over a results table. Runs against the live taxonomy."""

    DEFAULT_CSS = """
    QueryScreen { background: $surface; layers: base popup; }
    #query-box { padding: 1 2; }
    #query-editor { height: 45%; border: round $primary; }
    #query-status { height: 1; color: $text-muted; padding: 0 1; }
    #query-results { height: 1fr; border: round $primary; }
    #ac-popup { layer: popup; width: auto; max-height: 10; border: round $accent;
                background: $panel; }
    """

    BINDINGS = [
        Binding("ctrl+r", "run", "Run"),
        Binding("ctrl+p", "presets", "Presets"),
        Binding("escape", "close", "Close"),
    ]

    def __init__(self, tax: Taxonomy) -> None:
        super().__init__()
        self._tax = tax
        # Build the graph once and reuse it for the index and every run — a large ontology
        # is otherwise re-serialised on each query. The screen is modal (no editing while
        # open), so the graph stays valid for the session.
        self._graph = query.build_graph(tax)
        self._index = query.build_entity_index(tax, graph=self._graph)
        self._last_result: QueryResult | None = None  # last run, for tests/introspection

    def compose(self) -> ComposeResult:
        with Vertical(id="query-box"):
            yield SparqlEditor(
                query.starter_query(self._index), suggest_fn=self._suggest, id="query-editor"
            )
            yield Static("", id="query-status")
            yield DataTable(id="query-results")
        yield Footer()

    def _suggest(self, text: str, cursor: int) -> tuple[list[Completion], int]:
        """Adapt the pure completion logic for the editor: completions + the replace start."""
        prefixes = set(self._index.prefixes)
        return suggest(text, cursor, self._index, SPARQL_KEYWORDS), replace_start(
            text, cursor, prefixes
        )

    def on_mount(self) -> None:
        editor = self.query_one("#query-editor", TextArea)
        editor.border_title = "SPARQL  (ctrl+r run · ctrl+p presets · esc close)"
        self.query_one("#query-results", DataTable).border_title = "Results"
        editor.focus()

    def action_run(self) -> None:
        """Execute the editor's query against the session graph and render its result."""
        text = self.query_one("#query-editor", TextArea).text
        self._show_result(query.run_on_graph(self._graph, text))

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
