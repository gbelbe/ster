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
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ChoiceModal(ModalScreen[str | None]):
    """Modal list of options; dismisses with the chosen value or None on cancel."""

    DEFAULT_CSS = """
    ChoiceModal { align: center middle; }
    #choice-box {
        width: 70%;
        max-width: 90;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: round $primary;
        border-title-color: $primary;
    }
    #choice-box.-danger { border: round $error; border-title-color: $error; }
    #choice-box Button {
        width: 100%;
        margin-bottom: 1;
        border: none;
        background: $primary;
        color: $background;
    }
    #choice-box Button:hover { background: $secondary; }
    #choice-box Button:focus { text-style: reverse; }
    #choice-box .modal-footer { color: $text-muted; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, options: list[tuple[str, str]], danger: bool = False) -> None:
        super().__init__()
        self._prompt = prompt
        self._options = options
        self._danger = danger

    def compose(self) -> ComposeResult:
        with Vertical(id="choice-box", classes="-danger" if self._danger else None):
            for label, value in self._options:
                yield Button(label, id=f"opt-{value}")
            yield Static("↑↓ move    enter  choose     esc  cancel", classes="modal-footer")

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
