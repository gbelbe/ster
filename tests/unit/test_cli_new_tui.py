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


def test_select_home_file_offers_the_demo(tmp_path, monkeypatch):
    """The file list includes a 'Load demo' entry (after the files); picking it → _DEMO_SENTINEL."""
    from ster.cli import _DEMO_SENTINEL, _select_home_file

    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl"]
    with patch(
        "ster.cli.Prompt.ask", return_value=str(len(files) + 1)
    ):  # demo is right after files
        assert _select_home_file(files) == _DEMO_SENTINEL


def test_home_obtain_action_loads_a_fresh_demo_when_the_demo_is_picked(tmp_path, monkeypatch):
    """Picking the demo in the file list loads a fresh copy and opens it directly."""
    from ster.cli import _DEMO_SENTINEL, _home_obtain_action

    monkeypatch.chdir(tmp_path)
    with patch("ster.cli._select_home_file", return_value=_DEMO_SENTINEL):
        selected, action = _home_obtain_action(None, None, [])
    demo = tmp_path / "mixed-gear-demo.ttl"
    assert selected == demo and action == [demo] and demo.exists()  # fresh demo, opened directly


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


def test_action_menu_change_file_is_first(tmp_path, monkeypatch):
    """'Change file' is option 1 (the file list holds the local files + the demo)."""
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="1"):  # 1 = Change file
        assert _home_action_menu(f) == _CHANGE_FILE_SENTINEL


def test_action_menu_open_returns_the_selected_file(tmp_path, monkeypatch):
    """Option 2 (TTL Viewer-Editor) returns the selected file to open."""
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="2"):  # 2 = TTL Viewer-Editor
        assert _home_action_menu(f) == [f]


def test_action_menu_selects_import_external(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="7"):  # 7 = Import External Ontology
        assert _home_action_menu(f) == _EXT_ONT_SENTINEL


def test_action_menu_selects_quit(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="8"):  # 8 = Quit (last)
        assert _home_action_menu(f) == _QUIT_SENTINEL


def test_select_home_file_single_file_still_shows_the_picker(tmp_path, monkeypatch):
    """The picker always shows (so the demo is reachable); picking file 1 returns it."""
    _no_tty(monkeypatch)
    f = tmp_path / "only.ttl"
    with patch("ster.cli.Prompt.ask", return_value="1"):
        assert _select_home_file([f]) == f


def test_select_home_file_picks_from_multiple(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl", tmp_path / "c.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="3"):  # pick the 2nd file (b.ttl; 1 is Open all)
        assert _select_home_file(files) == files[1]


def test_select_home_file_quit_returns_none(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch(
        "ster.cli.Prompt.ask", return_value="5"
    ):  # 5 = Quit (Open all at 1, 2 files, demo at 4, quit at 5)
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
    """The user picks the 2nd file → it opens straight in the viewer; then a menu action
    (Query) dispatches with THAT file, not found[0] — the point of selecting it first."""
    from ster.cli import _QUERY_SENTINEL, _QUIT_SENTINEL, _home_screen

    a = tmp_path / "a.ttl"
    b = tmp_path / "b.ttl"
    for f in (a, b):
        f.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    dispatched: list[list] = []
    opened: list[list] = []

    def _fake_dispatch(action, found):
        if isinstance(action, list):  # the open-in-viewer action is not a menu action
            return False
        dispatched.append([action, list(found)])
        return True  # a menu sentinel → handled, loop continues

    # Turn 1: picking b opens the viewer directly. Turns 2-3: the action menu returns
    # Query, then Quit to end the loop.
    with (
        patch("ster.cli._select_home_file", return_value=b),  # user chose the 2nd file
        patch("ster.cli._home_action_menu", side_effect=[_QUERY_SENTINEL, _QUIT_SENTINEL]),
        patch("ster.cli._dispatch_menu_action", side_effect=_fake_dispatch),
        patch("ster.cli._open_selected_in_viewer", side_effect=lambda sel, *a: opened.append(sel)),
        patch("ster.cli._print_welcome"),
    ):
        _home_screen()
    assert opened == [[b]]  # the freshly picked file opened straight in the viewer
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


def test_home_screen_empty_folder_shows_the_picker_and_quits(tmp_path, monkeypatch):
    """An empty folder no longer dead-ends: the file picker (demo + Quit) still shows;
    quitting there returns cleanly."""
    from ster.cli import _home_screen

    monkeypatch.chdir(tmp_path)  # empty folder
    with (
        patch("ster.cli._select_home_file", return_value=None) as select,  # user quits at picker
        patch("ster.cli._print_welcome"),
    ):
        _home_screen()
    select.assert_called_once()  # the picker was offered even with no local files


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
        assert _home_action_menu(f) == [f]


def test_action_menu_out_of_range_defaults_to_open(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value="99"):  # out of range → default idx 0
        assert _home_action_menu(f) == [f]


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
        patch("ster.cli._open_selected_in_viewer"),  # turn 1 opens the viewer directly
        patch("ster.cli._print_welcome") as welcome,
        patch("ster.init_ci.prompt_if_missing", return_value=False),
    ):
        _home_screen()
    welcome.assert_called()  # the banner prints each home turn
    assert cli_module._ci_check_done is True  # the one-time CI check ran (guarded once)


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


