"""Step definitions for query_viz_auto_update.feature."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import OWLIndividual, RDFClass, Taxonomy
from ster.viz_vowl import (
    _build_query_result_html,
    open_query_result_in_browser,
    render_vowl_html,
)

scenarios("../features/ui/query_viz_auto_update.feature")

_NS = "https://ex.org/kai/"
_URI = _NS + "Digital"


@pytest.fixture
def ctx(tmp_path: Path) -> dict:
    return {"tmp_path": tmp_path}


@given("a valid taxonomy with a matching URI")
def given_taxonomy(ctx: dict) -> None:
    tax = Taxonomy()
    tax.namespace_bindings["kai"] = _NS
    tax.owl_classes[_URI] = RDFClass(uri=_URI)
    tax.owl_individuals[_NS + "Dev1"] = OWLIndividual(uri=_NS + "Dev1", types=[_URI])
    ctx["tax"] = tax
    ctx["uris"] = {_URI}


@given("a valid taxonomy with a matching URI and a file path")
def given_taxonomy_with_path(ctx: dict) -> None:
    given_taxonomy(ctx)
    fp = ctx["tmp_path"] / "ont.ttl"
    fp.write_text("", encoding="utf-8")
    ctx["file_path"] = fp


@when("the query result HTML is built with a full_graph_link")
def when_build_with_link(ctx: dict) -> None:
    _, html = _build_query_result_html(ctx["tax"], ctx["uris"], full_graph_link="/full.html")
    ctx["html"] = html


@when("the query result HTML is built without a full_graph_link")
def when_build_without_link(ctx: dict) -> None:
    _, html = _build_query_result_html(ctx["tax"], ctx["uris"])
    ctx["html"] = html


@when("render_vowl_html is called")
def when_render_vowl(ctx: dict) -> None:
    ctx["html"] = render_vowl_html(ctx["tax"], file_path=None)


@when("open_query_result_in_browser is called")
def when_open_query_result(ctx: dict) -> None:
    with (
        patch("ster.viz_vowl._ensure_server", return_value=8000),
        patch("ster.viz_vowl.webbrowser.open"),
        patch("ster.viz_vowl._d3_script_tag", return_value="<script></script>"),
        patch("ster.viz_vowl.Path.home", return_value=ctx["tmp_path"]),
    ):
        _url, out_path = open_query_result_in_browser(ctx["tax"], ctx["uris"], ctx["file_path"])
    ctx["out_path"] = out_path
    ctx["tmp_path_home"] = ctx["tmp_path"]


@then("the rendered HTML contains a Show all nodes button")
def then_has_show_all(ctx: dict) -> None:
    assert "Show all nodes" in ctx["html"]


@then("the rendered HTML does not contain a Show all nodes button")
def then_no_show_all(ctx: dict) -> None:
    assert "Show all nodes" not in ctx["html"]


@then("a full graph HTML file is written alongside the query result file")
def then_full_graph_written(ctx: dict) -> None:
    stem = ctx["file_path"].stem
    full_path = ctx["tmp_path"] / ".cache" / "ster" / f"{stem}_vowl.html"
    assert full_path.exists()
    result_html = ctx["out_path"].read_text(encoding="utf-8")
    assert "Show all nodes" in result_html
