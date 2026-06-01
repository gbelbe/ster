"""The graph app asset wires up the hover 'explore relations' overlay, the
class/individual expansion endpoints, escape-restore, and the superclasses
toggle. The overlay button uses addEventListener (no inline onclick), so the
only remaining inline-onclick handler is the relation navigation link, which
must stay single-quoted."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, RDFClass, Taxonomy
from ster.viz_vowl import _app_js, render_vowl_html

NS = "https://example.org/onto#"


def _tax() -> Taxonomy:
    t = Taxonomy()
    t.owl_classes[NS + "Person"] = RDFClass(uri=NS + "Person", labels=[Label("en", "Person")])
    t.owl_individuals[NS + "Alice"] = OWLIndividual(
        uri=NS + "Alice", labels=[Label("en", "Alice")], types=[NS + "Person"]
    )
    return t


# ── explore overlay + expansion ────────────────────────────────────────────────


def test_app_js_defines_explore_dispatcher():
    assert "exploreNode" in _app_js()


def test_app_js_explore_handles_both_individual_and_class_endpoints():
    js = _app_js()
    assert "/api/individual-relations" in js
    assert "/api/class-links" in js


def test_app_js_references_explore_overlay_element():
    assert "explore-btn" in _app_js()


def test_app_js_overlay_is_guarded_by_server_token():
    assert "API_TOKEN" in _app_js()


def test_app_js_can_restore_original_graph():
    assert "restoreGraph" in _app_js()


# ── superclass flag + toggle ────────────────────────────────────────────────────


def test_app_js_buildElements_carries_superclass_flag():
    js = _app_js()
    assert "superclass" in js


def test_app_js_defines_superclasses_toggle():
    js = _app_js()
    assert "toggleSuperclasses" in js or "ft-superclasses" in js


# ── inline onclick discipline (only the nav link remains) ───────────────────────


def test_nav_link_onclick_uses_single_quoted_attribute():
    js = _app_js()
    assert "onclick='window._sterNav(" in js
    assert 'onclick="window._sterNav(' not in js


def test_nav_link_markup_survives_html_parsing():
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

    markup = f"<button onclick='window._sterNav(\"{uri}\")'>x</button>"
    p = _P()
    p.feed(markup)
    assert p.onclick == f'window._sterNav("{uri}")'


# ── rendered-page wiring ────────────────────────────────────────────────────────


def test_rendered_html_has_explore_overlay_button():
    html = render_vowl_html(_tax(), file_path=None, api_token="TESTTOKEN")
    assert 'id="explore-btn"' in html


def test_rendered_html_has_superclasses_toggle_button():
    html = render_vowl_html(_tax(), file_path=None, api_token="TESTTOKEN")
    assert 'id="ft-superclasses"' in html
