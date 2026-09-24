"""Asking once whether ster should look one level down, and keeping the answer."""

from __future__ import annotations

import pytest

from ster.cli import _home, _workspace_ui
from ster.project import Project


def _touch(root, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


@pytest.fixture
def launch(tmp_path, monkeypatch):
    """ster started in *tmp_path*, with the question's answer scripted."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    monkeypatch.setattr("ster.cli._home._git_root", lambda cwd: None)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)  # a person is there to answer
    asked: list[list] = []

    def answer(value: bool):
        def ask(below):
            asked.append(list(below))
            return value

        monkeypatch.setattr(_workspace_ui, "ask_include_subfolders", ask)

    return answer, asked


def test_agreeing_offers_the_files_one_level_down(tmp_path, launch) -> None:
    answer, _ = launch
    answer(True)
    _touch(tmp_path, "top.ttl", "vocab/labels.ttl")
    assert _home._found_taxonomy_files() == [tmp_path / "top.ttl", tmp_path / "vocab/labels.ttl"]


def test_declining_keeps_today_s_behaviour(tmp_path, launch) -> None:
    answer, _ = launch
    answer(False)
    _touch(tmp_path, "top.ttl", "vocab/labels.ttl")
    assert _home._found_taxonomy_files() == [tmp_path / "top.ttl"]


def test_the_answer_is_remembered_and_not_asked_again(tmp_path, launch) -> None:
    answer, asked = launch
    answer(True)
    _touch(tmp_path, "top.ttl", "vocab/labels.ttl")
    _home._found_taxonomy_files()
    _home._found_taxonomy_files()
    assert len(asked) == 1
    assert Project.load(tmp_path).include_subfolders is True


def test_no_question_when_no_subfolder_holds_rdf(tmp_path, launch) -> None:
    answer, asked = launch
    answer(True)
    _touch(tmp_path, "top.ttl", "notes/readme.md", "ontology/gear.ttl")
    assert _home._found_taxonomy_files() == [tmp_path / "top.ttl"]
    assert asked == []


def test_the_question_names_what_it_found(tmp_path, launch) -> None:
    answer, asked = launch
    answer(False)
    _touch(tmp_path, "vocab/a.ttl", "data/b.owl")
    _home._found_taxonomy_files()
    assert asked == [[tmp_path / "data/b.owl", tmp_path / "vocab/a.ttl"]]


def test_without_a_terminal_the_default_is_no_and_nothing_is_saved(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    _touch(tmp_path, "top.ttl", "vocab/labels.ttl")
    assert _home._found_taxonomy_files() == [tmp_path / "top.ttl"]
    assert Project.load(tmp_path) is None, "an answer nobody gave is not remembered"


def test_opening_a_file_keeps_the_remembered_answers(tmp_path, monkeypatch) -> None:
    """Opening a file rewrites project.json; it must not forget what was answered."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    _touch(tmp_path, "top.ttl", "labels.ttl")
    project = Project(root=tmp_path, include_subfolders=True)
    project.remember_context(tmp_path / "top.ttl", [tmp_path / "labels.ttl"])
    project.save()
    monkeypatch.setattr(_workspace_ui, "_load_workspace", lambda selected, found: None)
    monkeypatch.setattr(_workspace_ui, "context_files_for", lambda *a, **k: [])
    monkeypatch.setattr("ster.cli._viewer._open_viewer", lambda *a, **k: None)
    monkeypatch.setattr("ster.cli._file_picker._save_session", lambda path: None)

    _home._open_selected_in_viewer([tmp_path / "top.ttl"], [tmp_path / "top.ttl"], project)

    reloaded = Project.load(tmp_path)
    assert reloaded.include_subfolders is True
    assert reloaded.remembered_context(tmp_path / "top.ttl") == [tmp_path / "labels.ttl"]


# ── --ask-again: forget both answers, then start as usual ───────────────────


def _remembered(root) -> Project:
    _touch(root, "gear.ttl", "labels.ttl", "vocab/extra.ttl")
    project = Project(root=root, include_subfolders=True)
    project.remember_context(root / "gear.ttl", [root / "labels.ttl"])
    project.save()
    return project


def _main(monkeypatch, *argv: str):
    from unittest.mock import patch

    import ster.cli

    monkeypatch.setattr("sys.argv", ["ster", *argv])
    with patch("ster.cli._home._home_screen") as home_screen:
        ster.cli.main()
    return home_screen


def test_ask_again_forgets_both_answers_then_starts(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    _remembered(tmp_path)

    home_screen = _main(monkeypatch, "--ask-again")

    home_screen.assert_called_once_with()
    project = Project.load(tmp_path)
    assert (project.include_subfolders, project.context) == (None, {})


def test_ask_again_applies_to_the_folder_given(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "proj"
    folder.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    _remembered(folder)

    home_screen = _main(monkeypatch, str(folder), "--ask-again")

    home_screen.assert_called_once_with()
    assert Project.load(folder).include_subfolders is None


def test_ask_again_with_a_file_opens_that_file(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    _remembered(tmp_path)

    home_screen = _main(monkeypatch, "--ask-again", "gear.ttl")

    assert home_screen.call_args.kwargs["initial_file"] == Path.cwd() / "gear.ttl"
    assert Project.load(tmp_path).context == {}


def test_ask_again_keeps_the_rest_of_the_project(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    project = _remembered(tmp_path)
    project.lang = "fr"
    project.add_file(tmp_path / "gear.ttl")
    project.save()

    _main(monkeypatch, "--ask-again")

    reloaded = Project.load(tmp_path)
    assert (reloaded.lang, reloaded.files) == ("fr", project.files)


def test_ask_again_without_a_project_file_creates_none(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    _main(monkeypatch, "--ask-again")
    assert not (tmp_path / ".ster").exists()


def test_ask_again_is_listed_in_help() -> None:
    from typer.testing import CliRunner

    from ster.cli._app import app

    result = CliRunner().invoke(app, ["--help"])
    assert "--ask-again" in result.output
