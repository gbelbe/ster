"""Weight falls off with depth, so the shape of a graph reads before its detail.

"Order" is the codebase's own word, not a new one: first order is a root class —
the same set the existing first-order filter uses — second is its direct
children, and so on down. Each step loses border weight, font size and opacity.

The top two orders keep their labels whatever the node count. Shedding labels is
right for the long tail and wrong for the handful of nodes carrying the
structure, which is what lets a 1,400-node graph still say what it is.

Measured on the four-file ontology at ?full=1 (1,417 nodes, level of detail
active): ord1 40 nodes / 5px / all labelled, ord2 30 / 3px / all labelled,
ord3 148 / 2px / opacity .82 / none labelled, ord4 1,199 / 1px / .6 / none.
Nothing left unclassed.
"""

from __future__ import annotations

import re

from ster.viz_vowl import _app_js


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_each_order_is_lighter_than_the_one_above():
    js = _js()

    assert "selector:'node.ord1',style:{'border-width':5" in js
    assert "selector:'node.ord2',style:{'border-width':3" in js
    assert "selector:'node.ord3',style:{'border-width':2" in js
    assert "selector:'node.ord4',style:{'border-width':1" in js


def test_the_tail_recedes_but_stays_visible():
    """Dimming recedes a node; it must not take it out of play."""
    js = _js()

    assert "'opacity':.82" in js
    assert "'opacity':.6" in js


def test_the_top_two_orders_keep_their_labels_under_level_of_detail():
    """The rules sit after the lod-quiet rules, which is the only reason they
    win — Cytoscape resolves equal specificity by order."""
    js = _js()

    assert "selector:'node.lod-quiet.ord1'" in js
    assert "selector:'node.lod-quiet.ord2'" in js
    assert js.index("selector:'node.lod-quiet.ord1'") > js.index("selector:'node.lod-quiet'")


def test_depth_is_walked_from_the_roots_down():
    """Roots are the nodes nothing in the hierarchy points down to: root
    classes, schemes, and anything orphaned."""
    js = _js()

    assert "n.outgoers('edge').filter(e=>_HIERARCHY_EDGES.has(e.data('type'))).empty()" in js


def test_below_means_the_same_here_as_when_dragging_a_branch():
    """Both walks read _HIERARCHY_EDGES, so a node that follows its parent on a
    drag is the same node that counts as its child for weighting.

    Asserted on the functions rather than by counting occurrences of one
    spelling: the loop variable is an implementation detail, and a rename should
    not read as a broken invariant.
    """
    raw = _app_js()
    walkers = ["_descendantsOf", "_hierarchyChildren"]

    for name in walkers:
        body = re.search(rf"function {name}\(.*?\n}}", raw, re.S)
        assert body is not None, f"{name} not found"
        assert "_HIERARCHY_EDGES" in body.group(0), f"{name} uses its own edge set"


def test_the_walk_stops_rather_than_multiplying_classes():
    """Past four the difference stops being legible."""
    assert "const_MAX_ORDER=4;" in _js()


def test_what_the_walk_never_reached_reads_as_tail_not_as_root():
    """A cycle with no entry point, or a node hanging off no hierarchy, would
    otherwise be left unclassed — which renders exactly like a root."""
    assert "cy.nodes().filter(n=>!seen.has(n.id())).addClass('ord4');" in _js()


def test_orders_are_recomputed_whenever_the_graph_changes():
    """Expanding a class adds a new layer of children; computing this once at
    load would leave every one of them weighted as though it were a root."""
    js = _js()

    assert "applyHierarchyOrders();" in js
    assert js.index("applyHierarchyOrders();") > js.index("_refreshLodButtons();")
