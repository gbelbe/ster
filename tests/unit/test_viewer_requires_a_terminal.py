"""The Textual viewer must refuse to start without a terminal.

Launching it under a pipe span the asyncio event loop at ~100% CPU forever: the
input driver selects on a non-tty stdin that is permanently readable at EOF, and
nothing ever delivers a quit. `ster` in a script or CI pipeline hangs there until
it is killed.
"""

from __future__ import annotations

import pytest

from ster import cli


def test_the_viewer_is_skipped_without_a_terminal(tmp_path, monkeypatch, capsys):
    launched: list[object] = []
    monkeypatch.setattr(cli, "_is_interactive_terminal", lambda: False)
    monkeypatch.setattr("ster.tui.launch_file", lambda *a, **k: launched.append(a))

    src = tmp_path / "o.ttl"
    src.write_text("", encoding="utf-8")
    cli._open_viewer(src)

    assert not launched, "the TUI must not run its event loop without a tty"
    assert "terminal" in capsys.readouterr().err.lower()  # a refusal belongs on stderr


def test_a_real_terminal_still_opens_the_viewer(tmp_path, monkeypatch):
    """The guard must not break the normal interactive path."""
    launched: list[object] = []
    monkeypatch.setattr(cli, "_is_interactive_terminal", lambda: True)
    monkeypatch.setattr(cli, "_prewarm_lint", lambda _p: None)
    monkeypatch.setattr(cli, "_start_git_fetch", lambda _gm: None)
    monkeypatch.setattr("ster.tui.launch_file", lambda *a, **k: launched.append(a))

    src = tmp_path / "o.ttl"
    src.write_text("", encoding="utf-8")
    cli._open_viewer(src)

    assert launched


@pytest.mark.parametrize(
    ("stdin_tty", "stdout_tty", "expected"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_both_streams_must_be_a_terminal(monkeypatch, stdin_tty, stdout_tty, expected):
    """Either half being a pipe is enough to break the driver."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: stdin_tty, raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: stdout_tty, raising=False)

    assert cli._is_interactive_terminal() is expected


# ── quitting is not a crash ───────────────────────────────────────────────────


def test_a_quit_from_inside_an_action_is_not_a_traceback(tmp_path, monkeypatch, capsys):
    """Regression: the home loop dumped a raw traceback on a clean quit.

    `_home_screen` runs outside typer's own runner, so a `typer.Exit` raised by a
    picker (Ctrl-D at "select a file", for instance) had nothing to translate it.
    The loop's guard covered only the action *choice*, not carrying it out.
    """
    import typer

    def quits(_action, _files):
        raise typer.Exit(0)

    monkeypatch.setattr(cli, "_found_taxonomy_files", lambda: [])
    chosen = tmp_path / "o.ttl"
    monkeypatch.setattr(cli, "_home_obtain_action", lambda *a: (chosen, [chosen]))
    monkeypatch.setattr(cli, "_dispatch_menu_action", quits)

    cli._home_screen()  # must return, not raise

    assert "Traceback" not in capsys.readouterr().err
