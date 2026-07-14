"""Tests for the reusable EditModal — single-line input vs the multi-line Markdown editor."""

from __future__ import annotations

import asyncio

from textual.app import App
from textual.widgets import Input, Markdown, TextArea

from ster.tui.edit_modal import EditModal


class _Host(App):
    def compose(self):  # type: ignore[no-untyped-def]
        return iter(())


def _run(coro_factory) -> None:  # noqa: ANN001
    asyncio.run(coro_factory())


def test_single_line_mode_uses_an_input() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(EditModal("Label", "hi"))
            await pilot.pause()
            assert app.screen.query("#edit-input")  # one-line Input
            assert not app.screen.query("#edit-area")  # no TextArea

    _run(scenario)


def test_multiline_esc_saves_and_closes() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            result: list = []
            app.push_screen(EditModal("Comment", "line1", multiline=True), result.append)
            await pilot.pause()
            assert app.screen.query_one("#edit-box").has_class("multiline")
            app.screen.query_one("#edit-area", TextArea).text = "edited\n\n# heading"
            await pilot.press("escape")  # Esc auto-saves the current content and closes
            await pilot.pause()
            assert result == ["edited\n\n# heading"]

    _run(scenario)


def test_value_with_newlines_auto_enables_multiline() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(EditModal("Comment", "a\nb"))  # multiline not passed
            await pilot.pause()
            assert app.screen.query("#edit-area")  # still opens the multi-line editor

    _run(scenario)


def test_preview_toggle_flips_between_editor_and_rendered_markdown() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(EditModal("Comment", "# Hello", multiline=True))
            await pilot.pause()
            box = app.screen.query_one("#edit-box")
            assert not box.has_class("preview")
            assert app.screen.query_one(Markdown)  # preview widget exists
            await pilot.press("ctrl+r")
            await pilot.pause()
            assert box.has_class("preview")  # rendered preview shown
            await pilot.press("ctrl+r")
            await pilot.pause()
            assert not box.has_class("preview")  # back to the editor

    _run(scenario)


def test_single_line_enter_saves() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            result: list = []
            app.push_screen(EditModal("Label", "Dog"), result.append)
            await pilot.pause()
            app.screen.query_one("#edit-input", Input).value = "Chien"
            await pilot.press("enter")  # Enter saves
            await pilot.pause()
            assert result == ["Chien"]

    _run(scenario)


def test_single_line_esc_saves_and_closes() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            result: list = []
            app.push_screen(EditModal("Label", "Dog"), result.append)
            await pilot.pause()
            app.screen.query_one("#edit-input", Input).value = "Chien"
            await pilot.press("escape")  # Esc auto-saves the current value and closes
            await pilot.pause()
            assert result == ["Chien"]

    _run(scenario)


def test_pasting_a_url_inserts_a_markdown_link() -> None:
    async def scenario() -> None:
        from textual import events

        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(EditModal("Comment", "", multiline=True, autolink=True))
            await pilot.pause()
            area = app.screen.query_one("#edit-area", TextArea)
            await area._on_paste(events.Paste("https://example.org"))  # paste a bare URL
            await pilot.pause()
            assert area.text == "[https://example.org](https://example.org)"

    _run(scenario)


def test_pasting_plain_text_is_inserted_verbatim() -> None:
    async def scenario() -> None:
        from textual import events

        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(EditModal("Comment", "", multiline=True))
            await pilot.pause()
            area = app.screen.query_one("#edit-area", TextArea)
            await area._on_paste(events.Paste("just some prose"))
            await pilot.pause()
            assert area.text == "just some prose"  # non-URL → not wrapped

    _run(scenario)


def test_ctrl_k_inserts_a_link_skeleton() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(EditModal("Comment", "", multiline=True))
            await pilot.pause()
            area = app.screen.query_one("#edit-area", TextArea)
            area.focus()
            await pilot.pause()
            await pilot.press("ctrl+k")
            await pilot.pause()
            assert "[text](url)" in area.text

    _run(scenario)


def test_multiline_close_discards_via_cancel() -> None:
    """The ✕ / click-away path discards (dismiss None); only Esc auto-saves."""

    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            result: list = []
            app.push_screen(EditModal("Comment", "x", multiline=True), result.append)
            await pilot.pause()
            app.screen.query_one("#edit-area", TextArea).text = "done"
            app.screen.dismiss(None)  # ✕ / click-away discards the edit
            await pilot.pause()
            assert result == [None]

    _run(scenario)


def test_autolink_wraps_existing_urls_on_open_for_prose() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(
                EditModal("Comment", "See https://example.org now", multiline=True, autolink=True)
            )
            await pilot.pause()
            text = app.screen.query_one("#edit-area", TextArea).text
            assert text == "See [https://example.org](https://example.org) now"

    _run(scenario)


def test_no_autolink_for_literal_value_editor() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            # a datatype literal that IS a URL → kept raw (autolink off)
            app.push_screen(EditModal("Literal value", "https://example.org", multiline=True))
            await pilot.pause()
            assert app.screen.query_one("#edit-area", TextArea).text == "https://example.org"

    _run(scenario)


def test_autolink_urls_is_idempotent() -> None:
    from ster.tui.urls import autolink_urls

    once = autolink_urls("See https://example.org and urn:x:y")
    assert once == "See [https://example.org](https://example.org) and [urn:x:y](urn:x:y)"
    assert autolink_urls(once) == once  # already-linked URLs are left untouched
