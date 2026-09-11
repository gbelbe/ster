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


def test_the_radius_grows_with_the_count():
    """A fixed radius would make a large class overlap itself: the ring has to
    be big enough to seat every member side by side."""
    assert "constradius=Math.max(centreRadius+widest,(n*spacing)/(2*Math.PI));" in _js()


def test_members_are_evenly_spaced():
    assert "constangle=(2*Math.PI*i)/n-Math.PI/2;" in _js()


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
