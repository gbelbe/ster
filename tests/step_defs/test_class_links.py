"""BDD step definitions for tests/features/owl/class_links.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Label, OWLProperty, RDFClass, Taxonomy
from ster.viz_vowl import build_class_links_graph

scenarios("../features/owl/class_links.feature")

NS = "https://example.org/onto#"


def _u(name: str) -> str:
    return NS + name


@pytest.fixture
def ctx() -> dict:
    return {"taxonomy": Taxonomy()}


def _ensure_class(t: Taxonomy, name: str) -> None:
    if _u(name) not in t.owl_classes:
        t.owl_classes[_u(name)] = RDFClass(uri=_u(name), labels=[Label("en", name)])


# ── Given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('classes where "{child}" is a subclass of "{parent}"'))
def given_subclass(ctx: dict, child: str, parent: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    _ensure_class(t, child)
    _ensure_class(t, parent)
    t.owl_classes[_u(child)].sub_class_of.append(_u(parent))


@given(parsers.parse('object property "{prop}" has domain "{dom}" and range "{rng}"'))
def given_object_property(ctx: dict, prop: str, dom: str, rng: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    _ensure_class(t, dom)
    _ensure_class(t, rng)
    t.owl_properties[_u(prop)] = OWLProperty(
        uri=_u(prop),
        prop_type="ObjectProperty",
        labels=[Label("en", prop)],
        domains=[_u(dom)],
        ranges=[_u(rng)],
    )


@given(parsers.parse('"{name}" is a class linked to nothing'))
def given_isolated(ctx: dict, name: str) -> None:
    _ensure_class(ctx["taxonomy"], name)


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I explore links for class "{name}"'))
def when_explore(ctx: dict, name: str) -> None:
    ctx["graph"] = build_class_links_graph(ctx["taxonomy"], _u(name))


# ── Then ──────────────────────────────────────────────────────────────────────


def _ids(ctx: dict) -> set[str]:
    return {n["id"] for n in ctx["graph"]["nodes"]}


@then(parsers.parse('class node "{name}" is present'))
def then_present(ctx: dict, name: str) -> None:
    assert _u(name) in _ids(ctx)


@then(parsers.parse('class node "{name}" is absent'))
def then_absent(ctx: dict, name: str) -> None:
    assert _u(name) not in _ids(ctx)


@then(parsers.parse('there is a subClassOf class-edge from "{src}" to "{tgt}"'))
def then_subclass_edge(ctx: dict, src: str, tgt: str) -> None:
    assert any(
        e["source"] == _u(src) and e["target"] == _u(tgt) and e["type"] == "subClassOf"
        for e in ctx["graph"]["edges"]
    )


@then(
    parsers.parse('there is an object-property class-edge from "{src}" to "{tgt}" labelled "{lbl}"')
)
def then_op_edge(ctx: dict, src: str, tgt: str, lbl: str) -> None:
    assert any(
        e["source"] == _u(src)
        and e["target"] == _u(tgt)
        and e["type"] == "objectProperty"
        and e["label"] == lbl
        for e in ctx["graph"]["edges"]
    )
