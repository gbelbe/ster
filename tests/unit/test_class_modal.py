"""Unit tests for the add/edit Class modal (ster.tui.class_modal)."""

from __future__ import annotations

import asyncio

from textual.app import App

from ster.tui.class_modal import ClassModal

PREFIX = "https://ex.org/onto#"


def _drive(factory) -> None:  # noqa: ANN001
    asyncio.run(factory())


def test_add_mode_collects_uri_labels_comments() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            app.push_screen(ClassModal(prefix=PREFIX, langs=["en", "fr"]), captured.append)
            await pilot.pause()
            await pilot.pause()
            modal = app.screen
            modal._uri.value = PREFIX + "Vehicle"
            modal._label_inputs["en"].value = "Vehicle"
            modal._label_inputs["fr"].value = "Véhicule"
            modal._comment_inputs["en"].value = "A wheeled thing"
            modal._submit()
            await pilot.pause()

    _drive(scenario)
    assert captured == [
        {
            "uri": PREFIX + "Vehicle",
            "labels": {"en": "Vehicle", "fr": "Véhicule"},
            "comments": {"en": "A wheeled thing", "fr": ""},
        }
    ]


def test_edit_mode_prefills_and_keeps_empty_for_cleared() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            app.push_screen(
                ClassModal(
                    prefix=PREFIX,
                    fragment="Car",
                    langs=["en", "fr"],
                    labels={"en": "Car", "fr": "Voiture"},
                    comments={"en": "old"},
                    title="Edit class",
                ),
                captured.append,
            )
            await pilot.pause()
            await pilot.pause()
            modal = app.screen
            assert modal._uri.value == PREFIX + "Car"  # prefilled URI
            assert modal._label_inputs["fr"].value == "Voiture"  # prefilled label
            modal._label_inputs["fr"].value = ""  # clear the French label
            modal._submit()
            await pilot.pause()

    _drive(scenario)
    # The cleared fr label is reported as "" (so the save can remove it).
    assert captured[0]["labels"] == {"en": "Car", "fr": ""}


def test_empty_fragment_blocks_submit() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            app.push_screen(ClassModal(prefix=PREFIX, langs=["en"]), captured.append)
            await pilot.pause()
            await pilot.pause()
            app.screen._submit()  # no fragment typed → should not dismiss
            await pilot.pause()
            assert isinstance(app.screen, ClassModal)  # still open

    _drive(scenario)
    assert captured == []
