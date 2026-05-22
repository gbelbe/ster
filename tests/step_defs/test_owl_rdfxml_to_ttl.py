"""BDD step definitions for tests/features/owl/rdfxml_to_ttl.feature."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from rdflib import Graph, URIRef
from typer.testing import CliRunner

from ster import store
from ster.cli import _maybe_backconvert, app

scenarios("../features/owl/rdfxml_to_ttl.feature")

runner = CliRunner()

_S = URIRef("https://example.org/subject")
_P = URIRef("https://example.org/predicate")
_O = URIRef("https://example.org/object")
_TRIPLE = (_S, _P, _O)

_RDF_XML = """\
<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="https://example.org/subject">
    <ns0:predicate xmlns:ns0="https://example.org/" rdf:resource="https://example.org/object"/>
  </rdf:Description>
</rdf:RDF>
"""

_TTL = "@prefix ex: <https://example.org/> .\nex:subject ex:predicate ex:object .\n"


@pytest.fixture
def ctx(tmp_path):
    return {"tmp_path": tmp_path}


# ── Given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('a file path with extension "{ext}"'))
def given_path_with_ext(ctx, ext):
    ctx["path"] = ctx["tmp_path"] / f"file{ext}"


@given("an RDF/XML file containing one triple")
def given_rdfxml_file(ctx):
    p = ctx["tmp_path"] / "onto.rdf"
    p.write_text(_RDF_XML)
    ctx["input"] = p
    ctx["expected_triple"] = _TRIPLE


@given("a .owl file containing one triple in RDF/XML format")
def given_owl_rdfxml_file(ctx):
    p = ctx["tmp_path"] / "onto.owl"
    p.write_text(_RDF_XML)
    ctx["input"] = p
    ctx["expected_triple"] = _TRIPLE


@given("a Turtle file containing one triple")
def given_ttl_file(ctx):
    p = ctx["tmp_path"] / "onto.ttl"
    p.write_text(_TTL)
    ctx["input"] = p
    ctx["expected_triple"] = _TRIPLE


@given(parsers.parse('an RDF/XML file named "{name}"'))
def given_named_rdfxml_file(ctx, name):
    p = ctx["tmp_path"] / name
    p.write_text(_RDF_XML)
    ctx["input"] = p


@given(parsers.parse('an RDF/XML file "{name}" on disk'))
def given_rdfxml_on_disk(ctx, name):
    p = ctx["tmp_path"] / name
    p.write_text(_RDF_XML)
    ctx["input"] = p


@given(parsers.parse('a Turtle file and its original "{original_name}"'))
def given_ttl_and_original(ctx, original_name):
    ttl = ctx["tmp_path"] / "onto.ttl"
    ttl.write_text(_TTL)
    original = ctx["tmp_path"] / original_name
    original.write_text(_RDF_XML)
    ctx["ttl"] = ttl
    ctx["original"] = original
    ctx["original_content"] = original.read_text()


@given("the Turtle file hash is unchanged")
def given_hash_unchanged(ctx):
    ctx["pre_hash"] = store.file_hash(ctx["ttl"])


@given("the Turtle file hash has changed")
def given_hash_changed(ctx):
    ctx["pre_hash"] = "stale-hash-value"


# ── When ──────────────────────────────────────────────────────────────────────


@when("I convert it to Turtle")
def when_convert_to_ttl(ctx):
    dst = ctx["input"].with_suffix(".ttl")
    ctx["output"] = store.convert(ctx["input"], dst)


@when("I convert it to RDF/XML")
def when_convert_to_rdfxml(ctx):
    dst = ctx["input"].with_suffix(".rdf")
    ctx["output"] = store.convert(ctx["input"], dst)


@when("I call convert_to_ttl without specifying an output")
def when_convert_to_ttl_default(ctx):
    ctx["output"] = store.convert_to_ttl(ctx["input"])


@when(parsers.parse('I run ster convert on "{name}"'))
def when_run_ster_convert(ctx, name):
    src = ctx["tmp_path"] / name
    ctx["result"] = runner.invoke(app, ["convert", str(src)])


@when(parsers.parse('I run ster convert on "{name}" with output "{out}"'))
def when_run_ster_convert_output(ctx, name, out):
    src = ctx["tmp_path"] / name
    dst = ctx["tmp_path"] / out
    ctx["result"] = runner.invoke(app, ["convert", str(src), "--output", str(dst)])
    ctx["explicit_output"] = dst


@when("_maybe_backconvert is called")
def when_maybe_backconvert(ctx):
    with patch("ster.cli.Confirm.ask") as mock_ask:
        ctx["mock_ask"] = mock_ask
        _maybe_backconvert(ctx["ttl"], ctx["pre_hash"], ctx["original"])


@when("the user accepts back-conversion")
def when_accept_backconvert(ctx):
    with patch("ster.cli.Confirm.ask", return_value=True):
        _maybe_backconvert(ctx["ttl"], ctx["pre_hash"], ctx["original"])


@when("the user declines back-conversion")
def when_decline_backconvert(ctx):
    with patch("ster.cli.Confirm.ask", return_value=False):
        _maybe_backconvert(ctx["ttl"], ctx["pre_hash"], ctx["original"])


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('the detected RDF format is "{fmt}"'))
def then_format(ctx, fmt):
    assert store._detect_format(ctx["path"]) == fmt


@then("is_rdfxml_path returns True")
def then_is_rdfxml_true(ctx):
    assert store.is_rdfxml_path(ctx["path"]) is True


@then("is_rdfxml_path returns False")
def then_is_rdfxml_false(ctx):
    assert store.is_rdfxml_path(ctx["path"]) is False


@then("the output file is valid Turtle")
def then_output_valid_turtle(ctx):
    g = Graph()
    g.parse(str(ctx["output"]), format="turtle")
    assert len(g) > 0


@then("the output file is valid RDF/XML")
def then_output_valid_rdfxml(ctx):
    g = Graph()
    g.parse(str(ctx["output"]), format="xml")
    assert len(g) > 0


@then("the output contains the same triple")
def then_output_has_triple(ctx):
    g = Graph()
    g.parse(str(ctx["output"]))
    assert ctx["expected_triple"] in g


@then(parsers.parse('the output path is "{name}" in the same directory'))
def then_output_path(ctx, name):
    expected = ctx["input"].parent / name
    assert ctx["output"] == expected
    assert expected.exists()


@then(parsers.parse('"{name}" exists and is valid Turtle'))
def then_file_is_valid_turtle(ctx, name):
    assert ctx["result"].exit_code == 0, ctx["result"].output
    out_path = ctx.get("explicit_output") or (ctx["tmp_path"] / name)
    assert out_path.exists()
    g = Graph()
    g.parse(str(out_path), format="turtle")
    assert len(g) > 0


@then("no prompt is shown")
def then_no_prompt(ctx):
    ctx["mock_ask"].assert_not_called()


@then(parsers.parse('a prompt asks to convert back to "{original_name}"'))
def then_prompt_shown(ctx, original_name):
    ctx["mock_ask"].assert_called_once()
    call_args = ctx["mock_ask"].call_args
    prompt_text = call_args[0][0] if call_args[0] else str(call_args)
    assert original_name in prompt_text


@then(parsers.parse('"{name}" contains valid RDF/XML'))
def then_original_is_rdfxml(ctx, name):
    p = ctx["tmp_path"] / name
    g = Graph()
    g.parse(str(p), format="xml")
    assert len(g) > 0


@then(parsers.parse('"{name}" is unchanged'))
def then_original_unchanged(ctx, name):
    p = ctx["tmp_path"] / name
    assert p.read_text() == ctx["original_content"]
