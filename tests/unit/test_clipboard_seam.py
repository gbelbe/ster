"""Copy and paste reaching the *OS* clipboard, not just Textual's own record.

Textual's `App.copy_to_clipboard` writes OSC 52 and nothing else, and its own
docstring says plainly that this "does not work on macOS Terminal". Its widgets
all copy through it, so Ctrl+C inside a modal emitted an escape sequence the
terminal discarded and put nothing on the clipboard — while ster's `action_copy`,
which does shell out to pbcopy, never ran because `Input` had already handled
the key.

`App.clipboard` has the mirror-image problem: it holds only what was copied
inside the app, so a paste served from it can never see text copied from a
browser or an editor.

Both are fixed at the App seam rather than per widget, which is what these tests
pin: the override, not any one widget's bindings.
"""

from __future__ import annotations

import asyncio
import pathlib

from ster import store
from ster.tui import clipboard as clip
from ster.tui.app import OntologyApp
from ster.tui.edit_modal import EditModal

DEMO = """
@prefix ex:   <https://ex.org/s#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Thing a owl:Class ; rdfs:label "Thing"@en .
"""


def _app(tmp_path: pathlib.Path) -> OntologyApp:
    source = tmp_path / "demo.ttl"
    source.write_text(DEMO, encoding="utf-8")
    return OntologyApp(store.load(source), source=str(source))


def test_copy_also_writes_the_os_clipboard(tmp_path, monkeypatch) -> None:
    """The bug: a copy that only ever emitted OSC 52 reached no clipboard at all."""
    written: list[str] = []
    monkeypatch.setattr(clip, "copy_to_system_clipboard", lambda text: bool(written.append(text)))
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.copy_to_clipboard("some turtle")
            await pilot.pause()

    asyncio.run(scenario())
    assert written == ["some turtle"]


def test_copy_from_a_modal_reaches_the_os_clipboard(tmp_path, monkeypatch) -> None:
    """Ctrl+C on a selection inside a modal — the report that started this."""
    written: list[str] = []
    monkeypatch.setattr(clip, "copy_to_system_clipboard", lambda text: bool(written.append(text)))
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.notify = lambda *a, **k: None  # type: ignore[method-assign]
            app.push_screen(EditModal("Label", "Thing"))
            await pilot.pause()
            await pilot.pause()
            await pilot.press("end")
            await pilot.press("shift+home")  # select the field's text
            await pilot.pause()
            await pilot.press("ctrl+c")
            await pilot.pause()

    asyncio.run(scenario())
    assert "Thing" in written


def test_paste_reads_the_os_clipboard(tmp_path, monkeypatch) -> None:
    """So Ctrl+V means the same thing here as everywhere else on the machine."""
    monkeypatch.setattr(clip, "paste_from_system_clipboard", lambda: "from outside ster")
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.clipboard == "from outside ster"

    asyncio.run(scenario())


def test_paste_falls_back_to_textuals_own_record(tmp_path, monkeypatch) -> None:
    """No clipboard tool on this machine is not the same as an empty clipboard."""
    monkeypatch.setattr(clip, "paste_from_system_clipboard", lambda: None)
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._clipboard = "copied in app"
            assert app.clipboard == "copied in app"

    asyncio.run(scenario())


def test_an_empty_os_clipboard_is_not_a_missing_one(tmp_path, monkeypatch) -> None:
    """ "" means paste nothing; None means ask Textual. Collapsing them would make
    an empty clipboard silently paste whatever was last copied in the app."""
    monkeypatch.setattr(clip, "paste_from_system_clipboard", lambda: "")
    app = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._clipboard = "stale in-app value"
            assert app.clipboard == ""

    asyncio.run(scenario())
