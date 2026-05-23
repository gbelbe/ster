"""Step definitions for sparql_qname_ac.feature."""

from __future__ import annotations

from pytest_bdd import given, scenarios, then, when

from ster.model import OWLIndividual, RDFClass, Taxonomy
from ster.sparql_query import (
    _uri_index_cache,
    build_uri_index,
    build_uri_index_cached,
    qname_candidates,
)

scenarios("../features/ui/sparql_qname_ac.feature")

_NS = "https://ex.org/kai/"


# ── Fixtures / context ────────────────────────────────────────────────────────


import pytest


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given('a taxonomy with two classes "Digital" and "Analog" and one individual "Device"')
def given_taxonomy(ctx: dict) -> None:
    tax = Taxonomy()
    for name in ("Digital", "Analog"):
        uri = _NS + name
        tax.owl_classes[uri] = RDFClass(uri=uri)
    ind_uri = _NS + "Device"
    tax.owl_individuals[ind_uri] = OWLIndividual(uri=ind_uri)
    tax.namespace_bindings["kai"] = _NS
    ctx["taxonomy"] = tax
    ctx["index"] = build_uri_index(tax)


@given('the cursor is after "a " in the query')
def given_cursor_after_a(ctx: dict) -> None:
    ctx["sparql_context"] = "class"
    ctx["buffer_snippet"] = "?x a kai:"
    ctx["buf_pos"] = len("?x a kai:")


@given('the cursor is after "rdfs:subClassOf " in the query')
def given_cursor_after_subclassof(ctx: dict) -> None:
    ctx["sparql_context"] = "class"
    ctx["buffer_snippet"] = "rdfs:subClassOf kai:"
    ctx["buf_pos"] = len("rdfs:subClassOf kai:")


@given("the cursor is in a generic position")
def given_cursor_generic(ctx: dict) -> None:
    ctx["sparql_context"] = "any"
    ctx["buffer_snippet"] = "?x ?p kai:"
    ctx["buf_pos"] = len("?x ?p kai:")


@given("the popup has more items than fit in the visible window of 5 rows")
def given_many_items(ctx: dict) -> None:
    ctx["window_h"] = 5
    ctx["n_items"] = 12


@given("the URI index has been built for a set of paths")
def given_uri_index_built(ctx: dict, tmp_path) -> None:
    ttl = tmp_path / "test.ttl"
    ttl.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix kai: <https://ex.org/kai/> .\n"
        "kai:Digital a owl:Class .\n",
        encoding="utf-8",
    )
    _uri_index_cache.clear()
    ctx["paths"] = [ttl]
    ctx["first_index"] = build_uri_index_cached([ttl])


# ── When ──────────────────────────────────────────────────────────────────────


@when('the QName trigger fires for prefix "kai"')
def when_trigger_fires(ctx: dict) -> None:
    idx = ctx["index"]
    sparql_ctx = ctx.get("sparql_context", "any")
    ctx["candidates"] = qname_candidates(idx, "kai", "", sparql_ctx)


@when('the QName trigger fires for prefix "kai" and the user types "Di"')
def when_trigger_and_filter(ctx: dict) -> None:
    idx = ctx["index"]
    sparql_ctx = ctx.get("sparql_context", "any")
    ctx["candidates"] = qname_candidates(idx, "kai", "Di", sparql_ctx)


@when("the user moves the cursor down past the visible window")
def when_cursor_past_window(ctx: dict) -> None:
    from ster.nav.query_logic import _qn_clamp_scroll

    ctx["cursor"] = ctx["window_h"] + 2  # well past window
    ctx["scroll"] = _qn_clamp_scroll(ctx["cursor"], 0, ctx["window_h"])


@when("the file modification time changes")
def when_mtime_changes(ctx: dict) -> None:
    from unittest.mock import patch

    paths = ctx["paths"]
    original_stat = paths[0].stat()

    class FakeStat:
        st_mtime = original_stat.st_mtime + 1

    with patch("pathlib.Path.stat", return_value=FakeStat()):
        ctx["second_index"] = build_uri_index_cached(paths)


# ── Then ──────────────────────────────────────────────────────────────────────


@then('the popup lists all local names for "kai" in alphabetical order')
def then_all_names_alphabetical(ctx: dict) -> None:
    cands = ctx["candidates"]
    assert cands == sorted(cands)
    assert len(cands) >= 3  # Digital, Analog, Device


@then('the popup includes both "Digital" and "Analog" and "Device"')
def then_includes_all(ctx: dict) -> None:
    cands = ctx["candidates"]
    assert "Digital" in cands
    assert "Analog" in cands
    assert "Device" in cands


@then("the popup lists only class local names")
def then_only_classes(ctx: dict) -> None:
    assert "Device" not in ctx["candidates"]


@then('"Digital" and "Analog" appear in the list')
def then_classes_present(ctx: dict) -> None:
    assert "Digital" in ctx["candidates"]
    assert "Analog" in ctx["candidates"]


@then('"Device" does not appear in the list')
def then_individual_absent(ctx: dict) -> None:
    assert "Device" not in ctx["candidates"]


@then('the popup includes both "Digital" and "Device"')
def then_includes_class_and_individual(ctx: dict) -> None:
    assert "Digital" in ctx["candidates"]
    assert "Device" in ctx["candidates"]


@then("the popup items are sorted alphabetically")
def then_sorted(ctx: dict) -> None:
    cands = ctx["candidates"]
    assert cands == sorted(cands)


@then("qn_scroll advances so the selected item remains visible")
def then_scroll_advances(ctx: dict) -> None:
    scroll = ctx["scroll"]
    cursor = ctx["cursor"]
    window_h = ctx["window_h"]
    assert scroll <= cursor
    assert scroll + window_h > cursor


@then('only "Digital" appears in the popup')
def then_only_digital(ctx: dict) -> None:
    assert "Digital" in ctx["candidates"]
    assert len([c for c in ctx["candidates"] if not c.lower().startswith("di")]) == 0


@then('"Analog" does not appear in the popup')
def then_analog_absent(ctx: dict) -> None:
    assert "Analog" not in ctx["candidates"]


@then("calling build_uri_index_cached returns a fresh index")
def then_fresh_index(ctx: dict) -> None:
    assert ctx["second_index"] is not ctx["first_index"]
