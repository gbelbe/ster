"""Opening the graph view when the live-server port is already held.

Regression: a previous graph window/process holding the port used to pop a
ChoiceModal, and clicking "Close it" then ran the blocking ``free_port`` on the
UI thread (freeze / "it bugs"). Desired behaviour — no modal: reclaim the port
(close the previous process) and open the graph directly; if it can't be freed,
or it was never ours to close, report why and leave the graph closed — there
is no offline snapshot to fall back to.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from ster import store, viz_vowl
from ster.tui.app import OntologyApp
from ster.tui.choice_modal import ChoiceModal

pytestmark = pytest.mark.tui

DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    from ster import api_server
    from ster.nav import prefs

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(api_server, "_SERVER_CONFIG_FILE", tmp_path / "server_config.json")
    monkeypatch.setattr(api_server, "_TOKEN_FILE", tmp_path / "api_token")


def _stub_graph(monkeypatch, holder: str = "ster serve onto.ttl --port 8765") -> dict:
    """Stub the viz_vowl entry points and record how the graph was opened.

    *holder* is the command line of whatever has the port. It matters now: only
    a `ster serve` is reclaimed. The default is one, since that is what "a
    previous graph window" actually is — the old fixture said "old ster", which
    reads as an interactive session and would no longer be touched.
    """
    rec: dict = {"opened": [], "freed": []}
    monkeypatch.setattr(viz_vowl, "is_live_server", lambda: False)
    monkeypatch.setattr(viz_vowl, "port_holder", lambda host=None, port=None: (1234, holder))
    monkeypatch.setattr(
        viz_vowl,
        "open_in_browser",
        lambda tax, path=None, on_change_fn=None: rec["opened"].append("GLOBAL") or "http://g",
    )
    return rec


def _run(scenario: Callable[..., Awaitable[None]]) -> None:
    asyncio.run(scenario())


def test_port_conflict_reclaims_and_opens_without_a_modal(monkeypatch) -> None:
    rec = _stub_graph(monkeypatch)
    monkeypatch.setattr(viz_vowl, "free_port", lambda pid, **kw: rec["freed"].append(pid) or True)

    async def scenario() -> None:
        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("g")  # open the (global) graph
            await pilot.pause()
            # the previous process was closed, the graph opened, and NO modal appeared
            assert rec["freed"] == [1234]
            assert rec["opened"] == ["GLOBAL"]
            assert not isinstance(app.screen, ChoiceModal)
            assert not app.query(ChoiceModal)

    _run(scenario)


def test_port_that_cannot_be_freed_reports_it_without_opening(monkeypatch) -> None:
    """If the holder won't die, ster does not attempt to open the graph — there is
    no offline snapshot to fall back to, so trying would only raise a second,
    redundant error on top of the one already reported. No prompt, no crash."""
    rec = _stub_graph(monkeypatch)
    monkeypatch.setattr(viz_vowl, "free_port", lambda pid, **kw: rec["freed"].append(pid) or False)

    async def scenario() -> None:
        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert rec["freed"] == [1234]  # we tried to close it
            assert rec["opened"] == []  # and did not attempt to open — nothing to fall back to
            assert not app.query(ChoiceModal)

    _run(scenario)


def test_free_port_when_the_port_is_available(monkeypatch) -> None:
    """No holder → open straight away, never touching free_port."""
    rec = _stub_graph(monkeypatch)
    monkeypatch.setattr(viz_vowl, "port_holder", lambda host=None, port=None: None)
    monkeypatch.setattr(viz_vowl, "free_port", lambda pid, **kw: rec["freed"].append(pid) or True)

    async def scenario() -> None:
        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert rec["freed"] == []  # port was free — nothing to close
            assert rec["opened"] == ["GLOBAL"]

    _run(scenario)


def test_another_ster_session_on_the_port_is_left_running(monkeypatch) -> None:
    """The bug this guards: SIGTERM to another interactive session kills that
    TUI mid-render with mouse tracking still on, so its terminal fills with
    escape codes — and the person who lost the session is not the one who gets
    the message. The self-PID guard was the only protection, and it only ever
    covered our own process.
    """
    rec = _stub_graph(monkeypatch, holder="/Users/me/.local/bin/ster ontology/x.ttl")
    monkeypatch.setattr(viz_vowl, "free_port", lambda pid, **kw: rec["freed"].append(pid) or True)

    async def scenario() -> None:
        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()

    _run(scenario)

    assert rec["freed"] == [], "the other session must survive"
    assert rec["opened"] == [], "no snapshot to fall back to — the graph stays closed"


def test_a_process_that_is_not_ster_is_left_running(monkeypatch) -> None:
    """It was never ster's to kill. Before this, someone's dev server on the
    configured port would simply be SIGTERMed."""
    rec = _stub_graph(monkeypatch, holder="/usr/bin/python3 -m http.server 8765")
    monkeypatch.setattr(viz_vowl, "free_port", lambda pid, **kw: rec["freed"].append(pid) or True)

    async def scenario() -> None:
        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()

    _run(scenario)

    assert rec["freed"] == []
    assert rec["opened"] == []


def test_a_race_that_still_fails_to_open_is_reported_once_not_twice(monkeypatch) -> None:
    """Regression: unavailable_reason() used to carry its own "Couldn't open the
    graph:" prefix, and _open_graph_now's except-handler added a second one on
    top — so the one path where open_in_browser is actually called and still
    raises (port looked free/reclaimed, then wasn't by the time it tried to
    bind) showed the reader "Couldn't open the graph: Couldn't open the graph:
    ...". The reason clause now carries no framing of its own; each caller
    supplies exactly one."""
    monkeypatch.setattr(viz_vowl, "is_live_server", lambda: False)
    monkeypatch.setattr(viz_vowl, "port_holder", lambda host=None, port=None: None)

    def _raise(tax, path=None, on_change_fn=None):
        raise RuntimeError(viz_vowl._server.unavailable_reason(port=8765))

    monkeypatch.setattr(viz_vowl, "open_in_browser", _raise)

    notified: list[tuple[str, str]] = []

    async def scenario() -> None:
        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            def _record(message: str, *, severity: str = "information", **_kw) -> None:
                notified.append((message, severity))

            monkeypatch.setattr(app, "notify", _record)
            await pilot.press("g")
            await pilot.pause()

    _run(scenario)

    assert len(notified) == 1
    message, severity = notified[0]
    assert severity == "error"
    assert message.count("Couldn't open the graph:") == 1
    assert "isn't running" in message
