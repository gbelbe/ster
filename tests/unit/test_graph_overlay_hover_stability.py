"""Reaching for a node's overlay button must not hand the overlay to a neighbour.

The buttons hug the node's top and bottom edges, but in a crowded graph the trip
onto one still crosses whatever node is stacked over that edge. Switching the
overlay the instant the cursor touches that node moved the buttons out from
under a cursor already on its way to them: you reach for "show individuals" and
it becomes a different class's button, or leaves entirely.

Verified live against adeo-retail-geography.ttl + competitors.ttl: with the
overlay on `Kbane` and the cursor on its button, a `mouseover` from the stacked
`Obramat` left the button where it was, and the click expanded Kbane (1
individual) and not Obramat (0).
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_a_button_under_the_cursor_cannot_be_stolen():
    """The case the grace period exists to protect: while the cursor is on a
    button, a node firing underneath it does not get to interrupt."""
    js = _js()

    assert "if(_onOverlayBtn)return;" in js
    assert "b.addEventListener('mouseenter',()=>{_onOverlayBtn=true;" in js
    assert "b.addEventListener('mouseleave',()=>{_onOverlayBtn=false;" in js


def test_a_different_node_waits_out_a_grace_period():
    """Long enough to cross a node in passing; short enough that deliberately
    hovering a neighbour still feels immediate."""
    js = _js()

    assert "const_RETARGET_GRACE_MS=260;" in js
    assert "_retargetTimer=setTimeout(" in js


def test_returning_to_the_same_node_switches_nothing():
    assert "if(uri===_exploreHoverUri){_cancelRetarget();_showOverlay(node);return;}" in _js()


def test_the_grace_period_only_applies_while_an_overlay_is_up():
    """With no overlay showing there is nothing to protect, so the first node
    hovered takes it immediately."""
    assert "if(_exploreHoverUri&&exploreBtn.style.display==='block'){" in _js()


def test_hiding_the_overlay_drops_any_pending_switch():
    """A pending switch outliving the overlay would pop the buttons back up on
    a node the cursor has already left."""
    assert "function_hideOverlay(){_cancelRetarget();" in _js()


def test_a_missing_button_skips_its_wiring_rather_than_aborting_setup():
    """This loop sits mid-function: `return` on a null button would abandon
    everything wired after it, including both click handlers."""
    js = _js()

    assert "if(!b)continue;" in js
    assert "if(!b)return;" not in js
