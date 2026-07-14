"""Modal to create a new *local* annotation property for the open ontology.

Opened from the configuration modal's "Add local annotation property" button. The
ontology base IRI is fixed; the user supplies the predicate name (and, later, a
label / comment). On confirm it dismisses with ``{"name", "label", "comment"}``;
the catalog declares the property in the ``.ttl`` and ticks it in.

NOTE: this is a placeholder — the form layout is intentionally minimal and will be
designed in a follow-up. The result contract (the dismissed dict) is what the
config modal already consumes, so the design can change without touching callers.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static

from .modal import ModalBase


class LocalPropertyModal(ModalBase[dict | None]):
    """Collect a new local annotation property; dismiss with its fields or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, base_uri: str) -> None:
        super().__init__()
        self._base_uri = base_uri

    def compose(self) -> ComposeResult:
        with Vertical(id="local-prop-box", classes="modal-box"):
            yield Static(f"Base IRI: {self._base_uri}", classes="cfg-hint")
            yield Static("(property-creation form — to be designed)", classes="cfg-hint")

    def on_mount(self) -> None:
        self.query_one("#local-prop-box").border_title = "Add local annotation property"

    def action_cancel(self) -> None:
        self.dismiss(None)
