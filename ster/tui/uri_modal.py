"""A shared URI editor whose namespace prefix is locked.

Used by every add / rename flow that produces a URI. The full URI is shown in a
single field, but only the *fragment* after the last ``#`` / ``/`` is editable —
the namespace prefix is protected (cursor can't enter it, deletes stop at the
boundary, selection and paste are clamped). On open the fragment is preselected
so typing replaces it.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, Static
from textual.widgets.input import Selection

from .modal import ModalBase


class FragmentInput(Input):
    """An ``Input`` whose leading *prefix* (the namespace) cannot be edited."""

    def __init__(self, prefix: str, fragment: str = "", **kwargs: object) -> None:
        self._prefix = prefix  # set before super().__init__ — validators read it
        super().__init__(value=prefix + fragment, **kwargs)  # type: ignore[arg-type]

    @property
    def fragment(self) -> str:
        """The editable part — everything after the locked namespace prefix."""
        return self.value[len(self._prefix) :]

    def on_mount(self) -> None:
        # Preselect the fragment so the first keystroke replaces it.
        self.selection = Selection(len(self._prefix), len(self.value))

    # ── prefix protection ──────────────────────────────────────────────────────
    def validate_value(self, value: str) -> str:
        """Never let the namespace prefix be lost (paste / select-all safety net).

        Cursor + selection clamping keep edits inside the fragment, so the only way
        here is a whole-value replacement (e.g. select-all then type); re-prepending
        the prefix is then exactly right.
        """
        if self._prefix and not value.startswith(self._prefix):
            return self._prefix + value
        return value

    def validate_selection(self, selection: Selection) -> Selection:
        """Clamp any selection (and the cursor) into the editable fragment."""
        floor = len(self._prefix)
        return Selection(max(selection.start, floor), max(selection.end, floor))

    def action_home(self, select: bool = False) -> None:
        self.cursor_position = len(self._prefix)  # "home" = fragment start, not URI start

    def action_select_all(self) -> None:
        self.selection = Selection(len(self._prefix), len(self.value))  # fragment only

    def action_delete_left(self) -> None:
        if self.cursor_position > len(self._prefix) or self.selection.start != self.selection.end:
            super().action_delete_left()


class UriModal(ModalBase[str | None]):
    """Edit a URI's fragment; dismiss with the full URI, or ``None`` if empty/cancel."""

    DEFAULT_CSS = """
    #uri-box { width: 70%; }
    #uri-input { border: round $primary; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, prefix: str, fragment: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._prefix = prefix
        self._fragment = fragment

    def compose(self) -> ComposeResult:
        with Vertical(id="uri-box", classes="modal-box"):
            yield FragmentInput(self._prefix, self._fragment, id="uri-input")
            yield Static("enter  save     esc  cancel", classes="modal-footer")

    def on_mount(self) -> None:
        self.query_one("#uri-box").border_title = self._prompt
        self.query_one(FragmentInput).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        field = self.query_one(FragmentInput)
        # An empty fragment means "nothing entered" → treat like cancel.
        self.dismiss(field.value if field.fragment.strip() else None)

    def action_cancel(self) -> None:
        self.dismiss(None)
