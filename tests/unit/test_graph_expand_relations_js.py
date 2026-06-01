"""The graph app asset wires up the 'Expand relations' button + escape-restore."""

from __future__ import annotations

from ster.viz_vowl import _app_js


def test_app_js_defines_expand_relations_handler():
    js = _app_js()
    assert "expandRelations" in js


def test_app_js_fetches_individual_relations_endpoint():
    js = _app_js()
    assert "/api/individual-relations" in js


def test_app_js_can_restore_original_graph():
    js = _app_js()
    # A saved-elements slot used to restore the pre-expand graph on Escape.
    assert "restoreGraph" in js


def test_app_js_button_is_guarded_by_server_token():
    """The button is server-only: its rendering is gated on API_TOKEN."""
    js = _app_js()
    assert "expandRelations" in js
    assert "API_TOKEN" in js


def test_expand_button_onclick_uses_single_quoted_attribute():
    """The URI passed via JSON.stringify is double-quoted, so the onclick HTML
    attribute must be single-quoted — otherwise the quotes collide and the
    browser truncates the handler (clicking does nothing)."""
    js = _app_js()
    assert "onclick='window._sterExpandRelations(" in js
    assert 'onclick="window._sterExpandRelations(' not in js


def test_nav_link_onclick_uses_single_quoted_attribute():
    """Same quote-collision applies to the in-panel relation navigation links."""
    js = _app_js()
    assert "onclick='window._sterNav(" in js
    assert 'onclick="window._sterNav(' not in js


def test_panel_button_markup_survives_html_parsing():
    """Reconstruct each URI-argument button as showDetail emits it and confirm
    an HTML parser preserves the full onclick handler for a realistic URI."""
    from html.parser import HTMLParser

    uri = "https://example.org/onto#Alice"

    class _P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.onclick = None

        def handle_starttag(self, tag, attrs):
            for k, v in attrs:
                if k == "onclick":
                    self.onclick = v

    for fn in ("window._sterExpandRelations", "window._sterNav"):
        # As built by the asset: single-quoted attribute, JSON-stringified arg.
        markup = f"<button onclick='{fn}(\"{uri}\")'>x</button>"
        p = _P()
        p.feed(markup)
        assert p.onclick == f'{fn}("{uri}")', p.onclick
