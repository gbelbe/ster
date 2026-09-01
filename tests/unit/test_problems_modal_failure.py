"""A fix that did not apply must not leave its row looking untried.

The Problems modal drops a row on success and did nothing at all on failure —
same border, same button, same prefill — so the only evidence was a toast that
had already faded. The row now says why, in place, and stays until it works.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Static

from ster.plugins.semanticlint.fixes import Fix
from ster.tui.plugins.semanticlint_ui.problems_modal import ProblemRow, ProblemsModal

ISSUE = {
    "check_id": "RDF003",
    "subject": "https://example.org/gear#Camping#",
    "message": "Malformed URI",
}
FIX = Fix("edit", "Rename to a valid URI.", ISSUE["subject"], prefill="https://example.org/gear#C")


class _Host(App[None]):
    """A bare app whose only job is to host the modal under test."""

    def __init__(self, outcome: str | None) -> None:
        super().__init__()
        self._outcome = outcome
        self.calls: list[tuple[dict, str]] = []

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(ProblemsModal([(ISSUE, FIX)], self._apply))

    def _apply(self, issue: dict, choice: str) -> str | None:
        self.calls.append((issue, choice))
        return self._outcome


async def _press_apply(pilot) -> None:
    pilot.app.screen.query_one(".problem-fix", Button).press()
    await pilot.pause()
    await pilot.pause()


@pytest.mark.asyncio
async def test_a_failed_fix_keeps_the_row_and_states_the_reason():
    app = _Host("Concept not found: gear#Camping#")

    async with app.run_test() as pilot:
        await _press_apply(pilot)

        rows = app.screen.query(ProblemRow)
        assert len(rows) == 1, "an unapplied fix must not drop off the worklist"
        assert "Concept not found" in _status_text(rows[0])


@pytest.mark.asyncio
async def test_a_failed_row_is_marked_so_it_reads_as_tried():
    app = _Host("Concept not found")

    async with app.run_test() as pilot:
        await _press_apply(pilot)

        assert app.screen.query_one(ProblemRow).has_class("problem-failed")


@pytest.mark.asyncio
async def test_retrying_clears_the_previous_reason():
    """A stale error next to a fresh attempt is worse than none."""
    app = _Host("Concept not found")

    async with app.run_test() as pilot:
        await _press_apply(pilot)
        app._outcome = None
        await _press_apply(pilot)

        assert not app.screen.query(ProblemRow), "the successful retry drops the row"


@pytest.mark.asyncio
async def test_a_successful_fix_still_drops_the_row_and_closes():
    app = _Host(None)

    async with app.run_test() as pilot:
        await _press_apply(pilot)

        assert not isinstance(app.screen, ProblemsModal), "the last error resolved → close"


@pytest.mark.asyncio
async def test_submitting_the_field_reports_failure_the_same_way():
    """Enter in the edit field is the other route to the same apply."""
    app = _Host("Concept not found")

    async with app.run_test() as pilot:
        field = app.screen.query_one(".problem-edit", Input)
        field.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert "Concept not found" in _status_text(app.screen.query_one(ProblemRow))


def _status_text(row: ProblemRow) -> str:
    return " ".join(str(s.render()) for s in row.query(Static) if s.has_class("problem-status"))
