"""A background lint that lands after the view is gone must not crash.

The lint is debounced 1.5 s behind the edit that schedules it, and the app can
go in between — the user quits, or a working-file switch tears the panes down.
``_on_lint_ready`` then rebuilt a tree that no longer existed and Textual
reported it as ``WorkerFailed``.

It surfaced as an intermittent test failure under ``-n auto``, which is how it
was found; in the wild it is a crash on quit for anyone who exits within a
second or two of an edit. ``_refresh_busy`` already guards the other end of the
same lifecycle — a job scheduled before the UI mounts — and this is that guard's
twin.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ster import store
from ster.tui.app import OntologyApp

DEMO = Path(__file__).resolve().parents[1].parent / "ster" / "tui" / "demo.ttl"


def _app(tmp_path: Path) -> OntologyApp:
    src = tmp_path / "o.ttl"
    src.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src)


def test_a_lint_result_after_the_app_stops_is_dropped_not_raised(tmp_path: Path) -> None:
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()

    asyncio.run(scenario())

    # The worker's callback, arriving late. Before the guard this raised
    # NoMatches("No nodes match '#tree'") from _rebuild_tree.
    app._on_lint_ready(({"error": 0, "warning": 0, "info": 0}, []))


def test_the_panes_are_reported_mounted_while_the_app_runs(tmp_path: Path) -> None:
    """The guard must not be so cautious that it skips the work it exists for."""
    app = _app(tmp_path)
    seen: list[bool] = []

    async def scenario() -> None:
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            seen.append(app._panes_are_mounted())

    asyncio.run(scenario())

    assert seen == [True]
    assert not app._panes_are_mounted()  # and False once it has stopped


def test_the_panes_are_reported_unmounted_when_tree_lookup_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression: a late lint can arrive while the app still runs but the panes are gone."""
    app = _app(tmp_path)
    seen: list[bool] = []

    async def scenario() -> None:
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()

            def _missing_tree(*_args, **_kwargs) -> None:
                raise RuntimeError("tree already torn down")

            monkeypatch.setattr(app, "query_one", _missing_tree)
            seen.append(app._panes_are_mounted())

    asyncio.run(scenario())

    assert seen == [False]
