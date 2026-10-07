"""Opening the TUI while another process holds the server port says so, once."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from ster import store
from ster.tui.app import OntologyApp
from ster.viz_vowl._claim import BLOCKED, Claim

pytestmark = pytest.mark.tui

DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"


def test_launch_with_the_port_held_by_another_session_warns_once(monkeypatch):
    import ster.tui.app._lifecycle as lifecycle

    done = threading.Event()

    def _failed_start(_tax, _path):
        done.set()
        return False  # the port was taken, so no server of our own

    monkeypatch.setattr(lifecycle, "_start_context_server", _failed_start)
    monkeypatch.setattr(
        "ster.viz_vowl.claim_port",
        lambda *_a, **_k: Claim(BLOCKED, "another ster session is open (x). Please close it."),
    )
    notices: list[tuple[str, str]] = []

    # On the class, before the app runs: the toast is raised from the startup
    # thread, which can fire before a test gets to wrap the instance.
    monkeypatch.setattr(
        OntologyApp,
        "notify",
        lambda _self, msg, **kw: notices.append((str(msg), kw.get("severity", ""))),
    )
    app = OntologyApp(store.load(DEMO), source="demo.ttl")

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(100):
                await pilot.pause(0.05)
                if done.is_set() and any("MCP is off" in m for m, _s in notices):
                    break

    asyncio.run(scenario())

    off = [(m, sev) for m, sev in notices if "MCP is off" in m]
    assert len(off) == 1
    assert off[0][1] == "warning"
