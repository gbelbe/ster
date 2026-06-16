"""A right-click context menu for tree nodes.

``push_screen(ContextMenu(title, items), callback)`` shows a compact list of
quick actions for the right-clicked entity and returns the chosen *action*
string (or ``None`` on cancel). The app maps that action to a flow (the same
ones the detail-pane rows use); see ``OntologyApp.open_context_menu``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class ContextMenu(ModalScreen[str | None]):
    """Modal list of (label, action) quick actions; dismisses with the action."""

    DEFAULT_CSS = """
    ContextMenu { align: center middle; }
    #ctx-box {
        width: auto;
        min-width: 36;
        max-width: 70;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        background: $surface;
        border: round $primary;
        border-title-color: $primary;
    }
    #ctx-list { height: auto; max-height: 16; background: $surface; }
    #ctx-box .modal-footer { color: $text-muted; margin-top: 1; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, items: list[tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._items = items

    def compose(self) -> ComposeResult:
        with Vertical(id="ctx-box"):
            yield OptionList(*(Option(label) for label, _ in self._items), id="ctx-list")
            yield Static("↑↓ move    enter run    esc cancel", classes="modal-footer")

    def on_mount(self) -> None:
        self.query_one("#ctx-box").border_title = f"Actions — {self._title}"
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._items[event.option_index][1])

    def action_cancel(self) -> None:
        self.dismiss(None)
