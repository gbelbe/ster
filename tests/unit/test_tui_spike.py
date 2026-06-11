"""Tests for the Textual ontology-browser spike (``ster.tui``).

The pure ``data`` adapters are always tested. The Textual ``app`` test is gated
behind ``importorskip`` so it runs only when the optional ``tui`` extra is
installed (CI's default env doesn't pull Textual)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ster import store
from ster.tui import data

DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"


@pytest.fixture
def tax():
    return store.load(DEMO)


# ── pure data adapters (no Textual) ─────────────────────────────────────────────


def test_class_hierarchy(tax):
    assert data.class_roots(tax) == [ZOO + "Animal", ZOO + "Person"]
    assert data.subclasses(tax, ZOO + "Animal") == [ZOO + "Bird", ZOO + "Mammal"]
    assert data.subclasses(tax, ZOO + "Mammal") == [ZOO + "Cat", ZOO + "Dog"]


def test_individuals_nest_under_their_class(tax):
    assert data.individuals_of(tax, ZOO + "Dog") == [ZOO + "Rex"]
    assert data.individuals_of(tax, ZOO + "Person") == [ZOO + "Alice"]


def test_search_rows_cover_every_entity(tax):
    rows = data.search_rows(tax)
    labels = {label for label, _uri, _kind in rows}
    assert {"Dog", "Eagle", "Rex", "has owner"} <= labels
    # classes + individuals + properties = 7 + 3 + 2
    assert len(rows) == 12


def test_label_and_kind(tax):
    assert data.label_of(tax, ZOO + "Dog") == "Dog"
    assert data.kind_of(tax, ZOO + "Dog") == "class"
    assert data.kind_of(tax, ZOO + "Rex") == "individual"
    assert data.kind_of(tax, ZOO + "hasOwner") == "property"


def test_detail_progressive_disclosure(tax):
    dog = data.detail_markup(tax, ZOO + "Dog")
    assert "Dog" in dog and "Mammal" in dog and "Rex" in dog  # parent + individual surfaced
    assert "Loyal domestic companion." in dog  # comment shown
    rex = data.detail_markup(tax, ZOO + "Rex")
    assert "Alice" in rex  # the hasOwner relation value is surfaced
    prop = data.detail_markup(tax, ZOO + "hasOwner")
    assert "Animal" in prop and "Person" in prop  # domain + range


# ── Textual app (optional; skipped without the `tui` extra) ─────────────────────


def test_app_builds_tree_and_search_jumps():
    pytest.importorskip("textual")
    from ster.tui.app import EntitySearch, OntologyApp

    async def scenario() -> None:
        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert len(app._uri_nodes) >= 12  # tree populated
            app.jump_to(ZOO + "Rex")  # search/jump lands on a nested individual
            await pilot.pause()
            assert "Alice" in app._detail_text  # detail panel followed
            provider = EntitySearch(app.screen)
            await provider.startup()
            hits = [hit async for hit in provider.search("eag")]
            assert any("Eagle" in hit.text for hit in hits)  # fuzzy search works

    asyncio.run(scenario())
