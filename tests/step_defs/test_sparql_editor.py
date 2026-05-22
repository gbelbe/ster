"""BDD step definitions for SPARQL editor smart completions."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import RDFClass, Taxonomy

scenarios("../features/ui/sparql_editor.feature")

_KAI_NS = "https://ex.org/kai/"


@pytest.fixture
def ctx():
    return {
        "taxonomy": None,
        "header": "",
        "index": {},
        "buffer": "",
        "pos": 0,
        "qs": None,
    }


# ── Given ──────────────────────────────────────────────────────────────────────


@given("an empty taxonomy")
def given_empty_taxonomy(ctx):
    ctx["taxonomy"] = Taxonomy()


@given("a taxonomy with kai namespace binding")
def given_taxonomy_kai(ctx):
    tax = Taxonomy()
    tax.namespace_bindings["kai"] = _KAI_NS
    ctx["taxonomy"] = tax


@given("a taxonomy that redeclares the rdf namespace")
def given_taxonomy_rdf_redeclared(ctx):
    tax = Taxonomy()
    tax.namespace_bindings["rdf"] = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    ctx["taxonomy"] = tax


@given('a class with URI "https://ex.org/kai/Digital"')
def given_kai_digital_class(ctx):
    ctx["taxonomy"].owl_classes[_KAI_NS + "Digital"] = RDFClass(uri=_KAI_NS + "Digital")


@given('a SPARQL buffer "WHERE " with cursor at the end')
def given_buffer_where(ctx):
    ctx["buffer"] = "WHERE "
    ctx["pos"] = len("WHERE ")


@given('a query state with buffer "WH"')
def given_qs_wh(ctx):
    from ster.nav.state import QueryState

    ctx["qs"] = QueryState(query_buffer="WH", query_pos=2)


# ── When ───────────────────────────────────────────────────────────────────────


@when("I build the prefix header")
def when_build_header(ctx):
    from ster.sparql_query import build_prefix_header

    ctx["header"] = build_prefix_header(ctx["taxonomy"].namespace_bindings)


@when("I build the QName index")
def when_build_qname_index(ctx):
    from ster.sparql_query import build_qname_index

    ctx["index"] = build_qname_index(ctx["taxonomy"])


@when('the user types "{"')
def when_type_brace(ctx):
    from ster.nav.query_logic import _auto_close_bracket

    ctx["buffer"], ctx["pos"] = _auto_close_bracket(ctx["buffer"], ctx["pos"], "{")


@when('the user inserts keyword "WHERE"')
def when_insert_where(ctx):
    from ster.nav.query_logic import _sparql_kw_insert

    _sparql_kw_insert(ctx["qs"], "WHERE")
    ctx["buffer"] = ctx["qs"].query_buffer
    ctx["pos"] = ctx["qs"].query_pos


# ── Then ───────────────────────────────────────────────────────────────────────


@then('the header declares "PREFIX rdf:"')
def then_header_rdf(ctx):
    assert "PREFIX rdf:" in ctx["header"]


@then('the header declares "PREFIX rdfs:"')
def then_header_rdfs(ctx):
    assert "PREFIX rdfs:" in ctx["header"]


@then('the header declares "PREFIX owl:"')
def then_header_owl(ctx):
    assert "PREFIX owl:" in ctx["header"]


@then('the header declares "PREFIX skos:"')
def then_header_skos(ctx):
    assert "PREFIX skos:" in ctx["header"]


@then('the header declares "PREFIX kai:"')
def then_header_kai(ctx):
    assert "PREFIX kai:" in ctx["header"]


@then('the header contains exactly one "PREFIX rdf:"')
def then_no_duplicate_rdf(ctx):
    assert ctx["header"].count("PREFIX rdf:") == 1


@then('"Digital" appears in the "kai" prefix candidates')
def then_digital_in_kai(ctx):
    assert "Digital" in ctx["index"].get("kai", [])


@then('"prefLabel" appears in the "skos" prefix candidates')
def then_preflabel_in_skos(ctx):
    assert "prefLabel" in ctx["index"].get("skos", [])


@then('"broader" appears in the "skos" prefix candidates')
def then_broader_in_skos(ctx):
    assert "broader" in ctx["index"].get("skos", [])


@then("the buffer contains a brace block")
def then_buffer_has_brace_block(ctx):
    assert "{\n" in ctx["buffer"] and "\n}" in ctx["buffer"]


@then("the cursor is positioned inside the block")
def then_cursor_inside(ctx):
    buf = ctx["buffer"]
    pos = ctx["pos"]
    open_pos = buf.find("{")
    close_pos = buf.rfind("}")
    assert open_pos < pos < close_pos
