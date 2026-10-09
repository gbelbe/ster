"""The TUI on a SPARQL endpoint: a loader instead of a file, read-only, re-fetchable.

The loader is a stub here (the HTTP side is covered in test_sparql_endpoint);
what these pin is how the app uses it — off the UI thread, behind a spinner
that keeps moving, with editing refused and a failed re-fetch leaving the
screen as it was.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from ster import store
from ster.tui.app import OntologyApp

_REFETCH = "refetch"  # the busy-overlay job name
LOADS_BEFORE_AND_AFTER = 2  # the first load, then the re-fetch
SKOS = "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n@prefix ex: <https://e.org/#> .\n"


def _tax(*names: str):
    body = "".join(f'ex:{n} a skos:Concept ; skos:prefLabel "{n}"@en .\n' for n in names)
    return store.taxonomy_from_bytes((SKOS + body).encode())


class _Loader:
    """A loader whose calls can be held open, and that records who ran them."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0
        self.threads: list[int] = []
        self.hold = threading.Event()
        self.hold.set()
        self.entered = threading.Event()

    def __call__(self, _progress):
        self.calls += 1
        self.threads.append(threading.get_ident())
        self.entered.set()
        self.hold.wait(10)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


async def _until(pilot, predicate, tries=200):
    for _ in range(tries):
        if predicate():
            return
        await pilot.pause(0.05)
    raise AssertionError("condition never became true")


def _run(scenario):
    asyncio.run(scenario())


@pytest.mark.tui
def test_loader_runs_off_the_ui_thread():
    loader = _Loader((_tax("Tent"), None))
    app = OntologyApp(None, source="https://x/sparql", progressive_startup=True, loader=loader)
    ui_thread = threading.get_ident()

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: app._loaded_successfully)

    _run(scenario)
    assert loader.threads and loader.threads[0] != ui_thread
    assert "https://e.org/#Tent" in app.tax.concepts


@pytest.mark.tui
def test_loading_screen_spinner_advances_during_the_fetch():
    loader = _Loader((_tax("Tent"), None))
    loader.hold.clear()  # the "endpoint" is slow
    app = OntologyApp(None, source="https://x/sparql", progressive_startup=True, loader=loader)
    frames: set[int] = set()

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, loader.entered.is_set)
            for _ in range(12):  # ~0.6s of a blocked fetch
                frames.add(app._loading_spinner_frame)
                await pilot.pause(0.05)
            loader.hold.set()
            await _until(pilot, lambda: app._loaded_successfully)

    _run(scenario)
    assert len(frames) > 1, "the spinner froze while the fetch was in flight"


@pytest.mark.tui
def test_fetch_error_shows_the_load_error_screen():
    loader = _Loader(RuntimeError("Could not reach https://x/sparql: refused"))
    app = OntologyApp(None, source="https://x/sparql", progressive_startup=True, loader=loader)

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: not app._loading)

    _run(scenario)
    assert app._loaded_successfully is False


@pytest.mark.tui
def test_edit_is_refused_read_only(monkeypatch):
    notes: list[str] = []
    monkeypatch.setattr(OntologyApp, "notify", lambda _s, msg, **kw: notes.append(str(msg)))
    loader = _Loader((_tax("Tent"), None))
    app = OntologyApp(None, source="https://x/sparql", progressive_startup=True, loader=loader)

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: app._loaded_successfully)
            assert app._service is None and app._path is None
            app._apply_command(object())

    _run(scenario)
    assert any("read-only" in n.lower() for n in notes)


@pytest.mark.tui
def test_a_truncation_notice_is_shown_once_loaded(monkeypatch):
    notes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        OntologyApp,
        "notify",
        lambda _s, msg, **kw: notes.append((str(msg), kw.get("severity", ""))),
    )
    loader = _Loader((_tax("Tent"), "Showing the first 5 triples: the row limit (5) was reached."))
    app = OntologyApp(None, source="https://x/sparql", progressive_startup=True, loader=loader)

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: any("row limit" in m for m, _s in notes))

    _run(scenario)
    assert [s for m, s in notes if "row limit" in m] == ["warning"]


@pytest.mark.tui
def test_refetch_shows_the_busy_spinner_and_swaps_the_model():
    loader = _Loader((_tax("Tent"), None), (_tax("Tent", "Dome"), None))
    app = OntologyApp(None, source="https://x/sparql", progressive_startup=True, loader=loader)
    seen_busy: list[bool] = []

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: app._loaded_successfully and app._browser_ready)
            loader.hold.clear()
            loader.entered.clear()
            app.action_refetch()
            await _until(pilot, loader.entered.is_set)
            seen_busy.append(_REFETCH in app._activities)
            loader.hold.set()
            await _until(pilot, lambda: "https://e.org/#Dome" in app.tax.concepts)
            await _until(pilot, lambda: _REFETCH not in app._activities)

    _run(scenario)
    assert seen_busy == [True]
    assert loader.calls == LOADS_BEFORE_AND_AFTER


@pytest.mark.tui
def test_refetch_failure_keeps_the_old_data(monkeypatch):
    notes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        OntologyApp,
        "notify",
        lambda _s, msg, **kw: notes.append((str(msg), kw.get("severity", ""))),
    )
    loader = _Loader((_tax("Tent"), None), RuntimeError("endpoint down"))
    app = OntologyApp(None, source="https://x/sparql", progressive_startup=True, loader=loader)

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await _until(pilot, lambda: app._loaded_successfully and app._browser_ready)
            before = app.tax
            app.action_refetch()
            await _until(pilot, lambda: any("Re-fetch failed" in m for m, _s in notes))
            assert app.tax is before
            # The toast is raised before the spinner is cleared, so wait for it.
            await _until(pilot, lambda: _REFETCH not in app._activities)

    _run(scenario)
    assert ("Re-fetch failed: endpoint down", "error") in notes


@pytest.mark.tui
def test_refetch_on_a_file_session_says_there_is_nothing_to_fetch(monkeypatch):
    from pathlib import Path

    notes: list[str] = []
    monkeypatch.setattr(OntologyApp, "notify", lambda _s, msg, **kw: notes.append(str(msg)))
    demo = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"
    app = OntologyApp(store.load(demo), source="demo.ttl")

    async def scenario():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.action_refetch()

    _run(scenario)
    assert any("nothing to re-fetch" in n for n in notes)
