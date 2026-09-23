"""Step definitions for opening ster on a folder (tests/features/io/open_folder.feature).

Each ``When`` runs the real entry point with ``_home_screen`` stubbed, so the
steps can check what the home screen was asked to open and where ster ended
up working — the whole promise is "the same as cd-ing there first".
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import ster.cli

scenarios("../features/io/open_folder.feature")


@pytest.fixture
def ctx(tmp_path, monkeypatch) -> dict:
    monkeypatch.chdir(tmp_path)
    return {"tmp_path": tmp_path}


@given(parsers.parse('a folder "{name}" holding the file "{file}"'))
def given_folder_with_file(ctx, name, file):
    folder = ctx["tmp_path"] / name
    folder.mkdir()
    (folder / file).write_text("@prefix ex: <https://example.org/> .\n", encoding="utf-8")


@given(parsers.parse('an empty folder "{name}"'))
def given_empty_folder(ctx, name):
    (ctx["tmp_path"] / name).mkdir()


def _run(ctx: dict, monkeypatch, capsys, arg: str) -> None:
    monkeypatch.setattr("sys.argv", ["ster", arg])
    with patch("ster.cli._home._home_screen") as home_screen:
        try:
            ster.cli.main()
        except SystemExit as exc:
            ctx["exit"] = exc
    ctx["home_screen"] = home_screen
    ctx["cwd"] = Path.cwd()
    # Read here: capsys only captures from the step that first requests it.
    ctx["stderr"] = capsys.readouterr().err


@when(parsers.parse('I run ster with the absolute path of "{name}"'))
def when_absolute(ctx, monkeypatch, capsys, name):
    _run(ctx, monkeypatch, capsys, str((ctx["tmp_path"] / name).resolve()))


@when(parsers.parse('I run ster with the relative path "{name}"'))
def when_relative(ctx, monkeypatch, capsys, name):
    _run(ctx, monkeypatch, capsys, name)


@then("the home screen opens with no file preselected")
def then_home_screen(ctx):
    ctx["home_screen"].assert_called_once_with()


@then(parsers.parse('ster is working in "{name}"'))
def then_working_in(ctx, name):
    assert ctx["cwd"] == (ctx["tmp_path"] / name).resolve()


@then(parsers.parse('ster stops with an error naming "{name}"'))
def then_error(ctx, name):
    assert ctx["exit"].code != 0
    assert name in ctx["stderr"]


@then("the home screen does not open")
def then_no_home_screen(ctx):
    ctx["home_screen"].assert_not_called()
