"""Step definitions for map_geography_facet.feature.

Like the other map tests these read the served page's source; see the note atop
tests/unit/test_map_navigation.py for why that is a weak instrument, and
tests/unit/test_map_page_syntax.py for the parse check that backs it up.
"""

from __future__ import annotations

import pytest
from pytest_bdd import scenarios, then, when

from ster.api import _DEFAULT_MAP_QUERY
from ster.geo_map_html import render_map_html

scenarios("../features/ui/map_geography_facet.feature")


@pytest.fixture
def ctx() -> dict:
    return {}


@when("the map page is rendered")
def render(ctx: dict) -> None:
    ctx["page"] = render_map_html(_DEFAULT_MAP_QUERY, "tok")


def _tight(page: str) -> str:
    return page.replace(" ", "").replace("\n", "")


def _geo_handler(page: str) -> str:
    return _tight(page).split("querySelectorAll('.fval[data-geo]')")[1].split("for(const")[0]


@then("the strip offers a row of geography chips")
def offers_chips(ctx: dict) -> None:
    assert "functiongeographyInView()" in _tight(ctx["page"])
    assert "el.innerHTML = geo + groups.map(" in ctx["page"]


@then("the chips are grouped by the tier's own class name")
def grouped_by_class(ctx: dict) -> None:
    """`kind` is the class ster resolved, so the words come from the ontology."""
    assert "constkind=place.kind||'Place'" in _tight(ctx["page"])


@then("picking a geography chip drills to that place")
def chip_drills(ctx: dict) -> None:
    handler = _geo_handler(ctx["page"])
    assert "focus=place.uri" in handler
    assert "level=next" in handler
    assert "draw(true)" in handler


@then("a geography chip never becomes a filter")
def chip_is_not_a_filter(ctx: dict) -> None:
    assert "chosen" not in _geo_handler(ctx["page"])
    assert "querySelectorAll('.fval:not([data-geo])')" in _tight(ctx["page"])


@then("a tier holding a single place is left out")
def one_place_hidden(ctx: dict) -> None:
    assert "if (places.length > 1)" in ctx["page"]


@then("only the nearest tier below the place in focus is offered")
def nearest_tier_only(ctx: dict) -> None:
    body = ctx["page"]
    assert "tiers.sort((a, b) => a.level - b.level);" in body
    assert "return tiers.slice(0, 1);" in body
    assert "focus === null || descendsFrom(a, focus)" in body


@then("the tiers are built from the ancestors already in the payload")
def built_from_ancestors(ctx: dict) -> None:
    assert "for(consturiof(p.ancestors||[]))" in _tight(ctx["page"])
    assert "indexGeography();" in _tight(ctx["page"])


@then("ancestors are resolved through an index rather than a scan")
def resolved_by_index(ctx: dict) -> None:
    body = _tight(ctx["page"])
    assert "constbyUri=newMap();" in body
    assert "points.find(q=>q.uri===uri)" not in body
