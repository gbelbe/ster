"""Unit tests for the Edit Property modal (ster.tui.property_edit_modal)."""

from __future__ import annotations

import asyncio

from textual.app import App

from ster.tui.property_edit_modal import PropertyEditModal

PREFIX = "https://ex.org/onto#"


def _drive(factory) -> None:  # noqa: ANN001
    asyncio.run(factory())


def test_prefills_and_returns_uri_labels_comments() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            app.push_screen(
                PropertyEditModal(
                    prefix=PREFIX,
                    fragment="hasOwner",
                    langs=["en", "fr"],
                    labels={"en": "has owner"},
                    comments={"en": "the owner"},
                ),
                captured.append,
            )
            await pilot.pause()
            await pilot.pause()
            modal = app.screen
            assert modal._uri.value == PREFIX + "hasOwner"  # prefilled URI
            assert modal._label_inputs["en"].value == "has owner"  # prefilled label
            modal._uri.value = PREFIX + "hasKeeper"  # rename
            modal._label_inputs["fr"].value = "a pour gardien"
            modal._submit()
            await pilot.pause()

    _drive(scenario)
    assert captured == [
        {
            "uri": PREFIX + "hasKeeper",
            "labels": {"en": "has owner", "fr": "a pour gardien"},
            "comments": {"en": "the owner", "fr": ""},
        }
    ]
