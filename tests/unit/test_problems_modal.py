"""Unit tests for the scan-on-open Problems modal (inline-fix worklist)."""

from __future__ import annotations

import asyncio

from textual.app import App
from textual.widgets import Button, Input

from ster.plugins.semanticlint.fixes import Fix
from ster.tui.plugins.semanticlint_ui.problems_modal import ProblemRow, ProblemsModal, _headline


def _issue(check_id: str, subject: str = "http://ex.org/C1", message: str = "m") -> dict:
    return {"severity": "error", "check_id": check_id, "subject": subject, "message": message}


# ── pure helpers ────────────────────────────────────────────────────────────────


def test_headline_shows_check_subject_message_and_suggestion() -> None:
    text = _headline(_issue("SKO001", message="dup label"), Fix("pick", "Choose one")).plain
    assert "SKO001" in text
    assert "C1" in text
    assert "dup label" in text
    assert "Choose one" in text


def test_row_choice_reads_edit_field_over_button_name() -> None:
    # Not mounted here; choice() for a pick reads the button name directly.
    row = ProblemRow(_issue("X"), Fix("pick", "s", options=(("A", "urn:a"),)))
    assert row.choice(Button("A", name="urn:a")) == "urn:a"


# ── modal behaviour (Textual harness) ───────────────────────────────────────────


def _run(coro_factory) -> None:
    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(90, 30)) as pilot:
            await coro_factory(app, pilot)

    asyncio.run(scenario())


def test_auto_row_fix_button_applies_and_drops_the_row() -> None:
    calls: list = []
    problems = [(_issue("SKO003"), Fix("auto", "Remove dup"))]

    async def scenario(app, pilot) -> None:
        app.push_screen(ProblemsModal(problems, lambda i, c: calls.append((i, c)) or True))
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one(".problem-fix", Button).press()
        await pilot.pause()
        await pilot.pause()
        assert calls and calls[0][1] == ""  # auto → empty choice
        # last error resolved → modal dismissed itself
        assert not app.screen.query(ProblemRow)

    _run(scenario)


def test_edit_row_passes_field_value_as_choice() -> None:
    calls: list = []
    problems = [
        (
            _issue("RDF003", subject="http://ex.org/x y"),
            Fix("edit", "rename", prefill="http://ex.org/x%20y"),
        )
    ]

    async def scenario(app, pilot) -> None:
        app.push_screen(ProblemsModal(problems, lambda i, c: calls.append((i, c)) or True))
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one(".problem-fix", Button).press()
        await pilot.pause()
        assert calls and calls[0][1] == "http://ex.org/x%20y"  # the prefilled field value

    _run(scenario)


def test_pick_row_offers_a_button_per_option_and_passes_its_value() -> None:
    calls: list = []
    fix = Fix("pick", "choose", options=(("Dog", "Dog"), ("Hound", "Hound")))
    problems = [(_issue("SKO001"), fix)]

    async def scenario(app, pilot) -> None:
        app.push_screen(ProblemsModal(problems, lambda i, c: calls.append((i, c)) or True))
        await pilot.pause()
        await pilot.pause()
        buttons = list(app.screen.query(".problem-fix").results(Button))
        assert [b.label.plain for b in buttons] == ["Dog", "Hound"]
        buttons[1].press()  # pick "Hound"
        await pilot.pause()
        assert calls and calls[0][1] == "Hound"

    _run(scenario)


def test_suggest_row_has_no_fix_control() -> None:
    problems = [(_issue("RDF007"), Fix("suggest", "Give distinct URIs"))]

    async def scenario(app, pilot) -> None:
        app.push_screen(ProblemsModal(problems, lambda i, c: True))
        await pilot.pause()
        await pilot.pause()
        assert not app.screen.query(".problem-fix")  # guidance only
        assert not app.screen.query(Input)

    _run(scenario)


def test_failed_fix_keeps_the_row() -> None:
    problems = [(_issue("SKO003"), Fix("auto", "Remove dup"))]

    async def scenario(app, pilot) -> None:
        app.push_screen(ProblemsModal(problems, lambda i, c: False))  # fix fails
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one(".problem-fix", Button).press()
        await pilot.pause()
        assert app.screen.query(ProblemRow)  # row stays

    _run(scenario)


def test_resolving_one_of_two_keeps_the_modal_open() -> None:
    problems = [
        (_issue("SKO003", subject="http://ex.org/A"), Fix("auto", "s")),
        (_issue("SKO003", subject="http://ex.org/B"), Fix("auto", "s")),
    ]

    async def scenario(app, pilot) -> None:
        app.push_screen(ProblemsModal(problems, lambda i, c: True))
        await pilot.pause()
        await pilot.pause()
        list(app.screen.query(".problem-fix").results(Button))[0].press()
        await pilot.pause()
        await pilot.pause()
        assert len(app.screen.query(ProblemRow)) == 1  # one left, modal still open

    _run(scenario)
