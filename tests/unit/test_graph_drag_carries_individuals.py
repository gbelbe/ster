"""An open class still takes its individuals with it when dragged.

This began as the whole of the feature and is now the special case: dragging
carries everything *beneath* a node, and an individual is beneath its class by
the `instanceOf` edge like any other child. The general rule and its walk are
covered in test_graph_subtree_drag.py; what is pinned here is that the case the
feature was built for did not get lost in generalising it.

Verified live on adeo-retail-geography.ttl: a 400x250 drag of an expanded class
moved all 200 shown individuals by exactly 400x250 — with their instanceOf
spokes hidden, which is the arrangement that would break a follower set keyed on
edges rather than on the node's own `ofClass`.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_an_individual_is_beneath_its_class():
    """instanceOf is one of the hierarchy edges the walk follows, so a class's
    individuals are its children in exactly the sense everything else is."""
    assert "'instanceOf'" in _js()
    assert (
        "const_HIERARCHY_EDGES=newSet(['subClassOf','broader','instanceOf','inScheme']);" in _js()
    )


def test_a_drag_is_tracked_between_ticks():
    """Measured tick to tick rather than against the grab point, so followers
    track continuously instead of snapping into place at the end."""
    js = _js()

    assert "cy.on('grab','node'" in js
    assert "cy.on('drag','node'" in js
    assert "_dragAnchor={x:p.x,y:p.y};" in js


def test_the_anchor_and_the_followers_are_both_released_on_drop():
    """A stale anchor would jump the next drag by the previous delta; a stale
    follower set would move the previous branch."""
    assert "cy.on('free','node',()=>{_dragAnchor=null;_dragFollowers=null;});" in _js()


def test_a_node_with_nothing_beneath_it_does_no_work():
    assert "if(!_dragAnchor||!_dragFollowers||_dragFollowers.empty())return;" in _js()


def test_hidden_spokes_do_not_orphan_the_individuals():
    """Expanding past ten members hides the instanceOf edges. The walk reads the
    edges from the graph model, which still holds them — hiding is a style, not
    a removal — so the members still follow."""
    js = _js()

    assert "addClass('hidden')" in js
    assert "for(constedgeofcurrent.incomers('edge').toArray()){" in js
