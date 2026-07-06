"""BDD step definitions for tests/features/ui/new_subclass.feature."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.exceptions import CircularHierarchyError
from ster.model import Label, RDFClass, Taxonomy
from ster.nav.logic import build_rdf_class_detail
from ster.operations import add_subclass_of

scenarios("../features/ui/new_subclass.feature")

BASE = "https://example.org/"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {"fields": [], "error": None}


# ── Givens ────────────────────────────────────────────────────────────────────


@given(
    parsers.parse('a taxonomy with class "{name}" that has a subclass "{child}"'),
    target_fixture="ctx",
)
def taxonomy_with_child(name: str, child: str) -> dict[str, Any]:
    t = Taxonomy()
    t.owl_classes[BASE + name] = RDFClass(uri=BASE + name, labels=[Label("en", name)])
    t.owl_classes[BASE + child] = RDFClass(uri=BASE + child, labels=[Label("en", child)])
    add_subclass_of(t, BASE + child, BASE + name)
    return {"taxonomy": t, "target": BASE + name, "fields": [], "error": None}


@given(parsers.parse('a taxonomy with class "{name}"'), target_fixture="ctx")
def taxonomy_with_class(name: str) -> dict[str, Any]:
    t = Taxonomy()
    t.owl_classes[BASE + name] = RDFClass(uri=BASE + name, labels=[Label("en", name)])
    return {"taxonomy": t, "target": BASE + name, "fields": [], "error": None}


@given(parsers.parse('a taxonomy where "{name}" is a subclass of "{parent}"'), target_fixture="ctx")
def taxonomy_with_hierarchy(name: str, parent: str) -> dict[str, Any]:
    t = Taxonomy()
    t.owl_classes[BASE + parent] = RDFClass(uri=BASE + parent, labels=[Label("en", parent)])
    t.owl_classes[BASE + name] = RDFClass(uri=BASE + name, labels=[Label("en", name)])
    add_subclass_of(t, BASE + name, BASE + parent)
    return {"taxonomy": t, "target": BASE + name, "fields": [], "error": None}


# ── Whens ─────────────────────────────────────────────────────────────────────


@when(parsers.parse('I build the detail fields for "{name}"'))
def build_fields(name: str, ctx: dict[str, Any]) -> None:
    ctx["fields"] = build_rdf_class_detail(ctx["taxonomy"], BASE + name, "en")


@when(parsers.parse('the new subclass URI "{uri}" is confirmed on "{parent}"'))
def confirm_new_subclass(uri: str, parent: str, ctx: dict[str, Any]) -> None:
    t = ctx["taxonomy"]
    parent_uri = BASE + parent
    try:
        if uri not in t.owl_classes:
            t.owl_classes[uri] = RDFClass(uri=uri)
        add_subclass_of(t, uri, parent_uri)
    except CircularHierarchyError as exc:
        ctx["error"] = exc


# ── Thens ─────────────────────────────────────────────────────────────────────


@then(parsers.parse('the detail panel contains a "New subclass" action'))
def has_new_subclass_action(ctx: dict[str, Any]) -> None:
    actions = [f.meta.get("action", "") for f in ctx["fields"] if f.meta.get("action")]
    assert "new_subclass" in actions, f"new_subclass action not found. Actions: {actions}"


@then(parsers.parse('no detail field has action "{action}"'))
def no_action(action: str, ctx: dict[str, Any]) -> None:
    actions = [f.meta.get("action", "") for f in ctx["fields"] if f.meta.get("action")]
    assert action not in actions, f"Unexpected action '{action}' found"


@then(parsers.parse('"{uri}" exists in the taxonomy owl_classes'))
def class_exists(uri: str, ctx: dict[str, Any]) -> None:
    assert uri in ctx["taxonomy"].owl_classes


@then(parsers.parse('"{parent_uri}" is in Cat\'s sub_class_of list'))
def parent_in_subclassof(parent_uri: str, ctx: dict[str, Any]) -> None:
    cat_uri = BASE + "Cat"
    cat = ctx["taxonomy"].owl_classes.get(cat_uri)
    assert cat is not None
    assert parent_uri in cat.sub_class_of


@then("a CircularHierarchyError is raised")
def circular_error_raised(ctx: dict[str, Any]) -> None:
    assert isinstance(ctx["error"], CircularHierarchyError)
