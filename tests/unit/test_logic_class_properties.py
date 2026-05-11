"""Unit tests for OWL class property helpers in ster/nav/logic.py."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.nav.logic import (
    _direct_properties,
    _inherited_properties,
    build_rdf_class_detail,
)

BASE = "https://example.org/onto/"


def _cls(name: str, parents: list[str] | None = None) -> RDFClass:
    return RDFClass(
        uri=BASE + name,
        labels=[Label("en", name)],
        sub_class_of=[BASE + p for p in (parents or [])],
    )


def _prop(name: str, domains: list[str] | None = None) -> OWLProperty:
    return OWLProperty(
        uri=BASE + name,
        labels=[Label("en", name)],
        domains=[BASE + d for d in (domains or [])],
    )


def _taxonomy(
    classes: list[RDFClass],
    properties: list[OWLProperty] | None = None,
    individuals: list[OWLIndividual] | None = None,
) -> Taxonomy:
    t = Taxonomy()
    for c in classes:
        t.owl_classes[c.uri] = c
    for p in properties or []:
        t.owl_properties[p.uri] = p
    for i in individuals or []:
        t.owl_individuals[i.uri] = i
    return t


# ── _direct_properties ────────────────────────────────────────────────────────


def test_direct_properties_returns_matching_domain():
    t = _taxonomy([_cls("Person")], [_prop("hasName", ["Person"])])
    result = _direct_properties(t, BASE + "Person")
    assert any(p.uri == BASE + "hasName" for p in result)


def test_direct_properties_excludes_non_matching_domain():
    t = _taxonomy([_cls("Person"), _cls("Animal")], [_prop("hasName", ["Person"])])
    result = _direct_properties(t, BASE + "Animal")
    assert result == []


def test_direct_properties_empty_when_no_properties():
    t = _taxonomy([_cls("Person")])
    result = _direct_properties(t, BASE + "Person")
    assert result == []


def test_direct_properties_multiple_domains():
    t = _taxonomy(
        [_cls("Person"), _cls("Animal")],
        [_prop("hasName", ["Person", "Animal"])],
    )
    result_p = _direct_properties(t, BASE + "Person")
    result_a = _direct_properties(t, BASE + "Animal")
    assert any(p.uri == BASE + "hasName" for p in result_p)
    assert any(p.uri == BASE + "hasName" for p in result_a)


# ── _inherited_properties ─────────────────────────────────────────────────────


def test_inherited_properties_returns_parent_props():
    person = _cls("Person")
    employee = _cls("Employee", ["Person"])
    t = _taxonomy([person, employee], [_prop("hasName", ["Person"])])
    result = _inherited_properties(t, BASE + "Employee")
    prop_uris = [p.uri for p, _ in result]
    assert BASE + "hasName" in prop_uris


def test_inherited_properties_includes_parent_uri():
    person = _cls("Person")
    employee = _cls("Employee", ["Person"])
    t = _taxonomy([person, employee], [_prop("hasName", ["Person"])])
    result = _inherited_properties(t, BASE + "Employee")
    parent_uris = [parent for _, parent in result]
    assert BASE + "Person" in parent_uris


def test_inherited_properties_multi_level():
    person = _cls("Person")
    employee = _cls("Employee", ["Person"])
    manager = _cls("Manager", ["Employee"])
    t = _taxonomy(
        [person, employee, manager],
        [_prop("hasName", ["Person"]), _prop("hasRole", ["Employee"])],
    )
    result = _inherited_properties(t, BASE + "Manager")
    prop_uris = [p.uri for p, _ in result]
    assert BASE + "hasName" in prop_uris
    assert BASE + "hasRole" in prop_uris


def test_inherited_properties_no_duplicates_diamond():
    base_cls = _cls("Base")
    a = _cls("A", ["Base"])
    b = _cls("B", ["Base"])
    c = _cls("C", ["A", "B"])
    t = _taxonomy([base_cls, a, b, c], [_prop("baseP", ["Base"])])
    result = _inherited_properties(t, BASE + "C")
    prop_uris = [p.uri for p, _ in result]
    assert prop_uris.count(BASE + "baseP") == 1


def test_inherited_properties_excludes_direct():
    parent = _cls("Parent")
    child = _cls("Child", ["Parent"])
    shared = _prop("sharedP", ["Parent", "Child"])
    t = _taxonomy([parent, child], [shared])
    result = _inherited_properties(t, BASE + "Child")
    prop_uris = [p.uri for p, _ in result]
    assert BASE + "sharedP" not in prop_uris


def test_inherited_properties_empty_for_root_class():
    person = _cls("Person")
    t = _taxonomy([person], [_prop("hasName", ["Person"])])
    result = _inherited_properties(t, BASE + "Person")
    assert result == []


# ── build_rdf_class_detail ────────────────────────────────────────────────────


def test_build_class_detail_contains_properties_section():
    t = _taxonomy([_cls("Person")], [_prop("hasName", ["Person"])])
    fields = build_rdf_class_detail(t, BASE + "Person", "en")
    sep_labels = [f.display for f in fields if f.meta.get("type") == "separator"]
    assert "Properties" in sep_labels


def test_build_class_detail_direct_prop_has_nav_field():
    t = _taxonomy([_cls("Person")], [_prop("hasName", ["Person"])])
    fields = build_rdf_class_detail(t, BASE + "Person", "en")
    nav_fields = [f for f in fields if f.meta.get("type") == "class_prop_nav"]
    assert any(f.meta.get("uri") == BASE + "hasName" for f in nav_fields)


def test_build_class_detail_inherited_prop_has_no_edit_action():
    person = _cls("Person")
    employee = _cls("Employee", ["Person"])
    t = _taxonomy([person, employee], [_prop("hasName", ["Person"])])
    fields = build_rdf_class_detail(t, BASE + "Employee", "en")
    inherited = [f for f in fields if f.meta.get("type") == "inherited_prop"]
    assert inherited, "expected at least one inherited_prop field"
    for f in inherited:
        assert not f.editable


def test_build_class_detail_inherited_label_includes_parent():
    person = _cls("Person")
    employee = _cls("Employee", ["Person"])
    t = _taxonomy([person, employee], [_prop("hasName", ["Person"])])
    fields = build_rdf_class_detail(t, BASE + "Employee", "en")
    inherited = [f for f in fields if f.meta.get("type") == "inherited_prop"]
    assert any("Person" in f.display for f in inherited)


def test_build_class_detail_add_property_action_present():
    t = _taxonomy([_cls("Person")])
    fields = build_rdf_class_detail(t, BASE + "Person", "en")
    actions = [f for f in fields if f.meta.get("action") == "add_class_property"]
    assert actions, "expected add_class_property action row"


def test_build_class_detail_no_properties_still_has_section():
    t = _taxonomy([_cls("Animal")])
    fields = build_rdf_class_detail(t, BASE + "Animal", "en")
    sep_labels = [f.display for f in fields if f.meta.get("type") == "separator"]
    assert "Properties" in sep_labels


def test_build_class_detail_direct_prop_not_in_inherited():
    person = _cls("Person")
    employee = _cls("Employee", ["Person"])
    shared = _prop("sharedP", ["Person", "Employee"])
    t = _taxonomy([person, employee], [shared])
    fields = build_rdf_class_detail(t, BASE + "Employee", "en")
    inherited = [f for f in fields if f.meta.get("type") == "inherited_prop"]
    inherited_uris = [f.meta.get("uri") for f in inherited]
    assert BASE + "sharedP" not in inherited_uris
