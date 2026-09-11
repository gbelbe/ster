"""Dragging an open class takes the individuals it opened along with it.

Expanding a class drops its individuals onto the canvas around it. Before this,
moving that cluster anywhere meant dragging the class and then every individual
separately — the grouping the expansion just created existed on screen but not
in the interaction.

These read the shipped asset rather than driving a browser: the behaviour was
verified live (a 300x120 drag of an expanded class moved both its individuals by
exactly 300x120, while dragging one individual moved neither its sibling nor its
class). What the tests defend is that the wiring survives edits to the file.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_a_drag_is_tracked_between_ticks():
    """Measured tick to tick, not against the grab point, so followers track the
    class continuously rather than jumping when the drag ends."""
    js = _js()

    assert "cy.on('grab','node'" in js
    assert "cy.on('drag','node'" in js
    assert "cy.on('free','node'" in js


def test_only_an_expanded_class_carries_anything():
    """`_expanded` gates it: a class nobody opened has no passengers."""
    assert "if(!_dragAnchor||!_expanded.has(uri))return;" in _js()


def test_the_followers_are_that_class_own_individuals():
    """`ofClass` is set when the expansion adds them, so the followers are
    exactly the nodes that class put on the canvas — and never the class
    itself."""
    js = _js()

    assert "n.data('ofClass')===uri" in js
    assert "&&n!==node" in js


def test_the_anchor_is_released_on_drop():
    """A stale anchor would make the next drag jump by the previous delta."""
    assert "cy.on('free','node',()=>{_dragAnchor=null;});" in _js()


def test_a_class_with_nothing_open_does_no_work():
    assert "if(followers.empty())return;" in _js()
