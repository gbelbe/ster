"""CLI wiring for the New-TUI — the ``ster show`` command, the home-menu
dispatch, and the non-interactive picker. ``ster.tui.launch`` is patched so the
Textual app never actually starts.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ster.cli import (
    _CHANGE_FILE_SENTINEL,
    _EXT_ONT_SENTINEL,
    _QUIT_SENTINEL,
    _dispatch_menu_action,
    _home_action_menu,
    _launch_query,
    _select_home_file,
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


# ── load-demo home action ───────────────────────────────────────────────────--


def test_bundled_demo_is_a_valid_mixed_taxonomy():
    """The shipped sample loads and actually contains puns (concept+class) to showcase."""
    from ster import store
    from ster.cli import _DEMO_FILE

    tax = store.load(_DEMO_FILE)
    assert [u for u in tax.concepts if u in tax.owl_classes]  # has puns
    assert tax.owl_individuals  # has individuals to tag


def test_load_demo_resets_to_a_fresh_copy_each_time(tmp_path, monkeypatch):
    """The demo is a throwaway sandbox — reloading discards edits and restores pristine."""
    from ster.cli import _DEMO_FILE, _load_demo_into_cwd

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)  # non-interactive → silent reset
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)

    dest = _load_demo_into_cwd()
    assert dest == tmp_path / "mixed-gear-demo.ttl"
    assert dest.read_text(encoding="utf-8") == _DEMO_FILE.read_text(encoding="utf-8")

    dest.write_text("EDITED", encoding="utf-8")  # a local edit
    _load_demo_into_cwd()  # reload → reset
    assert dest.read_text(encoding="utf-8") == _DEMO_FILE.read_text(encoding="utf-8")  # discarded


def test_load_demo_offers_to_save_edits_before_resetting(tmp_path, monkeypatch):
    """When the local demo has edits, reloading offers to keep them under a new .ttl."""
    from ster.cli import _DEMO_FILE, _load_demo_into_cwd

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    dest = _load_demo_into_cwd()  # fresh (no prompt — nothing to keep yet)
    dest.write_text("MY EDITS", encoding="utf-8")
    with (
        patch("rich.prompt.Confirm.ask", return_value=True),
        patch("rich.prompt.Prompt.ask", return_value="my-work.ttl"),
    ):
        _load_demo_into_cwd()  # edits present → save-as, then reset
    assert (tmp_path / "my-work.ttl").read_text(encoding="utf-8") == "MY EDITS"  # kept
    assert dest.read_text(encoding="utf-8") == _DEMO_FILE.read_text(encoding="utf-8")  # reset


def test_home_action_menu_offers_load_demo():
    from ster.cli import _DEMO_SENTINEL, _home_actions

    assert any(s is _DEMO_SENTINEL for s, _label in _home_actions(allow_change=False))


def test_dispatch_demo_sentinel_loads_and_opens_the_demo(tmp_path, monkeypatch):
    from ster.cli import _DEMO_SENTINEL

    monkeypatch.chdir(tmp_path)
    with patch("ster.cli._open_viewer") as open_viewer:
        handled = _dispatch_menu_action(_DEMO_SENTINEL, [])
    assert handled is True
    open_viewer.assert_called_once()
    assert open_viewer.call_args[0][0] == tmp_path / "mixed-gear-demo.ttl"


def test_offer_demo_when_empty_loads_on_confirm_else_none(tmp_path, monkeypatch):
    from ster.cli import _offer_demo_when_empty

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    with patch("rich.prompt.Confirm.ask", return_value=True):
        assert _offer_demo_when_empty() == tmp_path / "mixed-gear-demo.ttl"
    (tmp_path / "mixed-gear-demo.ttl").unlink()
    with patch("rich.prompt.Confirm.ask", return_value=False):
        assert _offer_demo_when_empty() is None


def test_offer_demo_when_empty_is_noop_without_a_tty(tmp_path, monkeypatch):
    from ster.cli import _offer_demo_when_empty

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert _offer_demo_when_empty() is None  # never blocks a pipe / CI run


# ── graph: free a busy port by default (no phantom "install ster[api]") ─────────


def test_free_graph_port_closes_a_previous_process(monkeypatch):
    from ster import viz_vowl
    from ster.cli import _free_graph_port

    freed: list = []
    monkeypatch.setattr(viz_vowl, "is_live_server", lambda: False)
    monkeypatch.setattr(viz_vowl, "port_holder", lambda host=None, port=None: (999, "old graph"))
    monkeypatch.setattr(viz_vowl, "free_port", lambda pid, **k: freed.append(pid) or True)
    _free_graph_port()
    assert freed == [999]  # the leftover graph process on the port is closed


def test_free_graph_port_is_a_noop_when_live_or_port_free(monkeypatch):
    from ster import viz_vowl
    from ster.cli import _free_graph_port

    freed: list = []
    monkeypatch.setattr(viz_vowl, "free_port", lambda pid, **k: freed.append(pid) or True)
    monkeypatch.setattr(viz_vowl, "is_live_server", lambda: True)  # our server is live → skip
    _free_graph_port()
    monkeypatch.setattr(viz_vowl, "is_live_server", lambda: False)
    monkeypatch.setattr(viz_vowl, "port_holder", lambda host=None, port=None: None)  # free → skip
    _free_graph_port()
    assert freed == []


# ── non-interactive picker (covers the fallback action menu) ───────────────────


def _no_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)


def test_action_menu_option_one_opens_the_selected_file(tmp_path, monkeypatch):
    """Option 1 (Open Browser) returns the selected file to open — the actions all act on it."""
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="1"):
        assert _home_action_menu(f, allow_change=False) == [f]


def test_action_menu_selects_import_external(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="4"):  # 4 = Import External Ontology
        assert _home_action_menu(f, allow_change=False) == _EXT_ONT_SENTINEL


def test_action_menu_selects_load_demo(tmp_path, monkeypatch):
    from ster.cli import _DEMO_SENTINEL

    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="8"):  # 8 = Load demo
        assert _home_action_menu(f, allow_change=False) == _DEMO_SENTINEL


def test_action_menu_selects_quit(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="9"):  # 9 = Quit (no 'Change file' for 1 file)
        assert _home_action_menu(f, allow_change=False) == _QUIT_SENTINEL


def test_action_menu_offers_change_file_only_with_multiple_files(tmp_path, monkeypatch):
    """With >1 file, a 'Change file' action appears (option 9, before Quit at 10)."""
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="9"):  # 9 = Change file when allow_change
        assert _home_action_menu(f, allow_change=True) == _CHANGE_FILE_SENTINEL
    with patch("ster.cli.Prompt.ask", return_value="10"):  # 10 = Quit when allow_change
        assert _home_action_menu(f, allow_change=True) == _QUIT_SENTINEL


def test_select_home_file_returns_the_only_file_without_prompting(tmp_path, monkeypatch):
    """A single file is auto-selected — no picker shown."""
    _no_tty(monkeypatch)
    f = tmp_path / "only.ttl"
    with patch("ster.cli.Prompt.ask", side_effect=AssertionError("should not prompt")):
        assert _select_home_file([f]) == f


def test_select_home_file_picks_from_multiple(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl", tmp_path / "c.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="2"):  # pick the 2nd file
        assert _select_home_file(files) == files[1]


def test_select_home_file_quit_returns_none(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="3"):  # 3 = Quit (last, after 2 files)
        assert _select_home_file(files) is None


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
        patch("ster.cli._home_action_menu", return_value=_QUIT_SENTINEL),  # 2nd loop → quit
        patch("ster.cli._print_welcome"),
    ):
        _home_screen(initial_file=src)  # 1st loop opens the file
    load_workspace.assert_called_once()  # workspace validated
    open_viewer.assert_called_once()  # opened in the New-TUI


def test_home_screen_actions_use_the_chosen_file_not_the_first(tmp_path, monkeypatch):
    """The user picks the 2nd file, then a menu action (Query) → it dispatches with THAT file,
    not found[0] — the whole point of selecting the file first."""
    from ster.cli import _QUERY_SENTINEL, _QUIT_SENTINEL, _home_screen

    a = tmp_path / "a.ttl"
    b = tmp_path / "b.ttl"
    for f in (a, b):
        f.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    dispatched: list[list] = []

    def _fake_dispatch(action, found):
        dispatched.append([action, list(found)])
        return True  # handled → loop continues

    # first the action menu returns Query, then Quit to end the loop
    with (
        patch("ster.cli._select_home_file", return_value=b),  # user chose the 2nd file
        patch("ster.cli._home_action_menu", side_effect=[_QUERY_SENTINEL, _QUIT_SENTINEL]),
        patch("ster.cli._dispatch_menu_action", side_effect=_fake_dispatch),
        patch("ster.cli._print_welcome"),
    ):
        _home_screen()
    assert dispatched == [[_QUERY_SENTINEL, [b]]]  # Query dispatched with the chosen file b


def test_prewarm_lint_caches_then_skips_recompute(tmp_path, monkeypatch):
    """`_prewarm_lint` computes + caches the lint on first call (cache miss), then serves
    the cache on the second call for an unchanged file (no recompute)."""
    from ster import plugins
    from ster.cli import _prewarm_lint
    from ster.nav import prefs
    from ster.plugins.semanticlint import config, lint_cache, runner

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(config, "_config_path", lambda: tmp_path / "quality.json")
    monkeypatch.setattr(lint_cache, "_cache_path", lambda: tmp_path / "lint_cache.json")
    plugins.set_enabled("semanticlint", True)

    calls: list[int] = []
    monkeypatch.setattr(runner, "lint_overview", lambda p: calls.append(1) or ({"error": 0}, []))
    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")

    _prewarm_lint(src)
    assert calls == [1]  # first open → computed + cached
    _prewarm_lint(src)
    assert calls == [1]  # unchanged file → cache hit, not recomputed


def test_prewarm_lint_is_a_noop_when_semanticlint_is_off(tmp_path, monkeypatch):
    """With semanticlint disabled, pre-warming does nothing (no lint, no crash)."""
    from ster import plugins
    from ster.cli import _prewarm_lint
    from ster.nav import prefs

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    plugins.set_enabled("semanticlint", False)
    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    _prewarm_lint(src)  # must not raise


def test_prewarm_lint_swallows_lint_errors(tmp_path, monkeypatch):
    """A failure during pre-warm (e.g. lint raises) must never block opening the file."""
    from ster import plugins
    from ster.cli import _prewarm_lint
    from ster.nav import prefs
    from ster.plugins.semanticlint import config, lint_cache, runner

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(config, "_config_path", lambda: tmp_path / "quality.json")
    monkeypatch.setattr(lint_cache, "_cache_path", lambda: tmp_path / "lint_cache.json")
    plugins.set_enabled("semanticlint", True)

    def _boom(_p):
        raise RuntimeError("lint blew up")

    monkeypatch.setattr(runner, "lint_overview", _boom)
    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    _prewarm_lint(src)  # must not raise


def test_select_home_file_uses_the_arrow_picker_in_a_tty(tmp_path, monkeypatch):
    from ster.cli import _QUIT_SENTINEL, _select_home_file

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch("ster.cli._arrow_file_picker", return_value=files[1]):
        assert _select_home_file(files) == files[1]
    with patch("ster.cli._arrow_file_picker", return_value=_QUIT_SENTINEL):
        assert _select_home_file(files) is None  # Quit → None


def test_home_screen_exits_when_no_files(tmp_path, monkeypatch, capsys):
    from ster.cli import _home_screen

    monkeypatch.chdir(tmp_path)  # empty folder
    with patch("ster.cli._print_welcome"):
        _home_screen()  # no taxonomy files → prints a note and returns
    assert "No taxonomy files" in capsys.readouterr().out


def test_home_screen_change_file_reselects(tmp_path, monkeypatch):
    from ster.cli import _CHANGE_FILE_SENTINEL, _QUIT_SENTINEL, _home_screen

    a, b = tmp_path / "a.ttl", tmp_path / "b.ttl"
    for f in (a, b):
        f.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    select = MagicMock(side_effect=[a, b])
    with (
        patch("ster.cli._select_home_file", select),
        patch("ster.cli._home_action_menu", side_effect=[_CHANGE_FILE_SENTINEL, _QUIT_SENTINEL]),
        patch("ster.cli._print_welcome"),
    ):
        _home_screen()
    assert select.call_count == 2  # picked a file, chose 'Change file', picked again, quit


def test_open_selected_in_viewer_reports_a_workspace_error(tmp_path, monkeypatch):
    from ster.cli import _open_selected_in_viewer

    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with (
        patch("ster.cli._load_workspace", side_effect=RuntimeError("bad mapping")),
        patch("ster.cli._open_viewer") as open_viewer,
    ):
        _open_selected_in_viewer([src], [src], None)
    open_viewer.assert_not_called()  # a workspace error aborts before opening the viewer


def test_select_home_file_non_numeric_defaults_to_first(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="abc"):  # ValueError → default to first
        assert _select_home_file(files) == files[0]


def test_action_menu_non_numeric_defaults_to_open(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="abc"):  # ValueError → default idx 0 = Open
        assert _home_action_menu(f, allow_change=False) == [f]


def test_action_menu_out_of_range_defaults_to_open(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="99"):  # out of range → default idx 0
        assert _home_action_menu(f, allow_change=False) == [f]


def test_home_screen_runs_the_intro_and_ci_check_once(tmp_path, monkeypatch):
    import ster.cli as cli_module
    from ster.cli import _QUIT_SENTINEL, _home_screen

    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "_ci_check_done", False)
    with (
        patch("ster.cli._select_home_file", return_value=src),
        patch("ster.cli._home_action_menu", return_value=_QUIT_SENTINEL),
        patch("ster.cli._print_welcome") as welcome,
        patch("ster.init_ci.prompt_if_missing", return_value=False),
    ):
        _home_screen()
    welcome.assert_called_once()
    assert cli_module._ci_check_done is True  # the one-time CI check ran


def test_home_screen_quits_when_no_file_selected(tmp_path, monkeypatch):
    from ster.cli import _home_screen

    for name in ("a.ttl", "b.ttl"):
        (tmp_path / name).write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with (
        patch("ster.cli._select_home_file", return_value=None),  # user quit at file selection
        patch("ster.cli._home_action_menu") as menu,
        patch("ster.cli._print_welcome"),
    ):
        _home_screen()
    menu.assert_not_called()  # quitting at file selection never reaches the action menu


def test_open_selected_in_viewer_reports_a_viewer_error(tmp_path, monkeypatch):
    from ster.cli import _open_selected_in_viewer

    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with (
        patch("ster.cli._load_workspace"),
        patch("ster.cli._open_viewer", side_effect=RuntimeError("boom")),
    ):
        _open_selected_in_viewer([src], [src], None)  # a viewer error is caught, not raised
