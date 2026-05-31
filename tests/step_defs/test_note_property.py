"""BDD step definitions for ns1:note annotation property."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/owl/note_property.feature")

NS = "https://example.org/onto#"


def _uri(name: str) -> str:
    return NS + name


@pytest.fixture
def ctx():
    return {}


@given("a fresh RDFClass")
def given_fresh_rdfclass(ctx):
    from ster.model import RDFClass

    ctx["entity"] = RDFClass(uri=_uri("MyClass"))


@given("a fresh OWLIndividual")
def given_fresh_individual(ctx):
    from ster.model import OWLIndividual

    ctx["entity"] = OWLIndividual(uri=_uri("MyInd"))


@given("a fresh OWLProperty")
def given_fresh_owlproperty(ctx):
    from ster.model import OWLProperty

    ctx["entity"] = OWLProperty(uri=_uri("myProp"))


@then("the note field is empty")
def then_note_empty(ctx):
    assert ctx["entity"].note == ""


@given('a taxonomy with a class that has a note "Hello **world**"')
def given_taxonomy_class_note(ctx):
    from ster.model import RDFClass, Taxonomy

    t = Taxonomy()
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"), note="Hello **world**")
    ctx["taxonomy"] = t
    ctx["class_uri"] = _uri("A")


@given('a taxonomy with a class that has a note "# Title"')
def given_taxonomy_class_note_title(ctx):
    from ster.model import RDFClass, Taxonomy

    t = Taxonomy()
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"), note="# Title")
    ctx["taxonomy"] = t
    ctx["class_uri"] = _uri("A")


@given("a taxonomy with a class that has a multiline note")
def given_taxonomy_class_multiline_note(ctx):
    from ster.model import RDFClass, Taxonomy

    t = Taxonomy()
    note = "# Heading\n- item 1\n- item 2\nplain text"
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"), note=note)
    ctx["taxonomy"] = t
    ctx["class_uri"] = _uri("A")
    ctx["original_note"] = note


@given("a taxonomy with a class that has an empty note")
def given_taxonomy_class_empty_note(ctx):
    from ster.model import RDFClass, Taxonomy

    t = Taxonomy()
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"), note="")
    ctx["taxonomy"] = t
    ctx["class_uri"] = _uri("A")


@given('a taxonomy with an individual that has a note "# Title"')
def given_taxonomy_individual_note(ctx):
    from ster.model import OWLIndividual, Taxonomy

    t = Taxonomy()
    t.owl_individuals[_uri("Ind")] = OWLIndividual(uri=_uri("Ind"), note="# Title")
    ctx["taxonomy"] = t
    ctx["ind_uri"] = _uri("Ind")


@given('a taxonomy with a property that has a note "# Title"')
def given_taxonomy_property_note(ctx):
    from ster.model import OWLProperty, Taxonomy

    t = Taxonomy()
    t.owl_properties[_uri("prop")] = OWLProperty(uri=_uri("prop"), note="# Title")
    ctx["taxonomy"] = t
    ctx["prop_uri"] = _uri("prop")


@when("the taxonomy is saved and reloaded")
def when_save_reload(ctx):
    from ster import store

    t = ctx["taxonomy"]
    with tempfile.NamedTemporaryFile(suffix=".ttl", delete=False) as f:
        tmp = Path(f.name)
    store.save(t, tmp)
    ctx["reloaded"] = store.load(tmp)
    tmp.unlink(missing_ok=True)


@when("the taxonomy is serialised to a graph")
def when_serialise(ctx):
    from ster import store

    ctx["graph"] = store.taxonomy_to_graph(ctx["taxonomy"])


@then('the class note value is "Hello **world**"')
def then_class_note_value(ctx):
    reloaded = ctx["reloaded"]
    cls = reloaded.owl_classes.get(ctx["class_uri"])
    assert cls is not None
    assert cls.note == "Hello **world**"


@then("all note lines are preserved")
def then_multiline_preserved(ctx):
    reloaded = ctx["reloaded"]
    cls = reloaded.owl_classes.get(ctx["class_uri"])
    assert cls is not None
    assert cls.note == ctx["original_note"]


@then("there is no ns1:note triple for that class")
def then_no_note_triple(ctx):
    from rdflib import URIRef

    from ster.store import NOTE_PROPERTY_URI

    g = ctx["graph"]
    class_ref = URIRef(ctx["class_uri"])
    note_pred = URIRef(NOTE_PROPERTY_URI)
    triples = list(g.triples((class_ref, note_pred, None)))
    assert triples == []


@when("I build the class detail fields")
def when_build_class_detail(ctx):
    from ster.nav.logic import build_rdf_class_detail

    ctx["fields"] = build_rdf_class_detail(ctx["taxonomy"], ctx["class_uri"], "en")


@when("I build the individual detail fields")
def when_build_individual_detail(ctx):
    from ster.nav.logic import build_individual_detail

    ctx["fields"] = build_individual_detail(ctx["taxonomy"], ctx["ind_uri"], "en")


@when("I build the property detail fields")
def when_build_property_detail(ctx):
    from ster.nav.logic import build_property_detail

    ctx["fields"] = build_property_detail(ctx["taxonomy"], ctx["prop_uri"], "en")


@then("a note_line field is present")
def then_note_line_present(ctx):
    fields = ctx["fields"]
    types = [f.meta.get("type") for f in fields]
    assert "note_line" in types
