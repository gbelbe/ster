"""A full add / edit modal for an OWL class.

Collects everything basic about a class in one place: the URI (fragment-locked,
like :class:`~ster.tui.uri_modal.FragmentInput`) plus an ``rdfs:label`` and an
``rdfs:comment`` for every *configured* language. Dismisses with
``{"uri": str, "labels": {lang: value}, "comments": {lang: value}}`` (every
configured language present, empty when blank — so an edit can clear a value), or
``None`` on cancel / empty fragment.
"""

from __future__ import annotations

from collections.abc import Mapping

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Static

from .modal import ModalBase
from .uri_modal import FragmentInput


class ClassModal(ModalBase[dict | None]):
    """Add or edit a class: URI + rdfs:label / rdfs:comment per configured language."""

    DEFAULT_CSS = """
    #class-box { width: 80%; max-width: 90; max-height: 90%; }
    #class-box .cm-label { text-style: bold; margin-top: 1; }
    #class-box .cm-row { height: auto; }
    #class-box .cm-lang { width: 6; padding: 1 0 0 0; color: $text-muted; }
    #class-box Input { border: round $primary; }
    #class-box Button { margin-top: 1; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        prefix: str,
        fragment: str = "",
        langs: list[str],
        labels: Mapping[str, str] | None = None,
        comments: Mapping[str, str] | None = None,
        title: str = "New class",
    ) -> None:
        super().__init__()
        self._prefix = prefix
        self._fragment = fragment
        self._langs = langs or ["en"]
        self._labels = dict(labels or {})
        self._comments = dict(comments or {})
        self._title = title

    def compose(self) -> ComposeResult:
        self._uri = FragmentInput(self._prefix, self._fragment, id="cm-uri")
        self._label_inputs = {lg: Input(value=self._labels.get(lg, "")) for lg in self._langs}
        self._comment_inputs = {lg: Input(value=self._comments.get(lg, "")) for lg in self._langs}
        with VerticalScroll(id="class-box", classes="modal-box"):
            yield Static("URI", classes="cm-label")
            yield self._uri
            yield Static("rdfs:label", classes="cm-label")
            yield from self._lang_rows(self._label_inputs)
            yield Static("rdfs:comment", classes="cm-label")
            yield from self._lang_rows(self._comment_inputs)
            yield Button("Save", id="cm-save", variant="primary")
            yield Static("enter  save     esc  cancel", classes="modal-footer")

    def _lang_rows(self, inputs: dict[str, Input]) -> ComposeResult:
        for lg in self._langs:
            with Horizontal(classes="cm-row"):
                yield Static(f"[{lg}]", classes="cm-lang")
                yield inputs[lg]

    def on_mount(self) -> None:
        self.query_one("#class-box").border_title = self._title
        self._uri.focus()  # land on the URI fragment (preselected in edit mode)

    def _result(self) -> dict | None:
        if not self._uri.fragment.strip():
            return None  # a class needs a URI fragment
        return {
            "uri": self._uri.value,
            "labels": {lg: inp.value.strip() for lg, inp in self._label_inputs.items()},
            "comments": {lg: inp.value.strip() for lg, inp in self._comment_inputs.items()},
        }

    def _submit(self) -> None:
        result = self._result()
        if result is not None:
            self.dismiss(result)
        else:
            self.notify("A class needs a URI.", severity="warning")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)
