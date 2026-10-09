"""CLI wiring for the New-TUI — the ``ster show`` command, the home-menu
 dispatch, and the non-interactive picker. ``ster.tui.launch_file`` is patched so the
Textual app never actually starts.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ster import cli, store
from ster.cli import (
    _CHANGE_FILE_SENTINEL,
    _MCP_SENTINEL,
    _QUIT_SENTINEL,
    _dispatch_menu_action,
    _home_action_menu,
    _home_actions,
    _launch_query,
    _select_home_file,
    app,
)

pytestmark = pytest.mark.tui  # noqa: V107
PICKS_BEFORE_QUIT = 2


@pytest.fixture(autouse=True)  # noqa: V103
def _pretend_there_is_a_terminal(monkeypatch):
    """`_open_viewer` refuses to start the Textual app without a tty.

    Under pytest neither stream is a terminal, and the guard exists because the
    app spins its event loop at ~100% CPU forever there. These tests are about
    the launch wiring, so they stand in for the terminal the real user has.
    """
    monkeypatch.setattr(cli._viewer, "_is_interactive_terminal", lambda: True)


_runner = CliRunner()
DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"


def test_launch_query_opens_the_new_tui_in_query_mode():
    with patch("ster.tui.launch_file") as launch_file:
        _launch_query([DEMO])
    launch_file.assert_called_once()
    (path,), kwargs = launch_file.call_args
    assert kwargs.get("open_query") is True
    assert kwargs.get("source") == "demo.ttl"
    assert path == DEMO


def test_launch_query_with_no_files_is_noop():
    with patch("ster.tui.launch") as launch:
        _launch_query([])
    launch.assert_not_called()


def test_launch_file_starts_the_progressive_app(monkeypatch):
    """The file entry point delegates loading to the Textual app."""
    from ster.model import Taxonomy
    from ster.tui import launch_file

    app = MagicMock()
    app.tax = Taxonomy()
    app._loaded_successfully = True
    app_class = MagicMock(return_value=app)
    # launch_file imports OntologyApp from ster.tui.app at call time.
    monkeypatch.setattr("ster.tui.app.OntologyApp", app_class)

    result = launch_file(DEMO, source="chosen.ttl", lang="fr", open_query=True)

    assert result is app.tax
    app_class.assert_called_once_with(
        None,
        source="chosen.ttl",
        lang="fr",
        path=DEMO,
        open_query=True,
        progressive_startup=True,
        context=None,  # no context files were named
    )
    app.run.assert_called_once()


def test_launch_file_returns_none_when_the_app_does_not_load(monkeypatch):
    """A failed load leaves the caller with no taxonomy to persist."""
    from ster.tui import launch_file

    app = MagicMock()
    app._loaded_successfully = False
    app_class = MagicMock(return_value=app)
    monkeypatch.setattr("ster.tui.app.OntologyApp", app_class)

    assert launch_file(DEMO) is None
    app.run.assert_called_once()


def test_open_viewer_launches_the_new_tui():
    """`ster show` / the home-menu 'open' now launch the New-TUI (git disabled here)."""
    from ster.cli import _open_viewer

    with (
        patch("ster.tui.launch_file", return_value=store.load(DEMO)) as launch_file,
        patch("ster.git.manager.GitManager") as gm,
    ):
        gm.return_value.is_enabled.return_value = False
        _open_viewer(DEMO, lang="en")
    launch_file.assert_called_once()
    (path,), kwargs = launch_file.call_args
    assert kwargs.get("source") == "demo.ttl"
    assert path == DEMO


def test_open_viewer_returns_early_when_the_file_fails_to_load():
    """A broken file (``_load_safe`` → None) short-circuits before launching the TUI."""
    from ster.cli import _open_viewer

    with (
        patch("ster.cli._viewer._prewarm_lint"),
        patch("ster.tui.launch_file", return_value=None) as launch_file,
        patch("ster.git.manager.GitManager") as gm,
    ):
        gm.return_value.is_enabled.return_value = False
        _open_viewer(DEMO, lang="en")
    launch_file.assert_called_once()


def test_open_viewer_pulls_and_pushes_when_git_is_enabled():
    """With git configured, the viewer waits on the remote fetch then commits on exit."""
    from ster.cli import _open_viewer

    with (
        patch("ster.tui.launch_file", return_value=store.load(DEMO)) as launch_file,
        patch("ster.git.manager.GitManager") as gm_cls,
    ):
        gm = gm_cls.return_value
        gm.is_enabled.return_value = True
        gm.is_configured.return_value = True
        gm.check_and_pull.return_value = ""  # no incoming diff to render
        _open_viewer(DEMO, lang="en")
    launch_file.assert_called_once()
    gm.check_and_pull.assert_called_once()  # fetch_event fired → pull path taken
    gm.commit_and_push.assert_called_once()


def test_open_viewer_backconverts_after_a_rdfxml_session(monkeypatch):
    """A viewer session still offers RDF/XML back-conversion when the TTL changed."""
    from ster.cli import _open_viewer

    original = DEMO.with_suffix(".rdf")
    with (
        patch("ster.tui.launch_file", return_value=store.load(DEMO)),
        patch("ster.git.manager.GitManager") as gm,
        patch("ster.cli._state.converted_from", original),
        patch("ster.cli.store.file_hash", return_value="before"),
        patch("ster.cli._rdfxml._maybe_backconvert") as backconvert,
    ):
        gm.return_value.is_enabled.return_value = False
        _open_viewer(DEMO, lang="en")

    backconvert.assert_called_once_with(DEMO, "before", original)


# ── home-menu dispatch ──────────────────────────────────────────────────────--


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
    with patch("ster.cli._workspace_ui._select_home_file", return_value=_DEMO_SENTINEL):
        selected, action = _home_obtain_action(None, None, [])
    demo = tmp_path / "mixed-gear-demo.ttl"
    assert selected == demo and action == [demo] and demo.exists()  # fresh demo, opened directly


# ── graph: free a busy port by default (no phantom "install ster[api]") ─────────


def _claim_stub(monkeypatch, *, outcome: str, message: str = ""):
    from ster import viz_vowl
    from ster.viz_vowl._claim import Claim

    asked: list = []
    monkeypatch.setattr(viz_vowl, "is_live_server", lambda: False)

    def _claim(taxonomy_file, confirm=None, host=None, port=None):
        asked.append(confirm)
        return Claim(outcome, message)

    monkeypatch.setattr(viz_vowl, "claim_port", _claim)
    return asked


def test_free_graph_port_asks_before_closing_a_previous_server(monkeypatch):
    from ster.cli import _free_graph_port
    from ster.cli._publish import _confirm_replace

    asked = _claim_stub(monkeypatch, outcome="free")

    assert _free_graph_port(Path("tax.ttl")) is True
    assert asked == [_confirm_replace]  # the CLI never replaces a view without asking


def test_free_graph_port_reports_a_blocked_port_and_refuses(monkeypatch):
    from ster import cli
    from ster.cli import _free_graph_port

    _claim_stub(monkeypatch, outcome="blocked", message="another ster session is open (x)")

    with cli._app.err.capture() as captured:
        assert _free_graph_port(Path("tax.ttl")) is False

    assert "another ster session is open" in captured.get()


def test_free_graph_port_is_a_noop_when_our_server_is_live(monkeypatch):
    from ster import viz_vowl
    from ster.cli import _free_graph_port

    called: list = []
    monkeypatch.setattr(viz_vowl, "is_live_server", lambda: True)
    monkeypatch.setattr(viz_vowl, "claim_port", lambda *a, **k: called.append(a))

    assert _free_graph_port(Path("tax.ttl")) is True
    assert called == []


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


def _row_number(sentinel: object) -> str:
    """The 1-based menu number for *sentinel*.

    Derived rather than hardcoded: these tests used fixed numbers, so inserting
    a row silently retargeted them at their neighbour.
    """
    return str([s for s, _label in _home_actions()].index(sentinel) + 1)


def test_action_menu_selects_quit(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value=_row_number(_QUIT_SENTINEL)):
        assert _home_action_menu(f) == _QUIT_SENTINEL


def test_action_menu_selects_connect_mcp(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    f = tmp_path / "a.ttl"
    with patch("ster.cli.Prompt.ask", return_value=_row_number(_MCP_SENTINEL)):
        assert _home_action_menu(f) == _MCP_SENTINEL


def test_select_home_file_single_file_still_shows_the_picker(tmp_path, monkeypatch):
    """The picker always shows (so the demo is reachable); picking file 1 returns it."""
    _no_tty(monkeypatch)
    f = tmp_path / "only.ttl"
    with patch("ster.cli.Prompt.ask", return_value="1"):
        assert _select_home_file([f]) == f


def test_select_home_file_picks_from_multiple(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl", tmp_path / "c.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="2"):  # pick the 2nd file
        assert _select_home_file(files) == files[1]


def test_select_home_file_quit_returns_none(tmp_path, monkeypatch):
    _no_tty(monkeypatch)
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="4"):  # 4 = Quit (2 files, then demo at 3)
        assert _select_home_file(files) is None


def test_show_command_opens_the_new_tui():
    """`ster show <file>` opens the New-TUI (via _open_viewer) with git disabled."""
    with (
        patch("ster.tui.launch_file") as launch_file,
        patch("ster.git.manager.GitManager") as gm,
    ):
        gm.return_value.is_enabled.return_value = False
        result = _runner.invoke(app, ["show", str(DEMO)])
    assert result.exit_code == 0, result.output
    launch_file.assert_called_once()


def test_home_screen_opens_selected_file_in_the_new_tui(tmp_path, monkeypatch):
    """The home-screen loop validates the workspace then opens the file in the New-TUI."""
    from ster.cli import _QUIT_SENTINEL, _home_screen

    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with (
        patch("ster.cli._viewer._open_viewer") as open_viewer,
        patch("ster.cli._workspace_ui._load_workspace") as load_workspace,
        patch(
            "ster.cli._workspace_ui._home_action_menu", return_value=_QUIT_SENTINEL
        ),  # 2nd loop → quit
        patch("ster.cli._app._print_welcome"),
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
        patch(
            "ster.cli._workspace_ui._select_home_file", return_value=b
        ),  # user chose the 2nd file
        patch(
            "ster.cli._workspace_ui._home_action_menu",
            side_effect=[_QUERY_SENTINEL, _QUIT_SENTINEL],
        ),
        patch("ster.cli._query_launcher._dispatch_menu_action", side_effect=_fake_dispatch),
        patch(
            "ster.cli._home._open_selected_in_viewer",
            side_effect=lambda sel, *a: opened.append(sel),
        ),
        patch("ster.cli._app._print_welcome"),
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
    with patch("ster.cli._file_picker._arrow_file_picker", return_value=files[1]):
        assert _select_home_file(files) == files[1]
    with patch("ster.cli._file_picker._arrow_file_picker", return_value=_QUIT_SENTINEL):
        assert _select_home_file(files) is None  # Quit → None


def test_home_screen_empty_folder_shows_the_picker_and_quits(tmp_path, monkeypatch):
    """An empty folder no longer dead-ends: the file picker (demo + Quit) still shows;
    quitting there returns cleanly."""
    from ster.cli import _home_screen

    monkeypatch.chdir(tmp_path)  # empty folder
    with (
        patch(
            "ster.cli._workspace_ui._select_home_file", return_value=None
        ) as select,  # user quits at picker
        patch("ster.cli._app._print_welcome"),
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
        patch("ster.cli._workspace_ui._select_home_file", select),
        patch(
            "ster.cli._workspace_ui._home_action_menu",
            side_effect=[_CHANGE_FILE_SENTINEL, _QUIT_SENTINEL],
        ),
        patch("ster.cli._app._print_welcome"),
        # Two files in the folder, so opening one now asks which others to load
        # read-only. This test is about reselection; answering it is not its job.
        patch("ster.cli._workspace_ui.context_files_for", return_value=[]),
    ):
        _home_screen()
    assert (
        select.call_count == PICKS_BEFORE_QUIT
    )  # picked a file, chose 'Change file', picked again, quit


def test_open_selected_in_viewer_reports_a_workspace_error(tmp_path, monkeypatch):
    from ster.cli import _open_selected_in_viewer

    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with (
        patch("ster.cli._workspace_ui._load_workspace", side_effect=RuntimeError("bad mapping")),
        patch("ster.cli._viewer._open_viewer") as open_viewer,
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
    monkeypatch.setattr(cli_module._state, "ci_check_done", False)
    with (
        patch("ster.cli._workspace_ui._select_home_file", return_value=src),
        patch("ster.cli._workspace_ui._home_action_menu", return_value=_QUIT_SENTINEL),
        patch("ster.cli._home._open_selected_in_viewer"),  # turn 1 opens the viewer directly
        patch("ster.cli._app._print_welcome") as welcome,
        patch("ster.init_ci.prompt_if_missing", return_value=False),
    ):
        _home_screen()
    welcome.assert_called()  # the banner prints each home turn
    assert cli_module._state.ci_check_done is True  # the one-time CI check ran (guarded once)


def test_home_screen_quits_when_no_file_selected(tmp_path, monkeypatch):
    from ster.cli import _home_screen

    for name in ("a.ttl", "b.ttl"):
        (tmp_path / name).write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with (
        patch(
            "ster.cli._workspace_ui._select_home_file", return_value=None
        ),  # user quit at file selection
        patch("ster.cli._workspace_ui._home_action_menu") as menu,
        patch("ster.cli._app._print_welcome"),
    ):
        _home_screen()
    menu.assert_not_called()  # quitting at file selection never reaches the action menu


def test_open_selected_in_viewer_reports_a_viewer_error(tmp_path, monkeypatch):
    from ster.cli import _open_selected_in_viewer

    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with (
        patch("ster.cli._workspace_ui._load_workspace"),
        patch("ster.cli._viewer._open_viewer", side_effect=RuntimeError("boom")),
    ):
        _open_selected_in_viewer([src], [src], None)  # a viewer error is caught, not raised


# ── git-fetch/pull/push helpers (ster/cli/_viewer.py) ───────────────────────


def test_start_git_fetch_disabled_returns_none():
    from ster.cli._viewer import _start_git_fetch

    gm = MagicMock()
    gm.is_enabled.return_value = False
    assert _start_git_fetch(gm) is None
    gm.setup.assert_not_called()


def test_start_git_fetch_setup_fails_returns_none():
    """Not configured, and setup() doesn't fix it → no background fetch is started."""
    from ster.cli._viewer import _start_git_fetch

    gm = MagicMock()
    gm.is_enabled.return_value = True
    gm.is_configured.return_value = False
    assert _start_git_fetch(gm) is None
    gm.setup.assert_called_once()


