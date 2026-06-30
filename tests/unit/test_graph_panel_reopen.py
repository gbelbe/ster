"""Regression: the graph's detail panel must be re-openable after closing it.

Closing the right-hand detail panel (the × button) also hides its own close
button, so the only way back is the keyboard. Previously Escape was consumed by
search-clear / subgraph-restore / highlight-clear first, so a closed panel could
be stranded shut. Escape must reopen a closed panel as its top priority. This
applies to both the live and static (HTML) graph — both share graph_app.js.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def test_panel_close_button_is_a_persistent_toggle() -> None:
    js = _app_js()
    # The close button must never hide itself — that left a closed panel with no
    # visible control to reopen it. It stays visible and flips to a reopen glyph.
    assert "getElementById('panel-close').style.display" not in js
    assert "panelVisible?'×':'‹'" in js


def test_app_js_escape_reopens_closed_panel() -> None:
    js = _app_js()
    # Escape's first action, when the panel is closed, is to reopen it.
    assert "if(!panelVisible){togglePanel(true);return;}" in js


def test_escape_reopen_precedes_other_escape_actions() -> None:
    js = _app_js()
    handler_at = js.index("if(e.key==='Escape'){")
    reopen_at = js.index("if(!panelVisible){togglePanel(true);return;}", handler_at)
    clear_search_at = js.index("clearSearch();return;", handler_at)
    # The reopen guard must come before the search-clear branch in the handler.
    assert handler_at < reopen_at < clear_search_at
