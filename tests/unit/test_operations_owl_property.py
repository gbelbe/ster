"""Unit tests for OWL property operations in ster/operations.py."""

from __future__ import annotations

import pytest

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.operations import (
    add_owl_property,
    clear_property_values,
    delete_owl_property,
    find_individuals_using_property,
)

BASE = "https://example.org/onto/"


def _taxonomy(
    classes: list[str] | None = None,
    properties: list[OWLProperty] | None = None,
    individuals: list[OWLIndividual] | None = None,
) -> Taxonomy:
    t = Taxonomy()
    for c in classes or []:
        t.owl_classes[BASE + c] = RDFClass(uri=BASE + c, labels=[Label("en", c)])
    for p in properties or []:
        t.owl_properties[p.uri] = p
    for i in individuals or []:
        t.owl_individuals[i.uri] = i
    return t


def _prop(name: str, domains: list[str] | None = None) -> OWLProperty:
    return OWLProperty(
        uri=BASE + name,
        labels=[Label("en", name)],
        domains=[BASE + d for d in (domains or [])],
    )


def _ind(name: str, prop_values: list[tuple[str, str]] | None = None) -> OWLIndividual:
    ind = OWLIndividual(uri=BASE + name, labels=[Label("en", name)])
    ind.property_values = list(prop_values or [])
    return ind


# ── add_owl_property ──────────────────────────────────────────────────────────


def test_add_owl_property_creates_entry():
    t = _taxonomy(classes=["Animal"])
    add_owl_property(t, BASE + "hasAge", "DatatypeProperty", "hasAge", "en", BASE + "Animal")
    assert BASE + "hasAge" in t.owl_properties


def test_add_owl_property_sets_domain():
    t = _taxonomy(classes=["Animal"])
    prop = add_owl_property(t, BASE + "hasAge", "DatatypeProperty", "hasAge", "en", BASE + "Animal")
    assert BASE + "Animal" in prop.domains


def test_add_owl_property_sets_range():
    t = _taxonomy(classes=["Animal", "Food"])
    prop = add_owl_property(
        t, BASE + "eats", "ObjectProperty", "eats", "en", BASE + "Animal", BASE + "Food"
    )
    assert BASE + "Food" in prop.ranges


def test_add_owl_property_no_range():
    t = _taxonomy(classes=["Animal"])
    prop = add_owl_property(t, BASE + "hasAge", "DatatypeProperty", "hasAge", "en", BASE + "Animal")
    assert prop.ranges == []


def test_add_owl_property_no_domain():
    t = _taxonomy()
    prop = add_owl_property(t, BASE + "globalP", "ObjectProperty", "globalP", "en")
    assert prop.domains == []


def test_add_owl_property_sets_label():
    t = _taxonomy(classes=["Animal"])
    prop = add_owl_property(t, BASE + "hasAge", "DatatypeProperty", "hasAge", "en", BASE + "Animal")
    assert prop.label("en") == "hasAge"


def test_add_owl_property_sets_prop_type():
    t = _taxonomy(classes=["Animal"])
    prop = add_owl_property(t, BASE + "hasAge", "DatatypeProperty", "hasAge", "en", BASE + "Animal")
    assert prop.prop_type == "DatatypeProperty"


def test_add_owl_property_duplicate_uri_raises():
    t = _taxonomy(classes=["Animal"], properties=[_prop("hasAge", ["Animal"])])
    with pytest.raises(ValueError, match="already exists"):
        add_owl_property(t, BASE + "hasAge", "DatatypeProperty", "hasAge", "en", BASE + "Animal")


# ── find_individuals_using_property ──────────────────────────────────────────


def test_find_individuals_using_property_hit():
    prop_uri = BASE + "hasColor"
    ind = _ind("RedCar", [(prop_uri, BASE + "Red")])
    t = _taxonomy(properties=[_prop("hasColor")], individuals=[ind])
    result = find_individuals_using_property(t, prop_uri)
    assert BASE + "RedCar" in result


def test_find_individuals_using_property_miss():
    prop_uri = BASE + "hasColor"
    ind = _ind("BlueBike")  # no property values
    t = _taxonomy(properties=[_prop("hasColor")], individuals=[ind])
    result = find_individuals_using_property(t, prop_uri)
    assert result == []


def test_find_individuals_using_property_only_matching():
    color_uri = BASE + "hasColor"
    size_uri = BASE + "hasSize"
    ind1 = _ind("RedCar", [(color_uri, BASE + "Red")])
    ind2 = _ind("BigBox", [(size_uri, BASE + "Large")])
    t = _taxonomy(properties=[_prop("hasColor"), _prop("hasSize")], individuals=[ind1, ind2])
    result = find_individuals_using_property(t, color_uri)
    assert BASE + "RedCar" in result
    assert BASE + "BigBox" not in result


# ── delete_owl_property ───────────────────────────────────────────────────────


def test_delete_owl_property_removes_entry():
    t = _taxonomy(properties=[_prop("hasColor")])
    delete_owl_property(t, BASE + "hasColor")
    assert BASE + "hasColor" not in t.owl_properties


def test_delete_owl_property_returns_impacted_uris():
    prop_uri = BASE + "hasColor"
    ind = _ind("RedCar", [(prop_uri, BASE + "Red")])
    t = _taxonomy(properties=[_prop("hasColor")], individuals=[ind])
    impacted = delete_owl_property(t, prop_uri)
    assert BASE + "RedCar" in impacted


def test_delete_owl_property_no_impact():
    t = _taxonomy(properties=[_prop("hasColor")])
    impacted = delete_owl_property(t, BASE + "hasColor")
    assert impacted == []


def test_delete_owl_property_raises_if_missing():
    t = _taxonomy()
    with pytest.raises(KeyError):
        delete_owl_property(t, BASE + "nonexistent")


# ── clear_property_values ─────────────────────────────────────────────────────


def test_clear_property_values_removes_tuples():
    prop_uri = BASE + "hasColor"
    ind = _ind("RedCar", [(prop_uri, BASE + "Red")])
    t = _taxonomy(properties=[_prop("hasColor")], individuals=[ind])
    clear_property_values(t, prop_uri)
    assert all(p != prop_uri for p, _ in t.owl_individuals[BASE + "RedCar"].property_values)


def test_clear_property_values_all_individuals():
    prop_uri = BASE + "hasColor"
    ind1 = _ind("RedCar", [(prop_uri, BASE + "Red")])
    ind2 = _ind("BlueBike", [(prop_uri, BASE + "Blue")])
    t = _taxonomy(properties=[_prop("hasColor")], individuals=[ind1, ind2])
    clear_property_values(t, prop_uri)
    for ind in t.owl_individuals.values():
        assert all(p != prop_uri for p, _ in ind.property_values)


def test_clear_property_values_leaves_other_props():
    color_uri = BASE + "hasColor"
    size_uri = BASE + "hasSize"
    ind = _ind("RedCar", [(color_uri, BASE + "Red"), (size_uri, BASE + "Large")])
    t = _taxonomy(properties=[_prop("hasColor"), _prop("hasSize")], individuals=[ind])
    clear_property_values(t, color_uri)
    remaining = [p for p, _ in t.owl_individuals[BASE + "RedCar"].property_values]
    assert size_uri in remaining
    assert color_uri not in remaining
