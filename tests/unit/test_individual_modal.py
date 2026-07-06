"""Unit tests for the add/edit Individual modal (ster.tui.individual_modal)."""

from __future__ import annotations

import asyncio

from textual.app import App

from ster.tui.individual_modal import IndividualModal, PropField

PREFIX = "https://ex.org/onto#"


def _drive(factory) -> None:  # noqa: ANN001
    asyncio.run(factory())


def _props() -> tuple[PropField, ...]:
    return (
        PropField(prop_uri=PREFIX + "breed", label="breed", kind="datatype"),
        PropField(
            prop_uri=PREFIX + "hasOwner",
            label="has owner  (inherited from Animal)",
            kind="object",
            candidates=((("Alice", PREFIX + "Alice"),)),
        ),
    )


def test_add_mode_collects_uri_labels_comments_and_values() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            app.push_screen(
                IndividualModal(
                    prefix=PREFIX,
                    langs=["en", "fr"],
                    type_label="Dog",
                    prop_fields=_props(),
                ),
                captured.append,
            )
            await pilot.pause()
            await pilot.pause()
            modal = app.screen
            modal._uri.value = PREFIX + "Buddy"
            modal._label_inputs["en"].value = "Buddy"
            modal._comment_inputs["en"].value = "A good dog"
            modal._value_widgets[PREFIX + "breed"].value = "Labrador"
            modal._value_widgets[PREFIX + "hasOwner"].value = PREFIX + "Alice"
            modal._submit()
            await pilot.pause()

    _drive(scenario)
    assert captured == [
        {
            "uri": PREFIX + "Buddy",
            "labels": {"en": "Buddy", "fr": ""},
            "comments": {"en": "A good dog", "fr": ""},
            "values": {
                PREFIX + "breed": ("datatype", "Labrador"),
                PREFIX + "hasOwner": ("object", PREFIX + "Alice"),
            },
        }
    ]


def test_object_property_with_no_candidates_is_free_text() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            fields = (PropField(prop_uri=PREFIX + "hasOwner", label="has owner", kind="object"),)
            app.push_screen(
                IndividualModal(prefix=PREFIX, langs=["en"], prop_fields=fields),
                captured.append,
            )
            await pilot.pause()
            await pilot.pause()
            modal = app.screen
            modal._uri.value = PREFIX + "X"
            # free-text Input accepts a typed URI when there are no candidates
            modal._value_widgets[PREFIX + "hasOwner"].value = PREFIX + "Someone"
            modal._submit()
            await pilot.pause()

    _drive(scenario)
    assert captured[0]["values"] == {PREFIX + "hasOwner": ("object", PREFIX + "Someone")}


def test_edit_mode_prefills_and_hides_property_rows() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            app.push_screen(
                IndividualModal(
                    prefix=PREFIX,
                    fragment="Rex",
                    langs=["en"],
                    labels={"en": "Rex"},
                    title="Edit individual",
                ),
                captured.append,
            )
            await pilot.pause()
            await pilot.pause()
            modal = app.screen
            assert modal._uri.value == PREFIX + "Rex"
            assert modal._label_inputs["en"].value == "Rex"
            assert modal._value_widgets == {}  # no property rows in edit mode
            modal._submit()
            await pilot.pause()

    _drive(scenario)
    assert captured[0]["uri"] == PREFIX + "Rex"
    assert captured[0]["values"] == {}


def test_empty_fragment_blocks_submit() -> None:
    captured: list = []

    async def scenario() -> None:
        app: App = App()
        async with app.run_test(size=(100, 40)) as pilot:
            app.push_screen(IndividualModal(prefix=PREFIX, langs=["en"]), captured.append)
            await pilot.pause()
            await pilot.pause()
            app.screen._submit()
            await pilot.pause()
            assert isinstance(app.screen, IndividualModal)

    _drive(scenario)
    assert captured == []
