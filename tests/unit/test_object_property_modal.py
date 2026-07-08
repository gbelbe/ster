"""Unit tests for the add Object Property modal (ster.tui.object_property_modal)."""

from __future__ import annotations

import asyncio

from textual.app import App

from ster.tui.object_property_modal import ObjectPropertyModal

PREFIX = "https://ex.org/onto#"
CLASSES = [("Animal", PREFIX + "Animal"), ("Person", PREFIX + "Person")]


def _drive(factory) -> None:  # noqa: ANN001
    asyncio.run(factory())


def test_collects_uri_labels_comments_domain_range() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            app.push_screen(
                ObjectPropertyModal(prefix=PREFIX, langs=["en", "fr"], classes=CLASSES),
                captured.append,
            )
            await pilot.pause()
            await pilot.pause()
            modal = app.screen
            modal._uri.value = PREFIX + "hasOwner"
            modal._label_inputs["en"].value = "has owner"
            modal._label_inputs["fr"].value = "a pour propriétaire"
            modal._comment_inputs["en"].value = "Links an animal to its owner"
            modal._domain.value = PREFIX + "Animal"
            modal._range.value = PREFIX + "Person"
            modal._submit()
            await pilot.pause()

    _drive(scenario)
    assert captured == [
        {
            "uri": PREFIX + "hasOwner",
            "labels": {"en": "has owner", "fr": "a pour propriétaire"},
            "comments": {"en": "Links an animal to its owner", "fr": ""},
            "domain": PREFIX + "Animal",
            "range": PREFIX + "Person",
        }
    ]


def test_domain_and_range_are_optional() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            app.push_screen(
                ObjectPropertyModal(prefix=PREFIX, langs=["en"], classes=CLASSES),
                captured.append,
            )
            await pilot.pause()
            await pilot.pause()
            modal = app.screen
            modal._uri.value = PREFIX + "relatedTo"
            modal._label_inputs["en"].value = "related to"
            modal._submit()
            await pilot.pause()

    _drive(scenario)
    assert captured == [
        {
            "uri": PREFIX + "relatedTo",
            "labels": {"en": "related to"},
            "comments": {"en": ""},
            "domain": None,  # nothing picked
            "range": None,
        }
    ]


def test_empty_uri_cancels_with_none() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            app.push_screen(
                ObjectPropertyModal(prefix=PREFIX, langs=["en"], classes=CLASSES),
                captured.append,
            )
            await pilot.pause()
            await pilot.pause()
            app.screen._submit()  # no fragment typed
            await pilot.pause()

    _drive(scenario)
    assert captured == []  # not dismissed with a result
