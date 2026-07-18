"""A filterable, multi-select modal built on Textual's native ``SelectionList``.

Bulk actions (e.g. "tag these individuals with a concept") need the user to pick
*several* entities at once. ``push_screen(MultiPickerModal(...), callback)`` shows
the candidates as a checklist and returns the list of chosen values, or ``None``
on cancel.

``space``/click toggles each row (native SelectionList behaviour); typing filters
the list; ``enter`` confirms the current ticks.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, SelectionList
from textual.widgets.selection_list import Selection

from .hint_bar import Hint
from .modal import ModalBase
from .picker_modal import rank_options


class MultiPickerModal(ModalBase[list[str] | None]):
    """Filterable checklist of ``(label, value)`` candidates; returns the ticked values."""

    DEFAULT_CSS = """
    #multi-box { width: 70%; max-height: 80%; }
    #multi-filter { border: none; padding: 0; margin-bottom: 1; background: $surface; }
    #multi-list { height: auto; max-height: 16; background: $surface; border: none; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "confirm", "Tag", show=False),
    ]

    def __init__(self, prompt: str, options: list[tuple[str, str]]) -> None:
        super().__init__()
        self._prompt = prompt
        self._options = options
        self._chosen: set[str] = set()  # persists ticks across filtering
        self._visible: list[tuple[str, str]] = list(options)

    def compose(self) -> ComposeResult:
        with Vertical(id="multi-box", classes="modal-box"):
            yield Input(placeholder="type to filter…", id="multi-filter")
            yield SelectionList[str](id="multi-list")

    def footer_hints(self) -> list[Hint]:
        return [
            Hint("type", "to filter"),
            Hint("␣", "tick"),
            Hint("⏎", "tag", "confirm"),
            Hint("esc", "cancel", "cancel"),
        ]

    def on_mount(self) -> None:
        self.query_one("#multi-box").border_title = self._prompt
        self._populate(self._options)
        self.query_one("#multi-filter", Input).focus()

    def _populate(self, ranked: list[tuple[str, str]]) -> None:
        self._visible = ranked
        sel = self.query_one(SelectionList)
        sel.clear_options()
        sel.add_options([Selection(label, value, value in self._chosen) for label, value in ranked])

    def on_input_changed(self, event: Input.Changed) -> None:
        self._remember()  # capture ticks/unticks made before this filter change
        self._populate(rank_options(self._options, event.value))

    def _remember(self) -> None:
        """Sync the visible list's tick state into the persistent chosen set — additions
        *and* removals — while leaving off-screen (filtered-out) ticks untouched."""
        try:
            selected = set(self.query_one(SelectionList).selected)
        except Exception:  # noqa: BLE001 — list not mounted yet
            return
        visible = {value for _label, value in self._visible}
        self._chosen = (self._chosen - visible) | selected

    def action_confirm(self) -> None:
        self._remember()
        self.dismiss(sorted(self._chosen))

    def action_cancel(self) -> None:
        self.dismiss(None)