def test_select_home_file_offers_open_all_when_multiple_files(tmp_path, monkeypatch):
    """When 2+ files are found, Option 1 is 'Open all project files' returning _ALL_FILES_SENTINEL."""
    from ster.cli import _ALL_FILES_SENTINEL, _select_home_file

    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="1"):  # 1 = Open all project files
        assert _select_home_file(files) == _ALL_FILES_SENTINEL


def test_home_obtain_action_returns_all_files_when_all_files_picked(tmp_path, monkeypatch):
    """Picking 'Open all' returns the primary file and the list of all files as the action target."""
    from ster.cli import _ALL_FILES_SENTINEL, _home_obtain_action

    monkeypatch.chdir(tmp_path)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch("ster.cli._select_home_file", return_value=_ALL_FILES_SENTINEL):
        selected, action = _home_obtain_action(None, None, files)
    assert selected == files[0] and action == files


def test_open_selected_in_viewer_passes_workspace_to_open_viewer(tmp_path, monkeypatch):
    from ster.cli import _open_selected_in_viewer

    src1 = tmp_path / "a.ttl"
    src2 = tmp_path / "b.ttl"
    src1.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    src2.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    passed_ws = []

    def fake_open_viewer(primary, workspace=None, lang="en"):
        passed_ws.append(workspace)

    with (
        patch("ster.cli._open_viewer", side_effect=fake_open_viewer),
    ):
        _open_selected_in_viewer([src1, src2], [src1, src2], None)

    assert len(passed_ws) == 1
    assert passed_ws[0] is not None
    assert set(passed_ws[0].taxonomies.keys()) == {src1, src2}


def test_found_taxonomy_files_includes_project_json_and_subdirectories(tmp_path, monkeypatch):
    """_found_taxonomy_files includes files listed in .ster/project.json and subfolders."""
    from ster.cli import _found_taxonomy_files
    from ster.project import Project

    sub = tmp_path / "sub"
    sub.mkdir()
    f1 = sub / "a.ttl"
    f2 = tmp_path / "b.ttl"
    f1.write_text("a", encoding="utf-8")
    f2.write_text("b", encoding="utf-8")

    proj = Project(root=tmp_path, files=[Path("sub/a.ttl"), Path("b.ttl")])
    proj.save()

    monkeypatch.chdir(tmp_path)
    found = _found_taxonomy_files()
    assert f1 in found and f2 in found


def test_main_with_multiple_ttl_arguments_opens_all_files(tmp_path, monkeypatch):
    import sys

    from ster.cli import main

    f1 = tmp_path / "a.ttl"
    f2 = tmp_path / "b.ttl"
    f1.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    f2.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")

    opened = []
    monkeypatch.setattr(sys, "argv", ["ster", str(f1), str(f2)])
    with patch(
        "ster.cli._home_screen", side_effect=lambda initial_file=None: opened.append(initial_file)
    ):
        main()

    assert len(opened) == 1
    assert opened[0] == [f1.resolve(), f2.resolve()]


def test_select_home_file_numeric_supports_comma_separated_selection(tmp_path, monkeypatch):
    """Entering e.g. '2,3' at the file prompt returns a list of selected files."""
    from ster.cli import _select_home_file

    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl", tmp_path / "c.ttl"]
    # 1 is Open all, 2 is a.ttl, 3 is b.ttl, 4 is c.ttl
    with patch("ster.cli.Prompt.ask", return_value="2, 4"):
        selected = _select_home_file(files)
        assert selected == [files[0], files[2]]


def test_home_obtain_action_handles_list_choice(tmp_path, monkeypatch):
    """When _select_home_file returns a list of files, _home_obtain_action returns primary file and list."""
    from ster.cli import _home_obtain_action

    monkeypatch.chdir(tmp_path)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch("ster.cli._select_home_file", return_value=[files[0], files[1]]):
        selected, action = _home_obtain_action(None, None, files)
    assert selected == files[0] and action == [files[0], files[1]]


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