def test_start_git_fetch_swallows_fetch_errors():
    """The background thread's own fetch_remote() exception must not escape."""
    from ster.cli._viewer import _start_git_fetch

    gm = MagicMock()
    gm.is_enabled.return_value = True
    gm.is_configured.return_value = True
    gm.fetch_remote.side_effect = RuntimeError("network down")
    event = _start_git_fetch(gm)
    assert event is not None
    assert event.wait(timeout=5)  # the finally-block still sets the event
    gm.record_head.assert_called_once()


def test_finish_configured_git_renders_pulled_diff():
    from ster.cli._viewer import _finish_configured_git

    gm = MagicMock()
    gm.check_and_pull.return_value = "+added line"
    event = threading.Event()
    event.set()
    with patch("ster.git.manager.render_diff") as render_diff:
        _finish_configured_git(gm, event)
    render_diff.assert_called_once_with("+added line")
    gm.commit_and_push.assert_called_once()


def test_finish_configured_git_no_fetch_event_skips_pull():
    from ster.cli._viewer import _finish_configured_git

    gm = MagicMock()
    _finish_configured_git(gm, None)
    gm.check_and_pull.assert_not_called()
    gm.commit_and_push.assert_called_once()


def test_finish_configured_git_swallows_keyboard_interrupt():
    from ster.cli._viewer import _finish_configured_git

    gm = MagicMock()
    gm.commit_and_push.side_effect = KeyboardInterrupt
    _finish_configured_git(gm, None)  # must not propagate


