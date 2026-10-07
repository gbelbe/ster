"""Selecting text with the mouse copies it, anywhere in the TUI.

Generic by construction: Textual's Screen posts ``TextSelected`` after every
mouse release, on every screen (dialogs included), and it bubbles to the app.
So one handler here covers every widget, and no widget has to opt in.

A plain click also ends in ``TextSelected`` — Textual clears the selection on a
click just before posting it — so the same handler takes the message down
again: something selected means copy and say so, nothing selected means hide.

``Input`` and ``TextArea`` keep their own selection and do not post the event.
They are left alone on purpose: selecting text in order to edit it is not a
request to copy it, and their Ctrl+C already works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from textual.widgets import Static

from ._state import _AppState

if TYPE_CHECKING:
    from textual.geometry import Offset
    from textual.timer import Timer

# Long enough to read, short enough not to sit over the text being read.
FLASH_SECONDS: Final[float] = 2.5
COPIED_MESSAGE: Final = "Copied to clipboard"


class CopiedFlash(Static):
    """The "copied" message, floated above whatever screen is showing.

    ``overlay: screen`` puts it above every other widget without needing a
    layer declared on each screen; ``constrain`` keeps it on screen when the
    mouse was released near an edge.
    """

    DEFAULT_CSS = """  # noqa: V101
    CopiedFlash {
        overlay: screen;
        position: absolute;
        constrain: inside inside;
        width: auto;
        height: 1;
        padding: 0 1;
        background: $success;
        color: $text;
    }
    """


class _CopyOnSelectMixin(_AppState):
    """Mixin: copy a mouse selection as soon as it is made, and say so beside it."""

    _flash_timer: Timer | None = None

    def on_text_selected(self, _event: Any) -> None:  # noqa: V105
        """After every mouse release: copy what is selected, or clear the message."""
        text = self.screen.get_selected_text()
        if not text:
            self._hide_copied_flash()
            return
        self._copy_text(text)
        self._show_copied_flash(self.mouse_position)

    def _copy_text(self, text: str) -> bool:
        """To the terminal's clipboard (OSC 52) and the local one; True if local worked."""
        from ..clipboard import copy_to_system_clipboard  # noqa: PLC0415

        self.copy_to_clipboard(text)
        return copy_to_system_clipboard(text)

    def _show_copied_flash(self, at: Offset) -> None:
        """Put the message just right of *at*, replacing any still showing."""
        self._hide_copied_flash()
        flash = CopiedFlash(COPIED_MESSAGE)
        flash.styles.offset = (at.x + 1, at.y)
        self.screen.mount(flash)
        self._flash_timer = self.set_timer(FLASH_SECONDS, self._hide_copied_flash)

    def _hide_copied_flash(self) -> None:
        if self._flash_timer is not None:
            self._flash_timer.stop()
            self._flash_timer = None
        for flash in self.screen.query(CopiedFlash):
            flash.remove()

    def action_clear_text_selection(self) -> None:  # noqa: V105
        """Escape while text is selected: drop the selection and the message."""
        self.screen.clear_selection()
        self._hide_copied_flash()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Claim Escape only while there is a selection to clear.

        Otherwise the binding stands aside and Escape reaches the focused widget
        exactly as before, so no existing Escape behaviour changes.
        """
        if action == "clear_text_selection":
            return bool(self.screen.selections) or bool(self.screen.query(CopiedFlash))
        if action == "open_agent":  # the key exists only while the talk-to-graph plugin is on
            from ster.plugins import talk_to_graph  # noqa: PLC0415

            return talk_to_graph.is_enabled()
        return super().check_action(action, parameters)  # type: ignore[misc]
