"""Dragging a node carries everything beneath it, at every level.

This used to apply to an expanded class and its individuals alone, which meant
the one arrangement you could rearrange was the one the machine had just made.

"Beneath" is read off the hierarchy edges, all of which point child → parent: a
subclass names its superclass, a narrower concept its broader, an individual its
class, a concept its scheme. So a node's children are the *sources* of its
incoming edges of those types.

Verified live on the four-file ontology: grabbing `BusinessActivities` moved all
15 nodes beneath it by exactly the drag delta, and moved nothing else.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_the_hierarchy_is_the_four_child_to_parent_edges():
    js = _js()

    assert "const_HIERARCHY_EDGES=newSet(['subClassOf','broader','instanceOf','inScheme']);" in js


def test_children_are_the_sources_of_incoming_hierarchy_edges():
    """Following outgoers instead would drag a node's ancestors, which is the
    whole graph."""
    js = _js()

    assert "for(constedgeofcurrent.incomers('edge').toArray()){" in js
    assert "constchild=edge.source();" in js


def test_a_cycle_or_a_second_parent_cannot_loop_it():
    assert "if(seen.has(child.id()))continue;" in _js()


def test_the_branch_is_walked_once_per_drag_not_once_per_tick():
    """The set cannot change mid-drag, and re-walking a deep branch on every
    mouse-move is what would make a large graph stutter."""
    js = _js()

    assert "cy.on('grab','node',e=>{" in js
    assert "_dragFollowers=_descendantsOf(e.target);" in js


def test_the_delta_is_measured_between_ticks():
    """Against the grab point instead, the followers would lag by a growing
    offset and snap at the end."""
    assert "_dragAnchor={x:p.x,y:p.y};" in _js()


def test_dropping_releases_both_the_anchor_and_the_branch():
    """A stale follower set would make the next drag move the previous
    branch."""
    assert "cy.on('free','node',()=>{_dragAnchor=null;_dragFollowers=null;});" in _js()
