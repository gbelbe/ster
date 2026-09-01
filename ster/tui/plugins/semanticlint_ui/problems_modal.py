"""The scan-on-open "Problems" modal — a fix-it worklist for semanticlint ERRORs.

Unlike :class:`~ster.tui.lint_modal.LintModal` (which lists issues and jumps you to
the entity), this modal resolves each error **in place**: every row carries an inline
control sized to its :class:`~ster.plugins.semanticlint.fixes.Fix` —

* ``auto``   — a single *Fix* button;
* ``edit``   — a field pre-filled with a corrected value + *Apply*;
* ``pick``   — one button per option;
* ``suggest``— no control, just concrete guidance.

Applying a fix calls back into the app (``apply_fix(issue, choice) -> str | None``);
on success — ``None`` — the row drops out of the list, and the modal closes once none
remain, so the user never leaves the modal to fix the file. A returned string is the
reason it did not apply, shown on the row itself: a toast alone left a failed row
indistinguishable from one nobody had touched.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Static

from ster.tui.hint_bar import Hint
from ster.tui.modal import ModalBase

if TYPE_CHECKING:
    from ster.plugins.semanticlint.fixes import Fix


def _local(uri: str) -> str:
    """The local name of a subject URI (last path / fragment segment)."""
    return uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1] if uri else uri


def _headline(issue: dict, fix: Fix) -> Text:
    """The severity-coloured problem line + its concrete suggestion, as Rich ``Text``
    (built segment-by-segment so a URI or message can never inject markup)."""
    text = Text()
    text.append(f"⊘ {issue.get('check_id', '')} ", style="bold red")
    subj = _local(issue.get("subject", ""))
    if subj:
        text.append(f"{subj}\n", style="bold")
    else:
        text.append("\n")
    text.append(f"{issue.get('message', '')}\n")
    text.append(f"→ {fix.suggestion}", style="dim")
    return text


class ProblemRow(Vertical):
    """One error and its inline fix control (or plain guidance for ``suggest``)."""

    def __init__(self, issue: dict, fix: Fix) -> None:
        super().__init__(classes="problem-row")
        self.issue = issue
        self.fix = fix

    def compose(self) -> ComposeResult:
        yield Static(_headline(self.issue, self.fix), classes="problem-headline")
        yield from self._control()
        # Composed empty and hidden by CSS rather than mounted on demand, so the
        # failure notice cannot race the modal's own mount.
        yield Static("", classes="problem-status")

    def _control(self) -> ComposeResult:
        kind = self.fix.kind
        if kind == "auto":
            yield Button("Fix", variant="success", classes="problem-fix")
        elif kind == "edit":
            with Horizontal(classes="problem-controls"):
                yield Input(value=self.fix.prefill, classes="problem-edit")
                yield Button("Apply", variant="success", classes="problem-fix")
        elif kind == "pick":
            with Horizontal(classes="problem-controls"):
                for label, value in self.fix.options:
                    yield Button(label, name=value, variant="success", classes="problem-fix")
        # "suggest" → guidance only, no control.

    def choice(self, button: Button) -> str:
        """The user's input for this row: the edit field's text, or the picked option
        value carried on the button (empty for a one-shot ``auto`` fix)."""
        if self.fix.kind == "edit":
            return self.query_one(Input).value
        return button.name or ""

    def report_failure(self, reason: str) -> None:
        """Show *reason* on the row and mark it as tried-and-failed."""
        self.add_class("problem-failed")
        # Segment-built Text, like the headline: a message carrying the file's own
        # URIs must never be parsed as console markup.
        self._status.update(Text(f"✗ {reason}", style="bold red"))

    def clear_failure(self) -> None:
        """Drop any previous failure notice, so a retry is not read against a stale one."""
        self.remove_class("problem-failed")
        self._status.update("")

    @property
    def _status(self) -> Static:
        return self.query_one(".problem-status", Static)


class ProblemsModal(ModalBase[None]):
    """A worklist of ERROR violations, each fixed in place. Dismisses (``None``) when
    the last one is resolved or the user closes it."""

    DEFAULT_CSS = """
    #problems-box { width: 90%; max-width: 100; height: auto; max-height: 85%; }
    #problems-box > VerticalScroll { height: auto; max-height: 1fr; }
    .problem-row {
        height: auto;
        border: round $foreground 30%;
        padding: 0 1;
        margin-bottom: 1;
    }
    .problem-headline { margin-bottom: 1; }
    .problem-controls { height: auto; }
    .problem-row.problem-failed { border: round $error; }
    .problem-status { display: none; }
    .problem-row.problem-failed .problem-status { display: block; margin-top: 1; }
    .problem-row .problem-fix { width: auto; min-width: 8; margin-right: 1; }
    .problem-row .problem-edit { width: 1fr; margin-right: 1; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding("q", "cancel", "Close"),
    ]

    def __init__(
        self, problems: list[tuple[dict, Fix]], apply_fix: Callable[[dict, str], str | None]
    ) -> None:
        super().__init__()
        self._problems = problems
        self._apply_fix = apply_fix

    def compose(self) -> ComposeResult:
        with Vertical(id="problems-box", classes="modal-box"), VerticalScroll():
            for issue, fix in self._problems:
                yield ProblemRow(issue, fix)

    def footer_hints(self) -> list[Hint]:
        return [
            Hint("↵", "apply fix", "confirm"),
            Hint("esc / q", "close", "cancel"),
            Hint("!", "reopen after edits"),
        ]

    def on_mount(self) -> None:
        self.query_one("#problems-box").border_title = f"Problems · {len(self._problems)} error(s)"

    @on(Button.Pressed, ".problem-fix")
    async def _on_fix(self, event: Button.Pressed) -> None:
        event.stop()
        await self._try_apply(event.button)

    @on(Input.Submitted, ".problem-edit")
    async def _on_edit_submit(self, event: Input.Submitted) -> None:
        event.stop()
        row = self._row_of(event.input)
        if row is not None:
            await self._apply(row, event.value)

    async def _try_apply(self, button: Button) -> None:
        row = self._row_of(button)
        if row is not None:
            await self._apply(row, row.choice(button))

    async def _apply(self, row: ProblemRow, choice: str) -> None:
        """Run the row's fix: drop it when it lands, say why on the row when it does not."""
        row.clear_failure()
        reason = self._apply_fix(row.issue, choice)
        if reason is None:
            await self._drop(row)
        else:
            row.report_failure(reason)

    @staticmethod
    def _row_of(widget: object) -> ProblemRow | None:
        node = widget
        while node is not None and not isinstance(node, ProblemRow):
            node = getattr(node, "parent", None)
        return node

    async def _drop(self, row: ProblemRow) -> None:
        """Remove a resolved error; close the modal once the worklist is empty."""
        await row.remove()
        if not self.query(ProblemRow):
            self.dismiss(None)
