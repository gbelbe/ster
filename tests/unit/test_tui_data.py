"""Pure view-model adapter tests for the New-TUI (``ster.tui.data``).

No Textual needed — these exercise the taxonomy→view-model functions directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import store
from ster.tui import data

DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"


@pytest.fixture
def tax():
    return store.load(DEMO)


def test_class_hierarchy(tax):
    assert data.class_roots(tax) == [ZOO + "Animal", ZOO + "Person"]
    assert data.subclasses(tax, ZOO + "Animal") == [ZOO + "Bird", ZOO + "Mammal"]
    assert data.subclasses(tax, ZOO + "Mammal") == [ZOO + "Cat", ZOO + "Dog"]


def test_individuals_nest_under_their_class(tax):
    assert data.individuals_of(tax, ZOO + "Dog") == [ZOO + "Rex"]
    assert data.individuals_of(tax, ZOO + "Person") == [ZOO + "Alice"]


def test_properties_listed_and_sorted(tax):
    assert data.properties(tax) == [ZOO + "hasAge", ZOO + "hasOwner"]


def test_search_rows_cover_every_entity(tax):
    labels = {label for label, _uri, _kind in data.search_rows(tax)}
    assert {"Dog", "Eagle", "Rex", "has owner"} <= labels
    assert len(data.search_rows(tax)) == 12  # 7 classes + 3 individuals + 2 properties


def test_label_and_kind(tax):
    assert data.label_of(tax, ZOO + "Dog") == "Dog"
    assert data.kind_of(tax, ZOO + "Dog") == "class"
    assert data.kind_of(tax, ZOO + "Rex") == "individual"
    assert data.kind_of(tax, ZOO + "hasOwner") == "property"
    assert data.label_of(tax, ZOO + "Unknown") == "Unknown"  # fallback to local name


# Detail rendering moved to ster.tui.detail.render_detail — see test_tui_detail.py.
