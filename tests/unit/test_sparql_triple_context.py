"""Unit tests for SPARQL triple-position-aware autocomplete context detection."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.operations import add_subclass_of
from ster.sparql_query import (
    _sparql_context_at_cursor,
    build_uri_index,
    qname_candidates,
    qname_level_candidates,
)

BASE = "https://example.org/onto/"


def _ctx(buffer: str) -> str:
    return _sparql_context_at_cursor(buffer, len(buffer))


# ── Triple position detection ──────────────────────────────────────────────────


def test_subject_position_is_any():
    assert _ctx("WHERE { kai:") == "any"


def test_predicate_position_is_property():
    assert _ctx("WHERE { kai:Foo kai:") == "property"


def test_object_position_after_unknown_predicate_is_any():
    assert _ctx("WHERE { kai:Foo kai:bar kai:") == "any"


def test_after_dot_position_two_is_predicate():
    assert _ctx("WHERE { kai:A kai:p kai:B . kai:C kai:") == "property"


def test_after_semicolon_next_is_predicate():
    assert _ctx("WHERE { kai:A kai:p kai:B ; kai:") == "property"


def test_after_comma_next_is_object():
    # comma reuses subject + predicate; position after comma is object → any
    assert _ctx("WHERE { kai:A kai:p kai:B , kai:") == "any"


def test_after_open_brace_position_one_is_subject():
    assert _ctx("SELECT * WHERE { kai:") == "any"


def test_predicate_position_with_variable_subject():
    assert _ctx("WHERE { ?x kai:") == "property"


def test_predicate_position_with_literal_subject():
    assert _ctx('WHERE { "hello" kai:') == "property"


# ── Class-predicate regression ─────────────────────────────────────────────────


def test_class_predicate_rdf_type_still_class():
    assert _ctx("WHERE { ?x rdf:type kai:") == "class"


def test_class_predicate_rdfs_subclassof_still_class():
    assert _ctx("WHERE { kai:A rdfs:subClassOf kai:") == "class"


def test_class_predicate_a_still_class():
    assert _ctx("WHERE { ?x a kai:") == "class"


# ── URI index properties bucket ────────────────────────────────────────────────


def _taxonomy_with_property(name: str) -> Taxonomy:
    t = Taxonomy()
    t.namespace_bindings["kai"] = BASE
    t.owl_properties[BASE + name] = OWLProperty(
        uri=BASE + name,
        labels=[Label("en", name)],
    )
    return t


def test_properties_bucket_populated():
    t = _taxonomy_with_property("hasAge")
    idx = build_uri_index(t)
    assert "hasAge" in idx.get("kai", {}).get("properties", [])


def test_properties_bucket_excludes_classes():
    t = Taxonomy()
    t.namespace_bindings["kai"] = BASE
    from ster.model import RDFClass

    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    t.owl_properties[BASE + "hasAge"] = OWLProperty(uri=BASE + "hasAge")
    idx = build_uri_index(t)
    props = idx.get("kai", {}).get("properties", [])
    assert "hasAge" in props
    assert "Animal" not in props


# ── qname_candidates property context ─────────────────────────────────────────


def test_qname_candidates_property_context_returns_only_properties():
    t = _taxonomy_with_property("hasAge")
    from ster.model import RDFClass

    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    idx = build_uri_index(t)
    results = qname_candidates(idx, "kai", "", "property")
    assert "hasAge" in results
    assert "Animal" not in results


def test_qname_candidates_any_context_returns_all():
    t = _taxonomy_with_property("hasAge")
    from ster.model import RDFClass

    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    idx = build_uri_index(t)
    results = qname_candidates(idx, "kai", "", "any")
    assert "hasAge" in results
    assert "Animal" in results


def test_qname_candidates_property_context_filter_applied():
    t = _taxonomy_with_property("hasAge")
    t.owl_properties[BASE + "hasName"] = OWLProperty(uri=BASE + "hasName")
    idx = build_uri_index(t)
    results = qname_candidates(idx, "kai", "hasA", "property")
    assert results == ["hasAge"]


# ── qname_level_candidates property context ────────────────────────────────────


def test_qname_level_candidates_property_context_returns_properties():
    t = _taxonomy_with_property("hasAge")
    idx = build_uri_index(t)
    results = qname_level_candidates(idx, "kai", "", "", "property")
    names = [name for name, _ in results]
    assert "hasAge" in names


def test_qname_level_candidates_property_context_no_hierarchy():
    """Properties have no subproperty hierarchy in the flat list."""
    t = _taxonomy_with_property("hasAge")
    t.owl_properties[BASE + "hasName"] = OWLProperty(uri=BASE + "hasName")
    idx = build_uri_index(t)
    results = qname_level_candidates(idx, "kai", "", "", "property")
    # All properties returned, none marked as having children
    assert all(not has_children for _, has_children in results)


# ── Subject-position hierarchical autocomplete ────────────────────────────────


def _tax_with_class_and_individual(
    class_name: str,
    ind_name: str,
    *,
    typed: bool = True,
) -> Taxonomy:
    t = Taxonomy()
    t.namespace_bindings["kai"] = BASE
    t.owl_classes[BASE + class_name] = RDFClass(uri=BASE + class_name)
    types = [BASE + class_name] if typed else []
    t.owl_individuals[BASE + ind_name] = OWLIndividual(uri=BASE + ind_name, types=types)
    return t


def _names(results: list[tuple[str, bool]]) -> list[str]:
    return [name for name, _ in results]


# ── individuals_by_class bucket ───────────────────────────────────────────────


def test_individuals_by_class_bucket_populated():
    t = _tax_with_class_and_individual("Animal", "Fido")
    idx = build_uri_index(t)
    ibc = idx.get("kai", {}).get("individuals_by_class", {})
    assert "Fido" in ibc.get("Animal", [])


def test_individuals_by_class_only_typed_individuals():
    t = _tax_with_class_and_individual("Animal", "Fido", typed=False)
    idx = build_uri_index(t)
    ibc = idx.get("kai", {}).get("individuals_by_class", {})
    assert "Fido" not in ibc.get("Animal", [])


def test_individuals_by_class_multiple_types():
    t = Taxonomy()
    t.namespace_bindings["kai"] = BASE
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    t.owl_classes[BASE + "Pet"] = RDFClass(uri=BASE + "Pet")
    t.owl_individuals[BASE + "Fido"] = OWLIndividual(
        uri=BASE + "Fido", types=[BASE + "Animal", BASE + "Pet"]
    )
    idx = build_uri_index(t)
    ibc = idx.get("kai", {}).get("individuals_by_class", {})
    assert "Fido" in ibc.get("Animal", [])
    assert "Fido" in ibc.get("Pet", [])


# ── Root level "any" context ──────────────────────────────────────────────────


def test_root_level_any_shows_class_roots():
    t = Taxonomy()
    t.namespace_bindings["kai"] = BASE
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    idx = build_uri_index(t)
    assert "Animal" in _names(qname_level_candidates(idx, "kai", "", "", "any"))


def test_root_level_any_shows_properties():
    t = Taxonomy()
    t.namespace_bindings["kai"] = BASE
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    t.owl_properties[BASE + "hasAge"] = OWLProperty(uri=BASE + "hasAge")
    idx = build_uri_index(t)
    assert "hasAge" in _names(qname_level_candidates(idx, "kai", "", "", "any"))


def test_root_level_any_does_not_show_typed_individuals():
    t = _tax_with_class_and_individual("Animal", "Fido")
    idx = build_uri_index(t)
    assert "Fido" not in _names(qname_level_candidates(idx, "kai", "", "", "any"))


def test_root_level_any_shows_untyped_individuals():
    t = _tax_with_class_and_individual("Animal", "Mystery", typed=False)
    idx = build_uri_index(t)
    assert "Mystery" in _names(qname_level_candidates(idx, "kai", "", "", "any"))


def test_root_level_properties_have_no_children_marker():
    t = Taxonomy()
    t.namespace_bindings["kai"] = BASE
    t.owl_properties[BASE + "hasAge"] = OWLProperty(uri=BASE + "hasAge")
    idx = build_uri_index(t)
    results = qname_level_candidates(idx, "kai", "", "", "any")
    prop_results = [(n, hc) for n, hc in results if n == "hasAge"]
    assert prop_results and not prop_results[0][1]


# ── Drill-down into a class ───────────────────────────────────────────────────


def test_drill_shows_subclasses():
    t = Taxonomy()
    t.namespace_bindings["kai"] = BASE
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    t.owl_classes[BASE + "Dog"] = RDFClass(uri=BASE + "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    idx = build_uri_index(t)
    assert "Dog" in _names(qname_level_candidates(idx, "kai", "Animal", "", "any"))


def test_drill_shows_individuals_of_class():
    t = _tax_with_class_and_individual("Animal", "Fido")
    idx = build_uri_index(t)
    assert "Fido" in _names(qname_level_candidates(idx, "kai", "Animal", "", "any"))


def test_drill_does_not_show_individuals_of_other_class():
    t = Taxonomy()
    t.namespace_bindings["kai"] = BASE
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    t.owl_classes[BASE + "Vehicle"] = RDFClass(uri=BASE + "Vehicle")
    t.owl_individuals[BASE + "Car"] = OWLIndividual(uri=BASE + "Car", types=[BASE + "Vehicle"])
    idx = build_uri_index(t)
    assert "Car" not in _names(qname_level_candidates(idx, "kai", "Animal", "", "any"))


def test_drill_individuals_have_no_children_marker():
    t = _tax_with_class_and_individual("Animal", "Fido")
    idx = build_uri_index(t)
    results = qname_level_candidates(idx, "kai", "Animal", "", "any")
    ind_results = [(n, hc) for n, hc in results if n == "Fido"]
    assert ind_results and not ind_results[0][1]


# ── has_children marker correctness ──────────────────────────────────────────


def test_root_class_with_only_individuals_has_children_marker():
    """A leaf class that has individuals but no subclasses must show ▶ so the
    user can drill into it to reach those individuals."""
    t = _tax_with_class_and_individual("Animal", "Fido")
    idx = build_uri_index(t)
    results = qname_level_candidates(idx, "kai", "", "", "any")
    animal_results = [(n, hc) for n, hc in results if n == "Animal"]
    assert animal_results, "Animal should appear at root level"
    assert animal_results[0][1], "Animal should have ▶ because it has individuals"


def test_subclass_with_only_individuals_has_children_marker():
    """A subclass that has individuals but no sub-subclasses must also show ▶."""
    t = Taxonomy()
    t.namespace_bindings["kai"] = BASE
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal")
    t.owl_classes[BASE + "Dog"] = RDFClass(uri=BASE + "Dog")
    add_subclass_of(t, BASE + "Dog", BASE + "Animal")
    t.owl_individuals[BASE + "Fido"] = OWLIndividual(uri=BASE + "Fido", types=[BASE + "Dog"])
    idx = build_uri_index(t)
    results = qname_level_candidates(idx, "kai", "Animal", "", "any")
    dog_results = [(n, hc) for n, hc in results if n == "Dog"]
    assert dog_results, "Dog should appear when drilling into Animal"
    assert dog_results[0][1], "Dog should have ▶ because it has individuals"
