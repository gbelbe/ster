"""A scrollable list of semanticlint issues for the New-TUI.

Opened from the ontology overview's "Errors" / "Warnings" count rows (see
:class:`~ster.tui.app.OntologyApp`), each scoped to a single severity. Each issue
is one severity-coloured row: ``WARNING  [check-id] subject: message``.

The list is a Textual :class:`OptionList`. Issues that point at a navigable
entity (e.g. a class with a missing label) are *selectable* — Enter / click
dismisses the modal with that subject URI so the app jumps straight to it.
File-level / coverage issues have no entity to fix in place, so they render as
disabled rows that the arrows skip over.

The modal takes plain issue dicts (from ``lint_runner.lint_overview``) so it
never depends on the semanticlint ``Violation`` type.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from .modal import ModalBase

# Per-severity text colour. Warnings are black (readable on the light surface);
# errors red, info blue.
_SEVERITY_STYLE = {"error": "bold red", "warning": "black", "info": "blue"}
# Worst-first, so errors lead the list.
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _short(subject: str) -> str:
    """The local name of a subject URI (last path / fragment segment)."""
    return subject.rsplit("/", 1)[-1].rsplit("#", 1)[-1] if subject else ""


def _issue_text(issue: dict[str, str]) -> Text:
    """One issue as a severity-coloured Rich ``Text`` (plain text, no markup)."""
    sev = issue.get("severity", "info")
    subj = _short(issue.get("subject", ""))
    where = f" {subj}" if subj else ""
    line = f"{sev.upper():7} [{issue.get('check_id', '')}]{where}: {issue.get('message', '')}"
    return Text(line, style=_SEVERITY_STYLE.get(sev, ""))


class LintModal(ModalBase[str | None]):
    """Modal listing every semanticlint error / warning / info.

    Dismisses with the subject URI of the chosen issue (so the caller can jump to
    it), or ``None`` if the modal is just closed.
    """

    DEFAULT_CSS = """
    #lint-box { width: 80%; max-width: 100; height: auto; max-height: 80%; }
    #lint-box > OptionList { height: auto; max-height: 1fr; background: $background; border: none; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def __init__(
        self,
        issues: list[dict[str, str]],
        navigable: set[str] | None = None,
        kind: str = "semanticlint",
    ) -> None:
        super().__init__()
        self._issues = sorted(
            issues, key=lambda i: _SEVERITY_ORDER.get(i.get("severity", "info"), 3)
        )
        self._navigable = navigable  # entity URIs we can jump to; None ⇒ any non-empty subject
        self._kind = kind  # border-title label (e.g. "Errors", "Warnings")

    def _is_navigable(self, subject: str) -> bool:
        """True when an issue's subject is an entity the app can navigate to."""
        if not subject:
            return False
        return self._navigable is None or subject in self._navigable

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical

        with Vertical(id="lint-box", classes="modal-box"):
            if self._issues:
                yield OptionList(
                    *(
                        Option(
                            _issue_text(i), disabled=not self._is_navigable(i.get("subject", ""))
                        )
                        for i in self._issues
                    )
                )
            else:
                yield Static("[green]✓ No issues found.[/green]")
            yield Static("↑↓ move   enter  go to issue   esc / q  close", classes="modal-footer")

    def on_mount(self) -> None:
        box = self.query_one("#lint-box")
        box.border_title = f"{self._kind} · {len(self._issues)} issue(s)"
        if self._issues:
            self.query_one(OptionList).focus()  # arrows drive the list
        else:
            box.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter / click on a selectable issue → close, returning its subject URI."""
        subject = self._issues[event.option_index].get("subject") or None
        self.dismiss(subject)
