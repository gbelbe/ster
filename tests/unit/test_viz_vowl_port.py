"""Unit tests for the live-server port-conflict helpers in viz_vowl.

When the graph's live-server port is already taken, ster identifies the process
holding it (``port_holder``) and can gracefully free it (``free_port``) so the
TUI can warn the user and offer to close it — instead of silently degrading to
a read-only snapshot.
"""

from __future__ import annotations

from types import SimpleNamespace

import ster.viz_vowl as vv

# ── _listening_pid (lsof parsing) ───────────────────────────────────────────────


def test_listening_pid_parses_first_pid(monkeypatch) -> None:
    monkeypatch.setattr(vv.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="60130\n"))
    assert vv._listening_pid(8765) == 60130


def test_listening_pid_none_when_port_free(monkeypatch) -> None:
    monkeypatch.setattr(vv.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="\n"))
    assert vv._listening_pid(8765) is None


def test_listening_pid_none_when_lsof_missing(monkeypatch) -> None:
    def _raise(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(vv.subprocess, "run", _raise)
    assert vv._listening_pid(8765) is None  # never raises — best-effort


# ── port_holder (compose pid + command) ─────────────────────────────────────────


def test_port_holder_returns_pid_and_command(monkeypatch) -> None:
    monkeypatch.setattr(vv, "_listening_pid", lambda port: 60130)
    monkeypatch.setattr(vv, "_process_name", lambda pid: "ster show x.ttl")
    assert vv.port_holder(host="127.0.0.1", port=8765) == (60130, "ster show x.ttl")


def test_port_holder_none_when_free(monkeypatch) -> None:
    monkeypatch.setattr(vv, "_listening_pid", lambda port: None)
    assert vv.port_holder(host="127.0.0.1", port=8765) is None


# ── free_port (SIGTERM + wait for the port to free) ─────────────────────────────


def test_free_port_terminates_then_reports_free(monkeypatch) -> None:
    killed: list = []
    monkeypatch.setattr(vv.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    frees = iter([False, True])  # busy on the first poll, free on the second
    monkeypatch.setattr(vv, "_port_is_free", lambda host, port: next(frees))
    assert vv.free_port(60130, host="127.0.0.1", port=8765, poll=0) is True
    assert killed == [(60130, vv.signal.SIGTERM)]


def test_free_port_false_when_it_never_frees(monkeypatch) -> None:
    monkeypatch.setattr(vv.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(vv, "_port_is_free", lambda host, port: False)
    assert vv.free_port(60130, host="127.0.0.1", port=8765, timeout=0.0, poll=0) is False


def test_free_port_reports_port_state_when_kill_fails(monkeypatch) -> None:
    """A missing process (ProcessLookupError) is not an error — report the port state."""

    def _gone(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(vv.os, "kill", _gone)
    monkeypatch.setattr(vv, "_port_is_free", lambda host, port: True)
    assert vv.free_port(999999, host="127.0.0.1", port=8765) is True
