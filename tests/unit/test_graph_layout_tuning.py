"""The graph layout is tuned for readability, and the tuning is measured.

Benchmarked over 8 real graphs (ster demo, PROV-O, mixed-gear-demo, and the
adeo geography merged with competitors at five expansion levels), 10 to 429
nodes, 5 configurations x 5 runs each in Chrome, scoring

    2 * node-circle overlaps + 2 * label-box overlaps + edge crossings

weighting hidden nodes above merely-crossed edges. The previous settings won
none of the 8 graphs and placed last on the four largest; these won 5 and cut
the score by a median 27% (-23% PROV-O, -32% mixed-gear, -45% adeo merged,
-27% and -32% on the two expanded-class graphs).

Below roughly 20 nodes the whole spread is a few edge crossings, so these
values neither help nor hurt there.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_the_layout_accounts_for_label_size():
    """The decisive one. Nodes are fixed pixel sizes while labels wrap past the
    shape, so without this fcose packs circles smaller than those drawn."""
    assert _js().count("nodeDimensionsIncludeLabels:true") == 2, "both layout passes"


def test_repulsion_and_edge_length_are_the_measured_values():
    js = _js()

    assert js.count("nodeRepulsion:12000") == 2
    assert js.count("idealEdgeLength:180") == 2


def test_nodes_are_given_separation():
    assert _js().count("nodeSeparation:150") == 2


def test_the_previous_values_are_gone():
    """They lost on every graph measured; leaving one behind in either pass
    would silently keep half the old behaviour."""
    js = _js()

    assert "nodeRepulsion:4500" not in js
    assert "nodeRepulsion:5000" not in js
    assert "idealEdgeLength:100" not in js
    assert "idealEdgeLength:110" not in js
