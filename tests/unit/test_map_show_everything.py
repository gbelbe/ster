"""Drawing every leaf beneath the focus instead of one tier of the hierarchy.

The map draws one containment level at a time. That answers "what is inside
here" and never "show me all of them", and no query can stand in for it: the
server adds every containing place back as context (``_places_wanted``) so the
drill-down has a hierarchy to walk, which means a stores-only query still
arrives with its countries and its continent attached, and the map opens on
them.

"Everything" means the *leaves*, not the query's rows. The default map query
asks for every entity that can be drawn, so its rows include the containers the
reader is trying to see past — 1,509 rows on the retail file is 1,450 stores
plus 49 regions, 9 countries and a continent — and filtering on ``result`` drew
the flags straight back on top of the stores. Leaf-ness is read from the
ancestor chains the payload already carries, so it holds for stores, sensors or
branches without this module naming any of them.

These assert on the served page's source, the weak instrument the rest of the
map tests use; see the note atop ``test_map_navigation.py``.
"""

from __future__ import annotations

from ster.api import _DEFAULT_MAP_QUERY
from ster.geo_map_html import render_map_html


def _page(show_all: bool = False) -> str:
    return render_map_html(_DEFAULT_MAP_QUERY, "tok", show_all=show_all)


def _tight(page: str) -> str:
    return page.replace(" ", "").replace("\n", "")


# ── the control ───────────────────────────────────────────────────────────────


def test_the_page_offers_a_levels_everything_switch():
    page = _page()

    assert 'id="mode"' in page
    assert ">Levels<" in page
    assert ">Everything<" in page


def test_levels_stays_the_default_mode():
    """Regression: defaulting the other way opens the map on every point in the
    file — 1,477 markers on a world view — instead of the handful of continents
    the drill-down is designed to start from."""
    assert "let showAll = false;" in _page()


def test_the_url_can_ask_for_everything_mode():
    assert "let showAll = true;" in _page(show_all=True)


# ── what gets drawn ───────────────────────────────────────────────────────────


def test_everything_mode_draws_leaves_not_a_tier():
    """Regression: this filtered on p.result, and the default query returns the
    containers too — so Everything mode redrew the country flags and region
    shapes over the stores and looked like no change at all."""
    body = _tight(_page())

    assert "if(!showAll)returnatLevel();" in body
    assert "points.filter(p=>!containers.has(p.uri)&&(focus===null||descendsFrom(p,focus)))" in body


def test_everything_mode_still_respects_the_focus():
    """Drilling into France must still mean France. Dropping this makes the
    crumb trail inert while the switch is on."""
    assert (
        "points.filter(p=>!containers.has(p.uri)&&(focus===null||descendsFrom(p,focus)))"
        in _tight(_page())
    )


def test_the_selector_is_not_shadowed_by_a_local_of_the_same_name():
    """Regression, and the reason it is called placesToDraw. It was `visible`,
    and draw() declares its own `const visible` for the coordinate-filtered
    list — six lines *after* the call. Same scope, so every draw threw
    ReferenceError in the temporal dead zone and the map came up empty with a
    working switch on top of it. Source assertions cannot see a runtime throw,
    so the name itself is what is pinned."""
    body = _tight(_page())

    assert "functionplacesToDraw()" in body
    assert "constplacesToDraw=" not in body
    assert "letplacesToDraw=" not in body


def test_the_level_view_is_left_untouched():
    """atLevel keeps its own meaning — the switch chooses between the two, it
    does not rewrite the tier logic."""
    body = _tight(_page())

    assert "functionatLevel(){" in body
    assert "(p.level??0)===target" in body


def test_the_draw_reads_the_switch_rather_than_the_level_directly():
    """Regression: draw() called atLevel() outright, so the switch could flip
    with nothing on screen changing."""
    body = _tight(_page())

    assert "groupBy!==null?points.filter(p=>rowOf(p)!==null):placesToDraw()" in body


def test_shape_mode_follows_what_is_actually_drawn():
    """Outlines are offered when few enough shapes are on screen. Reading the
    tier instead of the drawn set offers them for places that are not there."""
    body = _tight(_page())

    assert "constwithShapes=placesToDraw().filter(p=>p.shape).length" in body


# ── the facet menu ────────────────────────────────────────────────────────────


def test_facets_read_the_drawn_set_in_both_modes():
    body = _tight(_page())

    assert "constshown=placesToDraw();" in body


def test_the_container_index_is_built_once_per_load():
    """hasChildren() scans every point, so asking it per point is quadratic —
    2.4M ancestor lookups on a 1,500-place file. The chains are already walked
    to index facets; the container set rides along."""
    body = _tight(_page())

    assert "constcontainers=newSet();" in body
    assert "containers.add(ancestor)" in body
    assert "containers.clear();" in body


def test_everything_mode_does_not_expand_the_facet_scope():
    """Performance guard. The level branch grows its scope to the descendants of
    the tier, because a country carries no facets of its own. In Everything mode
    the leaves are already on screen, and expanding them asks descendsFrom about
    every pair of ~1,500 places to learn nothing."""
    body = _tight(_page())

    assert "showAll?shown:points.filter(" in body


# ── the URL ───────────────────────────────────────────────────────────────────


def test_the_switch_rewrites_the_url_in_place():
    body = _tight(_page())

    assert "history.replaceState" in body
    assert "history.pushState" not in body


def test_the_url_drops_the_parameter_in_levels_mode():
    """A shared link should carry the mode it is in, not accumulate a stale one."""
    body = _tight(_page())

    assert "searchParams.set('show','all')" in body
    assert "searchParams.delete('show')" in body


def test_the_switch_does_not_disturb_level_or_focus():
    """Toggling back must land where you were standing."""
    picker = _tight(_page()).split("constpick=")[1].split("};")[0]

    assert "level=" not in picker
    assert "focus=" not in picker
