"""BDD step definitions for tests/features/cli/talk_to_graph_menu.feature."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import cli
from ster.plugins import set_enabled

scenarios("../features/cli/talk_to_graph_menu.feature")


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict[str, Any]:
    monkeypatch.setattr("ster.nav.prefs._prefs_path", lambda: tmp_path / "prefs.json")
    return {"mp": monkeypatch}


@given(parsers.parse('the "MCP" plugin is {state}'))
def option(ctx: dict[str, Any], state: str) -> None:
    set_enabled("mcp", state == "on")


@given("an agent is usable")
def usable(ctx: dict[str, Any]) -> None:
    ctx["mp"].setattr("agent_app.launcher.has_usable_agent", lambda *a, **k: True)


@given("no agent is usable")  # noqa: V103
def unusable(ctx: dict[str, Any]) -> None:
    ctx["mp"].setattr("agent_app.launcher.has_usable_agent", lambda *a, **k: False)


@when("the home menu is built")
def build(ctx: dict[str, Any]) -> None:
    ctx["actions"] = cli._workspace_ui._home_actions()


def _labels(ctx: dict[str, Any]) -> list[str]:
    return [label for _s, label in ctx["actions"]]


@then(parsers.parse('the menu offers "{text}"'))  # noqa: V103
def offers(ctx: dict[str, Any], text: str) -> None:
    assert any(text in label for label in _labels(ctx))


@then(parsers.parse('the menu does not offer "{text}"'))  # noqa: V103
def does_not_offer(ctx: dict[str, Any], text: str) -> None:
    assert not any(text in label for label in _labels(ctx))


@then(parsers.parse('the "{text}" row is wired to a handler'))  # noqa: V103
def wired(ctx: dict[str, Any], text: str) -> None:
    sentinel = next(s for s, label in ctx["actions"] if text in label)
    handled: list[Any] = []
    ctx["mp"].setattr(
        cli._agent, "_run_agent_page_interactive", lambda files: handled.append(files)
    )
    assert cli._query_launcher._dispatch_menu_action(sentinel, ["f.ttl"]) is True
    assert handled == [["f.ttl"]]
