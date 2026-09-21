"""Marks on a shape wrap, the clustering control retires, and the strip folds.

Three changes that share a page.

A shape already carried the marks of what trades inside it — addBadges has done
that all along. What it did not do was wrap: eight logos went in one row, and
`badgeSize` divided the shape's width between all eight, so across France they
came out 8px each and said nothing. Two rows buy the size back.

The clustering control offered one option and sat permanently pressed. It is
not useless — a query returning a URI column beside the locating one clusters
by it — but the default query returns a label, so nothing qualifies. One option
is not a choice, which is the rule the facets already follow.

And the strip itself folds, because five rows of filters push the map off the
screen for a reader who has finished setting them.

These assert on the served page's source; the parse is guarded by
``test_map_page_syntax.py``.
"""

from __future__ import annotations

from ster.api import _DEFAULT_MAP_QUERY
from ster.geo_map_html import render_map_html


def _page() -> str:
    return render_map_html(_DEFAULT_MAP_QUERY, "tok")


def _tight(page: str) -> str:
    return page.replace(" ", "").replace("\n", "")


# ── the marks on a shape ──────────────────────────────────────────────────────


def test_marks_wrap_onto_a_second_row():
    body = _page()

    assert "const BADGE_PER_ROW_MAX = 4;" in body
    assert "const BADGE_ROWS_MAX = 2;" in body
    assert "return count > BADGE_PER_ROW_MAX ? BADGE_ROWS_MAX : 1;" in body


def test_never_a_third_row():
    """A third row is thinner than the shape it sits on at any readable zoom."""
    body = _tight(_page())

    assert "count>BADGE_PER_ROW_MAX?BADGE_ROWS_MAX:1" in body
    assert "BADGE_ROWS_MAX=2" in body


def test_the_size_is_shared_per_row_not_per_logo():
    """The bug this fixes: width divided between all eight marks gave 8px each
    across France. Divided between the four on a line, they are 17px."""
    body = _page()

    assert "const perRow = Math.ceil(count / rows);" in body
    assert "const perLogo = (wide * 0.8 - BADGE_GAP * (perRow - 1)) / perRow;" in body


def test_the_height_is_shared_between_the_rows():
    """Sizing two rows off the full height overflows the shape vertically."""
    assert "(tall * 0.6 - BADGE_GAP * (rows - 1)) / rows" in _page()


def test_the_icon_box_matches_the_two_rows():
    """A one-row iconSize on a two-row block anchors the marks off-centre."""
    body = _page()

    assert "const height = rows * size + BADGE_GAP * (rows - 1);" in body
    assert "iconSize: [width, height]" in body


def test_the_row_is_allowed_to_wrap():
    assert "flex-wrap:wrap" in _page()


# ── the clustering control ────────────────────────────────────────────────────


def test_the_clustering_control_hides_when_it_offers_no_choice():
    body = _page()

    assert "const useful = options.length > 1;" in body
    assert "seg.hidden = !useful;" in body


def test_the_hidden_attribute_beats_the_class_that_lays_it_out():
    """Regression: .seg sets display:flex, which outranks a UA's
    [hidden]{display:none}, so the control stayed on screen while "hidden"."""
    assert "[hidden] { display:none !important; }" in _page()


def test_the_clustering_label_hides_with_it():
    """Leaving "Cluster by" behind an empty control reads as a broken widget."""
    assert "document.getElementById('seg-label').hidden = !useful;" in _page()


# ── folding the strip ─────────────────────────────────────────────────────────


def test_the_strip_can_be_folded():
    page = _page()

    assert 'id="fold"' in page
    assert "#facets.folded { display:none; }" in page


def test_the_button_says_what_it_will_do():
    body = _page()

    assert "'Show filters' : 'Hide filters'" in body


def test_the_fold_is_remembered_across_reloads():
    """A fold that forgets is a fold you set every time."""
    body = _page()

    assert "const FOLD_KEY = 'ster.map.filters.folded';" in body
    assert "localStorage.setItem(FOLD_KEY" in body


def test_reading_the_fold_survives_blocked_site_data():
    """localStorage throws outright where site data is blocked — not returns
    null — so an unguarded read takes the whole page down with it."""
    body = _tight(_page())

    assert "try{returnlocalStorage.getItem(FOLD_KEY)==='1';}catch{returnfalse;}" in body


def test_redrawing_the_strip_does_not_unfold_it():
    """drawFacets rebuilds the element on every draw, so the class has to be
    reapplied or the strip springs open whenever the map moves."""
    assert "el.classList.toggle('folded', readFold());" in _page()
