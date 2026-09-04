"""The graph app asset wires up the hover 'explore relations' overlay, the
class/individual expansion endpoints, escape-restore, and the superclasses
toggle. The overlay button and, since the detail panel moved off innerHTML
templating, the relation navigation link too, use addEventListener — no
inline onclick handler remains anywhere in the asset."""

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


def _explore_node_body(js: str) -> str:
    """Return the source of the exploreNode function (up to restoreGraph)."""
    start = js.index("function exploreNode(")
    end = js.index("function restoreGraph(", start)
    return js[start:end]


def test_explore_does_not_dim_the_expanded_subgraph():
    # Regression: expanding an individual must not dim down to the focus node's
    # immediate neighbourhood — that hid superclass trails and the related
    # individuals' classes. exploreNode clears the highlight instead of pinning
    # it to the focus URI (navigateTo still highlights, so check exploreNode only).
    body = _explore_node_body(_app_js()).replace(" ", "")
    assert "highlighted=null;applyHighlight()" in body
    assert "highlighted=uri;applyHighlight()" not in body


# ── superclass flag + toggle ────────────────────────────────────────────────────


def test_app_js_buildElements_carries_superclass_flag():
    js = _app_js()
    assert "superclass" in js


def test_app_js_defines_superclasses_toggle():
    js = _app_js()
    assert "toggleSuperclasses" in js or "ft-superclasses" in js


# ── inline onclick discipline (only the nav link remains) ───────────────────────


def test_no_inline_onclick_handlers_remain():
    """The relation-navigation link used to be the last inline onclick handler,
    built with a JSON.stringify-inside-a-single-quoted-attribute trick — safe
    only as long as nothing downstream ever double-quoted it. It is now a real
    button wired with addEventListener like every other panel control, so no
    inline onclick handler should exist anywhere in the asset any more.
    """
    js = _app_js()
    assert "onclick=" not in js


# ── rendered-page wiring ────────────────────────────────────────────────────────


def test_rendered_html_has_explore_overlay_button():
    html = render_vowl_html(_tax(), file_path=None, api_token="TESTTOKEN")
    assert 'id="explore-btn"' in html


def test_rendered_html_has_superclasses_toggle_button():
    html = render_vowl_html(_tax(), file_path=None, api_token="TESTTOKEN")
    assert 'id="ft-superclasses"' in html
