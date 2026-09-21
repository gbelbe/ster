"""Step definitions for map_show_everything.feature.

Like the other map tests these read the served page's source. That is a weak
instrument — see the note at the top of tests/unit/test_map_navigation.py — so
what is pinned here is the wiring and the traps, not the rendering.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.geo_map_html import render_map_html

scenarios("../features/ui/map_show_everything.feature")

QUERY = "SELECT * WHERE {?s ?p ?o}"


@pytest.fixture
def ctx() -> dict:
    return {"show_all": False}


@given("the map is asked for Everything mode in the URL")
def asked_for_everything(ctx: dict) -> None:
    ctx["show_all"] = True


@when("the map page is rendered")
@when("the map page is rendered for that request")
def render(ctx: dict) -> None:
    ctx["page"] = render_map_html(QUERY, "tok", show_all=ctx["show_all"])


def _tight(page: str) -> str:
    return page.replace(" ", "").replace("\n", "")


@then("the page offers a Levels and an Everything mode")
def offers_both(ctx: dict) -> None:
    assert ">Levels<" in ctx["page"]
    assert ">Everything<" in ctx["page"]


@then("the page opens in Levels mode")
def opens_on_levels(ctx: dict) -> None:
    assert "let showAll = false;" in ctx["page"]


@then("the page opens in Everything mode")
def opens_on_everything(ctx: dict) -> None:
    assert "let showAll = true;" in ctx["page"]


@then("what is drawn in Everything mode is the leaves of the hierarchy")
def draws_leaves(ctx: dict) -> None:
    assert "!containers.has(p.uri)" in _tight(ctx["page"])


@then("what is drawn in Everything mode ignores the level")
def ignores_the_level(ctx: dict) -> None:
    """The whole point: no tier test on the Everything branch, or the map keeps
    drawing one level and the switch does nothing."""
    body = _tight(ctx["page"])
    assert "if(!showAll)returnatLevel();" in body
    assert "points.filter(p=>!containers.has(p.uri)&&(focus===null||descendsFrom(p,focus)))" in body


@then("Everything mode still keeps only what descends from the focus")
def keeps_the_focus(ctx: dict) -> None:
    assert (
        "points.filter(p=>!containers.has(p.uri)&&(focus===null||descendsFrom(p,focus)))"
        in _tight(ctx["page"])
    )


@then("flipping the switch rewrites the URL in place")
def rewrites_the_url(ctx: dict) -> None:
    """replaceState, not pushState: the switch is not a navigation and must not
    need a press of Back to undo."""
    body = _tight(ctx["page"])
    assert "history.replaceState" in body
    assert "history.pushState" not in body
    assert "searchParams.set('show','all')" in body


@then("flipping the switch leaves the level and the focus alone")
def leaves_state_alone(ctx: dict) -> None:
    """Regression guard: resetting either on toggle drops the reader back at the
    top of the map instead of where they were standing."""
    body = _tight(ctx["page"])
    picker = body.split("constpick=")[1].split("};")[0]
    assert "level=" not in picker
    assert "focus=" not in picker
