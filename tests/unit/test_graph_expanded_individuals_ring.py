"""Expanded individuals land in a ring around their class, not piled on it.

An individual's only edge is `instanceOf` to its class, so the seeding pass —
which places a new node at the average of its existing neighbours — put every
one of them at the class's own position with a few pixels of jitter. A class
holding nine individuals became a blob, and the class's own overlay buttons
ended up underneath its individuals, which is what made "hide individuals"
unclickable.

Measured live on `Leroy Merlin` (9 individuals) in adeo-retail-geography.ttl:

                              before ring    ring + fcose    ring + settle
    overlapping the class          many            1               0
    individual pairs overlapping   many            0               0
    overlapping other nodes          -             -               0

fcose is deliberately not run over the ring: it aims for its ideal edge length
from the class centre, which is shorter than the ring's radius once a class
holds more than a handful, so it pulled members back onto the class.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_expansion_places_individuals_on_a_ring():
    js = _js()

    assert "_ringAround(node,addedNodes);" in js
    assert "function_ringAround(centre,nodes){" in js


def test_the_cluster_grows_in_rings_rather_than_in_radius():
    """One ring has to grow its radius linearly with the count: 200 members at
    68px put it 2,922px out, a circle whose centre and rim are never on screen
    together. Ring k sits one node-width beyond ring k-1, so the same 200 land
    inside 576px — eight rings instead of one enormous one."""
    js = _js()

    assert "constradius=centreRadius+widest/2+ring*step;" in js
    assert "constcapacity=Math.max(1,Math.floor((2*Math.PI*radius)/step));" in js


def test_each_ring_is_packed_to_its_own_circumference():
    """`count` is what fits on *this* ring, not a share of the total."""
    assert "constcount=Math.min(capacity,n-placed);" in _js()


def test_alternate_rings_are_staggered():
    """Members sitting in the gaps of the ring inside them is what makes the
    cluster read as a disc rather than as spokes."""
    assert "constoffset=(ring%2)?Math.PI/count:0;" in _js()


def test_members_are_evenly_spaced_within_a_ring():
    assert "constangle=(2*Math.PI*i)/count+offset-Math.PI/2;" in _js()


def test_the_spokes_are_dropped_once_the_disc_speaks_for_itself():
    """Past a handful the instanceOf edges say nothing the disc does not, and
    cost a line each across the densest part of the picture."""
    js = _js()

    assert "const_RING_EDGES_UP_TO=10;" in js
    assert "if(addedNodes.length>_RING_EDGES_UP_TO)added.edges().addClass('hidden');" in js


def test_hiding_the_spokes_keeps_the_members_attached():
    """`ofClass` is what dragging the class and collapsing it both read, and it
    is set on the node, not on the edge."""
    assert "n.data('ofClass')===uri" in _js()


def test_the_ring_is_settled_outward_not_force_laid_out():
    """Each member steps out along its own spoke until it clears the existing
    graph, which resolves collisions while preserving the circle."""
    js = _js()

    assert "_settleRing(node,addedNodes);" in js
    assert "function_settleRing(centre,nodes){" in js


def test_settling_gives_up_rather_than_looping_forever():
    """A node boxed in on all sides must not spin: the walk is bounded."""
    assert "for(letstep=0;step<24;step++){" in _js()


def test_the_generic_seeding_path_still_seeds():
    """`explore`/`extend` still use the average-of-anchors seeding; only class
    expansion pre-places its nodes, and says so via the flag."""
    js = _js()

    assert "function_seedAndSpread(addedNodes,fp,preseeded){" in js
    assert "for(constnofpreseeded?[]:addedNodes){" in js


def test_a_large_expansion_goes_on_small_and_unlabelled():
    """Past _INDIVIDUAL_COMPACT_ABOVE a name on every node stops helping — the
    ring is the point, not any one member — so they render as small dots."""
    js = _js()

    assert "const_INDIVIDUAL_COMPACT_ABOVE=50;" in js
    assert "if(addedNodes.length>_INDIVIDUAL_COMPACT_ABOVE)addedNodes.addClass('compact');" in js
    assert (
        "{selector:'node.compact',style:{'label':'','width':14,'height':14,'border-width':1}}" in js
    )


def test_compact_sizing_is_decided_before_the_ring_is_measured():
    """A compact node is drawn far smaller than a full individual, so it must be
    classed before its width is read for the ring/room math, not after — else
    the ring plans for nodes three times the size actually drawn."""
    js = _js()

    compact_at = js.index("addedNodes.addClass('compact')")
    ring_at = js.index("_ringAround(node,addedNodes);")
    assert compact_at < ring_at


def test_the_ring_reveals_its_own_label_when_selected():
    """.lod-reveal is declared after .compact, so Cytoscape's last-one-wins
    resolution lets a tap restore the label of an otherwise-compact node."""
    js = _js()

    compact_at = js.index("node.compact")
    reveal_at = js.index("node.lod-reveal")
    assert compact_at < reveal_at


def test_expanding_clears_room_before_the_ring_is_drawn():
    """The ring must never have to fight the rest of the graph for space: room
    is cleared first, then the ring is placed into it."""
    js = _js()

    assert "_makeRoomFor(node,addedNodes.length,widest);" in js
    room_at = js.index("_makeRoomFor(node,addedNodes.length,widest);")
    ring_at = js.index("_ringAround(node,addedNodes);")
    assert room_at < ring_at


def test_room_is_cleared_by_pushing_neighbours_outward_not_by_shrinking_the_ring():
    """_makeRoomFor moves whatever is in the way, along its own line from the
    centre — the ring itself is never deformed to fit a crowded neighbourhood."""
    js = _js()

    assert "function_makeRoomFor(centre,plannedCount,widest){" in js
    assert "constrequired=_ringRadius(centreRadius,widest,plannedCount);" in js
    assert "constshiftX=cp.x+clearance*Math.cos(angle)-refPos.x;" in js
    assert "constshiftY=cp.y+clearance*Math.sin(angle)-refPos.y;" in js


def test_an_obstacle_that_is_itself_a_ring_moves_as_one_group():
    """Pushing an already-expanded class's individuals one by one, each along
    its own angle from the *new* centre, is what could tear that ring apart
    into a stray arc stranded away from its own class. A member's group is
    anchored on its own class and moved as a rigid unit instead."""
    js = _js()

    assert "function_groupAnchor(node){" in js
    assert "constowner=cy.getElementById(ofClass);" in js
    assert "function_groupMembers(anchor){" in js
    assert "constkin=cy.nodes().filter(n=>n.data('ofClass')===anchor.id());" in js


def test_a_groups_radius_is_measured_from_its_real_current_positions():
    """Not re-derived from ring math: a group that is not a perfect ring
    (already nudged by _settleRing, or dragged by hand) must still be cleared
    by its actual footprint, not an idealised one."""
    assert (
        "r=Math.max(r,Math.hypot(p.x-refPos.x,p.y-refPos.y)+Math.max(m.width(),m.height())/2);"
        in _js()
    )


def test_a_pushed_node_remembers_where_it_came_from():
    """The first push is what gets recorded — a node already displaced by one
    open expansion must not have that memory overwritten by a second."""
    js = _js()

    assert "if(!_originalPos.has(m.id()))_originalPos.set(m.id(),{x:p.x,y:p.y});" in js


def test_each_obstacle_group_is_only_considered_once():
    """Every individual of an already-expanded class shares its class's
    anchor, so the group must be evaluated (and, if needed, pushed) exactly
    once per expansion, not once per member."""
    js = _js()

    assert "consthandled=newSet([centre.id()]);" in js
    assert "if(handled.has(anchor.id()))continue;" in js


def test_collapsing_restores_pushed_neighbours():
    """Collapsing a class undoes its own push via _restoreRoom before the
    expansion's bookkeeping (_expanded, shownCount) is cleared."""
    js = _js()

    assert "_restoreRoom(uri);" in js
    assert "function_restoreRoom(classUri){" in js
    restore_at = js.index("_restoreRoom(uri);")
    expanded_delete_at = js.index(
        "_expanded.delete(uri);node.data('shownCount',0);_saveLayout();return;"
    )
    assert restore_at < expanded_delete_at


def test_a_node_pushed_by_two_expansions_waits_for_both_to_close():
    """Only a node with no pushers left actually moves back — shared neighbours
    of two simultaneously-open classes must not snap back while either is
    still open."""
    js = _js()

    assert "constremaining=(_pusherCount.get(id)||1)-1;" in js
    assert "if(remaining>0){_pusherCount.set(id,remaining);continue;}" in js
