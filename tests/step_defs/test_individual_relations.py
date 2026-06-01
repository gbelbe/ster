"""BDD step definitions for tests/features/owl/individual_relations.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.viz_vowl import build_individual_relations_graph

scenarios("../features/owl/individual_relations.feature")

NS = "https://example.org/onto#"


def _u(name: str) -> str:
    return NS + name


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('an A-Box where "{a}" owns "{b}" and "{b2}" livesIn "{c}"'))
def given_abox(ctx: dict, a: str, b: str, b2: str, c: str) -> None:
    t = Taxonomy()
    t.owl_properties[_u("owns")] = OWLProperty(uri=_u("owns"), labels=[Label("en", "owns")])
    t.owl_properties[_u("livesIn")] = OWLProperty(
        uri=_u("livesIn"), labels=[Label("en", "livesIn")]
    )
    for name in (a, b, c):
        t.owl_individuals[_u(name)] = OWLIndividual(uri=_u(name), labels=[Label("en", name)])
    t.owl_individuals[_u(a)].property_values.append((_u("owns"), _u(b)))
    t.owl_individuals[_u(b2)].property_values.append((_u("livesIn"), _u(c)))
    ctx["taxonomy"] = t


@given(parsers.parse('"{a}" is a "{ca}", "{b}" is a "{cb}", "{c}" is a "{cc}"'))
def given_types(ctx: dict, a: str, ca: str, b: str, cb: str, c: str, cc: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    for cls in (ca, cb, cc):
        if _u(cls) not in t.owl_classes:
            t.owl_classes[_u(cls)] = RDFClass(uri=_u(cls), labels=[Label("en", cls)])
    t.owl_individuals[_u(a)].types.append(_u(ca))
    t.owl_individuals[_u(b)].types.append(_u(cb))
    t.owl_individuals[_u(c)].types.append(_u(cc))


@given(parsers.parse('"{name}" is an unrelated "{cls}"'))
def given_unrelated(ctx: dict, name: str, cls: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    if _u(cls) not in t.owl_classes:
        t.owl_classes[_u(cls)] = RDFClass(uri=_u(cls), labels=[Label("en", cls)])
    t.owl_individuals[_u(name)] = OWLIndividual(
        uri=_u(name), labels=[Label("en", name)], types=[_u(cls)]
    )


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I expand relations for "{name}"'))
def when_expand(ctx: dict, name: str) -> None:
    ctx["graph"] = build_individual_relations_graph(ctx["taxonomy"], _u(name))


# ── Then ──────────────────────────────────────────────────────────────────────


def _ids(ctx: dict) -> set[str]:
    return {n["id"] for n in ctx["graph"]["nodes"]}


@then(parsers.parse('node "{name}" is present'))
def then_present(ctx: dict, name: str) -> None:
    assert _u(name) in _ids(ctx)


@then(parsers.parse('node "{name}" is absent'))
def then_absent(ctx: dict, name: str) -> None:
    assert _u(name) not in _ids(ctx)


@then(parsers.parse('there is an object-property edge from "{src}" to "{tgt}" labelled "{lbl}"'))
def then_edge(ctx: dict, src: str, tgt: str, lbl: str) -> None:
    assert any(
        e["source"] == _u(src)
        and e["target"] == _u(tgt)
        and e["type"] == "objectProperty"
        and e["label"] == lbl
        for e in ctx["graph"]["edges"]
    ), f"no {src}->{tgt} '{lbl}' edge in {ctx['graph']['edges']}"
