"""Unit tests for add_subclass_of in ster/operations.py."""

from __future__ import annotations

import pytest

from ster.exceptions import CircularHierarchyError, ClassNotFoundError
from ster.model import Label, RDFClass, Taxonomy
from ster.operations import add_subclass_of

BASE = "https://example.org/onto/"


def _taxonomy(*class_names: str) -> Taxonomy:
    t = Taxonomy()
    for name in class_names:
        t.owl_classes[BASE + name] = RDFClass(uri=BASE + name, labels=[Label("en", name)])
    return t


# ── happy path ────────────────────────────────────────────────────────────────


def test_add_subclass_link_present():
    t = _taxonomy("Animal", "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    assert BASE + "Animal" in t.owl_classes[BASE + "Dog"].sub_class_of


def test_add_subclass_parent_unchanged():
    t = _taxonomy("Animal", "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    assert t.owl_classes[BASE + "Animal"].sub_class_of == []


def test_add_superclass_same_result():
    t = _taxonomy("Animal", "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    assert BASE + "Animal" in t.owl_classes[BASE + "Dog"].sub_class_of


def test_add_subclass_idempotent():
    t = _taxonomy("Animal", "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    assert t.owl_classes[BASE + "Dog"].sub_class_of.count(BASE + "Animal") == 1


def test_add_subclass_multiple_parents():
    t = _taxonomy("Pet", "Animal", "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    add_subclass_of(t, BASE + "Dog", BASE + "Pet")
    sub = t.owl_classes[BASE + "Dog"].sub_class_of
    assert BASE + "Animal" in sub
    assert BASE + "Pet" in sub


# ── error paths ───────────────────────────────────────────────────────────────


def test_add_subclass_child_not_found():
    t = _taxonomy("Animal")
    with pytest.raises(ClassNotFoundError):
        add_subclass_of(t, BASE + "Dog", BASE + "Animal")


def test_add_subclass_parent_not_found():
    t = _taxonomy("Dog")
    with pytest.raises(ClassNotFoundError):
        add_subclass_of(t, BASE + "Dog", BASE + "Animal")


def test_add_subclass_self_reference():
    t = _taxonomy("Animal")
    with pytest.raises(CircularHierarchyError):
        add_subclass_of(t, BASE + "Animal", BASE + "Animal")


def test_add_subclass_circular_direct():
    t = _taxonomy("Animal", "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    with pytest.raises(CircularHierarchyError):
        add_subclass_of(t, BASE + "Animal", BASE + "Dog")


def test_add_subclass_circular_indirect():
    t = _taxonomy("Animal", "Dog", "Poodle")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    add_subclass_of(t, BASE + "Poodle", BASE + "Dog")
    with pytest.raises(CircularHierarchyError):
        add_subclass_of(t, BASE + "Animal", BASE + "Poodle")
