"""A plugin that is on but whose package is missing says so, with the command that works where ster runs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ster import plugins
from ster.cli import _constants, _history, _query_launcher, _workspace_ui
from ster.plugins import dependency, semanticdiff
from ster.plugins.registry import get
from ster.tui.config_modal._plugins_mixin import _PluginsMixin

RECEIPT = '[tool]\nrequirements = [\n    { name = "ster", editable = "/src/ster" },\n    { name = "rdfdiff" },\n]\n'
PLAIN_RECEIPT = '[tool]\nrequirements = [\n    { name = "ster" },\n]\n'
DIFF, LINT = "semanticdiff", "semanticlint"


@pytest.fixture
def uv_tool(tmp_path, monkeypatch):
    """An environment that ``uv tool install`` made: its prefix holds a receipt."""

    def make(receipt: str | None = RECEIPT) -> Path:
        monkeypatch.setattr(sys, "prefix", str(tmp_path))
        if receipt is not None:
            (tmp_path / "uv-receipt.toml").write_text(receipt, encoding="utf-8")
        return tmp_path

    return make


# ── the command that fixes it ─────────────────────────────────────────────────


def test_an_ordinary_environment_is_told_to_install_the_extra(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    assert dependency.is_uv_tool_env() is False
    assert dependency.install_command(get(DIFF)) == "pip install 'ster[rdfdiff]'"  # type: ignore[arg-type]
    assert dependency.install_command(get(LINT)) == "pip install 'ster[semanticlint]'"  # type: ignore[arg-type]


def test_a_uv_tool_environment_is_told_to_reinstall_the_tool_keeping_what_it_has(uv_tool):
    uv_tool()
    assert dependency.is_uv_tool_env() is True
    assert dependency.install_command(get(LINT)) == (  # type: ignore[arg-type]
        "uv tool install --force --editable /src/ster --with rdfdiff --with semanticlint"
    )


def test_a_package_already_in_the_tool_is_not_listed_twice(uv_tool):
    uv_tool()
    assert dependency.install_command(get(DIFF)).count("--with rdfdiff") == 1  # type: ignore[arg-type]


def test_a_tool_installed_from_the_index_names_ster_not_a_path(uv_tool):
    uv_tool(PLAIN_RECEIPT)
    assert dependency.install_command(get(DIFF)) == "uv tool install --force ster --with rdfdiff"  # type: ignore[arg-type]


def test_a_tool_whose_receipt_cannot_be_read_still_gets_a_command(uv_tool):
    uv_tool("this is = not toml [")
    assert dependency.install_command(get(DIFF)) == "uv tool install --force ster --with rdfdiff"  # type: ignore[arg-type]


# ── whether it is missing ─────────────────────────────────────────────────────


def test_a_plugin_whose_package_is_missing_says_what_and_how(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr("ster.plugins.semanticdiff.deps.is_installed", lambda: False)
    message = plugins.missing_dependency(DIFF)
    assert message is not None
    assert "Semantic History" in message
    assert "semanticdiff package" in message
    assert message.endswith("Run: pip install 'ster[rdfdiff]'")


def test_a_plugin_whose_package_is_there_has_nothing_missing(monkeypatch):
    monkeypatch.setattr("ster.plugins.semanticdiff.deps.is_installed", lambda: True)
    assert plugins.missing_dependency(DIFF) is None


def test_a_plugin_with_no_package_and_an_unknown_one_have_nothing_missing():
    assert plugins.missing_dependency("mcp") is None
    assert plugins.missing_dependency("nope") is None


# ── installing ────────────────────────────────────────────────────────────────


class _Run:
    def __init__(self, code=0):
        self.commands: list[list[str]] = []
        self.code = code

    def __call__(self, command, **_kw):
        self.commands.append(command)
        return SimpleNamespace(returncode=self.code, stdout="out ", stderr="err")


def _no_pip(monkeypatch, has_pip: bool, uv: str | None):
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: (
            object() if name == "pip" and has_pip else (None if name == "pip" else real(name, *a))
        ),
    )
    monkeypatch.setattr(dependency.shutil, "which", lambda _name: uv)


def test_pip_is_used_when_this_interpreter_has_it(monkeypatch):
    run = _Run()
    monkeypatch.setattr(dependency.subprocess, "run", run)
    _no_pip(monkeypatch, has_pip=True, uv="/bin/uv")
    assert dependency.install("rdfdiff>=0.1.1") == (True, "out err")
    assert run.commands == [[sys.executable, "-m", "pip", "install", "rdfdiff>=0.1.1"]]


def test_uv_pip_is_used_where_there_is_no_pip(monkeypatch):
    run = _Run()
    monkeypatch.setattr(dependency.subprocess, "run", run)
    _no_pip(monkeypatch, has_pip=False, uv="/bin/uv")
    ok, _out = dependency.install("rdfdiff>=0.1.1")
    assert ok is True
    assert run.commands == [
        ["/bin/uv", "pip", "install", "--python", sys.executable, "rdfdiff>=0.1.1"]
    ]


def test_with_neither_the_result_says_so_instead_of_failing_unseen(monkeypatch):
    run = _Run()
    monkeypatch.setattr(dependency.subprocess, "run", run)
    _no_pip(monkeypatch, has_pip=False, uv=None)
    ok, out = dependency.install("rdfdiff>=0.1.1")
    assert ok is False
    assert "neither pip nor uv" in out
    assert run.commands == []


def test_a_failed_install_reports_failure_with_its_output(monkeypatch):
    monkeypatch.setattr(dependency.subprocess, "run", _Run(code=1))
    _no_pip(monkeypatch, has_pip=True, uv=None)
    assert dependency.install("x") == (False, "out err")


@pytest.mark.parametrize("module", ["semanticdiff", "semanticlint"])
def test_each_plugins_installer_goes_through_the_shared_one(monkeypatch, module):
    seen: list[str] = []
    monkeypatch.setattr(
        "ster.plugins.dependency.install",
        lambda requirement: seen.append(requirement) or (True, ""),
    )
    deps = __import__(f"ster.plugins.{module}.deps", fromlist=["install"])
    assert deps.install("pkg>=1") == (True, "")
    assert seen == ["pkg>=1"]


# ── where it is said ──────────────────────────────────────────────────────────


def test_the_plugins_tab_puts_the_problem_under_the_card(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr("ster.plugins.semanticdiff.deps.is_installed", lambda: False)
    [line] = _PluginsMixin._plugin_problem(None, DIFF)  # type: ignore[arg-type]
    assert "pip install 'ster[rdfdiff]'" in str(line.render())  # the brackets are text, not markup


def test_the_plugins_tab_adds_nothing_when_nothing_is_missing(monkeypatch):
    monkeypatch.setattr("ster.plugins.semanticdiff.deps.is_installed", lambda: True)
    assert _PluginsMixin._plugin_problem(None, DIFF) == []  # type: ignore[arg-type]


def _toggle(plugin_id: str, value: bool):
    notes: list[tuple] = []
    modal = SimpleNamespace(notify=lambda message, **kw: notes.append((message, kw)))
    event = SimpleNamespace(value=value, checkbox=SimpleNamespace(id=f"cfg-plugin-{plugin_id}"))
    _PluginsMixin._warn_when_plugin_cannot_run(modal, event)  # type: ignore[arg-type]
    return notes


def test_switching_on_a_plugin_that_cannot_run_warns(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr("ster.plugins.semanticdiff.deps.is_installed", lambda: False)
    [(message, kw)] = _toggle(DIFF, True)
    assert "pip install 'ster[rdfdiff]'" in message
    assert kw["severity"] == "warning"


def test_switching_a_plugin_off_or_one_that_can_run_says_nothing(monkeypatch):
    monkeypatch.setattr("ster.plugins.semanticdiff.deps.is_installed", lambda: False)
    assert _toggle(DIFF, False) == []
    monkeypatch.setattr("ster.plugins.semanticdiff.deps.is_installed", lambda: True)
    assert _toggle(DIFF, True) == []
    assert _toggle("mcp", True) == []


def test_the_home_menu_keeps_a_row_for_a_plugin_that_is_on_but_not_installed(monkeypatch):
    monkeypatch.setattr(semanticdiff, "is_active", lambda: False)
    monkeypatch.setattr(plugins, "is_enabled", lambda plugin_id: plugin_id == DIFF)
    rows = dict(_workspace_ui._home_actions())
    assert "not installed" in rows[_constants._HISTORY_SENTINEL]


def test_the_home_menu_has_no_row_for_a_plugin_that_is_off(monkeypatch):
    monkeypatch.setattr(semanticdiff, "is_active", lambda: False)
    monkeypatch.setattr(plugins, "is_enabled", lambda _plugin_id: False)
    assert _constants._HISTORY_SENTINEL not in dict(_workspace_ui._home_actions())


def test_choosing_that_row_prints_the_fix_instead_of_opening_nothing(monkeypatch):
    said: list[str] = []
    monkeypatch.setattr(semanticdiff, "is_active", lambda: False)
    monkeypatch.setattr(plugins, "is_enabled", lambda plugin_id: plugin_id == DIFF)
    monkeypatch.setattr(plugins, "missing_dependency", lambda _id: "needs the thing. Run: do it")
    monkeypatch.setattr(_history.console, "print", lambda text: said.append(text))
    assert (
        _query_launcher._dispatch_menu_action(_constants._HISTORY_SENTINEL, [Path("a.ttl")]) is True
    )
    assert "Run: do it" in said[0]


def _order(monkeypatch, agent_ready: bool) -> list[object]:
    from ster.plugins import talk_to_graph

    monkeypatch.setattr(semanticdiff, "is_active", lambda: True)
    monkeypatch.setattr(talk_to_graph, "agent_ready", lambda: agent_ready)
    return [sentinel for sentinel, _label in _workspace_ui._home_actions()]


def test_the_history_row_sits_just_above_the_mcp_row(monkeypatch):
    order = _order(monkeypatch, agent_ready=False)
    assert order.index(_constants._HISTORY_SENTINEL) == order.index(_constants._MCP_SENTINEL) - 1


def test_the_history_row_sits_just_above_the_agent_row_when_that_replaces_mcp(monkeypatch):
    order = _order(monkeypatch, agent_ready=True)
    assert order.index(_constants._HISTORY_SENTINEL) == order.index(_constants._AGENT_SENTINEL) - 1
