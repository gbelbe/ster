"""Every question ster asks goes through one adapter, which never asks without a terminal.

In CI or any script nobody is there to answer, so a question must not hang or
fail obscurely: it becomes ``NeedsAnswer``, carrying the question and — where
an option can supply the answer — how to pass it.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ster import ask

# Taken at import, before the suite-wide fixture (tests/conftest.py) replaces it
# with "a terminal is present" so existing prompt tests keep working.
_REAL_HAS_TERMINAL = ask.has_terminal


@pytest.fixture
def no_terminal(monkeypatch):
    monkeypatch.setattr(ask, "has_terminal", lambda: False)


def test_with_a_terminal_confirm_asks_as_before() -> None:
    with patch("rich.prompt.Confirm.ask", return_value=False) as rich_confirm:
        assert ask.confirm("Proceed?", default=True) is False
    rich_confirm.assert_called_once_with("Proceed?", default=True)


def test_with_a_terminal_text_asks_as_before() -> None:
    with patch("rich.prompt.Prompt.ask", return_value="gear.ttl") as rich_prompt:
        assert ask.text("File", default="x.ttl", choices=["x.ttl", "gear.ttl"]) == "gear.ttl"
    rich_prompt.assert_called_once_with("File", default="x.ttl", choices=["x.ttl", "gear.ttl"])


def test_without_a_terminal_confirm_raises_instead_of_asking(no_terminal) -> None:
    with (
        patch("rich.prompt.Confirm.ask") as rich_confirm,
        pytest.raises(ask.NeedsAnswer) as raised,
    ):
        ask.confirm("Use this file?", hint="Pass --file <path>.")
    rich_confirm.assert_not_called()
    assert (raised.value.question, raised.value.hint) == ("Use this file?", "Pass --file <path>.")


def test_without_a_terminal_text_raises_instead_of_asking(no_terminal) -> None:
    with patch("rich.prompt.Prompt.ask") as rich_prompt, pytest.raises(ask.NeedsAnswer):
        ask.text("Bump", default="patch")
    rich_prompt.assert_not_called()


def test_the_question_is_shown_without_rich_markup(no_terminal) -> None:
    """The error line is plain text in a CI log, not "[cyan]…[/cyan]"."""
    with pytest.raises(ask.NeedsAnswer) as raised:
        ask.confirm("Delete cache for [cyan]ex:[/cyan]?")
    assert raised.value.question == "Delete cache for ex:?"


def test_a_terminal_means_someone_can_type_an_answer(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert _REAL_HAS_TERMINAL() is True
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert _REAL_HAS_TERMINAL() is False
