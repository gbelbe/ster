"""Level of detail: what the graph stops drawing once it is too big to read.

Detail is shed in the order it costs. Edge labels and arrowheads go first —
every label is a shaped, measured, background-boxed draw, and arrowheads are
per-edge geometry. Node labels go second, with the nodes shrunk to dots.

This is how the large-graph viewers stay usable (Cytoscape Desktop and Gephi
both drop labels before anything else), and the trade is explicit: past the
second threshold the picture shows structure, not names. Whatever you point at
gets its name back, and the detail panel always has it in full.
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_edge_labels_and_arrowheads_go_first():
    assert "{selector:'edge.lod-quiet',style:{'label':'','target-arrow-shape':'none'}}" in _js()


def test_node_labels_go_second_and_the_node_shrinks():
    js = _js()

    assert "selector:'node.lod-quiet'" in js
    assert "'label':''" in js
    assert "'width':20,'height':20" in js


def test_the_quiet_rules_come_last_so_they_win():
    """Cytoscape resolves equal specificity by order. Placed anywhere earlier,
    the per-type rules above would override these and nothing would change."""
    js = _js()

    assert js.index("selector:'node.lod-quiet'") > js.index("selector:'node[type=\"class\"]'")
    assert js.index("selector:'edge.lod-quiet'") > js.index("selector:'edge[type=\"broader\"]'")


def test_thresholds_come_from_config_with_a_fallback():
    """Injected by the server from ster setup → Graph Viz; the constant is what
    the offline export uses, since it carries no config."""
    js = _js()

    assert "const_lodCfg=globalThis.__STER_GRAPH__.lod||{};" in js
    assert "constLOD_QUIET_EDGES_ABOVE=_lodCfg.lodEdges||300;" in js
    assert "constLOD_QUIET_NODES_ABOVE=_lodCfg.lodNodes||800;" in js


def test_level_of_detail_is_recomputed_when_the_graph_changes_size():
    """Expanding a class is exactly when a graph crosses a threshold, so doing
    this only at first draw would leave the setting half-applied."""
    assert "cy.on('addremove'" in _js()


def test_what_you_point_at_is_readable_again():
    js = _js()

    assert "selector:'node.lod-reveal'" in js
    assert "selector:'edge.lod-reveal'" in js


def test_revealing_a_node_also_reveals_its_edges_and_neighbours():
    """A node with no visible label and no visible connections is not something
    you can explore from."""
    assert (
        "ele.connectedEdges().addClass('lod-reveal').connectedNodes().addClass('lod-reveal')"
        in _js()
    )


def test_an_edge_can_be_clicked_and_named():
    """Edges were not clickable before. An unlabelled arrow is unreadable unless
    you can ask it what it is."""
    js = _js()

    assert "cy.on('tap','edge'" in js
    assert "functionselectEdge(edge){" in js


def test_clearing_the_selection_clears_the_reveal():
    assert "revealAround(null)" in _js()
