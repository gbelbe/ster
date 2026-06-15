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
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class WrappingOptionList(OptionList):
    """An ``OptionList`` whose up/down wrap around the ends (fast access to the far end)."""

    def action_cursor_down(self) -> None:
        if self.option_count and self.highlighted == self.option_count - 1:
            self.highlighted = 0  # past the last → wrap to the first
        else:
            super().action_cursor_down()

    def action_cursor_up(self) -> None:
        if self.option_count and self.highlighted == 0:
            self.highlighted = self.option_count - 1  # before the first → wrap to the last
        else:
            super().action_cursor_up()


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
        border: round $primary;
        border-title-color: $primary;
    }
    #picker-box .modal-footer { color: $text-muted; margin-top: 1; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, options: list[tuple[str, str]]) -> None:
        super().__init__()
        self._prompt = prompt
        self._options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield WrappingOptionList(*[Option(label) for label, _ in self._options])
            yield Static("↑↓ move    enter  select     esc  cancel", classes="modal-footer")

    def on_mount(self) -> None:
        self.query_one("#picker-box").border_title = self._prompt
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._options[event.option_index][1])

    def action_cancel(self) -> None:
        self.dismiss(None)
