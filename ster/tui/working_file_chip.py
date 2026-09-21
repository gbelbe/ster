"""The header's working-file control — the chip, and the menu it drops down.

Which file is writable used to be visible only as a filename in the window
title and as a lock glyph on the rows you could not edit; changing it meant
quitting. The chip states the answer where the eye already goes for it and
makes it a control:

    Working file ▾ leboncoin-2026-08-20.ttl · +2 context

The menu is the same overlay pattern as :mod:`ster.tui.context_menu` — an
``OptionList`` on the screen's overlay layer rather than a modal screen, so the
tree stays visible behind it and the choice reads as a change to what is on
screen rather than a detour away from it.
"""

from __future__ import annotations

from pathlib import Path

from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

# The chip is docked into a one-row header, so the name is the only part that
# can give: everything else in it is either a fixed label or a two-character
# badge. Below this many characters the name stops being recognisable at all.
_MIN_NAME_WIDTH = 12
_MENU_WIDTH = 52


def truncate_name(name: str, width: int) -> str:
    """Shorten *name* to *width*, keeping the start and the extension.

    The extension survives because it is often the only difference that matters
    between two files in one session — ``adeo.ttl`` next to ``adeo.rdf`` is the
    same ontology exported twice, and a plain right-truncation renders both as
    ``adeo…``.
    """
    if len(name) <= width:
        return name
    stem, dot, suffix = name.rpartition(".")
    if not dot:  # rpartition puts the *whole* string in the tail when there is no dot
        stem, suffix = name, ""
    tail = f"…{dot}{suffix}"
    keep = max(1, width - len(tail))
    return f"{stem[:keep]}{tail}"


class WorkingFileChip(Static):
    """The header control naming the writable file and opening the menu."""

    DEFAULT_CSS = """
    WorkingFileChip {
        dock: right;
        width: auto;
        padding: 0 1;
        color: $foreground;
    }
    /* Reads as actionable, and matches the footer's own hover treatment. */
    WorkingFileChip.-switchable:hover { background: $boost; }
    """

    class Pressed(Message):
        """The chip was clicked — the app opens the menu at its position."""

    def __init__(self, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._working: Path | None = None
        self._context_count = 0

    def update_files(self, working: Path | None, context_count: int) -> None:
        """Show *working* as the writable file, with *context_count* beside it."""
        self._working = working
        self._context_count = context_count
        self.set_class(self.switchable, "-switchable")
        self.update(self.render_text())

    @property
    def switchable(self) -> bool:
        """False when there is nothing to switch *to*.

        A caret on a menu whose only entry is the row you are already on is an
        affordance that does nothing, so a single-file session gets a plain
        label instead.
        """
        return self._working is not None and self._context_count > 0

    def render_text(self) -> str:
        if self._working is None:
            return ""
        name = truncate_name(self._working.name, self._name_width())
        if not self.switchable:
            return f"[dim]Working file[/dim] {name}"
        badge = f" [dim]· +{self._context_count} context[/dim]"
        return f"[dim]Working file[/dim] [$accent b]▾ {name}[/]{badge}"

    def _name_width(self) -> int:
        """How much of the filename fits beside the label and the badge.

        ``Widget.screen`` *raises* ``NoScreen`` when the widget is not mounted
        rather than returning None, and the chip is rendered once from
        ``on_mount`` before layout has settled — so the terminal width has to be
        asked for defensively, not truth-tested.
        """
        fixed = len("Working file ▾  · +N context") + len(str(self._context_count))
        try:
            width = self.screen.size.width
        except Exception:  # noqa: BLE001 — not mounted yet; assume a standard terminal
            width = 80
        return max(_MIN_NAME_WIDTH, width // 2 - fixed)

    def on_click(self) -> None:
        if self.switchable:
            self.post_message(self.Pressed())


class WorkingFileMenu(OptionList):
    """The drop-down layer listing every open file and its current role."""

    DEFAULT_CSS = """
    WorkingFileMenu {
        layer: overlay;
        display: none;
        width: 52;
        height: auto;
        max-height: 16;
        padding: 0 1;
        background: $background;
        border: round $primary;
        border-title-color: $primary;
        border-subtitle-color: $text-muted;
    }
    WorkingFileMenu:focus { border: round $primary; border-title-color: $primary; }
    WorkingFileMenu.open { display: block; }
    WorkingFileMenu > .option-list--option-highlighted {
        background: $secondary;
        color: auto;
        text-style: bold;
    }
    """

    BINDINGS = [Binding("escape", "close", "Close")]

    class Chosen(Message):
        """A file was picked — the app decides whether that means a switch."""

        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    def __init__(self, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._paths: list[Path] = []

    def show(self, working: Path, loaded: list[Path], anchor: tuple[int, int]) -> None:
        """Populate from *loaded*, position under *anchor*, reveal and focus."""
        self.clear_options()
        self._paths = list(loaded)
        self.border_title = "Switch working file"
        # Stated up front rather than discovered afterwards: a switch re-parses
        # the chosen file, which on a large ontology is the same wait that
        # opening it cost, and an unexplained pause reads as a hang.
        self.border_subtitle = "switching re-reads the chosen file"
        self.add_options([Option(self._row(path, working)) for path in loaded])
        self.styles.offset = self._position(anchor, len(loaded))
        self.add_class("open")
        self.highlighted = loaded.index(working) if working in loaded else None
        self.focus()

    def _row(self, path: Path, working: Path) -> str:
        if path == working:
            return f"[$accent b]✎ {path.name}[/]  [dim]writable[/dim]"
        return f"🔒 {path.name}  [dim]context[/dim]"

    def _position(self, anchor: tuple[int, int], count: int) -> tuple[int, int]:
        """Hang under the chip, clamped so the whole menu stays on screen."""
        height = count + 4  # + border, padding, subtitle
        size = self.screen.size
        x, y = anchor
        x = max(0, min(x, size.width - _MENU_WIDTH))
        y = y + 1 if y + 1 + height <= size.height else max(0, y - height)
        return x, y

    def close(self) -> None:
        self.remove_class("open")

    def action_close(self) -> None:
        self.close()

    def on_blur(self) -> None:
        """Clicking away dismisses, like the right-click menu."""
        self.close()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.close()
        if event.option_index < len(self._paths):
            self.post_message(self.Chosen(self._paths[event.option_index]))
