"""A full add / edit modal for an OWL individual.

Mirrors :class:`~ster.tui.class_modal.ClassModal`: a fragment-locked URI plus an
``rdfs:label`` and ``rdfs:comment`` for every configured language. On top of that,
when *adding* an individual of a class it offers a row per applicable property —
direct and inherited (see :func:`ster.nav.logic.suggested_properties`) — so the
author fills the instance's values in one place. Object-property rows offer a
dropdown of the range class's existing individuals (free text when there are
none); datatype rows are plain text.

Dismisses with ``{"uri", "labels", "comments", "values"}`` where ``values`` maps
``prop_uri -> (kind, value)`` (``kind`` ∈ ``object``/``datatype``; empty values
kept so the caller can skip them), or ``None`` on cancel / empty fragment.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Select, Static

from .modal import ModalBase
from .uri_modal import FragmentInput


@dataclass(frozen=True)
class PropField:
    """One property row in the add-individual modal.

    *candidates* are ``(label, uri)`` pairs of existing individuals of the range
    class — offered as a dropdown for object properties (empty ⇒ free-text input).
    """

    prop_uri: str
    label: str
    kind: str  # "object" | "datatype"
    candidates: Sequence[tuple[str, str]] = field(default_factory=tuple)
    value: str = ""


class IndividualModal(ModalBase[dict | None]):
    """Add or edit an individual: URI + rdfs:label / rdfs:comment per language,
    plus (add mode) a value row per applicable property."""

    DEFAULT_CSS = """
    #ind-box { width: 70%; max-width: 64; max-height: 90%; }
    #ind-box .cm-label { text-style: bold; margin-top: 1; }
    #ind-box .cm-type { color: $text-muted; margin-bottom: 1; }
    #ind-box .cm-row { height: 3; }
    #ind-box .cm-lang { width: 5; height: 3; content-align: right middle; color: $text-muted; }
    #ind-box .cm-prop { width: 22; height: 3; content-align: right middle; color: $text-muted; }
    #ind-box Input { width: 1fr; border: round $primary; }
    #ind-box Select { width: 1fr; }
    #ind-box #ind-save { margin-top: 1; width: auto; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        prefix: str,
        fragment: str = "",
        langs: list[str],
        type_label: str = "",
        labels: Mapping[str, str] | None = None,
        comments: Mapping[str, str] | None = None,
        prop_fields: Sequence[PropField] = (),
        title: str = "New individual",
    ) -> None:
        super().__init__()
        self._prefix = prefix
        self._fragment = fragment
        self._langs = langs or ["en"]
        self._type_label = type_label
        self._labels = dict(labels or {})
        self._comments = dict(comments or {})
        self._prop_fields = list(prop_fields)
        self._title = title
        self._value_widgets: dict[str, Input | Select] = {}

    def compose(self) -> ComposeResult:
        self._uri = FragmentInput(self._prefix, self._fragment, id="ind-uri")
        self._label_inputs = {
            lg: Input(value=self._labels.get(lg, ""), placeholder=f"label [{lg}]")
            for lg in self._langs
        }
        self._comment_inputs = {
            lg: Input(value=self._comments.get(lg, ""), placeholder=f"comment [{lg}]")
            for lg in self._langs
        }
        with VerticalScroll(id="ind-box", classes="modal-box"):
            if self._type_label:
                yield Static(f"rdf:type · {self._type_label}", classes="cm-type")
            yield Static("URI", classes="cm-label")
            yield self._uri
            yield Static("rdfs:label", classes="cm-label")
            yield from self._lang_rows(self._label_inputs)
            yield Static("rdfs:comment", classes="cm-label")
            yield from self._lang_rows(self._comment_inputs)
            yield from self._property_rows()
            yield Button("Save", id="ind-save", variant="primary")
            yield Static("enter  save     esc  cancel", classes="modal-footer")

    def _lang_rows(self, inputs: dict[str, Input]) -> ComposeResult:
        for lg in self._langs:
            with Horizontal(classes="cm-row"):
                yield Static(f"[{lg}]", classes="cm-lang")
                yield inputs[lg]

    def _property_rows(self) -> ComposeResult:
        if not self._prop_fields:
            return
        yield Static("Properties", classes="cm-label")
        for pf in self._prop_fields:
            widget = self._value_widget(pf)
            self._value_widgets[pf.prop_uri] = widget
            with Horizontal(classes="cm-row"):
                yield Static(pf.label, classes="cm-prop")
                yield widget

    def _value_widget(self, pf: PropField) -> Input | Select:
        """A dropdown of candidate individuals for an object property with candidates,
        else a free-text input (datatype attributes, or object props with no candidates)."""
        if pf.kind == "object" and pf.candidates:
            options = [(label, uri) for label, uri in pf.candidates]
            select: Select = Select(options, allow_blank=True, prompt="— pick individual —")
            if pf.value:
                select.value = pf.value
            return select
        return Input(value=pf.value, placeholder=self._placeholder(pf))

    @staticmethod
    def _placeholder(pf: PropField) -> str:
        return "individual URI" if pf.kind == "object" else "value"

    def on_mount(self) -> None:
        self.query_one("#ind-box").border_title = self._title
        self._uri.focus()

    @staticmethod
    def _read(widget: Input | Select) -> str:
        value = widget.value
        return "" if value is Select.BLANK else str(value).strip()

    def _result(self) -> dict | None:
        if not self._uri.fragment.strip():
            return None  # an individual needs a URI fragment
        values = {
            pf.prop_uri: (pf.kind, self._read(self._value_widgets[pf.prop_uri]))
            for pf in self._prop_fields
        }
        return {
            "uri": self._uri.value,
            "labels": {lg: inp.value.strip() for lg, inp in self._label_inputs.items()},
            "comments": {lg: inp.value.strip() for lg, inp in self._comment_inputs.items()},
            "values": values,
        }

    def _submit(self) -> None:
        result = self._result()
        if result is not None:
            self.dismiss(result)
        else:
            self.notify("An individual needs a URI.", severity="warning")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)
