"""BDD step definitions for tests/features/owl/rename_ontology_uri.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.operations import count_ontology_rename_changes, rename_ontology_uri

scenarios("../features/owl/rename_ontology_uri.feature")


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('a taxonomy with ontology URI "{ont}" and a class "{cls}"'))
def given_taxonomy_hash_class(ctx: dict, ont: str, cls: str) -> None:
    t = Taxonomy()
    t.ontology_uri = ont
    u = f"{ont}#{cls}"
    t.owl_classes[u] = RDFClass(uri=u, labels=[Label("en", cls)])
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with ontology URI "{ont}" using "#" and a class "{cls}"'))
def given_taxonomy_explicit_hash(ctx: dict, ont: str, cls: str) -> None:
    t = Taxonomy()
    t.ontology_uri = ont
    u = f"{ont}#{cls}"
    t.owl_classes[u] = RDFClass(uri=u, labels=[Label("en", cls)])
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with ontology URI "{ont}" using "/" and a class "{cls}"'))
def given_taxonomy_slash_class(ctx: dict, ont: str, cls: str) -> None:
    t = Taxonomy()
    t.ontology_uri = ont
    u = f"{ont}/{cls}"
    t.owl_classes[u] = RDFClass(uri=u, labels=[Label("en", cls)])
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with ontology URI "{ont}" and two classes "{a}" and "{b}"'))
def given_taxonomy_two_classes(ctx: dict, ont: str, a: str, b: str) -> None:
    t = Taxonomy()
    t.ontology_uri = ont
    for name in (a, b):
        u = f"{ont}#{name}"
        t.owl_classes[u] = RDFClass(uri=u, labels=[Label("en", name)])
    ctx["taxonomy"] = t


@given(parsers.parse('an individual "{ind}" typed as "{cls}"'))
def given_individual_full_uri(ctx: dict, ind: str, cls: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    t.owl_individuals[ind] = OWLIndividual(
        uri=ind, labels=[Label("en", ind.split("#")[-1])], types=[cls]
    )


@given(parsers.parse('a property "{prop}" with domain "{dom}"'))
def given_property_full_uri(ctx: dict, prop: str, dom: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    t.owl_properties[prop] = OWLProperty(
        uri=prop, labels=[Label("en", prop.split("#")[-1])], domains=[dom], ranges=[]
    )


@given(parsers.parse('the class "{cls}" has a subclass link to "{parent}"'))
def given_subclass_full_uri(ctx: dict, cls: str, parent: str) -> None:
    ctx["taxonomy"].owl_classes[cls].sub_class_of.append(parent)


@given(parsers.parse('"{child}" is a subclass of "{parent}"'))
def given_subclass_link(ctx: dict, child: str, parent: str) -> None:
    ctx["taxonomy"].owl_classes[child].sub_class_of.append(parent)


@given(parsers.parse('a class "{uri}" exists independently'))
def given_independent_class(ctx: dict, uri: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    local = uri.split("/")[-1]
    t.owl_classes[uri] = RDFClass(uri=uri, labels=[Label("en", local)])


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I rename the ontology URI to "{new_uri}" with separator "{sep}"'))
def when_rename_ontology(ctx: dict, new_uri: str, sep: str) -> None:
    rename_ontology_uri(ctx["taxonomy"], new_uri, sep)


@when(parsers.parse('I count URI changes renaming to "{new_uri}" with separator "{sep}"'))
def when_count_changes(ctx: dict, new_uri: str, sep: str) -> None:
    old_base, new_base, count = count_ontology_rename_changes(ctx["taxonomy"], new_uri, sep)
    ctx["old_base"] = old_base
    ctx["new_base"] = new_base
    ctx["change_count"] = count


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('the taxonomy ontology URI is "{uri}"'))
def then_ontology_uri(ctx: dict, uri: str) -> None:
    assert ctx["taxonomy"].ontology_uri == uri


@then(parsers.parse('class "{uri}" exists in the taxonomy'))
def then_class_present(ctx: dict, uri: str) -> None:
    assert uri in ctx["taxonomy"].owl_classes, (
        f"{uri!r} not found; classes={list(ctx['taxonomy'].owl_classes)}"
    )


@then(parsers.parse('class "{uri}" does not exist in the taxonomy'))
def then_class_absent(ctx: dict, uri: str) -> None:
    assert uri not in ctx["taxonomy"].owl_classes


@then(parsers.parse('class "{uri}" still exists in the taxonomy'))
def then_class_still_present(ctx: dict, uri: str) -> None:
    assert uri in ctx["taxonomy"].owl_classes


@then(parsers.parse('individual "{uri}" exists in the taxonomy'))
def then_individual_present(ctx: dict, uri: str) -> None:
    assert uri in ctx["taxonomy"].owl_individuals


@then(parsers.parse('property "{uri}" exists in the taxonomy'))
def then_property_present(ctx: dict, uri: str) -> None:
    assert uri in ctx["taxonomy"].owl_properties


@then(parsers.parse('"{child}" still references "{parent}"'))
def then_still_references(ctx: dict, child: str, parent: str) -> None:
    cls = ctx["taxonomy"].owl_classes[child]
    assert parent in cls.sub_class_of


@then(parsers.parse('"{child}" is a subclass of "{parent}"'))
def then_is_subclass(ctx: dict, child: str, parent: str) -> None:
    assert parent in ctx["taxonomy"].owl_classes[child].sub_class_of


@then(parsers.parse("the change count is {n:d}"))
def then_change_count(ctx: dict, n: int) -> None:
    assert ctx["change_count"] == n


@then(parsers.parse('the old base is "{base}"'))
def then_old_base(ctx: dict, base: str) -> None:
    assert ctx["old_base"] == base


@then(parsers.parse('the new base is "{base}"'))
def then_new_base(ctx: dict, base: str) -> None:
    assert ctx["new_base"] == base
