"""The browser never paints an empty tree for a file ster could not model."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ster import store
from ster.tui.app import OntologyApp
from ster.tui.unreadable_modal import UnreadableModal

_CAPABILITY_TTL = """\
@prefix ex: <https://example.com/business-capability/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:one a ex:BusinessCapability ;
    skos:prefLabel "Collect Supplier Information" .

ex:two a ex:BusinessCapability ;
    skos:prefLabel "Calculate Costs" .

ex:three a ex:BusinessCapability ;
    skos:prefLabel "Manage Treasury" .
"""

_READABLE_TTL = """\
@prefix ex: <https://example.com/taxonomy/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:tent a skos:Concept ;
    skos:prefLabel "Tent"@en .
"""


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch) -> None:
    monkeypatch.setenv("STER_NO_CACHE", "1")


@pytest.fixture(autouse=True)
def _scan_on_open_off() -> None:
    """The guard must fire on its own, not via the semanticlint plugin's scan."""
    from ster.plugins.semanticlint import config

    config.set_feature("check_on_open", False)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _drive(factory) -> None:  # noqa: ANN001
    asyncio.run(factory())


def test_guard_blocks_the_tree_on_an_unmodelled_file(tmp_path: Path) -> None:
    seen: list = []

    async def scenario() -> None:
        path = _write(tmp_path, "business_capabilities.ttl", _CAPABILITY_TTL)
        app = OntologyApp(store.load(path), source=path.name, path=path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            seen.append(app.screen)

    _drive(scenario)
    assert isinstance(seen[0], UnreadableModal)


def test_guard_is_silent_on_a_readable_file(tmp_path: Path) -> None:
    seen: list = []

    async def scenario() -> None:
        path = _write(tmp_path, "gear.ttl", _READABLE_TTL)
        app = OntologyApp(store.load(path), source=path.name, path=path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            seen.append(app.screen)

    _drive(scenario)
    assert not isinstance(seen[0], UnreadableModal)


def test_declaring_the_missing_types_writes_and_reloads(tmp_path: Path) -> None:
    result: dict = {}

    async def scenario() -> None:
        path = _write(tmp_path, "business_capabilities.ttl", _CAPABILITY_TTL)
        app = OntologyApp(store.load(path), source=path.name, path=path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            app.screen.query_one(f"#{UnreadableModal.DECLARE}").press()
            for _ in range(10):
                await pilot.pause()
            result["individuals"] = len(app.tax.owl_individuals)
            result["classes"] = len(app.tax.owl_classes)
            result["on_disk"] = path.read_text(encoding="utf-8")
            # The declaration has to survive on disk, not just in memory: it is
            # what makes the *next* open readable.
            result["reloaded"] = len(store.load(path).owl_individuals)

    _drive(scenario)
    assert result["classes"] == 1
    assert result["individuals"] == 3
    assert result["reloaded"] == 3
    assert "a owl:Class ." in result["on_disk"]


def test_opening_anyway_leaves_the_file_alone(tmp_path: Path) -> None:
    result: dict = {}

    async def scenario() -> None:
        path = _write(tmp_path, "business_capabilities.ttl", _CAPABILITY_TTL)
        before = path.read_text(encoding="utf-8")
        app = OntologyApp(store.load(path), source=path.name, path=path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            app.screen.query_one(f"#{UnreadableModal.OPEN}").press()
            await pilot.pause()
            await pilot.pause()
            result["screen"] = app.screen
            result["unchanged"] = path.read_text(encoding="utf-8") == before

    _drive(scenario)
    assert not isinstance(result["screen"], UnreadableModal)
    assert result["unchanged"]


def test_cancelling_quits_rather_than_showing_nothing(tmp_path: Path) -> None:
    result: dict = {}

    async def scenario() -> None:
        path = _write(tmp_path, "business_capabilities.ttl", _CAPABILITY_TTL)
        app = OntologyApp(store.load(path), source=path.name, path=path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            await pilot.press("escape")
            for _ in range(4):
                await pilot.pause()
            result["running"] = app.is_running

    _drive(scenario)
    assert not result["running"]
