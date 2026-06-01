"""BDD step definitions for tests/features/model/rename_uri_count.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Concept, Label, LabelType, RDFClass, Taxonomy
from ster.operations import (
    count_concept_uri_references,
    count_owl_uri_references,
    count_uri_references,
    rename_entity_uri,
    rename_kind,
)

scenarios("../features/model/rename_uri_count.feature")

BASE = "https://example.org/onto#"


def _u(name: str) -> str:
    return BASE + name


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('a model with concept "{a}" and concept "{b}" broader "{a2}"'))
def given_concepts_broader(ctx: dict, a: str, b: str, a2: str) -> None:
    t = Taxonomy()
    t.concepts[_u(a)] = Concept(uri=_u(a), labels=[Label("en", a, LabelType.PREF)])
    t.concepts[_u(b)] = Concept(
        uri=_u(b), labels=[Label("en", b, LabelType.PREF)], broader=[_u(a2)]
    )
    ctx["taxonomy"] = t


@given(parsers.parse('a model with concept "{a}" and concept "{b}" exactMatch "{a2}"'))
def given_concepts_exact_match(ctx: dict, a: str, b: str, a2: str) -> None:
    t = Taxonomy()
    t.concepts[_u(a)] = Concept(uri=_u(a), labels=[Label("en", a, LabelType.PREF)])
    t.concepts[_u(b)] = Concept(
        uri=_u(b), labels=[Label("en", b, LabelType.PREF)], exact_match=[_u(a2)]
    )
    ctx["taxonomy"] = t


@given(parsers.parse('a model with class "{a}" and class "{b}" subClassOf "{a2}"'))
def given_classes_subclass(ctx: dict, a: str, b: str, a2: str) -> None:
    t = Taxonomy()
    t.owl_classes[_u(a)] = RDFClass(uri=_u(a), labels=[Label("en", a)])
    t.owl_classes[_u(b)] = RDFClass(uri=_u(b), labels=[Label("en", b)], sub_class_of=[_u(a2)])
    ctx["taxonomy"] = t


@given(parsers.parse('"{a}" is also an OWL class with subclass "{child}"'))
def given_also_class(ctx: dict, a: str, child: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    t.owl_classes[_u(a)] = RDFClass(uri=_u(a), labels=[Label("en", a)])
    t.owl_classes[_u(child)] = RDFClass(
        uri=_u(child), labels=[Label("en", child)], sub_class_of=[_u(a)]
    )


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I ask for the rename kind of "{name}"'))
def when_ask_kind(ctx: dict, name: str) -> None:
    ctx["kind"] = rename_kind(ctx["taxonomy"], _u(name))


@when(parsers.parse('I rename entity "{old}" to "{new}"'))
def when_rename_entity(ctx: dict, old: str, new: str) -> None:
    rename_entity_uri(ctx["taxonomy"], _u(old), _u(new))


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('the rename kind is "{kind}"'))
def then_kind_is(ctx: dict, kind: str) -> None:
    assert ctx["kind"] == kind, f"Expected kind {kind!r}, got {ctx['kind']!r}"


@then(parsers.parse('counting all references to "{name}" returns at least {n:d}'))
def then_count_at_least(ctx: dict, name: str, n: int) -> None:
    count = count_uri_references(ctx["taxonomy"], _u(name))
    assert count >= n, f"Expected count >= {n}, got {count}"


@then(
    parsers.parse(
        'counting all references to "{name}" is at least the concept plus class counts'
    )
)
def then_count_sums_layers(ctx: dict, name: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    total = count_uri_references(t, _u(name))
    concept_part = count_concept_uri_references(t, _u(name))
    owl_part = count_owl_uri_references(t, _u(name))
    assert total >= concept_part + owl_part
    assert concept_part > 0 and owl_part > 0


@then(parsers.parse('concept "{name}" exists in the model'))
def then_concept_present(ctx: dict, name: str) -> None:
    assert _u(name) in ctx["taxonomy"].concepts


@then(parsers.parse('concept "{name}" does not exist in the model'))
def then_concept_absent(ctx: dict, name: str) -> None:
    assert _u(name) not in ctx["taxonomy"].concepts


@then(parsers.parse('class "{name}" exists in the model'))
def then_class_present(ctx: dict, name: str) -> None:
    assert _u(name) in ctx["taxonomy"].owl_classes


@then(parsers.parse('"{src}" exactMatch contains "{tgt}"'))
def then_exact_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) in ctx["taxonomy"].concepts[_u(src)].exact_match


@then(parsers.parse('"{src}" broader contains "{tgt}"'))
def then_broader_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) in ctx["taxonomy"].concepts[_u(src)].broader


@then(parsers.parse('"{src}" subClassOf contains "{tgt}"'))
def then_subclass_contains(ctx: dict, src: str, tgt: str) -> None:
    assert _u(tgt) in ctx["taxonomy"].owl_classes[_u(src)].sub_class_of
