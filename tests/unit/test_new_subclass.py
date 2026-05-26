"""Unit tests for the New Subclass feature in the class detail panel."""

from __future__ import annotations

import pytest

from ster.exceptions import CircularHierarchyError
from ster.model import Label, RDFClass, Taxonomy
from ster.nav.logic import build_rdf_class_detail
from ster.operations import add_subclass_of

BASE = "https://example.org/"


def _taxonomy(*class_names: str) -> Taxonomy:
    t = Taxonomy()
    for name in class_names:
        t.owl_classes[BASE + name] = RDFClass(uri=BASE + name, labels=[Label("en", name)])
    return t


def _actions(fields) -> list[str]:
    return [f.meta.get("action", "") for f in fields if f.meta.get("action")]


def _sep_labels(fields) -> list[str]:
    return [f.display for f in fields if f.meta.get("type") == "separator"]


def _field_keys(fields) -> list[str]:
    return [f.key for f in fields]


# ── detail panel structure ────────────────────────────────────────────────────


def test_detail_shows_subclasses_separator():
    t = _taxonomy("Animal", "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    fields = build_rdf_class_detail(t, BASE + "Animal", "en")
    assert "Subclasses" in _sep_labels(fields)


def test_detail_shows_child_row():
    t = _taxonomy("Animal", "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    fields = build_rdf_class_detail(t, BASE + "Animal", "en")
    assert f"subclass:{BASE}Dog" in _field_keys(fields)


def test_detail_child_row_label_is_class_label():
    t = _taxonomy("Animal", "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    fields = build_rdf_class_detail(t, BASE + "Animal", "en")
    child_field = next(f for f in fields if f.key == f"subclass:{BASE}Dog")
    assert child_field.value == "Dog"


def test_detail_shows_new_subclass_action():
    t = _taxonomy("Animal")
    fields = build_rdf_class_detail(t, BASE + "Animal", "en")
    assert "new_subclass" in _actions(fields)


def test_detail_no_children_shows_empty_subclasses_section():
    t = _taxonomy("Animal")
    fields = build_rdf_class_detail(t, BASE + "Animal", "en")
    assert "Subclasses" in _sep_labels(fields)
    child_keys = [f.key for f in fields if f.key.startswith("subclass:")]
    assert child_keys == []


def test_old_link_subclass_action_removed():
    t = _taxonomy("Animal")
    fields = build_rdf_class_detail(t, BASE + "Animal", "en")
    assert "link_subclass" not in _actions(fields)


# ── new_subclass_uri handler logic (pure) ────────────────────────────────────


def test_new_subclass_creates_class_and_link():
    t = _taxonomy("Animal")
    new_uri = BASE + "Cat"
    if new_uri not in t.owl_classes:
        t.owl_classes[new_uri] = RDFClass(uri=new_uri)
    add_subclass_of(t, new_uri, BASE + "Animal")
    assert new_uri in t.owl_classes
    assert BASE + "Animal" in t.owl_classes[new_uri].sub_class_of


def test_new_subclass_rejects_circular():
    t = _taxonomy("LivingThing", "Animal")
    add_subclass_of(t, BASE + "Animal", BASE + "LivingThing")
    with pytest.raises(CircularHierarchyError):
        add_subclass_of(t, BASE + "LivingThing", BASE + "Animal")
