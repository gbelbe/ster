"""Clicking one edge shows every other use of the same relation.

"Which individuals share this property" is a question about the predicate, not
about the pair you happened to click, so selecting an edge marks all of its kin
and lists them in the panel.

Verified live against adeo-retail-geography.ttl + competitors.ttl: tapping one
`subClassOf` edge marked all 24 of them and 26 endpoints; tapping the single
`hasRetailType` edge reported "Also used here (0) — Nowhere else in this view."
"""

from __future__ import annotations

from ster.viz_vowl import _app_js


def _js() -> str:
    return _app_js().replace(" ", "").replace("\n", "")


def test_the_same_relation_is_identified_by_type_and_label():
    """The payload gives an edge a type and a label and no property URI. For an
    object or datatype property the label *is* the property name; for
    subClassOf / instanceOf / broader the label is empty and the type is the
    whole predicate. The pair identifies it either way."""
    raw = _app_js()

    # raw string: the NUL separator is six literal characters in the JS, and
    # only r"" keeps it that way through Python's own escaping.
    assert r"edge.data('type') + '\u0000' + (edge.data('label') || '')".replace(
        " ", ""
    ) in raw.replace(" ", "")


def test_selecting_an_edge_marks_every_edge_that_shares_its_predicate():
    js = _js()

    assert "constkin=_edgeKin(edge);" in js
    assert "kin.addClass('kin').addClass('lod-reveal');" in js


def test_the_endpoints_of_those_edges_are_marked_too():
    """The relation is only legible if you can see what it joins."""
    assert "kin.connectedNodes().addClass('kin-end').addClass('lod-reveal');" in _js()


def test_kin_styling_outranks_both_the_type_colours_and_the_dimming():
    """The point of picking an edge is to see the others, so they have to show
    through whatever is currently receding them."""
    js = _js()

    assert js.index("selector:'edge.kin'") > js.index("selector:'edge.dimmed'")
    assert js.index("selector:'edge.kin'") > js.index("selector:'edge[type=\"objectProperty\"]'")


def test_the_kin_are_listed_and_the_list_is_capped():
    """A common predicate can have thousands; a panel that long is a scroll,
    not a list."""
    js = _js()

    assert "const_KIN_LIST_LIMIT=25;" in js
    assert "'…and'+(others.length-_KIN_LIST_LIMIT)+'more,allhighlightedinthegraph.'" in js


def test_a_relation_used_once_says_so_rather_than_showing_an_empty_list():
    assert "'Nowhereelseinthisview.'" in _js()


def test_clearing_the_selection_clears_the_kin():
    js = _js()

    assert "cy.edges('.kin').removeClass('kin');" in js
    assert "cy.nodes('.kin-end').removeClass('kin-end');" in js