def test_finish_configured_git_reports_commit_error():
    from ster.cli._viewer import _finish_configured_git

    gm = MagicMock()
    gm.commit_and_push.side_effect = RuntimeError("push rejected")
    _finish_configured_git(gm, None)  # caught and reported, not raised


def test_offer_git_tracking_declined():
    from ster.cli._viewer import _offer_git_tracking

    gm = MagicMock()
    with patch("rich.prompt.Confirm.ask", return_value=False):
        _offer_git_tracking(gm, MagicMock(), Path("t.ttl"))
    gm.setup.assert_not_called()


def test_offer_git_tracking_accepted_and_configured():
    from ster.cli._viewer import _offer_git_tracking

    gm = MagicMock()
    gm.is_configured.return_value = True
    taxonomy = MagicMock()
    with (
        patch("rich.prompt.Confirm.ask", return_value=True),
        patch("ster.cli._export._make_taxonomy_commit_msg", return_value="msg"),
    ):
        _offer_git_tracking(gm, taxonomy, Path("t.ttl"))
    gm.setup.assert_called_once()
    gm.commit_new_taxonomy.assert_called_once_with("msg")


def test_offer_git_tracking_cancelled_treated_as_declined():
    from ster.cli._viewer import _offer_git_tracking

    gm = MagicMock()
    with patch("rich.prompt.Confirm.ask", side_effect=KeyboardInterrupt):
        _offer_git_tracking(gm, MagicMock(), Path("t.ttl"))
    gm.setup.assert_not_called()


