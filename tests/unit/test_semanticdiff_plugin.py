"""The optional rdfdiff-backed Semantic History plugin."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ster import plugins
from ster.cli import _constants, _query_launcher, _workspace_ui
from ster.plugins import dependency, semanticdiff


def test_plugin_is_inactive_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(plugins, "is_enabled", lambda _plugin_id: False)
    monkeypatch.setattr(semanticdiff.deps, "is_installed", lambda: True)

    assert semanticdiff.is_active() is False


def test_plugin_is_inactive_when_rdfdiff_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(plugins, "is_enabled", lambda _plugin_id: True)
    monkeypatch.setattr(semanticdiff.deps, "is_installed", lambda: False)

    assert semanticdiff.is_active() is False


def test_plugin_is_active_only_when_enabled_and_installed(monkeypatch) -> None:
    monkeypatch.setattr(plugins, "is_enabled", lambda _plugin_id: True)
    monkeypatch.setattr(semanticdiff.deps, "is_installed", lambda: True)

    assert semanticdiff.is_active() is True


def test_dependency_guard_rejects_a_missing_rdfdiff_import(monkeypatch) -> None:
    monkeypatch.setattr(semanticdiff.deps.importlib.util, "find_spec", lambda _name: None)

    assert semanticdiff.deps.is_installed() is False


def test_dependency_guard_accepts_an_importable_rdfdiff(monkeypatch) -> None:
    monkeypatch.setattr(semanticdiff.deps.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(semanticdiff.deps.importlib, "import_module", lambda _name: object())

    assert semanticdiff.deps.is_installed() is True


def test_dependency_guard_rejects_a_broken_rdfdiff_import(monkeypatch) -> None:
    monkeypatch.setattr(semanticdiff.deps.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        semanticdiff.deps.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("broken rdfdiff")),
    )

    assert semanticdiff.deps.is_installed() is False


def test_dependency_guard_installs_rdfdiff_with_the_running_interpreter(monkeypatch) -> None:
    command: list[str] = []

    def run(args, **_kwargs):
        command.extend(args)
        return SimpleNamespace(returncode=0, stdout="installed", stderr="")

    monkeypatch.setattr(dependency.subprocess, "run", run)
    monkeypatch.setattr(
        dependency.importlib.util, "find_spec", lambda _name: object()
    )  # an interpreter with pip

    ok, output = semanticdiff.deps.install()

    assert ok is True
    assert command[:3] == [dependency.sys.executable, "-m", "pip"]
    assert command[-1] == "rdfdiff>=0.1"
    assert output == "installed"


def test_history_menu_row_is_hidden_when_plugin_is_inactive(monkeypatch) -> None:
    monkeypatch.setattr(semanticdiff, "is_active", lambda: False)

    actions = _workspace_ui._home_actions()

    assert _constants._HISTORY_SENTINEL not in [sentinel for sentinel, _label in actions]


def test_history_menu_row_is_shown_when_plugin_is_active(monkeypatch) -> None:
    monkeypatch.setattr(semanticdiff, "is_active", lambda: True)

    actions = _workspace_ui._home_actions()

    assert _constants._HISTORY_SENTINEL in [sentinel for sentinel, _label in actions]


def test_history_sentinel_is_not_dispatched_when_plugin_is_inactive(monkeypatch) -> None:
    monkeypatch.setattr(semanticdiff, "is_active", lambda: False)

    assert _query_launcher._dispatch_menu_action(_constants._HISTORY_SENTINEL, []) is False


def test_history_sentinel_is_dispatched_when_plugin_is_active(monkeypatch) -> None:
    called: list[list[Path]] = []
    monkeypatch.setattr(semanticdiff, "is_active", lambda: True)
    monkeypatch.setattr(
        "ster.cli._history._run_history_interactive", lambda files: called.append(files)
    )

    assert _query_launcher._dispatch_menu_action(_constants._HISTORY_SENTINEL, []) is True
    assert called == [[]]
