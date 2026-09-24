"""Every command's --help shows examples, and ster --help explains scripting.

A command someone reaches from a script is learned from --help, not the
source: an example line is what gets copied into a CI job.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import ster.cli
from ster.cli._app import app

COMMANDS = [cmd.name for cmd in app.registered_commands]


def _help(*args: str) -> str:
    result = CliRunner().invoke(app, [*args, "--help"], env={"COLUMNS": "120"})
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_shows_examples(command) -> None:
    out = _help(command)
    assert "Examples" in out
    assert f"ster {command}" in out.split("Examples", 1)[1], "an example runs the command itself"


def test_every_command_is_covered() -> None:
    """A new command must come with examples, not quietly without them."""
    assert len(COMMANDS) >= 16


def test_top_level_help_lists_the_exit_codes() -> None:
    out = _help()
    for line in (
        "0  success",
        "1  problems found",
        "2  wrong usage",
        "3  file missing",
        "4  not valid RDF",
        "5  unexpected error",
    ):
        assert line in out


def test_top_level_help_explains_running_without_a_terminal() -> None:
    out = _help()
    assert "no terminal" in out
    assert "ster validate --file" in out


def test_the_registry_names_only_real_commands() -> None:
    from ster.cli._examples import EXAMPLES

    assert set(EXAMPLES) <= set(COMMANDS)


def test_examples_are_attached_once_even_if_applied_twice() -> None:
    ster.cli._examples.attach_examples(app)
    assert _help("validate").count("Examples") == 1
