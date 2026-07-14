"""A reusable modal that asks the user to pick one option (or cancel).

Used for integrity-sensitive operations that aren't a plain yes/no — most
importantly deleting a class, where the user must choose what happens to its
subclasses and instances. ``push_screen(ChoiceModal(...), callback)`` returns
the chosen option's value, or ``None`` on cancel. Pass ``danger=True`` for
destructive confirmations to give the frame a red (``$error``) accent.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Button

from .hint_bar import Hint
from .modal import ModalBase


class ChoiceModal(ModalBase[str | None]):
    """Modal list of options; dismisses with the chosen value or None on cancel."""

    DEFAULT_CSS = "#choice-box { width: 70%; }"  # chrome (incl. -danger, buttons) from ModalBase

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, options: list[tuple[str, str]], danger: bool = False) -> None:
        super().__init__()
        self._prompt = prompt
        self._options = options
        self._danger = danger

    def compose(self) -> ComposeResult:
        classes = "modal-box -danger" if self._danger else "modal-box"
        with Vertical(id="choice-box", classes=classes):
            for label, value in self._options:
                yield Button(label, id=f"opt-{value}")

    def footer_hints(self) -> list[Hint]:
        # The options are already clickable buttons, so "move" / "choose" are informational.
        return [Hint("↑↓", "move"), Hint("⏎", "choose"), Hint("esc", "cancel", "cancel")]

    def on_mount(self) -> None:
        self.query_one("#choice-box").border_title = self._prompt
        first = self.query(Button).first()
        if first is not None:
            first.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        assert event.button.id is not None
        self.dismiss(event.button.id.removeprefix("opt-"))

    def action_cancel(self) -> None:
        self.dismiss(None)
