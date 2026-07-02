"""Centralised styling + chrome for every ster modal window.

All modal screens (edit / choice / picker / help / config …) inherit :class:`ModalBase`,
so their chrome — the gentle dim that keeps the TUI visible behind them, the rounded
bordered ``.modal-box``, the danger accent, the footer hint, buttons, the top-right
close ``✕`` and click-away-to-close — lives in **one place**. Change it here and every
modal changes.

The close button and click-away are wired with ``@on`` handlers (not ``on_mount`` /
``on_click``), so they fire for every modal even though subclasses override those
methods for their own content.

The app deliberately leaves the main ``Screen`` without a ``background`` so it
can't override a modal's translucent dim (which would make modals opaque and
hide the TUI).
"""

from __future__ import annotations

from typing import TypeVar

from textual import events, on
from textual.screen import ModalScreen
from textual.widgets import Static

_R = TypeVar("_R")


class _ModalClose(Static):
    """The top-right ✕ affordance; clicking it cancels (dismisses) the modal."""

    def __init__(self) -> None:
        super().__init__("✕", classes="modal-close")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.screen.dismiss(None)  # None = the universal "cancelled" result


class ModalBase(ModalScreen[_R]):
    """Base for ster modals: see-through dim + shared bordered-box chrome, plus a
    top-right close button and click-outside-to-close (both defined once, here)."""

    DEFAULT_CSS = """
    ModalBase {
        align: center middle;
        background: $background 60%;   /* harlequin's dim: TUI shows through, no border bleed */
    }
    ModalBase .modal-box {
        height: auto;
        max-width: 88;
        margin: 2 4;
        padding: 1 2;
        background: $background;
        border: round $primary;
        border-title-color: $primary;
        layers: base overlay;   /* the ✕ floats on 'overlay' so it costs no content row */
    }
    ModalBase .modal-box.-danger {
        border: round $error;
        border-title-color: $error;
    }
    /* Top-right ✕ — on the 'overlay' layer (so it takes no content row) docked to the
       box's right edge at the top; only the ✕ glyph is clickable. */
    ModalBase .modal-close {
        layer: overlay;
        dock: right;
        width: auto;
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    ModalBase .modal-close:hover { color: $error; text-style: bold; }
    ModalBase .modal-footer { color: $text-muted; margin-top: 1; }
    ModalBase Button {
        width: 100%;
        margin-bottom: 1;
        border: none;
        background: $primary;
        color: $background;
    }
    ModalBase Button:hover { background: $secondary; }
    ModalBase Button:focus { text-style: reverse; }
    """

    @on(events.Mount)
    def _add_close_button(self) -> None:
        """Mount the ✕ header into the modal box once it exists (runs for every
        subclass, regardless of their own on_mount)."""
        boxes = self.query(".modal-box")
        if boxes and not self.query(".modal-close"):
            boxes.first().mount(_ModalClose())

    @on(events.Click)
    def _dismiss_on_click_away(self, event: events.Click) -> None:
        """A click that lands on the dim outside the modal box cancels the modal. A
        click inside the box (that bubbled up here unhandled) is ignored."""
        boxes = self.query(".modal-box")
        if not boxes:
            return
        if not boxes.first().region.contains(event.screen_x, event.screen_y):
            self.dismiss(None)
