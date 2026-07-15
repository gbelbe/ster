"""CLI wiring for the New-TUI — the ``ster new-tui`` command, the home-menu
dispatch, and the non-interactive picker. ``ster.tui.launch`` is patched so the
Textual app never actually starts.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from ster.cli import (
    _AI_CONFIG_SENTINEL,
    _EXT_ONT_SENTINEL,
    _NEW_TUI_SENTINEL,
    _SUBCOMMANDS,
    _dispatch_menu_action,
    _launch_new_tui,
    _launch_query,
    _multi_file_picker,
    app,
)

_runner = CliRunner()
DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"


def test_new_tui_is_registered_subcommand():
    assert "new-tui" in _SUBCOMMANDS


def test_new_tui_sentinel_is_distinct():
    assert Path(".__ster_new_tui__") == _NEW_TUI_SENTINEL


def test_new_tui_command_loads_and_launches():
    with patch("ster.tui.launch") as launch:
        result = _runner.invoke(app, ["new-tui", str(DEMO)])
    assert result.exit_code == 0, result.output
    launch.assert_called_once()
    (taxonomy,), kwargs = launch.call_args
    assert kwargs.get("source") == "demo.ttl"
    assert taxonomy.owl_classes  # a real taxonomy was loaded and handed off


def test_launch_new_tui_menu_handler():
    with patch("ster.tui.launch") as launch:
        _launch_new_tui([DEMO])
    launch.assert_called_once()
    (taxonomy,), kwargs = launch.call_args
    assert kwargs.get("source") == "demo.ttl"


def test_launch_new_tui_with_no_files_is_noop():
    with patch("ster.tui.launch") as launch:
        _launch_new_tui([])
    launch.assert_not_called()


def test_launch_query_opens_the_new_tui_in_query_mode():
    with patch("ster.tui.launch") as launch:
        _launch_query([DEMO])
    launch.assert_called_once()
    (taxonomy,), kwargs = launch.call_args
    assert kwargs.get("open_query") is True
    assert kwargs.get("source") == "demo.ttl"
    assert taxonomy.owl_classes  # a real taxonomy was loaded and handed off


def test_launch_query_with_no_files_is_noop():
    with patch("ster.tui.launch") as launch:
        _launch_query([])
    launch.assert_not_called()


# ── home-menu dispatch ──────────────────────────────────────────────────────--


def test_dispatch_new_tui_sentinel():
    with patch("ster.tui.launch") as launch:
        handled = _dispatch_menu_action(_NEW_TUI_SENTINEL, [DEMO])
    assert handled is True
    launch.assert_called_once()


def test_dispatch_ext_ontologies_sentinel():
    with patch("ster.ext_ontologies_ui.run_ext_ontologies_screen") as run:
        handled = _dispatch_menu_action(_EXT_ONT_SENTINEL, [])
    assert handled is True
    run.assert_called_once()


def test_dispatch_non_sentinel_returns_false(tmp_path):
    # A real file selection (not a sentinel) is not handled here.
    assert _dispatch_menu_action(tmp_path / "x.ttl", []) is False
    assert _dispatch_menu_action([tmp_path / "x.ttl"], []) is False


# ── non-interactive picker (covers the fallback action menu) ───────────────────


def _no_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)


def test_picker_fallback_selects_new_tui(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="2"):
        assert _multi_file_picker(files) == _NEW_TUI_SENTINEL


def test_picker_fallback_open_tree_view(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="1"):
        assert _multi_file_picker(files) == files


def test_picker_fallback_other_actions(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="9"):
        assert _multi_file_picker(files) == _AI_CONFIG_SENTINEL
