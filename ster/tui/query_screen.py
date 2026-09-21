"""A SPARQL query workspace for the New-TUI.

An editor above a results table. Ctrl+R runs the query against the *in-memory*
taxonomy (so unsaved edits are reflected), Ctrl+P loads a built-in preset, Esc
closes. The engine is reached only through :mod:`ster.tui.query`.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from typing import Final, Literal

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

# The editor's id, and the selector built from it. Declared once so the widget
# can be renamed in a single place — and so the four lookups below cannot drift
# apart from the id used to construct it.
_EDITOR_ID = "query-editor"
_EDITOR = f"#{_EDITOR_ID}"


# Every notify from this screen is advisory — nothing here fails an action,
# it declines one and says why. Named once so the ratchet does not count the
# word six times and so a future severity change is one edit.
# Typed as the literal, not str: Textual's notify() takes a Literal, so a
# plain str constant is rejected at the call site.
_WARN: Literal["warning"] = "warning"
_BROWSER_FAIL: Final = "Could not open a browser"


class QueryScreen(Screen[None]):
    """SPARQL editor over a results table. Runs against the live taxonomy."""

    DEFAULT_CSS = """
    QueryScreen { background: $surface; layers: base popup; }
    #query-box { padding: 1 2; }
    #query-editor { height: 45%; border: round $primary; }
    #query-status { height: 1; color: $text-muted; padding: 0 1; }
    #query-results { height: 1fr; border: round $primary; }
    #query-hint { height: 1; color: $text-muted; padding: 0 1; text-style: dim; }
    #ac-popup { layer: popup; width: auto; max-height: 10; border: round $accent;
                background: $panel; }
    """

    BINDINGS = [
        Binding("ctrl+r", "run", "Run"),
        Binding("ctrl+p", "presets", "Presets"),
        # NOT ctrl+m: terminals send carriage return for it, so it is
        # indistinguishable from Enter and the binding never fires.
        Binding("ctrl+g", "map", "Map"),
        # ctrl+y rather than a shifted ctrl+g: terminals do not distinguish
        # ctrl+G from ctrl+shift+G, so the second binding would never fire.
        Binding("ctrl+y", "graph", "Graph"),
        Binding("ctrl+t", "timeline", "Timeline"),
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
        self._located = 0  # rows of the last run that carry coordinates
        self._graphable = False  # last run returned triples the graph can draw
        self._dated = 0  # rows of the last run that carry a date
        self._status_line = ""  # last status rendered, for tests/introspection
        # Indirected so tests can capture the URL instead of launching a browser.
        # ``webbrowser.open`` rather than ``App.open_url``: the latter's driver
        # indirection silently no-ops here, as detail_view.py already documents.
        self._open: Callable[[str], object] = webbrowser.open
        # Indirected for the same reason as _open: tests drive both without a
        # live server or a browser.
        self._server_ok: Callable[[], bool] = query.server_is_running

    def compose(self) -> ComposeResult:
        with Vertical(id="query-box"):
            yield SparqlEditor(
                query.starter_query(self._index), suggest_fn=self._suggest, id=_EDITOR_ID
            )
            yield Static("", id="query-status")
            yield DataTable(id="query-results")
            yield Static(self._trigger_hint(), id="query-hint")
        yield Footer()

    @property
    def _editor(self) -> TextArea:
        """The SPARQL editor. The only place its selector is used."""
        return self.query_one(_EDITOR, TextArea)

    def _example_prefix(self) -> str:
        """The file's own prefix (with the colon) — the one the user most likely completes."""
        return f"{query.main_prefix(self._index)}:" if query.main_prefix(self._index) else "prefix:"

    def _trigger_hint(self) -> str:
        """The bottom hint line: how to trigger each kind of autocomplete for this file."""
        pfx = self._example_prefix()
        return (
            f"autocomplete —  [b]{pfx}[/b] entities · [b]?[/b]var variables · [b]word[/b] keywords"
            "     ↑↓ move · ⏎/tab accept · esc close popup"
        )

    def _suggest(self, text: str, cursor: int) -> tuple[list[Completion], int]:
        """Adapt the pure completion logic for the editor: completions + the replace start."""
        prefixes = set(self._index.prefixes)
        return suggest(text, cursor, self._index, SPARQL_KEYWORDS), replace_start(
            text, cursor, prefixes
        )

    def on_mount(self) -> None:
        editor = self._editor
        editor.border_title = "SPARQL  (ctrl+r run · ctrl+p presets · ctrl+g map · ctrl+y graph · ctrl+t timeline · esc close)"
        self.query_one("#query-results", DataTable).border_title = "Results"
        editor.focus()

    def action_run(self) -> None:
        """Execute the editor's query against the session graph and render its result."""
        text = self._editor.text
        self._show_result(query.run_on_graph(self._graph, text))

    def _show_result(self, result: QueryResult) -> None:
        self._last_result = result
        table = self.query_one("#query-results", DataTable)
        table.clear(columns=True)
        status = self.query_one("#query-status", Static)
        if result.error:
            self._status_line = result.error
            status.update(f"[red]{result.error}[/red]")
            return
        if result.columns:
            table.add_columns(*result.columns)
        for row in result.rows:
            table.add_row(*row)
        self._status_line = f"{result.query_type} · {len(result.rows)} row(s){self._view_hint(result)}{self._time_hint(result)}"
        status.update(self._status_line)

    def _view_hint(self, result: QueryResult) -> str:
        """What the result can be opened as, and what it cannot.

        Both views are named on every run, the unavailable one dimmed with its
        reason, rather than the available one appearing and the other staying
        invisible — a control you only see when it works is one you never learn
        exists. Kept to the status line deliberately: the query screen is a
        refine-and-rerun loop, and a modal on every run would interrupt it.
        """
        self._located = query.located_count(self._graph, result)
        self._graphable = query.is_graphable(result)
        parts = [
            f"{self._located} mappable · ctrl+g map"
            if self._located
            else "[dim]no coordinates · map unavailable[/dim]",
            "ctrl+y graph"
            if self._graphable
            else f"[dim]{result.query_type} returns rows, not triples · "
            "graph needs CONSTRUCT[/dim]",
        ]
        return " · " + " · ".join(parts)

    def _time_hint(self, result: QueryResult) -> str:
        """The trailing 'N can be dated' note, or nothing when none can be.

        Beside the geo hint rather than instead of it: a result can be both, and
        a reader who is told only about the map will not look for the frieze.
        """
        self._dated = query.dated_count(self._graph, result)
        if not self._dated:
            return ""
        return f" · {self._dated} datable · ctrl+t for timeline"

    def action_timeline(self) -> None:
        """Open the timeline page on the query that produced the current results."""
        if self._last_result is None or not self._dated:
            self.notify("No temporal data in these results", severity=_WARN)
            return
        if not self._server_ok():
            self.notify(query.server_unavailable_reason(), severity=_WARN)
            return
        url = query.timeline_url(self._editor.text)
        if not self._open(url):
            self.notify(_BROWSER_FAIL, severity=_WARN)

    def action_map(self) -> None:
        """Open the map page on the query that produced the current results."""
        if self._last_result is None or not self._located:
            self.notify("No geographic data in these results", severity=_WARN)
            return
        if not self._server_ok():
            self.notify(query.server_unavailable_reason(), severity=_WARN)
            return
        url = query.map_url(self._editor.text)
        if not self._open(url):
            self.notify(_BROWSER_FAIL, severity=_WARN)

    def action_graph(self) -> None:
        """Open the graph view on the triples this query produced."""
        if self._last_result is None or not self._graphable:
            self.notify(
                "The graph view draws triples — run a CONSTRUCT or DESCRIBE",
                severity=_WARN,
            )
            return
        if not self._server_ok():
            self.notify(query.server_unavailable_reason(), severity=_WARN)
            return
        if not self._open(query.graph_url(self._editor.text)):
            self.notify(_BROWSER_FAIL, severity=_WARN)

    def action_presets(self) -> None:
        presets = query.presets()
        options = [(p.label, str(i)) for i, p in enumerate(presets)]

        def _on_pick(value: str | None) -> None:
            if value is not None:
                self._apply_preset(presets[int(value)].sparql)

        self.app.push_screen(PickerModal("Preset queries", options), _on_pick)

    def _apply_preset(self, sparql: str) -> None:
        self._editor.text = sparql

    def action_close(self) -> None:
        self.dismiss()
