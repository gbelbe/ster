"""A reusable modal entity picker for the Textual TUI.

Relation actions (add a superclass, re-parent, set a type, relate concepts, …)
need the user to choose an existing entity. ``push_screen(PickerModal(...),
callback)`` shows the candidates and returns the chosen value (a URI), or
``None`` on cancel.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class PickerModal(ModalScreen[str | None]):
    """Modal single-select list of (label, value) candidates."""

    DEFAULT_CSS = """
    PickerModal { align: center middle; }
    #picker-box {
        width: 70%;
        max-width: 90;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }
    #picker-box Label { margin-bottom: 1; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, options: list[tuple[str, str]]) -> None:
        super().__init__()
        self._prompt = prompt
        self._options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Label(self._prompt)
            yield OptionList(*[Option(label) for label, _ in self._options])

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._options[event.option_index][1])

    def action_cancel(self) -> None:
        self.dismiss(None)
