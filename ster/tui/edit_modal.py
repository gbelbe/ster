"""A reusable modal text editor for the Textual TUI.

A centred overlay with a single prefilled ``Input``: Enter submits the new
value, Esc cancels. ``push_screen(EditModal(...), callback)`` delivers the value
(or ``None`` on cancel). This is the shared building block for every text edit
(labels, comments, definitions, notes, …) across the detail blocks.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, Static

from .modal import ModalBase


class EditModal(ModalBase[str | None]):
    """Modal text input. Returns the entered value on submit, or None on cancel."""

    DEFAULT_CSS = "#edit-box { width: 60%; }"  # chrome comes from ModalBase

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, value: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._value = value

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-box", classes="modal-box"):
            yield Input(value=self._value, id="edit-input")
            yield Static("enter  save     esc  cancel", classes="modal-footer")

    def on_mount(self) -> None:
        self.query_one("#edit-box").border_title = self._prompt
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)
