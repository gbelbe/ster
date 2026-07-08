"""Shared base for the "add / edit entity" modals.

Collects the parts every OWL entity form has in common: a fragment-locked URI
(:class:`~ster.tui.uri_modal.FragmentInput`) plus an ``rdfs:label`` and an
``rdfs:comment`` for every *configured* language, with Save / Esc handling. A
subclass adds its own fields via :meth:`_extra_fields` and merges them into the
result via :meth:`_augment_result`.

Dismisses with ``{"uri": str, "labels": {lang: value}, "comments": {lang: value}}``
(plus whatever a subclass adds), or ``None`` on cancel / empty fragment.
"""

from __future__ import annotations

from collections.abc import Mapping

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Static

from .modal import ModalBase
from .uri_modal import FragmentInput


class EntityFormModal(ModalBase[dict | None]):
    """URI + rdfs:label / rdfs:comment (per configured language) with Save / Cancel.

    Subclass hooks:
      * ``BOX_ID`` — the box's id (border title target); ``NEEDS_URI_MSG`` — warning
        shown on an empty fragment.
      * :meth:`_extra_fields` — yield extra widgets (rendered after the comments).
      * :meth:`_augment_result` — add subclass keys to the ``{uri, labels, comments}``.
    """

    BOX_ID = "entity-form-box"
    NEEDS_URI_MSG = "A URI is required."

    DEFAULT_CSS = """
    .entity-form { width: 70%; max-width: 64; max-height: 90%; }
    .entity-form .cm-label { text-style: bold; margin-top: 1; }
    .entity-form .cm-row { height: 3; }
    .entity-form .cm-lang { width: 5; height: 3; content-align: right middle; color: $text-muted; }
    /* Input / Select borders come from ModalBase (shared) — only widths here. */
    .entity-form Input { width: 1fr; }
    .entity-form Select { width: 1fr; }
    .entity-form .ef-save { margin-top: 1; width: auto; }
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
        title: str,
    ) -> None:
        super().__init__()
        self._prefix = prefix
        self._fragment = fragment
        self._langs = langs or ["en"]
        self._labels = dict(labels or {})
        self._comments = dict(comments or {})
        self._title = title

    def compose(self) -> ComposeResult:
        self._uri = FragmentInput(self._prefix, self._fragment, id="ef-uri")
        self._label_inputs = {
            lg: Input(value=self._labels.get(lg, ""), placeholder=f"label [{lg}]")
            for lg in self._langs
        }
        self._comment_inputs = {
            lg: Input(value=self._comments.get(lg, ""), placeholder=f"comment [{lg}]")
            for lg in self._langs
        }
        with VerticalScroll(id=self.BOX_ID, classes="modal-box entity-form"):
            yield Static("URI", classes="cm-label")
            yield self._uri
            yield Static("rdfs:label", classes="cm-label")
            yield from self._lang_rows(self._label_inputs)
            yield Static("rdfs:comment", classes="cm-label")
            yield from self._lang_rows(self._comment_inputs)
            yield from self._extra_fields()
            yield Button("Save", classes="ef-save", variant="primary")
            yield Static("enter  save     esc  cancel", classes="modal-footer")

    def _extra_fields(self) -> ComposeResult:
        """Override to yield subclass-specific widgets (rendered after the comments)."""
        return iter(())

    def _augment_result(self, result: dict) -> dict:
        """Override to add subclass keys to the base ``{uri, labels, comments}`` dict."""
        return result

    def _lang_rows(self, inputs: dict[str, Input]) -> ComposeResult:
        for lg in self._langs:
            with Horizontal(classes="cm-row"):
                yield Static(f"[{lg}]", classes="cm-lang")
                yield inputs[lg]

    def on_mount(self) -> None:
        self.query_one(f"#{self.BOX_ID}").border_title = self._title
        self._uri.focus()  # land on the URI fragment (preselected in edit mode)

    def _result(self) -> dict | None:
        if not self._uri.fragment.strip():
            return None  # every entity needs a URI fragment
        base = {
            "uri": self._uri.value,
            "labels": {lg: inp.value.strip() for lg, inp in self._label_inputs.items()},
            "comments": {lg: inp.value.strip() for lg, inp in self._comment_inputs.items()},
        }
        return self._augment_result(base)

    def _submit(self) -> None:
        result = self._result()
        if result is not None:
            self.dismiss(result)
        else:
            self.notify(self.NEEDS_URI_MSG, severity="warning")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)
