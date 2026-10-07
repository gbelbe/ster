"""The map and timeline retry a server that failed to start with the TUI."""

from __future__ import annotations

from ster.tui import query


def test_ensure_server_is_a_noop_when_the_server_is_running(monkeypatch):
    monkeypatch.setattr(query, "server_is_running", lambda: True)
    monkeypatch.setattr(
        "ster.viz_vowl.ensure_live_server", lambda *a, **k: (_ for _ in ()).throw(AssertionError)
    )

    assert query.ensure_server(object(), None) == ""


def test_ensure_server_starts_one_when_the_launch_attempt_failed(monkeypatch):
    started: list[bool] = []
    monkeypatch.setattr(query, "server_is_running", lambda: False)
    monkeypatch.setattr("ster.viz_vowl.ensure_live_server", lambda *a, **k: started.append(True))

    assert query.ensure_server(object(), None) == ""
    assert started == [True]


def test_ensure_server_returns_the_reason_a_held_port_gives(monkeypatch):
    """Regression: with a stale server on the port at launch the map said only
    "isn't running" and never retried; the TUI-holder case now names its next step."""

    def _blocked(*_a, **_k):
        raise RuntimeError("another ster session is open (x). Please close it first.")

    monkeypatch.setattr(query, "server_is_running", lambda: False)
    monkeypatch.setattr("ster.viz_vowl.ensure_live_server", _blocked)

    problem = query.ensure_server(object(), None)

    assert problem.startswith("Couldn't open the map: another ster session is open")
