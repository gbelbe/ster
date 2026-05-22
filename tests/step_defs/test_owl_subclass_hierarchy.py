"""BDD step definitions for tests/features/owl/subclass_hierarchy.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.exceptions import CircularHierarchyError, ClassNotFoundError
from ster.model import Label, RDFClass, Taxonomy
from ster.operations import add_subclass_of

scenarios("../features/owl/subclass_hierarchy.feature")

BASE = "https://example.org/onto/"


@pytest.fixture
def ctx():
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('a taxonomy with OWL classes "{a}" and "{b}"'))
def given_two_classes(ctx, a, b):
    t = Taxonomy()
    t.owl_classes[BASE + a] = RDFClass(uri=BASE + a, labels=[Label("en", a)])
    t.owl_classes[BASE + b] = RDFClass(uri=BASE + b, labels=[Label("en", b)])
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with OWL classes "{a}", "{b}", and "{c}"'))
def given_three_classes(ctx, a, b, c):
    t = Taxonomy()
    for name in (a, b, c):
        t.owl_classes[BASE + name] = RDFClass(uri=BASE + name, labels=[Label("en", name)])
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with OWL class "{a}" only'))
def given_one_class(ctx, a):
    t = Taxonomy()
    t.owl_classes[BASE + a] = RDFClass(uri=BASE + a, labels=[Label("en", a)])
    ctx["taxonomy"] = t


@given(parsers.parse('"{child}" is already a subclass of "{parent}"'))
def given_existing_subclass(ctx, child, parent):
    add_subclass_of(ctx["taxonomy"], BASE + child, BASE + parent)


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I add "{child}" as a subclass of "{parent}"'))
def when_add_subclass(ctx, child, parent):
    try:
        add_subclass_of(ctx["taxonomy"], BASE + child, BASE + parent)
        ctx["error"] = None
    except (ClassNotFoundError, CircularHierarchyError) as exc:
        ctx["error"] = exc


@when(parsers.parse('I add "{child}" as a subclass of "{parent}" again'))
def when_add_subclass_again(ctx, child, parent):
    try:
        add_subclass_of(ctx["taxonomy"], BASE + child, BASE + parent)
        ctx["error"] = None
    except (ClassNotFoundError, CircularHierarchyError) as exc:
        ctx["error"] = exc


@when(parsers.parse('I add "{parent}" as the superclass of "{child}"'))
def when_add_superclass(ctx, parent, child):
    try:
        add_subclass_of(ctx["taxonomy"], BASE + child, BASE + parent)
        ctx["error"] = None
    except (ClassNotFoundError, CircularHierarchyError) as exc:
        ctx["error"] = exc


@when(parsers.parse('I add "{child}" as a subclass of "{parent}"'))
def when_add_subclass_second(ctx, child, parent):
    try:
        add_subclass_of(ctx["taxonomy"], BASE + child, BASE + parent)
        ctx["error"] = None
    except (ClassNotFoundError, CircularHierarchyError) as exc:
        ctx["error"] = exc


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('"{child}" has "{parent}" in its sub_class_of list'))
def then_has_subclass_link(ctx, child, parent):
    assert ctx["error"] is None, f"Unexpected error: {ctx['error']}"
    cls = ctx["taxonomy"].owl_classes[BASE + child]
    assert BASE + parent in cls.sub_class_of


@then(parsers.parse('"{child}" has exactly one "{parent}" entry in its sub_class_of list'))
def then_no_duplicate(ctx, child, parent):
    assert ctx["error"] is None, f"Unexpected error: {ctx['error']}"
    cls = ctx["taxonomy"].owl_classes[BASE + child]
    assert cls.sub_class_of.count(BASE + parent) == 1


@then(parsers.parse('"{child}" has both "{a}" and "{b}" in its sub_class_of list'))
def then_has_both(ctx, child, a, b):
    assert ctx["error"] is None, f"Unexpected error: {ctx['error']}"
    sub = ctx["taxonomy"].owl_classes[BASE + child].sub_class_of
    assert BASE + a in sub
    assert BASE + b in sub


@then("a ClassNotFoundError is raised")
def then_class_not_found(ctx):
    assert isinstance(ctx["error"], ClassNotFoundError), (
        f"Expected ClassNotFoundError, got {ctx['error']!r}"
    )


@then("a CircularHierarchyError is raised")
def then_circular(ctx):
    assert isinstance(ctx["error"], CircularHierarchyError), (
        f"Expected CircularHierarchyError, got {ctx['error']!r}"
    )
