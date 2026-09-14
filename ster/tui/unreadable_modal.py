"""The modal that stands between a file ster could not model and an empty tree.

A load that recognises nothing is indistinguishable, on screen, from a file that
genuinely holds nothing — so the browser never renders that tree. This says what
was read, which type went undeclared, and offers to declare it. Opening anyway
stays available: inspecting a file ster cannot model is a legitimate thing to
want, it just has to be a choice rather than a silent default.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Button, Static

from ..store import Unreadable, declaration_turtle, describe_unreadable, type_lines
from .hint_bar import Hint
from .modal import ModalBase

_MAX_LISTED_TYPES = 5
_CANCEL = "cancel"


class UnreadableModal(ModalBase[str | None]):
    """Blocks the browser on an empty model; dismisses with a choice or None to cancel."""

    DECLARE = "declare"
    OPEN = "open"

    DEFAULT_CSS = """
    #unreadable-box { width: 80%; }
    #unreadable-box .turtle { color: $success; }
    #unreadable-box .undeclared { color: $warning; }
    """

    BINDINGS = [Binding("escape", _CANCEL, "Cancel")]

    def __init__(self, unreadable: Unreadable, name: str) -> None:
        super().__init__()
        self._unreadable = unreadable
        self._file_name = name

    def compose(self) -> ComposeResult:
        with Vertical(id="unreadable-box", classes="modal-box -danger"):
            yield Static(describe_unreadable(self._unreadable, self._file_name))
            yield from self._type_lines()
            yield from self._fix_lines()
            if self._unreadable.fixable:
                yield Button(self._declare_label(), id=self.DECLARE)
            yield Button("Open anyway (nothing will be shown)", id=self.OPEN)

    def _type_lines(self) -> ComposeResult:
        lines = type_lines(self._unreadable)
        if not lines:
            return
        yield Static("Used as a type, but never declared:")
        for line in lines[:_MAX_LISTED_TYPES]:
            yield Static(line, classes="undeclared")
        hidden = len(lines) - len(lines[:_MAX_LISTED_TYPES])
        if hidden > 0:
            yield Static(f"…and {hidden} more.", classes="undeclared")

    def _fix_lines(self) -> ComposeResult:
        turtle = declaration_turtle(self._unreadable)
        if not turtle:
            return
        yield Static("Declaring them would let ster read the file:")
        for line in turtle.splitlines():
            yield Static(line, classes="turtle")

    def _declare_label(self) -> str:
        count = len(self._unreadable.undeclared_types)
        return f"Declare {count} missing type(s) and reopen"

    def footer_hints(self) -> list[Hint]:
        return [Hint("⏎", "choose"), Hint("esc", _CANCEL, _CANCEL)]

    def on_mount(self) -> None:
        self.query_one("#unreadable-box").border_title = f"ster cannot read {self._file_name}"
        # DOMQuery.first() raises NoMatches on an empty query rather than
        # returning None, so the `is not None` guard this replaces could never
        # run — and on_mount fires before the children are guaranteed composed,
        # so the query really can be empty. That crashed the modal on open under
        # load, which is a worse outcome than not moving the focus.
        buttons = self.query(Button)
        if buttons:
            buttons.first().focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def action_cancel(self) -> None:
        self.dismiss(None)
