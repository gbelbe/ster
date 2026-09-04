"""BDD step definitions for multi-file selection and workspace editing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.cli import _ALL_FILES_SENTINEL, _home_obtain_action, _select_home_file

scenarios("../features/tui/multi_file_selection.feature")


@pytest.fixture
def bdd_ctx() -> dict:
    return {}


@given(parsers.parse('a project with multiple taxonomy files "{file1}" and "{file2}"'))
def setup_two_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bdd_ctx: dict, file1: str, file2: str
) -> None:
    monkeypatch.chdir(tmp_path)
    f1 = tmp_path / file1
    f2 = tmp_path / file2
    f1.write_text("""@prefix skos: <http://www.w3.org/2004/02/skos/core#> .""", encoding="utf-8")
    f2.write_text("""@prefix skos: <http://www.w3.org/2004/02/skos/core#> .""", encoding="utf-8")
    bdd_ctx["files"] = [f1, f2]


@given(
    parsers.parse('a project with multiple taxonomy files "{file1}", "{file2}", and "{file3}"')
)
def setup_three_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bdd_ctx: dict,
    file1: str,
    file2: str,
    file3: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    f1 = tmp_path / file1
    f2 = tmp_path / file2
    f3 = tmp_path / file3
    f1.write_text("""@prefix skos: <http://www.w3.org/2004/02/skos/core#> .""", encoding="utf-8")
    f2.write_text("""@prefix skos: <http://www.w3.org/2004/02/skos/core#> .""", encoding="utf-8")
    f3.write_text("""@prefix skos: <http://www.w3.org/2004/02/skos/core#> .""", encoding="utf-8")
    bdd_ctx["files"] = [f1, f2, f3]


@when("I select the open all project files option")
def select_open_all(bdd_ctx: dict) -> None:
    files = bdd_ctx["files"]
    with patch("ster.cli._select_home_file", return_value=_ALL_FILES_SENTINEL):
        selected, action = _home_obtain_action(None, None, files)
    bdd_ctx["selected"] = selected
    bdd_ctx["action"] = action


@when(parsers.parse('I enter comma-separated file numbers "{choice}"'))
def enter_comma_selection(bdd_ctx: dict, monkeypatch: pytest.MonkeyPatch, choice: str) -> None:
    files = bdd_ctx["files"]
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    with patch("ster.cli.Prompt.ask", return_value=choice):
        res = _select_home_file(files)
        selected, action = _home_obtain_action(None, None, files)
        if isinstance(res, list):
            action = res
    bdd_ctx["action"] = action


@then(parsers.parse('a workspace with both "{file1}" and "{file2}" is loaded'))
def verify_two_files_loaded(bdd_ctx: dict, file1: str, file2: str) -> None:
    action = bdd_ctx["action"]
    filenames = [p.name for p in action]
    assert file1 in filenames and file2 in filenames


@then(parsers.parse('a workspace with "{file1}" and "{file2}" is loaded'))
def verify_specific_files_loaded(bdd_ctx: dict, file1: str, file2: str) -> None:
    action = bdd_ctx["action"]
    filenames = [p.name for p in action]
    assert file1 in filenames and file2 in filenames