def test_handle_viewer_git_disabled_is_a_noop():
    from ster.cli._viewer import _handle_viewer_git

    gm = MagicMock()
    gm.is_enabled.return_value = False
    _handle_viewer_git(gm, MagicMock(), Path("t.ttl"), None)
    gm.is_configured.assert_not_called()


def test_handle_viewer_git_not_configured_offers_tracking():
    from ster.cli._viewer import _handle_viewer_git

    gm = MagicMock()
    gm.is_enabled.return_value = True
    gm.is_configured.return_value = False
    with patch("ster.cli._viewer._offer_git_tracking") as offer:
        _handle_viewer_git(gm, MagicMock(), Path("t.ttl"), None)
    offer.assert_called_once()


def test_print_home_intro_reports_ci_workflow_created(tmp_path, monkeypatch):
    import ster.cli as cli_module
    from ster.cli import _print_home_intro

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(cli_module._state, "ci_check_done", False)
    with (
        patch("ster.cli._app._print_welcome"),
        patch("ster.project._git_root", return_value=tmp_path),
        patch("ster.init_ci.prompt_if_missing", return_value=True),
    ):
        _print_home_intro()
    assert cli_module._state.ci_check_done is True


def test_found_taxonomy_files_globs_and_dedupes(tmp_path, monkeypatch):
    from ster.cli._home import _found_taxonomy_files

    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.ttl").write_text("", encoding="utf-8")
    (tmp_path / "b.owl").write_text("", encoding="utf-8")
    found = _found_taxonomy_files()
    assert {p.name for p in found} == {"a.ttl", "b.owl"}


def test_open_selected_in_viewer_tolerates_project_save_failure(tmp_path, monkeypatch):
    from ster.cli import _open_selected_in_viewer

    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with (
        patch("ster.project.Project.save", side_effect=OSError("read-only fs")),
        patch("ster.cli._workspace_ui._load_workspace"),
        patch("ster.cli._viewer._open_viewer"),
    ):
        _open_selected_in_viewer([src], [src], None)  # save() error is non-fatal


def test_home_screen_keyboard_interrupt_breaks_the_loop(tmp_path, monkeypatch):
    from ster.cli import _home_screen

    monkeypatch.chdir(tmp_path)
    with (
        patch("ster.cli._app._print_welcome"),
        patch("ster.cli._home._found_taxonomy_files", side_effect=KeyboardInterrupt),
    ):
        _home_screen()  # caught and the loop simply breaks, no traceback
