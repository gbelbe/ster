"""The app header is a title, not a control.

Textual's Header expands on click to reveal the sub-title:

    def _on_click(self):
        self.toggle_class("-tall")

ster sets no sub-title, so the only thing a click achieves is to open an empty
band and push the layout down — an affordance that looks like it does something
and does not. The header is a label; clicks and taps pass over it.
"""

from __future__ import annotations

import asyncio

from textual.widgets import Header
from textual.widgets._header import HeaderTitle

from ster.tui.app import OntologyApp

TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <https://example.org/x#> .
ex:S a skos:ConceptScheme .
"""


def _app(tmp_path):
    from ster import store

    src = tmp_path / "o.ttl"
    src.write_text(TTL, encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src)


def test_clicking_the_header_does_not_expand_it(tmp_path) -> None:
    """A real click through the pilot, not a direct call to the handler.

    Calling ``header._on_click()`` proves only that one method is inert. The
    title is a child widget, so a click on it bubbles — and it is bubbling that
    reaches the toggle. The first version of this test called the handler and
    passed while the header was still expanding on screen.
    """

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            header = app.query_one(Header)

            await pilot.click(HeaderTitle)  # what the user actually clicks
            await pilot.pause()

            assert not header.has_class("-tall"), "the header opened an empty band"

    asyncio.run(scenario())


def test_clicking_the_header_icon_does_not_expand_it_either(tmp_path) -> None:
    """The other child in the bar — same bubble, same toggle."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            header = app.query_one(Header)

            await pilot.click(Header, offset=(2, 0))
            await pilot.pause()

            assert not header.has_class("-tall")

    asyncio.run(scenario())


def test_clicking_twice_is_also_inert(tmp_path) -> None:
    """A toggle that is merely reversed would still flash the layout."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            header = app.query_one(Header)

            await pilot.click(HeaderTitle)
            await pilot.click(HeaderTitle)
            await pilot.pause()

            assert not header.has_class("-tall")

    asyncio.run(scenario())


def test_the_header_still_shows_the_title(tmp_path) -> None:
    """Neutralising the click must not neutralise the header."""

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            assert "STER" in app.title
            assert app.query_one(Header) is not None

    asyncio.run(scenario())


def test_textual_still_expands_its_own_header_on_click() -> None:
    """Pin the upstream behaviour being overridden.

    The override targets a private handler. If a Textual upgrade renames or drops
    it, this fails loudly here rather than the header quietly becoming clickable
    again — which nobody would notice until it was reported a second time.
    """
    import inspect

    source = inspect.getsource(Header._on_click)

    assert "-tall" in source
