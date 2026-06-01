"""BDD step definitions for tests/features/owl/graph_asset_separation.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import viz_vowl
from ster.model import Label, OWLIndividual, RDFClass, Taxonomy
from ster.viz_vowl import _app_js, render_vowl_html

scenarios("../features/owl/graph_asset_separation.feature")

NS = "https://example.org/onto#"
_LIB_MARKER = "/*__STUB_CYTOSCAPE_LIB__*/"


@pytest.fixture
def ctx() -> dict:
    return {}


def _stub(version: str) -> str:
    return (
        f"<script>{_LIB_MARKER} window.cytoscape=function(){{return{{}};}}; // {version}</script>"
    )


# ── Given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('an ontology with an individual "{ind}" of class "{cls}"'))
def given_ontology(ctx: dict, ind: str, cls: str) -> None:
    t = Taxonomy()
    t.owl_classes[NS + cls] = RDFClass(uri=NS + cls, labels=[Label("en", cls)])
    t.owl_individuals[NS + ind] = OWLIndividual(
        uri=NS + ind, labels=[Label("en", ind)], types=[NS + cls]
    )
    ctx["taxonomy"] = t
    ctx["ind"] = ind


# ── When ──────────────────────────────────────────────────────────────────────


@when("I load the ster graph app asset")
def when_load_asset(ctx: dict) -> None:
    ctx["asset"] = _app_js()


@when("I render the graph page with a stub Cytoscape library")
def when_render_stub(ctx: dict, monkeypatch) -> None:
    monkeypatch.setattr(viz_vowl, "_cytoscape_script_tag", lambda: _stub("3.29.2"))
    ctx["html"] = render_vowl_html(ctx["taxonomy"], file_path=None)


@when("I render the page with the old library and again with a new library")
def when_render_two_libs(ctx: dict, monkeypatch) -> None:
    monkeypatch.setattr(viz_vowl, "_cytoscape_script_tag", lambda: _stub("3.29.2-old"))
    ctx["html_old"] = render_vowl_html(ctx["taxonomy"], file_path=None)
    monkeypatch.setattr(
        viz_vowl,
        "_cytoscape_script_tag",
        lambda: (
            "<script>/* 9.9.9 NEW different bytes */window.cytoscape=function(){return 42;};</script>"
        ),
    )
    ctx["html_new"] = render_vowl_html(ctx["taxonomy"], file_path=None)


# ── Then ──────────────────────────────────────────────────────────────────────


@then("the asset is non-empty")
def then_asset_nonempty(ctx: dict) -> None:
    assert ctx["asset"].strip()


@then("the asset wires up the Cytoscape factory")
def then_asset_factory(ctx: dict) -> None:
    assert "cytoscape(" in ctx["asset"]


@then("the page contains the vendored library layer")
def then_has_lib(ctx: dict) -> None:
    assert _LIB_MARKER in ctx["html"]


@then("the page contains the data injection layer")
def then_has_data(ctx: dict) -> None:
    assert "window.__STER_GRAPH__" in ctx["html"]


@then("the page contains the app asset layer")
def then_has_app(ctx: dict) -> None:
    assert _app_js().strip() in ctx["html"]


@then("the app asset appears after the library script closes")
def then_app_after_lib(ctx: dict) -> None:
    html = ctx["html"]
    lib_end = html.index("</script>", html.index(_LIB_MARKER))
    assert html.index(_app_js().strip()) > lib_end


@then("the app layer is byte-for-byte identical across both renders")
def then_app_identical(ctx: dict) -> None:
    app = _app_js().strip()
    assert app in ctx["html_old"]
    assert app in ctx["html_new"]


@then("the individual data appears in the page")
def then_data_in_page(ctx: dict) -> None:
    assert NS + ctx["ind"] in ctx["html"]


@then("the app asset carries no per-ontology data")
def then_app_no_data(ctx: dict) -> None:
    assert NS + ctx["ind"] not in _app_js()
