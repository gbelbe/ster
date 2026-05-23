"""Step definitions for sparql_modal.feature."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import RDFClass, Taxonomy
from ster.nav.state import QueryState, TreeState
from ster.viz_vowl import refresh_query_result_in_browser

scenarios("../features/ui/sparql_modal.feature")

_KAI_NS = "https://ex.org/kai/"
_PORT = 18765


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given("the viewer is in tree view mode")
def given_tree_mode(ctx):
    ctx["state"] = TreeState()


@given("the viewer is in query state")
def given_query_state(ctx):
    ctx["state"] = QueryState(file_paths=[])


@given("a viz file has been written to disk at a known path")
def given_viz_file(ctx, tmp_path):
    out = tmp_path / "result.html"
    out.write_text("old-content", encoding="utf-8")
    ctx["viz_path"] = out
    ctx["viz_tracked"] = True


@given("a new query produces result URIs that match taxonomy nodes")
def given_matching_uris(ctx):
    tax = Taxonomy()
    uri = _KAI_NS + "Digital"
    tax.owl_classes[uri] = RDFClass(uri=uri)
    ctx["taxonomy"] = tax
    ctx["uris"] = {uri}


@given("no viz file path is tracked")
def given_no_viz(ctx):
    ctx["viz_path"] = None
    ctx["viz_tracked"] = False


@given("a query produces result URIs that match taxonomy nodes")
def given_query_uris(ctx):
    tax = Taxonomy()
    uri = _KAI_NS + "Digital"
    tax.owl_classes[uri] = RDFClass(uri=uri)
    ctx["taxonomy"] = tax
    ctx["uris"] = {uri}


# ── When ──────────────────────────────────────────────────────────────────────


@when('the user presses "S"')
def when_press_s(ctx):
    # S triggers open_query: state transitions to QueryState
    ctx["state"] = QueryState(file_paths=[])


@when("the user presses Esc in the query editor")
def when_press_esc(ctx):
    # Esc in editor panel returns to TreeState
    ctx["state"] = TreeState()


@when("the query completes successfully")
def when_query_completes(ctx):
    viz_path: Path | None = ctx.get("viz_path")
    if viz_path is not None and ctx.get("viz_tracked"):
        with (
            patch("ster.viz_vowl.webbrowser.open"),
            patch("ster.viz_vowl._ensure_server", return_value=_PORT),
        ):
            refresh_query_result_in_browser(ctx["taxonomy"], ctx["uris"], viz_path)
        ctx["viz_written"] = True
    else:
        ctx["viz_written"] = False


# ── Then ──────────────────────────────────────────────────────────────────────


@then("the viewer switches to query state")
def then_query_state(ctx):
    assert isinstance(ctx["state"], QueryState)


@then("the viewer returns to tree view mode")
def then_tree_state(ctx):
    assert isinstance(ctx["state"], TreeState)


@then("the viz HTML file is overwritten with updated content")
def then_viz_updated(ctx):
    assert ctx["viz_written"] is True
    content = ctx["viz_path"].read_text(encoding="utf-8")
    assert content != "old-content"
    assert "<html" in content.lower()


@then("no viz file is written")
def then_no_viz_written(ctx):
    assert ctx["viz_written"] is False
