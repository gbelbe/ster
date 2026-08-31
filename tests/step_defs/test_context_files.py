"""Step definitions for read-only context files."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store

scenarios("../features/io/context_files.feature")

NS = "https://example.org/t#"

GEAR = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <{NS}> .
ex:Scheme a skos:ConceptScheme .
ex:Tent a skos:Concept ; skos:prefLabel "Tent"@en ; skos:inScheme ex:Scheme .
"""

PLACES = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <{NS}> .
ex:Alps a skos:Concept ; skos:prefLabel "Alps"@en .
"""


@pytest.fixture
def ctx(tmp_path):
    return {"tmp_path": tmp_path}


@given('a gear file defining "Tent"')
def given_gear(ctx):
    path = ctx["tmp_path"] / "gear.ttl"
    path.write_text(GEAR, encoding="utf-8")
    ctx["gear"] = path


@given('a places file defining "Alps"')
def given_places(ctx):
    path = ctx["tmp_path"] / "places.ttl"
    path.write_text(PLACES, encoding="utf-8")
    ctx["places"] = path
    ctx["places_before"] = path.read_bytes()


@when("both files are loaded with the gear file editable")
def when_load_both(ctx):
    ctx["tax"] = store.load(ctx["gear"], context=[ctx["places"]])


@when("only the gear file is loaded")
def when_load_one(ctx):
    ctx["tax"] = store.load(ctx["gear"])


@when("the taxonomy is saved")
def when_save(ctx):
    store.save(ctx["tax"], ctx["gear"])


@then(parsers.parse('both "{first}" and "{second}" are in the taxonomy'))
def then_both_present(ctx, first, second):
    concepts = ctx["tax"].concepts
    assert NS + first in concepts
    assert NS + second in concepts


@then(parsers.parse('"{name}" is editable'))
def then_editable(ctx, name):
    assert store.is_editable(ctx["tax"], NS + name)


@then(parsers.parse('"{name}" is read-only'))
def then_read_only(ctx, name):
    assert not store.is_editable(ctx["tax"], NS + name)


@then(parsers.parse('"{name}" reports the places file as its source'))
def then_source(ctx, name):
    assert ctx["tax"].context_source[NS + name] == ctx["places"]


# Turtle writes the prefixed form (ex:Tent), not the expanded URI, so these
# assert on the local name.
@then(parsers.parse('the gear file still defines "{name}"'))
def then_gear_has(ctx, name):
    assert name in ctx["gear"].read_text(encoding="utf-8")


@then(parsers.parse('the gear file does not define "{name}"'))
def then_gear_lacks(ctx, name):
    """The whole point: saving must not merge the context file into this one."""
    assert name not in ctx["gear"].read_text(encoding="utf-8")


@then("the places file is unchanged")
def then_places_untouched(ctx):
    assert ctx["places"].read_bytes() == ctx["places_before"]


@then("nothing is read-only")
def then_nothing_read_only(ctx):
    assert ctx["tax"].context_source == {}
