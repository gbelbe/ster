"""CLI wiring for the New-TUI — the ``ster show`` command, the home-menu
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
    _dispatch_menu_action,
    _launch_query,
    _multi_file_picker,
    app,
)

_runner = CliRunner()
DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"


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


def test_open_viewer_launches_the_new_tui():
    """`ster show` / the home-menu 'open' now launch the New-TUI (git disabled here)."""
    from ster.cli import _open_viewer

    with (
        patch("ster.tui.launch") as launch,
        patch("ster.git.manager.GitManager") as gm,
    ):
        gm.return_value.is_enabled.return_value = False
        _open_viewer(DEMO, lang="en")
    launch.assert_called_once()
    (taxonomy,), kwargs = launch.call_args
    assert kwargs.get("source") == "demo.ttl"
    assert kwargs.get("path") == DEMO
    assert taxonomy.owl_classes


def test_open_viewer_returns_early_when_the_file_fails_to_load():
    """A broken file (``_load_safe`` → None) short-circuits before launching the TUI."""
    from ster.cli import _open_viewer

    with (
        patch("ster.cli._load_safe", return_value=None),
        patch("ster.tui.launch") as launch,
    ):
        _open_viewer(DEMO, lang="en")
    launch.assert_not_called()


def test_open_viewer_pulls_and_pushes_when_git_is_enabled():
    """With git configured, the viewer waits on the remote fetch then commits on exit."""
    from ster.cli import _open_viewer

    with (
        patch("ster.tui.launch") as launch,
        patch("ster.git.manager.GitManager") as gm_cls,
    ):
        gm = gm_cls.return_value
        gm.is_enabled.return_value = True
        gm.is_configured.return_value = True
        gm.check_and_pull.return_value = ""  # no incoming diff to render
        _open_viewer(DEMO, lang="en")
    launch.assert_called_once()
    gm.check_and_pull.assert_called_once()  # fetch_event fired → pull path taken
    gm.commit_and_push.assert_called_once()


# ── home-menu dispatch ──────────────────────────────────────────────────────--


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


def test_picker_fallback_open_browser_is_option_one(tmp_path, monkeypatch):
    """Option 1 (the primary 'open') now opens the New-TUI browser — the separate
    'Open New-TUI' menu link was removed as redundant."""
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="1"):
        assert _multi_file_picker(files) == files


def test_picker_fallback_selects_import_external(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="4"):  # 4 = Import External Ontology
        assert _multi_file_picker(files) == _EXT_ONT_SENTINEL


def test_picker_fallback_other_actions(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="8"):  # 8 = Setup / Options
        assert _multi_file_picker(files) == _AI_CONFIG_SENTINEL


def test_show_command_opens_the_new_tui():
    """`ster show <file>` opens the New-TUI (via _open_viewer) with git disabled."""
    with (
        patch("ster.tui.launch") as launch,
        patch("ster.git.manager.GitManager") as gm,
    ):
        gm.return_value.is_enabled.return_value = False
        result = _runner.invoke(app, ["show", str(DEMO)])
    assert result.exit_code == 0, result.output
    launch.assert_called_once()


def test_home_screen_opens_selected_file_in_the_new_tui(tmp_path, monkeypatch):
    """The home-screen loop validates the workspace then opens the file in the New-TUI."""
    from ster.cli import _QUIT_SENTINEL, _home_screen

    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with (
        patch("ster.cli._open_viewer") as open_viewer,
        patch("ster.cli._load_workspace") as load_workspace,
        patch("ster.cli._multi_file_picker", return_value=_QUIT_SENTINEL),  # 2nd loop → quit
        patch("ster.cli._print_welcome"),
    ):
        _home_screen(initial_file=src)  # 1st loop opens the file
    load_workspace.assert_called_once()  # workspace validated
    open_viewer.assert_called_once()  # opened in the New-TUI
