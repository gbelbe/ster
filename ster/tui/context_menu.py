"""A right-click context menu — an overlay widget anchored at the click.

Modelled on harlequin: this is **not** a modal screen (those hide the TUI behind
an opaque layer). It's an ``OptionList`` mounted on the screen's *overlay* layer,
so the tree stays fully visible behind it. It pops up at the click, flips up when
there's no room below, and is dismissed by selecting an item, Esc, or clicking
away (focus loss). Selecting posts :class:`ContextMenu.Chosen`; the app maps the
action to a flow.
"""

from __future__ import annotations

from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

_MENU_WIDTH = 44


class ContextMenu(OptionList):
    """Cursor-anchored overlay menu of (label, action) quick actions."""

    DEFAULT_CSS = """
    ContextMenu {
        layer: overlay;
        display: none;
        width: 44;
        height: auto;
        max-height: 18;
        padding: 0 1;
        background: $surface;
        border: round $primary;
        border-title-color: $primary;
    }
    ContextMenu.open { display: block; }
    ContextMenu > .option-list--option-highlighted {
        background: $secondary;
        color: auto;
        text-style: bold;
    }
    """

    BINDINGS = [Binding("escape", "close", "Close")]

    class Chosen(Message):
        """Posted when the user picks an action from the menu."""

        def __init__(self, action: str) -> None:
            self.action = action
            super().__init__()

    def __init__(self, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._items: list[tuple[str, str]] = []

    def show(
        self, title: str, items: list[tuple[str, str]], anchor: tuple[int, int] | None
    ) -> None:
        """Populate, position at *anchor*, reveal, and focus the menu."""
        self.clear_options()
        self._items = list(items)
        self.border_title = title
        self.add_options([Option(label) for label, _ in items])
        self.styles.offset = self._position(anchor, len(items))
        self.add_class("open")
        self.highlighted = 0
        self.focus()

    def _position(self, anchor: tuple[int, int] | None, count: int) -> tuple[int, int]:
        """Anchor at the click, flipping up / clamping so it stays on-screen."""
        width, height = _MENU_WIDTH, count + 4  # + border/padding
        size = self.screen.size
        if anchor is None:  # keyboard / fallback → centre
            return max(0, (size.width - width) // 2), max(0, (size.height - height) // 2)
        x, y = anchor
        y = y + 1 if y + 1 + height <= size.height else max(0, y - height)
        return min(x, max(0, size.width - width)), max(0, y)

    def close(self) -> None:
        self.remove_class("open")

    def action_close(self) -> None:
        self.close()
        trees = list(self.app.query("#tree"))
        if trees:
            trees[0].focus()  # Esc → return focus to the tree

    def on_blur(self) -> None:
        self.close()  # click / focus away dismisses the menu

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        action = self._items[event.option_index][1]
        self.close()
        self.post_message(self.Chosen(action))
