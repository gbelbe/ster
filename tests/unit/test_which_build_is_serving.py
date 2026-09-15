"""Which ster build drew this page, and what else is already serving.

Two installs commonly coexist on one machine — a `uv tool` copy and a project
venv, the latter often editable and tracking whichever branch is checked out. A
server started from one keeps serving *its* build until it is stopped, so
updating the other looks like it did nothing. It is doubly confusing because the
version string genuinely did change: the tool moved, the page did not come from
the tool.

Caching is not the cause and never was — the graph page has shipped
`Cache-Control: no-store` for exactly this reason. What was missing was any way
to see which build answered.
"""

from __future__ import annotations

from ster._version import __version__
from ster.viz_vowl import _app_js, other_ster_servers


def test_the_page_carries_the_build_that_drew_it():
    from ster import store
    from ster.viz_vowl import render_vowl_html

    taxonomy = store.load("ster/tui/demo.ttl")
    page = render_vowl_html(taxonomy, "ster/tui/demo.ttl", api_token="t")

    assert f'"sterVersion": "{__version__}"' in page


def test_the_version_is_shown_rather_than_only_sent():
    """Sending it without showing it would not have answered the question."""
    js = _app_js().replace(" ", "").replace("\n", "")

    assert "constver=globalThis.__STER_GRAPH__.sterVersion;" in js
    assert "if(ver)p.push('ster'+ver);" in js


def test_detecting_other_servers_never_raises():
    """Best-effort by design: this exists to explain a surprise, and must never
    be the reason a launch fails."""
    assert isinstance(other_ster_servers(), list)


def test_a_detected_server_is_a_pid_and_a_command():
    for pid, command in other_ster_servers():
        assert isinstance(pid, int)
        assert "ster serve" in command


def test_launching_reports_rather_than_kills():
    """Running several servers over different ontologies on different ports is
    normal. A new window silently closing the one you were reading is worse than
    the confusion it prevents, so this names them and stops there."""
    import inspect

    from ster.cli import _serve

    source = inspect.getsource(_serve._warn_about_other_servers)

    assert "kill" not in source.lower().split("killing them on launch")[0]
    assert "pkill" in source, "it tells you how, and leaves the choice to you"


# ── the detection's own branches ─────────────────────────────────────────────
# Driven with fake process output rather than by spawning servers: the point is
# the filtering rules, and a test that had to start real servers to check them
# would be both slow and unable to produce the awkward cases on demand.


def _fake_pgrep(monkeypatch, pids: str, commands: dict[int, str]) -> None:
    import subprocess

    from ster.viz_vowl import _server

    class _Result:
        stdout = pids

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
    monkeypatch.setattr(_server, "_process_name", lambda pid: commands.get(pid, ""))


def test_a_failing_pgrep_yields_nothing_rather_than_raising(monkeypatch):
    import subprocess

    def _boom(*_a, **_k):
        raise OSError("pgrep missing")

    monkeypatch.setattr(subprocess, "run", _boom)

    assert other_ster_servers() == []


def test_unparseable_output_is_skipped(monkeypatch):
    _fake_pgrep(monkeypatch, "not-a-pid\n", {})

    assert other_ster_servers() == []


def test_our_own_process_is_never_reported(monkeypatch):
    import os

    _fake_pgrep(monkeypatch, str(os.getpid()), {os.getpid(): "ster serve x.ttl"})

    assert other_ster_servers() == []


def test_a_shell_that_merely_mentions_the_phrase_is_not_a_server(monkeypatch):
    """`pgrep -f` matches command lines containing the words, so a script that
    greps for them looks exactly like a server until you check."""
    _fake_pgrep(monkeypatch, "4242", {4242: "/bin/zsh -c grep 'ster serve' log"})

    assert other_ster_servers() == []


def test_a_wrapper_and_the_process_it_execs_count_once(monkeypatch):
    """`uv run … ster serve X` and the python it execs are one server. They
    share everything after the subcommand, which is what identifies them."""
    _fake_pgrep(
        monkeypatch,
        "100\n101",
        {
            100: "uv run --project /repo ster serve onto.ttl --port 8899",
            101: "/repo/.venv/bin/python /repo/.venv/bin/ster serve onto.ttl --port 8899",
        },
    )

    found = other_ster_servers()

    assert len(found) == 1
    assert found[0][0] == 100


def test_genuinely_separate_servers_are_both_reported(monkeypatch):
    _fake_pgrep(
        monkeypatch,
        "200\n201",
        {200: "ster serve a.ttl --port 1", 201: "ster serve b.ttl --port 2"},
    )

    assert len(other_ster_servers()) == 2


def test_the_launch_warning_lists_what_it_found(monkeypatch, capsys):
    from ster.cli import _serve

    monkeypatch.setattr(_serve, "_warn_about_other_servers", _serve._warn_about_other_servers)
    monkeypatch.setattr(
        "ster.viz_vowl.other_ster_servers",
        lambda: [(4242, "ster serve other.ttl --port 9999")],
    )

    _serve._warn_about_other_servers()
    out = capsys.readouterr().out

    assert "4242" in out
    assert "pkill" in out


def test_the_launch_warning_says_nothing_when_there_is_nothing(monkeypatch, capsys):
    from ster.cli import _serve

    monkeypatch.setattr("ster.viz_vowl.other_ster_servers", list)

    _serve._warn_about_other_servers()

    assert capsys.readouterr().out == ""
