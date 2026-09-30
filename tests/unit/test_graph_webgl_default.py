"""WebGL is the graph view's default renderer; ?webgl=0 opts back out.

Cytoscape's WebGL renderer is a construction-time-only option — nothing in
its API lets you flip it on a live `cy` instance — so the toggle button
reloads the page with a URL param rather than mutating anything in place,
the same way the page already re-renders from `?q=`.
"""

from __future__ import annotations

from ster.model import Label, RDFClass, Taxonomy
from ster.viz_vowl import render_vowl_html

NS = "https://example.org/onto#"


def _make_taxonomy() -> Taxonomy:
    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal", labels=[Label("en", "Animal")])
    return tax


def _js() -> str:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    return html.replace(" ", "").replace("\n", "")


def test_webgl_is_on_unless_explicitly_turned_off() -> None:
    """Only the literal '0' opts out — anything else (missing, '1', a typo)
    must not silently fall back to canvas."""
    assert "const_webglOn=newURLSearchParams(location.search).get('webgl')!=='0';" in _js()


def test_webgl_renderer_options_used_when_on() -> None:
    assert "{name:'canvas',webgl:true,showFps:true}" in _js()


def test_canvas_specific_options_used_when_off() -> None:
    """The bitmap-caching tricks (textureOnViewport/hideEdgesOnViewport) are
    canvas-only — WebGL doesn't use that rendering strategy, so they are
    only passed in the opted-out branch."""
    assert (
        "{name:'canvas',textureOnViewport:true,hideEdgesOnViewport:true,minZoomedFontSize:8}"
        in _js()
    )


def test_deactivate_button_present() -> None:
    html = render_vowl_html(_make_taxonomy(), file_path=None)
    assert 'id="webgl-toggle"' in html
    assert "Deactivate WebGL" in html


def test_toggle_label_reflects_current_state() -> None:
    js = _js()
    assert "btn.textContent=_webglOn?'DeactivateWebGL':'ActivateWebGL';" in js


def test_toggle_click_sets_webgl_0_to_turn_off_and_clears_the_param_to_turn_on() -> None:
    """Clearing the param on re-activation (rather than writing webgl=1) keeps
    the URL clean, since "on" is what the page already renders by default."""
    js = _js()
    assert "if(_webglOn)params.set('webgl','0');elseparams.delete('webgl');" in js


def test_toggle_wiring_is_its_own_function() -> None:
    """Split out of initSterRelationsGraph, the same reason
    wireEdgeTypeFilters is: an unrelated branch inline in that function's body
    is what pushed its cognitive complexity over the ratchet."""
    js = _js()
    assert "functionwireWebglToggle(){" in js
    assert "wireWebglToggle();" in js
