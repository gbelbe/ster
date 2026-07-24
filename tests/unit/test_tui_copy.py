"""Copy to the system clipboard with Ctrl+C / Cmd+C.

Textual has no keyboard text-selection for read-only content, so the reliable way to grab a
URI (or any value) is to copy the *focused* element: Ctrl+C copies the current mouse
selection when there is one, else the value under the focus — a tree node's URI, or a detail
row's value. ``copy_to_clipboard`` records the text on ``app.clipboard`` (and emits OSC 52).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ster import store
from ster.tui.app import OntologyApp

E = "https://ex.org/"

TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <https://ex.org/> .
ex:Animal a owl:Class ; rdfs:label "Animal"@en .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:label "Dog"@en .
"""


def _app(tmp_path: Path) -> OntologyApp:
    src = tmp_path / "o.ttl"
    src.write_text(TTL, encoding="utf-8")
    return OntologyApp(store.load(src), source="o.ttl", path=src)


def test_ctrl_c_binding_is_wired_to_copy() -> None:
    """Ctrl+C and Cmd+C are bound to copy (not quit)."""
    keys = {b.key for b in OntologyApp.BINDINGS if b.action == "copy"}
    assert keys and any("ctrl+c" in k for k in keys) and any("super+c" in k for k in keys)


def test_help_screen_documents_the_copy_shortcut() -> None:
    """The ? help cheat-sheet documents ctrl+c = copy."""
    from ster.tui.help_screen import _HELP

    assert "ctrl+c" in _HELP.lower() and "copy" in _HELP.lower()


def test_ctrl_c_copies_the_focused_tree_node_uri(tmp_path) -> None:
    from textual.widgets import Tree

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            ont = app.query_one("#ont-tree", Tree)
            app._select_panel("ont-tree")
            await pilot.press("enter")  # into the item layer
            await pilot.press("down")  # onto the first class
            await pilot.pause()
            uri = ont.cursor_node.data
            assert uri.startswith("http")
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert app.clipboard == uri

    asyncio.run(scenario())


def test_ctrl_c_copies_the_focused_detail_row_value(tmp_path) -> None:
    from ster.tui.detail_view import DetailRow

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(E + "Dog")  # a class → the detail pane shows its URI/label rows
            await pilot.pause()
            row = next(r for r in app.query(DetailRow) if r.can_focus and r.field.value)
            row.focus()
            await pilot.pause()
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert app.clipboard == row.field.value

    asyncio.run(scenario())


def test_copy_to_system_clipboard_runs_the_platform_tool(monkeypatch) -> None:
    """The local-clipboard adapter shells out to the platform tool (pbcopy on darwin) with
    the text on stdin — so a copy lands even when the terminal ignores OSC 52."""
    from ster.tui import clipboard as clip

    calls: dict = {}
    monkeypatch.setattr(clip.sys, "platform", "darwin")
    monkeypatch.setattr(
        clip.shutil, "which", lambda name: "/usr/bin/pbcopy" if name == "pbcopy" else None
    )

    def fake_run(cmd, input=None, **kw):  # noqa: A002
        calls["cmd"], calls["input"] = cmd, input

    monkeypatch.setattr(clip.subprocess, "run", fake_run)
    assert clip.copy_to_system_clipboard("https://ex.org/Hiking") is True
    assert calls["cmd"] == ["pbcopy"] and calls["input"] == b"https://ex.org/Hiking"


def test_copy_to_system_clipboard_is_false_when_no_tool_is_available(monkeypatch) -> None:
    from ster.tui import clipboard as clip

    monkeypatch.setattr(clip.shutil, "which", lambda name: None)
    assert clip.copy_to_system_clipboard("x") is False


def test_ctrl_c_also_writes_to_the_system_clipboard(tmp_path, monkeypatch) -> None:
    """Ctrl+C writes the value to the local OS clipboard (not only OSC 52)."""
    from textual.widgets import Tree

    from ster.tui import clipboard as clip

    captured: dict = {}
    monkeypatch.setattr(
        clip, "copy_to_system_clipboard", lambda t: captured.setdefault("text", t) or True
    )

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            ont = app.query_one("#ont-tree", Tree)
            app._select_panel("ont-tree")
            await pilot.press("enter")
            await pilot.press("down")
            await pilot.pause()
            uri = ont.cursor_node.data
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert captured.get("text") == uri

    asyncio.run(scenario())


def test_ctrl_c_is_a_noop_when_there_is_no_value_under_the_focus(tmp_path) -> None:
    """On a pane header (a sentinel URI, not an entity) Ctrl+C copies nothing — it does not
    fall back to quitting the app."""
    from textual.widgets import Tree

    async def scenario() -> None:
        app = _app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.query_one("#ont-tree", Tree)
            app._select_panel("ont-tree")  # cursor on the header (a __ster: sentinel)
            await pilot.pause()
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert app.clipboard == ""  # nothing copied, and still running
            assert app.is_running

    asyncio.run(scenario())
