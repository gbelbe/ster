"""Step definitions for subfolder files and remembered answers
(tests/features/io/subfolder_files.feature).

Drives the real home-flow functions — ``_found_taxonomy_files`` and
``context_files_for`` — with the two questions answered by stubs, so the steps
check what ster offers, asks and remembers without a terminal.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.cli import _home, _workspace_ui
from ster.project import Project

scenarios("../features/io/subfolder_files.feature")


def _touch(root: Path, *names: str) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


@pytest.fixture
def ctx(tmp_path, monkeypatch) -> dict:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ster.project._git_root", lambda cwd: None)
    monkeypatch.setattr("ster.cli._home._git_root", lambda cwd: None)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    return {"root": tmp_path, "asked": 0, "monkeypatch": monkeypatch}


@given(parsers.parse('a project folder with "{top}" at the top and "{below}" one level down'))
def given_folder(ctx, top, below):
    _touch(ctx["root"], top, below)


@given(parsers.parse('the folder also holds "{a}", "{b}" and "{c}"'))
def given_more(ctx, a, b, c):
    _touch(ctx["root"], a, b, c)


def _start(ctx: dict, agree: bool) -> None:
    def ask(below):
        ctx["asked"] += 1
        return agree

    ctx["monkeypatch"].setattr(_workspace_ui, "ask_include_subfolders", ask)
    ctx["offered"] = _home._found_taxonomy_files()


@when("ster starts and I agree to include subfolders")
def when_agree(ctx):
    _start(ctx, True)


@when("ster starts and I decline to include subfolders")
def when_decline(ctx):
    _start(ctx, False)


@when("ster starts again")
def when_again(ctx):
    ctx["asked_before"] = ctx["asked"]
    _start(ctx, True)


@then(parsers.parse('ster offers "{a}" and "{b}"'))
def then_offers_two(ctx, a, b):
    assert ctx["offered"] == [ctx["root"] / a, ctx["root"] / b]


@then(parsers.parse('ster offers only "{a}"'))
def then_offers_one(ctx, a):
    assert ctx["offered"] == [ctx["root"] / a]


@then("I am not asked about subfolders the second time")
def then_not_asked_again(ctx):
    assert ctx["asked"] == ctx["asked_before"] == 1


@given(parsers.parse('I chose "{context}" as context for "{editable}" last time'))
def given_remembered(ctx, context, editable):
    project = Project(root=ctx["root"])
    project.remember_context(ctx["root"] / editable, [ctx["root"] / context])
    project.save()


@given(parsers.parse('"{name}" has since been deleted'))
def given_deleted(ctx, name):
    (ctx["root"] / name).unlink()


@given(parsers.parse('"{name}" is also in the folder'))
def given_also(ctx, name):
    _touch(ctx["root"], name)


@when(parsers.parse('I open "{editable}" again'))
def when_open_again(ctx, editable):
    def picker(e, found, ticked=()):
        ctx["ticked"] = list(ticked)
        return list(ticked)

    ctx["monkeypatch"].setattr(_workspace_ui, "prompt_for_context_files", picker)
    root = ctx["root"]
    offered = [root / editable, *[p for p in root.rglob("*.ttl") if p.name != editable]]
    _workspace_ui.context_files_for(root / editable, offered, Project.load(root))


@then(parsers.parse('"{context}" starts ticked in the context checklist'))
def then_ticked(ctx, context):
    assert ctx["ticked"] == [ctx["root"] / context]


@then("nothing starts ticked in the context checklist")
def then_nothing_ticked(ctx):
    assert ctx["ticked"] == []
