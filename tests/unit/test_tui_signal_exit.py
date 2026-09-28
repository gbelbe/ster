"""Regression: a TUI stopped by SIGTERM or SIGHUP must give the terminal back.

Root cause: Textual turns mouse tracking off (``\\e[?1000l … \\e[?1006l``) only
on its own shutdown path — a quit key, or Ctrl+C / SIGINT. SIGTERM (``kill``,
``pkill``, an IDE's stop button) and SIGHUP (a dropped SSH session) end the
process on the spot, so the shell underneath stayed in SGR mouse mode and
printed a report such as ``35;42;17M`` for every mouse move — "numbers showing
up randomly in a terminal where ster was open before".

Every TUI entry point now runs through :func:`ster.tui._run.run_app`, which turns
those signals into a clean exit and then lets the process die of the signal as
before. These tests drive a real Textual app in a pseudo-terminal, because what
is being checked is the bytes the terminal receives.
"""

from __future__ import annotations

import inspect
import os
import re
import select
import signal
import subprocess
import sys
import textwrap
import time

import pytest

pytestmark = pytest.mark.tui

pty = pytest.importorskip("pty")  # POSIX only: the bug and the fix are about POSIX signals

MOUSE_ON = re.compile(rb"\x1b\[\?100[036]h")
MOUSE_OFF = (b"\x1b[?1000l", b"\x1b[?1006l")

_APP = textwrap.dedent(
    """
    import sys, time
    from textual.app import App
    from ster.tui._run import run_app

    class Probe(App):
        def on_mount(self):
            if sys.argv[1] == "stuck":
                time.sleep(60)  # the event loop is blocked: exit cannot be delivered

    run_app(Probe())
    """
)


def _run_in_pty(tmp_path, mode: str, signum: int) -> tuple[bytes, int, float]:
    """Start the probe app on a pseudo-terminal, wait until it enables the mouse,
    send *signum*.

    Returns what the terminal received after the signal, the wait status, and
    how long the process took to end. The probe is started with ``Popen`` rather
    than ``pty.fork()``: forking a multi-threaded pytest worker (coverage,
    xdist) can deadlock the child before it ever runs.
    """
    script = tmp_path / "probe.py"
    script.write_text(_APP, encoding="utf-8")
    main_fd, child_fd = pty.openpty()
    probe = subprocess.Popen(  # noqa: S603 - the probe, run by this interpreter
        [sys.executable, str(script), mode],
        stdin=child_fd,
        stdout=child_fd,
        stderr=child_fd,
        env={**os.environ, "TERM": "xterm-256color"},
        start_new_session=True,
        close_fds=True,
    )
    os.close(child_fd)
    try:
        out = bytearray()
        _read_until(main_fd, out, lambda: MOUSE_ON.search(out) is not None, timeout=30)
        assert MOUSE_ON.search(out), f"the app never enabled the mouse:\n{bytes(out)[-400:]!r}"
        mark = len(out)
        sent = time.monotonic()
        probe.send_signal(signum)
        status = _wait(main_fd, out, probe, timeout=15)
        return bytes(out[mark:]), status, time.monotonic() - sent
    finally:
        if probe.poll() is None:
            probe.kill()
            probe.wait()
        os.close(main_fd)


def _read_until(fd: int, out: bytearray, done, timeout: float) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end and not done():
        ready, _, _ = select.select([fd], [], [], 0.1)
        if ready:
            try:
                data = os.read(fd, 65536)
            except OSError:
                return
            if not data:
                return
            out.extend(data)


