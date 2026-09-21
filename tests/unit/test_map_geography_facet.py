"""Geography as chips in the filter strip.

The containment hierarchy was reachable only by clicking a shape on the map,
which fails whenever the shape is small, buried under markers, or off screen.
The tiers now sit beside the other filters.

Two things make this ontology-agnostic. A tier is named by the class ster had
already resolved for the place — Continent, Country, AdministrativeArea on a
geography, Site and Floor on a building — so nothing here spells a vocabulary.
And the values come from the ancestor chains the payload already carries, so
there is no second request and no new server field.

They navigate rather than filter, which was a deliberate choice: picking a
country goes there, the way clicking its shape does. The cost is that geography
cannot be combined the way a real facet can — no France OR Spain — and the tier
hides once used, because a tier with one place left says nothing.

Assertions read the served page's source, the weak instrument the rest of the
map tests use; see the note atop ``test_map_navigation.py``. The parse itself is
guarded by ``test_map_page_syntax.py``.
"""

from __future__ import annotations

from ster.api import _DEFAULT_MAP_QUERY
from ster.geo_map_html import render_map_html


def _page() -> str:
    return render_map_html(_DEFAULT_MAP_QUERY, "tok")


def _tight(page: str) -> str:
    return page.replace(" ", "").replace("\n", "")


# ── the chips ─────────────────────────────────────────────────────────────────


def test_the_strip_offers_a_row_of_geography_chips():
    body = _tight(_page())

    assert "functiongeographyInView()" in body
    assert "el.innerHTML=geo+groups.map(" in body


def test_a_tier_is_named_by_the_place_s_own_class():
    """Not by a vocabulary this file knows: `kind` is what ster resolved, so the
    words come from the ontology rather than from here."""
    body = _tight(_page())

    assert "constkind=place.kind||'Place'" in body
    assert "plain(tier.kind)" in body


def test_geography_leads_the_strip():
    assert "el.innerHTML = geo + groups.map(" in _page()


# ── what they do ──────────────────────────────────────────────────────────────


def test_picking_a_place_drills_to_it():
    """The same move the map makes, so the two ways in cannot disagree."""
    body = _tight(_page())
    handler = body.split("querySelectorAll('.fval[data-geo]')")[1].split("for(const")[0]

    assert "focus=place.uri" in handler
    assert "level=next" in handler
    assert "draw(true)" in handler


def test_a_geography_chip_never_becomes_a_filter():
    """Regression guard for the choice made here. If a geo chip fell through to
    the filter handler it would enter `chosen`, and the strip would hold two
    controls that look identical and mean different things."""
    body = _tight(_page())
    handler = body.split("querySelectorAll('.fval[data-geo]')")[1].split("for(const")[0]

    assert "chosen" not in handler
    assert "querySelectorAll('.fval:not([data-geo])')" in body


def test_a_place_with_nothing_beneath_it_is_not_offered():
    """childLevel is null for a leaf; drilling to one lands on an empty map."""
    body = _tight(_page())
    handler = body.split("querySelectorAll('.fval[data-geo]')")[1].split("for(const")[0]

    assert "if(next===null)return;" in handler


# ── which tiers show ──────────────────────────────────────────────────────────


def test_a_tier_holding_one_place_is_left_out():
    """Same rule the other facets follow: one value cannot discriminate."""
    assert "if (places.length > 1)" in _page()


def test_only_tiers_below_the_focus_are_offered():
    body = _tight(_page())

    assert "a.uri!==focus" in body
    assert "focus===null||descendsFrom(a,focus)" in body


def test_only_the_nearest_tier_below_the_focus_is_offered():
    """Regression: every tier below the focus put all 96 regions of six
    countries in one row at the top level. The drill-down narrows as you
    descend; the chips do the same."""
    body = _page()

    assert "tiers.sort((a, b) => a.level - b.level);" in body
    assert "return tiers.slice(0, 1);" in body


# ── cost ──────────────────────────────────────────────────────────────────────


def test_the_tiers_are_built_from_ancestors_already_in_the_payload():
    body = _tight(_page())

    assert "for(consturiof(p.ancestors||[]))" in body
    assert "indexGeography();" in body


def test_ancestors_are_resolved_through_an_index_not_a_scan():
    """Resolving an ancestor with points.find() is a scan per ancestor per
    place — the quadratic shape this file has already been bitten by twice."""
    body = _tight(_page())

    assert "constbyUri=newMap();" in body
    assert "byUri.get(uri)" in body
    assert "points.find(q=>q.uri===uri)" not in body
