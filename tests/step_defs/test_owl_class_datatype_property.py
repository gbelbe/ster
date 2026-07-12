"""BDD step definitions for defining datatype/object properties on a class."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Label, OWLIndividual, RDFClass, Taxonomy

scenarios("../features/owl/class_datatype_property.feature")

XSD = "http://www.w3.org/2001/XMLSchema#"
BASE = "https://ex.org/onto"


@pytest.fixture
def ctx():
    return {}


@when(parsers.parse('I choose the property kind "{kind}"'))
def when_choose_kind(ctx, kind):
    from ster.operations import advance_property_create

    choice = 0 if kind == "attribute" else 1
    ctx["result"] = advance_property_create("kind", choice)


@then("the picker advances to the datatype step")
def then_advances_to_datatype(ctx):
    assert ctx["result"][0] == "datatype"


@then(parsers.parse('a "{ptype}" is created with no range'))
def then_created_no_range(ctx, ptype):
    nxt, prop_type, rng = ctx["result"]
    assert nxt == "create"
    assert prop_type == ptype
    assert rng is None


@given("the attribute kind was chosen")
def given_attribute_chosen(ctx):
    from ster.operations import advance_property_create

    ctx["result"] = advance_property_create("kind", 0)


@when("I choose the first datatype")
def when_choose_first_datatype(ctx):
    from ster.operations import advance_property_create

    ctx["result"] = advance_property_create("datatype", 0)


@then(parsers.parse('a "{ptype}" is created with an xsd range'))
def then_created_with_range(ctx, ptype):
    nxt, prop_type, rng = ctx["result"]
    assert nxt == "create"
    assert prop_type == ptype
    assert rng is not None and rng.startswith(XSD)


@given(parsers.parse('a class "{cls}" with an individual "{ind}"'))
def given_class_with_individual(ctx, cls, ind):
    t = Taxonomy()
    t.ontology_uri = BASE
    t.owl_classes[f"{BASE}#{cls}"] = RDFClass(uri=f"{BASE}#{cls}", labels=[Label("en", cls)])
    t.owl_individuals[f"{BASE}#{ind}"] = OWLIndividual(uri=f"{BASE}#{ind}", types=[f"{BASE}#{cls}"])
    ctx["tax"] = t
    ctx["cls"] = f"{BASE}#{cls}"
    ctx["ind"] = f"{BASE}#{ind}"


@when(parsers.parse('I add a datatype attribute "{name}" to the class'))
def when_add_datatype_attr(ctx, name):
    from ster.operations import add_owl_property

    add_owl_property(
        ctx["tax"], f"{BASE}#{name}", "DatatypeProperty", name, "en", ctx["cls"], XSD + "integer"
    )
    ctx["prop"] = f"{BASE}#{name}"


@then(parsers.parse('"{name}" is not shown on the individual "{ind}" until it has a value'))
def then_not_shown_on_individual(ctx, name, ind):
    from ster.nav.logic import build_individual_detail

    fields = build_individual_detail(ctx["tax"], ctx["ind"], "en")
    # The individual page prints only asserted data — an applicable but unasserted
    # property is not shown (add a value via the right-click menu).
    assert not any(f"{BASE}#{name}" in (f.key or "") for f in fields)
