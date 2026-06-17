"""Centralised styling for every ster modal window.

All modal screens (edit / choice / picker / help) inherit :class:`ModalBase`, so
their chrome — the gentle dim that keeps the TUI visible behind them, the rounded
bordered ``.modal-box``, the danger accent, the footer hint, and buttons — lives
in **one place**. Change it here and every modal changes.

The app deliberately leaves the main ``Screen`` without a ``background`` so it
can't override a modal's translucent dim (which would make modals opaque and
hide the TUI).
"""

from __future__ import annotations

from typing import TypeVar

from textual.screen import ModalScreen

_R = TypeVar("_R")


class ModalBase(ModalScreen[_R]):
    """Base for ster modals: see-through dim + shared bordered-box chrome."""

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
    }
    ModalBase .modal-box.-danger {
        border: round $error;
        border-title-color: $error;
    }
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
