"""Modal to edit the ontology identity as independent parts.

The base URI is decomposed into four fields, each editing only its own part:

- **Domain** — the host (e.g. ``example.org``)
- **Path** — the path after the host (e.g. ``zoo`` or ``onto/zoo``)
- **Separator** — ``#`` or ``/`` between the base and local names
- **Prefix** — the namespace prefix label

``push_screen(OntologyIdentityModal(...), cb)`` dismisses with a dict
``{"domain", "path", "sep", "prefix"}`` or ``None`` on cancel. The app recomposes
the base URI, confirms the cascade impact, applies ``OntoRenameUri`` (validated by
the service) and, if changed, sets the prefix.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Button, Input, RadioButton, RadioSet, Static

from .modal import ModalBase

# (label, separator char) — order matters: index 0 is the default/recommended.
_SEP_OPTIONS: tuple[tuple[str, str], ...] = (("# (recommended)", "#"), ("/ (slash)", "/"))


class OntologyIdentityModal(ModalBase[dict | None]):
    """Edit domain / path / separator / prefix independently. Returns a dict or None."""

    DEFAULT_CSS = """
    #oi-box { width: 80%; }
    #oi-box Input { border: round $primary; margin-bottom: 1; }
    #oi-sep { height: auto; border: round $foreground 40%; margin-bottom: 1; }
    #oi-box .oi-label { color: $text-muted; }
    #oi-error { color: $error; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, *, domain: str, path: str, sep: str, prefix: str) -> None:
        super().__init__()
        self._domain = domain
        self._path = path
        self._sep = sep
        self._prefix = prefix

    def compose(self) -> ComposeResult:
        with Vertical(id="oi-box", classes="modal-box"):
            yield Static("Domain (host)", classes="oi-label")
            yield Input(value=self._domain, id="oi-domain")
            yield Static("Ontology path", classes="oi-label")
            yield Input(value=self._path, id="oi-path")
            yield Static("Separator", classes="oi-label")
            with RadioSet(id="oi-sep"):
                for label, ch in _SEP_OPTIONS:
                    yield RadioButton(label, value=(ch == self._sep))
            yield Static("Prefix", classes="oi-label")
            yield Input(value=self._prefix, id="oi-prefix")
            yield Static("", id="oi-error")
            yield Button("Save", id="oi-save")
            yield Static("enter  save     tab  next field     esc  cancel", classes="modal-footer")

    def on_mount(self) -> None:
        self.query_one("#oi-box").border_title = "Edit ontology identity"
        self.query_one("#oi-domain", Input).focus()

    def _selected_sep(self) -> str:
        idx = self.query_one(RadioSet).pressed_index
        return _SEP_OPTIONS[idx][1] if idx >= 0 else "#"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._submit()

    def _submit(self) -> None:
        domain = self.query_one("#oi-domain", Input).value.strip()
        path = self.query_one("#oi-path", Input).value.strip().strip("/")
        prefix = self.query_one("#oi-prefix", Input).value.strip()
        error = self._validate(domain, prefix)
        if error is not None:
            self.query_one("#oi-error", Static).update(error)
            return
        self.dismiss(
            {"domain": domain, "path": path, "sep": self._selected_sep(), "prefix": prefix}
        )

    @staticmethod
    def _validate(domain: str, prefix: str) -> str | None:
        from ster.operations import validate_domain, validate_prefix

        error = validate_domain(domain)
        if error is not None:
            return error
        return validate_prefix(prefix) if prefix else None  # empty prefix = default namespace

    def action_cancel(self) -> None:
        self.dismiss(None)
