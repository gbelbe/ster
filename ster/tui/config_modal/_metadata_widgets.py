"""Per-predicate widgets for one metadata-catalog row: an offered-checkbox
(``_MetaCheckbox``), its optional SHACL enforce toggle (``_EnforceButton``), and
the row that composes them (``_MetaRow``)."""

from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button

from ster.tui.check import Check

from ._labels import suggest_label

# CSS selectors reused across several handlers in the catalog widget (S1192).
_SEL_MPROPS = ".cfg-mprops"
_SEL_MP_URI = ".cfg-mp-uri"
_SEL_MP_LABEL = ".cfg-mp-label"


class _MetaCheckbox(Check):
    """A registered ontology-metadata predicate as a checkbox (ticked = offered in
    "Add metadata"). Carries its predicate URI + display label."""

    def __init__(self, predicate: str, label: str) -> None:
        self.label_text = label or suggest_label(predicate)
        super().__init__(self.label_text, value=True, classes="cfg-mp-box")
        self.predicate = predicate


class _EnforceButton(Button):
    """Per-predicate toggle, styled by standard convention: a green (success) '◆ Enforce
    (SHACL rule)' when not enforced, a red (error) '⊘ Delete SHACL rule' when it is — so
    the create vs destructive action reads at a glance from both colour and icon."""

    def __init__(self, predicate: str, enforce: bool = False) -> None:
        self.predicate = predicate
        self._enforce = enforce
        super().__init__(self._text(), variant=self._variant(), classes="cfg-mp-enforce")

    def _text(self) -> str:
        return "⊘ Delete SHACL rule" if self._enforce else "◆ Enforce (SHACL rule)"

    def _variant(self) -> Literal["success", "error"]:
        return "error" if self._enforce else "success"  # destructive reads red, create reads green

    @property
    def enforce(self) -> bool:
        return self._enforce

    def toggle(self) -> bool:
        """Flip the enforced state, restyle (label + colour), and return the new state."""
        self._enforce = not self._enforce
        self.label = self._text()
        self.variant = self._variant()  # type: ignore[assignment]
        return self._enforce


class _MetaRow(Horizontal):
    """One catalog row: the offered-checkbox, plus its Enforce/Delete SHACL button when
    semanticlint's opt-in ``enforce`` feature is active (else just the checkbox)."""

    def __init__(self, predicate: str, label: str, enforce: bool = False) -> None:
        super().__init__(classes="cfg-mp-row")
        self._predicate, self._label, self._enforce = predicate, label, enforce
        from ster.plugins import semanticlint

        self._show_enforce = semanticlint.enforce_active()
        if self._show_enforce:
            self.add_class("has-enforce")  # taller row + centred checkbox to match the button

    def compose(self) -> ComposeResult:
        yield _MetaCheckbox(self._predicate, self._label)
        if self._show_enforce:
            yield _EnforceButton(self._predicate, self._enforce)
