"""Opening the graph view when the live-server port is already held.

Regression: a previous graph window/process holding the port used to pop a
ChoiceModal, and clicking "Close it" then ran the blocking ``free_port`` on the
UI thread (freeze / "it bugs"). Desired behaviour — no modal: reclaim the port
(close the previous process) and open the graph directly; if it can't be freed,
fall back to the offline snapshot without prompting.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from ster import store, viz_vowl
from ster.tui.app import OntologyApp
from ster.tui.choice_modal import ChoiceModal

DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    from ster import api_server
    from ster.nav import prefs

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(api_server, "_SERVER_CONFIG_FILE", tmp_path / "server_config.json")
    monkeypatch.setattr(api_server, "_TOKEN_FILE", tmp_path / "api_token")


def _stub_graph(monkeypatch) -> dict:
    """Stub the viz_vowl entry points and record how the graph was opened."""
    rec: dict = {"opened": [], "freed": []}
    monkeypatch.setattr(viz_vowl, "is_live_server", lambda: False)
    monkeypatch.setattr(viz_vowl, "port_holder", lambda host=None, port=None: (1234, "old ster"))
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


def test_port_that_cannot_be_freed_still_opens_a_snapshot_no_modal(monkeypatch) -> None:
    """If the holder won't die, open_in_browser (which falls back to a static snapshot
    when the port is busy) is still called — no prompt, no crash."""
    rec = _stub_graph(monkeypatch)
    monkeypatch.setattr(viz_vowl, "free_port", lambda pid, **kw: rec["freed"].append(pid) or False)

    async def scenario() -> None:
        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("g")
            await pilot.pause()
            assert rec["freed"] == [1234]  # we tried to close it
            assert rec["opened"] == ["GLOBAL"]  # and still opened (snapshot fallback)
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
