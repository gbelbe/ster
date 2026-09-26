"""BDD step definitions for tests/features/tui/semantic_history.feature."""

from __future__ import annotations

import asyncio
import io

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from rich.console import Console

from ster.cli import _constants, _workspace_ui
from ster.plugins.semanticdiff.history import open_history
from ster.plugins.semanticdiff.screen import HistoryScreen, _changes, _heading
from tests._ontology_repo import ONTOLOGY, RepoBuilder

scenarios("../features/tui/semantic_history.feature")

CLASS_A = "ex:A a owl:Class ."
CLASS_AB = "ex:A a owl:Class . ex:B a owl:Class ."


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given("an ontology file that is not in a git repository")
def given_loose_file(ctx, tmp_path):
    loose = tmp_path / "loose.ttl"
    loose.write_text("# not in git", encoding="utf-8")
    ctx["file"] = loose


@given("a repository whose ontology changed in two commits")
def given_two_commits(ctx, ontology_repo: RepoBuilder):
    ctx["first"] = ontology_repo.commit(ttl=CLASS_A, message="add A")
    ontology_repo.commit(ttl=CLASS_AB, message="add B")
    ctx["repo"] = ontology_repo
    ctx["file"] = ontology_repo.path / ONTOLOGY


@given(parsers.parse('the first commit is tagged "{tag}"'))
def given_tagged(ctx, tag):
    ctx["repo"]._git("tag", tag, ctx["first"])


# ── When ──────────────────────────────────────────────────────────────────────


@when("the home action menu is built")
def when_menu(ctx, monkeypatch):
    monkeypatch.setattr("ster.plugins.semanticdiff.is_active", lambda: True)
    ctx["actions"] = _workspace_ui._home_actions()


@when("the history is opened")
def when_open(ctx):
    ctx["history"] = open_history(ctx["file"])


@when("the history screen is opened")
def when_screen(ctx):
    ctx["history"] = open_history(ctx["file"])


# ── Then ──────────────────────────────────────────────────────────────────────


@then("it offers a semantic history row")
def then_row(ctx):
    assert any("History" in label for _s, label in ctx["actions"])


@then("that row carries its own sentinel")
def then_sentinel(ctx):
    assert _constants._HISTORY_SENTINEL in [s for s, _l in ctx["actions"]]


@then("no history is returned")
def then_none(ctx):
    assert ctx["history"] is None


@then("the newest commit is listed first")
def then_newest_first(ctx):
    assert [r.subject for r in ctx["history"].rows] == ["add B", "add A"]


# pytest-bdd calls step functions synchronously: an `async def` step is built
# into a coroutine and dropped, so its assertions never run and the scenario
# passes without testing anything. Each step below drives the app through
# asyncio.run instead.


def _render(renderable) -> str:
    console = Console(width=200, file=io.StringIO(), no_color=True)
    console.print(renderable)
    return console.file.getvalue()


def _drive(ctx, coro_factory):
    """Run one Textual session and return whatever the body asserts on.

    A fresh screen per step: a Textual App cannot be run twice, and a scenario
    with two Then steps would otherwise reuse one across event loops.
    """
    app = HistoryScreen(ctx["history"])

    async def _run():
        async with app.run_test() as pilot:
            return await coro_factory(app, pilot)

    return asyncio.run(_run())


@then(parsers.parse('the tag "{tag}" is shown beside that commit'))
def then_tag_shown(ctx, tag):
    async def body(app, _pilot):
        table = app.query_one("#commits")
        # index 2: the list is when · who · commit, and the tag rides the commit cell
        return [str(table.get_row_at(i)[2]) for i in range(table.row_count)]

    cells = _drive(ctx, body)
    assert any(tag in c for c in cells), cells


@then("the newest commit's changes are shown")
def then_changes_shown(ctx):
    history = ctx["history"]
    assert "ex:B" in _render(_changes(history, history.rows[0].sha))
    assert "add B" in _render(_heading(history.rows[0]))


@then("exactly one commit has been diffed")
def then_one_diffed(ctx):
    history = ctx["history"]
    history.changes(history.rows[0].sha)
    assert history.computed == 1


@then("no raw diff is shown")
def then_no_raw(ctx):
    async def body(app, _pilot):
        return app.query_one("#raw").has_class("hidden-pane")

    assert _drive(ctx, body) is True


@then(parsers.parse('pressing "{key}" shows the raw diff'))
def then_press_shows_raw(ctx, key):
    async def body(app, pilot):
        await pilot.press(key)
        return app.query_one("#raw").has_class("hidden-pane")

    assert _drive(ctx, body) is False
    assert "diff --git" in ctx["history"].raw(ctx["history"].rows[0].sha)