def _wait(fd: int, out: bytearray, probe: subprocess.Popen, timeout: float) -> int:
    """The probe's exit, as a raw wait status (so a death by signal can be told apart)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _read_until(fd, out, lambda: False, timeout=0.2)
        code = probe.poll()
        if code is not None:
            _read_until(fd, out, lambda: False, timeout=0.2)
            # Popen reports death by signal N as -N; turn it back into a wait status.
            return (-code) & 0x7F if code < 0 else code << 8
    pytest.fail(f"the app was still running {timeout}s after the signal")


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP], ids=["SIGTERM", "SIGHUP"])
def test_tui_signal_turns_mouse_tracking_off_regression(tmp_path, signum) -> None:
    after, status, _ = _run_in_pty(tmp_path, "normal", signum)

    for sequence in MOUSE_OFF:
        assert sequence in after, f"{sequence!r} never reached the terminal"


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP], ids=["SIGTERM", "SIGHUP"])
def test_tui_still_dies_of_the_signal(tmp_path, signum) -> None:
    """A clean exit, but still the exit the sender asked for: a parent (a shell,
    a supervisor, `timeout`) must see the process killed by that signal."""
    _, status, _ = _run_in_pty(tmp_path, "normal", signum)

    assert os.WIFSIGNALED(status)
    assert os.WTERMSIG(status) == signum


def test_a_stuck_tui_is_still_stopped_and_the_terminal_reset(tmp_path) -> None:
    """Handling SIGTERM must not make a frozen ster unkillable: when the event
    loop cannot deliver the exit, the terminal is reset directly and the process
    ends after a grace period."""
    from ster.tui import _run

    after, status, took = _run_in_pty(tmp_path, "stuck", signal.SIGTERM)

    for sequence in MOUSE_OFF:
        assert sequence in after
    assert os.WIFEXITED(status)
    assert os.WEXITSTATUS(status) == 128 + signal.SIGTERM
    assert took < _run.GRACE_SECONDS + 5


def test_every_tui_entry_point_runs_through_run_app() -> None:
    """A new entry point calling `App.run()` directly would reopen the bug."""
    from ster import tui
    from ster.plugins.semanticdiff import screen

    for function in (tui.launch, tui.launch_file, screen.run_history):
        source = inspect.getsource(function)
        assert "run_app(" in source, f"{function.__qualname__} bypasses run_app"
        assert ".run()" not in source, f"{function.__qualname__} calls App.run() directly"


def test_run_app_restores_the_previous_signal_handlers() -> None:
    """Outside the app, SIGTERM and SIGHUP behave exactly as before."""
    from textual.app import App

    from ster.tui._run import run_app

    class Quits(App[str]):
        def on_mount(self) -> None:
            self.exit("done")

    before = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP)}
    result = run_app(Quits(), headless=True)

    assert result == "done"
    assert {s: signal.getsignal(s) for s in before} == before


def test_run_app_goes_through_app_run_so_stubs_still_intercept() -> None:
    """Regression: run_app once drove `run_async` on a loop of its own, so a test
    stubbing `App.run` no longer intercepted anything — the real app started
    with no terminal and spun at 100% CPU, hanging the whole suite."""
    from unittest.mock import patch

    from textual.app import App

    from ster.tui._run import run_app

    with patch.object(App, "run", autospec=True, return_value="stubbed") as run:
        assert run_app(App()) == "stubbed"
    run.assert_called_once()


# ── The same pieces in-process, with the process-ending calls replaced ─────────
# The pseudo-terminal tests above prove the behaviour end to end, but in a child
# process that coverage does not see; these pin each step where it can be seen.


def test_a_signal_during_the_app_asks_it_to_exit_then_dies_of_it(monkeypatch) -> None:
    import asyncio
    from unittest.mock import MagicMock

    from ster.tui import _run

    died: list[int] = []
    monkeypatch.setattr(_run, "_die_of", died.append)
    monkeypatch.setattr(_run, "_start_watchdog", lambda signum, tty: None)
    app = MagicMock()

    def fake_run(**_kwargs):
        async def running() -> str:
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)  # the handler run_app installed
            await asyncio.sleep(0)
            return "result"

        return asyncio.run(running())

    app.run.side_effect = fake_run
    assert _run.run_app(app) == "result"
    app.exit.assert_called_once_with(return_code=128 + signal.SIGTERM)
    assert died == [signal.SIGTERM]


def test_a_second_signal_while_stopping_is_ignored(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from ster.tui import _run

    started: list[int] = []
    monkeypatch.setattr(_run, "_start_watchdog", lambda signum, tty: started.append(signum))
    app = MagicMock()

    _run._stop(app, [signal.SIGTERM], None, signal.SIGHUP, None)

    assert started == []
    app.exit.assert_not_called()


def test_a_signal_with_no_app_loop_takes_its_default_action(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from ster.tui import _run

    died: list[int] = []
    monkeypatch.setattr(_run, "_die_of", died.append)
    received: list[int] = []

    _run._stop(MagicMock(), received, None, signal.SIGTERM, None)

    assert died == [signal.SIGTERM]
    assert received == []


def test_off_the_main_thread_no_handler_is_installed() -> None:
    import threading

    from ster.tui import _run

    before = signal.getsignal(signal.SIGTERM)
    seen: list[object] = []

    def body() -> None:
        with _run._handling((signal.SIGTERM,), lambda *_: None):
            seen.append(signal.getsignal(signal.SIGTERM))

    worker = threading.Thread(target=body)
    worker.start()
    worker.join()

    assert seen == [before]


def test_the_watchdog_is_a_daemon_timer_of_the_grace_period(monkeypatch) -> None:
    from ster.tui import _run

    made: list[dict] = []

    class FakeTimer:
        def __init__(self, interval, function, args):
            made.append({"interval": interval, "function": function, "args": args})
            self.daemon = False

        def start(self) -> None:
            made[-1]["daemon"] = self.daemon

    monkeypatch.setattr(_run.threading, "Timer", FakeTimer)
    _run._start_watchdog(signal.SIGTERM, None)

    assert made == [
        {
            "interval": _run.GRACE_SECONDS,
            "function": _run._force_exit,
            "args": (signal.SIGTERM, None),
            "daemon": True,
        }
    ]


def test_forcing_the_exit_resets_the_terminal_and_restores_the_tty(monkeypatch) -> None:
    import termios

    from ster.tui import _run

    written: list[bytes] = []
    restored: list[tuple] = []
    exited: list[int] = []
    monkeypatch.setattr(_run.os, "write", lambda fd, data: written.append(data))
    monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, attrs: restored.append((fd, attrs)))
    monkeypatch.setattr(_run.os, "_exit", exited.append)
    monkeypatch.setattr(_run.sys, "__stdout__", _FakeStream())

    _run._force_exit(signal.SIGTERM, (7, ["saved"]))

    assert written == [_run._RESET]
    assert restored == [(7, ["saved"])]
    assert exited == [128 + signal.SIGTERM]


def test_forcing_the_exit_without_a_terminal_still_exits(monkeypatch) -> None:
    from ster.tui import _run

    exited: list[int] = []
    monkeypatch.setattr(_run.os, "_exit", exited.append)
    monkeypatch.setattr(_run.sys, "__stdout__", None)  # no stdout to write the reset to

    _run._force_exit(signal.SIGHUP, None)

    assert exited == [128 + signal.SIGHUP]


def test_no_termios_means_no_tty_to_save(monkeypatch) -> None:
    from ster.tui import _run

    monkeypatch.setitem(sys.modules, "termios", None)  # as on a platform without it

    assert _run._saved_tty() is None


def test_dying_of_a_signal_restores_its_default_action_first(monkeypatch) -> None:
    from ster.tui import _run

    calls: list[tuple] = []
    monkeypatch.setattr(
        _run.signal, "signal", lambda signum, handler: calls.append(("signal", signum, handler))
    )
    monkeypatch.setattr(_run.os, "kill", lambda pid, signum: calls.append(("kill", pid, signum)))

    _run._die_of(signal.SIGTERM)

    assert calls == [
        ("signal", signal.SIGTERM, signal.SIG_DFL),
        ("kill", os.getpid(), signal.SIGTERM),
    ]


class _FakeStream:
    def fileno(self) -> int:
        return 99
