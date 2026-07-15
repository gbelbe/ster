"""A Textual ``TextArea`` with a native autocomplete popup for the query editor.

The editor is decoupled from SPARQL: it is handed a *suggest_fn* that, given the
text and the flat cursor index, returns ``(completions, replace_start)`` (see
:mod:`ster.tui.sparql_complete`). It renders those in a native ``OptionList``
anchored at the cursor; ↑↓ move the highlight, Enter/Tab accept, Esc dismisses,
and any other key edits normally and refreshes the list. Focus never leaves the
editor — the popup is a passive display the editor drives.

Requires its screen to declare a ``popup`` layer (``layers: base popup;``).
"""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual import events
from textual.widgets import OptionList, TextArea
from textual.widgets.option_list import Option

from .sparql_complete import Completion

SuggestFn = Callable[[str, int], "tuple[list[Completion], int]"]

_KIND_STYLE = {
    "keyword": "bold",
    "variable": "bright_blue",
    "class": "cyan",
    "individual": "green",
    "property": "magenta",
    "concept": "yellow",
}


class SparqlEditor(TextArea):
    """A TextArea that offers completions from *suggest_fn* in a cursor-anchored popup."""

    def __init__(self, text: str = "", *, suggest_fn: SuggestFn, **kwargs: object) -> None:
        super().__init__(text, **kwargs)  # type: ignore[arg-type]
        self._suggest_fn = suggest_fn
        self._popup: OptionList | None = None
        self._completions: list[Completion] = []
        self._replace_start = 0
        # Best-effort syntax highlighting: no maintained tree-sitter SPARQL grammar exists,
        # but the built-in SQL grammar colours the shared keywords / variables / operators
        # well enough (and SPARQL '?var' maps to SQL's parameter). Editing must always work.
        try:
            self.language = "sql"
        except Exception:  # noqa: BLE001 — highlighting is optional; never block editing
            pass

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        popup = OptionList(id="ac-popup")
        popup.can_focus = False
        popup.display = False
        popup.styles.layer = "popup"
        popup.styles.max_height = 10
        popup.styles.width = "auto"
        self.screen.mount(popup)
        self._popup = popup

    def _popup_open(self) -> bool:
        return self._popup is not None and self._popup.display

    # ── keys ──────────────────────────────────────────────────────────────────

    async def _on_key(self, event: events.Key) -> None:
        if self._popup_open():
            if event.key in ("enter", "tab"):
                event.prevent_default()
                event.stop()
                self._accept()
                return
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._close()
                return
            if event.key in ("up", "down"):
                event.prevent_default()
                event.stop()
                self._move(1 if event.key == "down" else -1)
                return
        await super()._on_key(event)
        self.call_after_refresh(self._refresh)  # recompute after the edit/cursor move lands

    # ── popup state ───────────────────────────────────────────────────────────

    def _loc_to_index(self, location: tuple[int, int]) -> int:
        row, col = location
        lines = self.text.split("\n")
        return sum(len(line) + 1 for line in lines[:row]) + col

    def _index_to_loc(self, index: int) -> tuple[int, int]:
        prefix = self.text[:index]
        return prefix.count("\n"), index - (prefix.rfind("\n") + 1)

    def _cursor_index(self) -> int:
        return self._loc_to_index(self.cursor_location)

    def _refresh(self) -> None:
        if self._popup is None:
            return
        text = self.text
        cursor = self._cursor_index()
        self._completions, self._replace_start = self._suggest_fn(text, cursor)
        if not self._completions:
            self._close()
            return
        self._popup.clear_options()
        self._popup.add_options([self._option(c) for c in self._completions])
        self._popup.highlighted = 0
        offset = self.cursor_screen_offset
        self._popup.styles.offset = (offset.x, offset.y + 1)  # just below the caret
        self._popup.display = True

    @staticmethod
    def _option(comp: Completion) -> Option:
        text = Text(comp.label)
        text.append(f"  {comp.kind}", style="dim")
        return Option(text)

    def _move(self, delta: int) -> None:
        popup = self._popup
        if popup is None or not popup.option_count:
            return
        cur = popup.highlighted or 0
        popup.highlighted = (cur + delta) % popup.option_count

    def _accept(self) -> None:
        popup = self._popup
        if popup is None or popup.highlighted is None:
            return
        comp = self._completions[popup.highlighted]
        start = self._index_to_loc(self._replace_start)
        self.replace(comp.insert, start, self.cursor_location)
        self.move_cursor(self._index_to_loc(self._replace_start + comp.caret()))
        self._close()

    def _close(self) -> None:
        if self._popup is not None:
            self._popup.display = False
