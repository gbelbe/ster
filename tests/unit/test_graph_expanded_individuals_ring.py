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

    assert "_ringAround(node,added.nodes());" in js
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
    assert "if(added.nodes().length>_RING_EDGES_UP_TO)added.edges().addClass('hidden');" in js


def test_hiding_the_spokes_keeps_the_members_attached():
    """`ofClass` is what dragging the class and collapsing it both read, and it
    is set on the node, not on the edge."""
    assert "n.data('ofClass')===uri" in _js()


def test_the_ring_is_settled_outward_not_force_laid_out():
    """Each member steps out along its own spoke until it clears the existing
    graph, which resolves collisions while preserving the circle."""
    js = _js()

    assert "_settleRing(node,added.nodes());" in js
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
