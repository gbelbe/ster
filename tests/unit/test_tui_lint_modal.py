"""Unit tests for the New-TUI semanticlint issue modal."""

from __future__ import annotations

import asyncio

from textual.app import App
from textual.widgets import OptionList

from ster.tui.lint_modal import LintModal, _issue_text, _short


def test_short_takes_local_name() -> None:
    assert _short("http://example.org/onto#Widget") == "Widget"
    assert _short("http://example.org/onto/Widget") == "Widget"
    assert _short("") == ""


def test_issue_text_renders_severity_check_and_message() -> None:
    text = _issue_text(
        {
            "severity": "error",
            "check_id": "SKO001",
            "subject": "http://example.org/onto#C1",
            "message": "duplicate prefLabel",
        }
    ).plain
    assert "ERROR" in text
    assert "SKO001" in text
    assert "C1" in text
    assert "duplicate prefLabel" in text


def test_issue_text_warning_is_styled_black() -> None:
    text = _issue_text({"severity": "warning", "check_id": "W", "subject": "", "message": "m"})
    assert "black" in str(text.style)


def test_modal_sorts_issues_worst_first() -> None:
    issues = [
        {"severity": "info", "check_id": "I", "subject": "", "message": "i"},
        {"severity": "error", "check_id": "E", "subject": "", "message": "e"},
        {"severity": "warning", "check_id": "W", "subject": "", "message": "w"},
    ]
    modal = LintModal(issues)
    assert [i["severity"] for i in modal._issues] == ["error", "warning", "info"]


def test_is_navigable_only_for_known_entity_subjects() -> None:
    navigable = {"http://x/C1"}
    modal = LintModal([], navigable)
    assert modal._is_navigable("http://x/C1")  # a known entity
    assert not modal._is_navigable("http://x/Unknown")  # not in the tree
    assert not modal._is_navigable("")  # file-level / coverage issue


def test_coverage_issues_are_disabled_and_skipped() -> None:
    """An issue with a navigable subject is selectable; a file-level (no subject)
    coverage issue is disabled, so the arrows skip it."""
    issues = [
        {
            "severity": "error",
            "check_id": "E",
            "subject": "http://x/C1",
            "message": "missing label",
        },
        {"severity": "warning", "check_id": "COV", "subject": "", "message": "low coverage"},
    ]

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(80, 20)) as pilot:
            app.push_screen(LintModal(issues, {"http://x/C1"}))
            await pilot.pause()
            await pilot.pause()
            ol = app.screen.query_one(OptionList)
            # Errors sort first, so option 0 is the navigable one, option 1 the coverage one.
            assert not ol.get_option_at_index(0).disabled
            assert ol.get_option_at_index(1).disabled

    asyncio.run(scenario())


def test_selecting_an_issue_dismisses_with_its_subject() -> None:
    issues = [
        {"severity": "error", "check_id": "E", "subject": "http://x/C1", "message": "missing label"}
    ]
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(80, 20)) as pilot:
            app.push_screen(LintModal(issues, {"http://x/C1"}), captured.append)
            await pilot.pause()
            await pilot.pause()
            await pilot.press("enter")  # activate the highlighted (navigable) issue
            await pilot.pause()

    asyncio.run(scenario())
    assert captured == ["http://x/C1"]
