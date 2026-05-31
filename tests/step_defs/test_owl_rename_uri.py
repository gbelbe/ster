"""BDD step definitions for tests/features/owl/rename_uri.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.exceptions import URIAlreadyExistsError
from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.operations import rename_owl_uri

scenarios("../features/owl/rename_uri.feature")

BASE = "https://example.org/onto#"


def _u(name: str) -> str:
    return BASE + name


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('a taxonomy with OWL class "{a}"'))
def given_one_class(ctx: dict, a: str) -> None:
    t = Taxonomy()
    t.owl_classes[_u(a)] = RDFClass(uri=_u(a), labels=[Label("en", a)])
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with OWL classes "{a}" and "{b}"'))
def given_two_classes(ctx: dict, a: str, b: str) -> None:
    t = Taxonomy()
    for name in (a, b):
        t.owl_classes[_u(name)] = RDFClass(uri=_u(name), labels=[Label("en", name)])
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with OWL individual "{a}"'))
def given_one_individual(ctx: dict, a: str) -> None:
    t = Taxonomy()
    t.owl_individuals[_u(a)] = OWLIndividual(uri=_u(a), labels=[Label("en", a)])
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with OWL individuals "{a}" and "{b}"'))
def given_two_individuals(ctx: dict, a: str, b: str) -> None:
    t = Taxonomy()
    for name in (a, b):
        t.owl_individuals[_u(name)] = OWLIndividual(uri=_u(name), labels=[Label("en", name)])
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with OWL property "{a}"'))
def given_one_property(ctx: dict, a: str) -> None:
    t = Taxonomy()
    t.owl_properties[_u(a)] = OWLProperty(uri=_u(a), labels=[Label("en", a)])
    ctx["taxonomy"] = t


@given(parsers.parse('"{child}" is a subclass of "{parent}"'))
def given_subclass(ctx: dict, child: str, parent: str) -> None:
    ctx["taxonomy"].owl_classes[_u(child)].sub_class_of.append(_u(parent))


@given(parsers.parse('"{a}" is equivalent to "{b}"'))
def given_equivalent(ctx: dict, a: str, b: str) -> None:
    ctx["taxonomy"].owl_classes[_u(a)].equivalent_class.append(_u(b))


@given(parsers.parse('"{a}" is disjoint with "{b}"'))
def given_disjoint(ctx: dict, a: str, b: str) -> None:
    ctx["taxonomy"].owl_classes[_u(a)].disjoint_with.append(_u(b))


@given(parsers.parse('an individual "{name}" typed as "{cls}"'))
def given_individual_typed(ctx: dict, name: str, cls: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    if _u(name) not in t.owl_individuals:
        t.owl_individuals[_u(name)] = OWLIndividual(uri=_u(name), labels=[Label("en", name)])
    t.owl_individuals[_u(name)].types.append(_u(cls))


@given(parsers.parse('a property "{prop}" with domain "{cls}" and range "{rng}"'))
def given_property_domain_range(ctx: dict, prop: str, cls: str, rng: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    t.owl_properties[_u(prop)] = OWLProperty(
        uri=_u(prop),
        labels=[Label("en", prop)],
        domains=[_u(cls)],
        ranges=[_u(rng)],
    )


@given(parsers.parse('a property "{prop}" linking "{src}" to "{tgt}"'))
def given_property_value(ctx: dict, prop: str, src: str, tgt: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    if _u(prop) not in t.owl_properties:
        t.owl_properties[_u(prop)] = OWLProperty(uri=_u(prop), labels=[Label("en", prop)])
    t.owl_individuals[_u(src)].property_values.append((_u(prop), _u(tgt)))


@given(
    parsers.parse('individual "{name}" has a literal value with predicate "{pred}" value "{val}"')
)
def given_literal_value(ctx: dict, name: str, pred: str, val: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    if _u(name) not in t.owl_individuals:
        t.owl_individuals[_u(name)] = OWLIndividual(uri=_u(name), labels=[Label("en", name)])
    t.owl_individuals[_u(name)].literal_values.append((_u(pred), val, ""))


@given(parsers.parse('property "{prop}" is added to the taxonomy'))
def given_property_added(ctx: dict, prop: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    if _u(prop) not in t.owl_properties:
        t.owl_properties[_u(prop)] = OWLProperty(uri=_u(prop), labels=[Label("en", prop)])


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I rename class "{old}" to "{new}"'))
def when_rename_class(ctx: dict, old: str, new: str) -> None:
    try:
        rename_owl_uri(ctx["taxonomy"], _u(old), _u(new))
        ctx["error"] = None
    except URIAlreadyExistsError as exc:
        ctx["error"] = exc


@when(parsers.parse('I rename individual "{old}" to "{new}"'))
def when_rename_individual(ctx: dict, old: str, new: str) -> None:
    try:
        rename_owl_uri(ctx["taxonomy"], _u(old), _u(new))
        ctx["error"] = None
    except URIAlreadyExistsError as exc:
        ctx["error"] = exc


@when(parsers.parse('I rename property "{old}" to "{new}"'))
def when_rename_property(ctx: dict, old: str, new: str) -> None:
    try:
        rename_owl_uri(ctx["taxonomy"], _u(old), _u(new))
        ctx["error"] = None
    except URIAlreadyExistsError as exc:
        ctx["error"] = exc


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('class "{name}" exists in the taxonomy'))
def then_class_present(ctx: dict, name: str) -> None:
    assert _u(name) in ctx["taxonomy"].owl_classes


@then(parsers.parse('class "{name}" does not exist in the taxonomy'))
def then_class_absent(ctx: dict, name: str) -> None:
    assert _u(name) not in ctx["taxonomy"].owl_classes


@then(parsers.parse('individual "{name}" exists in the taxonomy'))
def then_individual_present(ctx: dict, name: str) -> None:
    assert _u(name) in ctx["taxonomy"].owl_individuals


@then(parsers.parse('individual "{name}" does not exist in the taxonomy'))
def then_individual_absent(ctx: dict, name: str) -> None:
    assert _u(name) not in ctx["taxonomy"].owl_individuals


@then(parsers.parse('property "{name}" exists in the taxonomy'))
def then_property_present(ctx: dict, name: str) -> None:
    assert _u(name) in ctx["taxonomy"].owl_properties


@then(parsers.parse('property "{name}" does not exist in the taxonomy'))
def then_property_absent(ctx: dict, name: str) -> None:
    assert _u(name) not in ctx["taxonomy"].owl_properties


@then(parsers.parse('"{child}" subClassOf contains "{parent}"'))
def then_subclass_contains(ctx: dict, child: str, parent: str) -> None:
    assert _u(parent) in ctx["taxonomy"].owl_classes[_u(child)].sub_class_of


@then(parsers.parse('"{child}" subClassOf does not contain "{parent}"'))
def then_subclass_not_contains(ctx: dict, child: str, parent: str) -> None:
    assert _u(parent) not in ctx["taxonomy"].owl_classes[_u(child)].sub_class_of


@then(parsers.parse('"{a}" equivalentClass contains "{b}"'))
def then_equivalent_contains(ctx: dict, a: str, b: str) -> None:
    assert _u(b) in ctx["taxonomy"].owl_classes[_u(a)].equivalent_class


@then(parsers.parse('"{a}" disjointWith contains "{b}"'))
def then_disjoint_contains(ctx: dict, a: str, b: str) -> None:
    assert _u(b) in ctx["taxonomy"].owl_classes[_u(a)].disjoint_with


@then(parsers.parse('individual "{name}" is typed as "{cls}"'))
def then_individual_typed(ctx: dict, name: str, cls: str) -> None:
    assert _u(cls) in ctx["taxonomy"].owl_individuals[_u(name)].types


@then(parsers.parse('individual "{name}" is not typed as "{cls}"'))
def then_individual_not_typed(ctx: dict, name: str, cls: str) -> None:
    assert _u(cls) not in ctx["taxonomy"].owl_individuals[_u(name)].types


@then(parsers.parse('property "{prop}" domain contains "{cls}"'))
def then_domain_contains(ctx: dict, prop: str, cls: str) -> None:
    assert _u(cls) in ctx["taxonomy"].owl_properties[_u(prop)].domains


@then(parsers.parse('property "{prop}" range contains "{cls}"'))
def then_range_contains(ctx: dict, prop: str, cls: str) -> None:
    assert _u(cls) in ctx["taxonomy"].owl_properties[_u(prop)].ranges


@then(parsers.parse('individual "{name}" has a "{prop}" value of "{val}"'))
def then_has_pv(ctx: dict, name: str, prop: str, val: str) -> None:
    pv = ctx["taxonomy"].owl_individuals[_u(name)].property_values
    assert (_u(prop), _u(val)) in pv


@then(parsers.parse('individual "{name}" has no "{prop}" value of "{val}"'))
def then_no_pv(ctx: dict, name: str, prop: str, val: str) -> None:
    pv = ctx["taxonomy"].owl_individuals[_u(name)].property_values
    assert (_u(prop), _u(val)) not in pv


@then(parsers.parse('individual "{name}" has a property value with predicate "{prop}"'))
def then_has_predicate(ctx: dict, name: str, prop: str) -> None:
    pv = ctx["taxonomy"].owl_individuals[_u(name)].property_values
    assert any(p == _u(prop) for p, _ in pv)


@then(parsers.parse('individual "{name}" has no property value with predicate "{prop}"'))
def then_no_predicate(ctx: dict, name: str, prop: str) -> None:
    pv = ctx["taxonomy"].owl_individuals[_u(name)].property_values
    assert not any(p == _u(prop) for p, _ in pv)


@then("a URIAlreadyExistsError is raised")
def then_uri_collision(ctx: dict) -> None:
    assert isinstance(ctx["error"], URIAlreadyExistsError), (
        f"Expected URIAlreadyExistsError, got {ctx['error']!r}"
    )


@then(parsers.parse('individual "{name}" has a literal value with predicate "{pred}"'))
def then_has_literal_predicate(ctx: dict, name: str, pred: str) -> None:
    lv = ctx["taxonomy"].owl_individuals[_u(name)].literal_values
    assert any(p == _u(pred) for p, _v, _ld in lv), (
        f"No literal value with predicate {_u(pred)} on {_u(name)}: {lv}"
    )


@then(parsers.parse('individual "{name}" has no literal value with predicate "{pred}"'))
def then_no_literal_predicate(ctx: dict, name: str, pred: str) -> None:
    lv = ctx["taxonomy"].owl_individuals[_u(name)].literal_values
    assert not any(p == _u(pred) for p, _v, _ld in lv), (
        f"Unexpected literal value with predicate {_u(pred)} on {_u(name)}: {lv}"
    )


@then(parsers.parse('counting references to "{uri}" returns at least {n:d}'))
def then_count_at_least(ctx: dict, uri: str, n: int) -> None:
    from ster.operations import count_owl_uri_references

    count = count_owl_uri_references(ctx["taxonomy"], _u(uri))
    assert count >= n, f"Expected count >= {n}, got {count}"
