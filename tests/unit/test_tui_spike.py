"""Tests for the Textual ontology-browser spike (``ster.tui``).

Three layers, mirroring Textual's own testing toolkit:

1. **Pure adapters** — plain functions over ``Taxonomy`` (no Textual). Always run.
2. **Pilot interaction tests** — ``App.run_test()`` returns a ``Pilot`` we drive
   with ``await pilot.press(...)`` / ``pilot.click(...)`` exactly like a user,
   then assert on app state. Gated behind the optional ``tui`` extra.
3. **Snapshot test** — ``pytest-textual-snapshot`` renders the app to SVG and
   compares against a committed baseline (visual regression). Gated behind the
   plugin; refresh baselines with ``pytest --snapshot-update``.
"""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from ster import store
from ster.tui import data

DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"

# Per-test gates so the pure-data tests still run without the optional `tui` extra.
needs_textual = pytest.mark.skipif(
    importlib.util.find_spec("textual") is None,
    reason="optional 'tui' extra (textual) not installed",
)
needs_snapshot = pytest.mark.skipif(
    importlib.util.find_spec("pytest_textual_snapshot") is None,
    reason="pytest-textual-snapshot not installed",
)


@pytest.fixture
def tax():
    return store.load(DEMO)


# ── 1 · pure data adapters (no Textual) ─────────────────────────────────────────


def test_class_hierarchy(tax):
    assert data.class_roots(tax) == [ZOO + "Animal", ZOO + "Person"]
    assert data.subclasses(tax, ZOO + "Animal") == [ZOO + "Bird", ZOO + "Mammal"]
    assert data.subclasses(tax, ZOO + "Mammal") == [ZOO + "Cat", ZOO + "Dog"]


def test_individuals_nest_under_their_class(tax):
    assert data.individuals_of(tax, ZOO + "Dog") == [ZOO + "Rex"]
    assert data.individuals_of(tax, ZOO + "Person") == [ZOO + "Alice"]


def test_search_rows_cover_every_entity(tax):
    labels = {label for label, _uri, _kind in data.search_rows(tax)}
    assert {"Dog", "Eagle", "Rex", "has owner"} <= labels
    assert len(data.search_rows(tax)) == 12  # 7 classes + 3 individuals + 2 properties


def test_label_and_kind(tax):
    assert data.label_of(tax, ZOO + "Dog") == "Dog"
    assert data.kind_of(tax, ZOO + "Dog") == "class"
    assert data.kind_of(tax, ZOO + "Rex") == "individual"
    assert data.kind_of(tax, ZOO + "hasOwner") == "property"


def test_detail_progressive_disclosure(tax):
    dog = data.detail_markup(tax, ZOO + "Dog")
    assert "Mammal" in dog and "Rex" in dog and "Loyal domestic companion." in dog
    assert "Alice" in data.detail_markup(tax, ZOO + "Rex")  # the hasOwner value
    prop = data.detail_markup(tax, ZOO + "hasOwner")
    assert "Animal" in prop and "Person" in prop  # domain + range


# ── 2 · Pilot interaction tests (drive the real UI) ─────────────────────────────


def _run(scenario: Callable[..., Awaitable[None]]) -> None:
    """Run an async Pilot scenario in a fresh loop (no pytest-asyncio needed)."""
    asyncio.run(scenario())


def _app():
    from ster.tui.app import OntologyApp

    return OntologyApp(store.load(DEMO), source="demo.ttl")


@needs_textual
def test_tree_populates_and_mounts() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert len(app._uri_nodes) == 12  # every class/individual/property indexed
            from textual.widgets import Tree

            assert isinstance(app.focused, Tree)  # tree gets focus on mount

    _run(scenario)


@needs_textual
def test_arrow_keys_drive_the_detail_panel() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("down", "down")  # Classes → Animal → Person
            await pilot.pause()
            assert "Person" in app._detail_text  # detail panel followed the cursor

    _run(scenario)


@needs_textual
def test_command_palette_search_jumps_end_to_end() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("slash")  # open the fuzzy search palette
            await pilot.pause()
            assert app.screen.__class__.__name__ == "CommandPalette"
            await pilot.press(*"rex")  # type a query
            for _ in range(3):
                await pilot.pause()  # let the async provider search settle
            await pilot.press("enter")  # pick the top hit
            for _ in range(3):
                await pilot.pause()
            assert app.screen.__class__.__name__ == "Screen"  # palette closed
            assert "Rex" in app._detail_text and "Alice" in app._detail_text  # jumped + detail

    _run(scenario)


@needs_textual
def test_expand_and_collapse_keys() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")  # expand all
            await pilot.pause()
            dog = app._uri_nodes[ZOO + "Dog"]
            assert dog.line >= 0  # a deep node is now visible after expand-all
            await pilot.press("c")  # collapse
            await pilot.pause()

    _run(scenario)


# ── 3 · snapshot test (visual regression; optional plugin) ──────────────────────

@needs_textual
@needs_snapshot
def test_browser_snapshot(snap_compare) -> None:
    """Render the app (after jumping to Rex) and diff against the committed SVG."""

    async def jump(pilot) -> None:  # run_before hook
        await pilot.pause()
        pilot.app.jump_to(ZOO + "Rex")
        await pilot.pause()

    assert snap_compare(_app(), terminal_size=(120, 40), run_before=jump)
