"""Unit tests for treeview section layout detection and rendering."""

from __future__ import annotations

from ster.model import Concept, ConceptScheme, Label, LabelType, OWLProperty, RDFClass, Taxonomy
from ster.nav.logic import (
    _ACTION_ADD_PROPERTY,
    SECTION_PROPERTIES,
    build_rdf_class_detail,
    flatten_mixed_tree,
    flatten_ontology_tree,
    flatten_tree,
)

BASE = "https://example.org/onto/"


def _owl_taxonomy(class_names: list[str] | None = None) -> Taxonomy:
    t = Taxonomy()
    for name in class_names or ["Person"]:
        t.owl_classes[BASE + name] = RDFClass(uri=BASE + name, labels=[Label("en", name)])
    return t


def _skos_taxonomy(concept_names: list[str] | None = None) -> Taxonomy:
    t = Taxonomy()
    names = concept_names or ["Animal"]
    scheme_uri = BASE + "Scheme"
    t.schemes[scheme_uri] = ConceptScheme(
        uri=scheme_uri,
        labels=[Label("en", "Test Scheme")],
        top_concepts=[BASE + names[0]],
    )
    for name in names:
        t.concepts[BASE + name] = Concept(
            uri=BASE + name,
            labels=[Label(lang="en", value=name, type=LabelType.PREF)],
            top_concept_of=scheme_uri,
        )
    return t


def _mixed_taxonomy() -> Taxonomy:
    t = _owl_taxonomy(["Person"])
    scheme_uri = BASE + "Scheme"
    t.schemes[scheme_uri] = ConceptScheme(
        uri=scheme_uri,
        labels=[Label("en", "Test Scheme")],
        top_concepts=[BASE + "Animal"],
    )
    t.concepts[BASE + "Animal"] = Concept(
        uri=BASE + "Animal",
        labels=[Label(lang="en", value="Animal", type=LabelType.PREF)],
        top_concept_of=scheme_uri,
    )
    return t


# ── Presence / absence ────────────────────────────────────────────────────────


def test_owl_only_contains_properties_section():
    flat = flatten_ontology_tree(_owl_taxonomy())
    uris = [line.uri for line in flat]
    assert SECTION_PROPERTIES in uris


def test_skos_only_has_no_properties_section():
    flat = flatten_tree(_skos_taxonomy())
    uris = [line.uri for line in flat]
    assert SECTION_PROPERTIES not in uris


def test_mixed_contains_properties_section():
    flat = flatten_mixed_tree(_mixed_taxonomy())
    uris = [line.uri for line in flat]
    assert SECTION_PROPERTIES in uris


def test_empty_owl_taxonomy_has_no_section():
    flat = flatten_ontology_tree(Taxonomy())
    uris = [line.uri for line in flat]
    assert SECTION_PROPERTIES not in uris


# ── Order ─────────────────────────────────────────────────────────────────────


def test_properties_section_is_first_in_owl_only():
    flat = flatten_ontology_tree(_owl_taxonomy())
    assert flat[0].uri == SECTION_PROPERTIES


def test_properties_section_is_first_in_mixed():
    flat = flatten_mixed_tree(_mixed_taxonomy())
    assert flat[0].uri == SECTION_PROPERTIES


def test_properties_section_before_class_nodes_in_owl():
    flat = flatten_ontology_tree(_owl_taxonomy())
    prop_idx = next(i for i, l in enumerate(flat) if l.uri == SECTION_PROPERTIES)
    class_indices = [i for i, l in enumerate(flat) if l.uri == BASE + "Person"]
    assert all(prop_idx < ci for ci in class_indices)


def test_class_nodes_before_concept_nodes_in_mixed():
    flat = flatten_mixed_tree(_mixed_taxonomy())
    class_indices = [i for i, l in enumerate(flat) if l.uri == BASE + "Person"]
    concept_indices = [i for i, l in enumerate(flat) if l.uri == BASE + "Animal"]
    assert class_indices and concept_indices
    assert max(class_indices) < min(concept_indices)


# ── Section node fields ───────────────────────────────────────────────────────


def test_properties_section_label():
    flat = flatten_ontology_tree(_owl_taxonomy())
    section = next(l for l in flat if l.uri == SECTION_PROPERTIES)
    assert section.label == "Properties"


def test_properties_section_depth_zero():
    flat = flatten_ontology_tree(_owl_taxonomy())
    section = next(l for l in flat if l.uri == SECTION_PROPERTIES)
    assert section.depth == 0


def test_properties_section_node_type():
    flat = flatten_ontology_tree(_owl_taxonomy())
    section = next(l for l in flat if l.uri == SECTION_PROPERTIES)
    assert section.node_type == "section"


# ── Class detail actions ──────────────────────────────────────────────────────


def test_class_actions_include_focused_graph():
    tax = _owl_taxonomy(["Person"])
    fields = build_rdf_class_detail(tax, BASE + "Person", "en")
    actions = [
        f.meta.get("action")
        for f in fields
        if f.meta and f.meta.get("type") in ("action", "action_add")
    ]
    assert "view_focused_graph" in actions


def test_class_focused_graph_action_carries_uri():
    tax = _owl_taxonomy(["Person"])
    fields = build_rdf_class_detail(tax, BASE + "Person", "en")
    field = next(f for f in fields if f.meta and f.meta.get("action") == "view_focused_graph")
    assert field.meta.get("uri") == BASE + "Person"


# ── Collapse behaviour ────────────────────────────────────────────────────────


def test_properties_section_is_folded_when_uri_in_folded_set():
    flat = flatten_ontology_tree(_owl_taxonomy(), folded={SECTION_PROPERTIES})
    section = next(l for l in flat if l.uri == SECTION_PROPERTIES)
    assert section.is_folded is True


def test_properties_section_is_not_folded_when_uri_absent_from_folded_set():
    flat = flatten_ontology_tree(_owl_taxonomy(), folded=set())
    section = next(l for l in flat if l.uri == SECTION_PROPERTIES)
    assert section.is_folded is False


def test_class_nodes_still_present_regardless_of_properties_fold_state():
    folded_flat = flatten_ontology_tree(_owl_taxonomy(), folded={SECTION_PROPERTIES})
    unfolded_flat = flatten_ontology_tree(_owl_taxonomy(), folded=set())
    folded_uris = {l.uri for l in folded_flat}
    unfolded_uris = {l.uri for l in unfolded_flat}
    assert BASE + "Person" in folded_uris
    assert BASE + "Person" in unfolded_uris


# ── Property child nodes ──────────────────────────────────────────────────────


def _owl_taxonomy_with_props(*prop_names: str) -> Taxonomy:
    t = _owl_taxonomy()
    for name in prop_names:
        t.owl_properties[BASE + name] = OWLProperty(uri=BASE + name, labels=[Label("en", name)])
    return t


def test_property_nodes_appear_when_section_expanded():
    t = _owl_taxonomy_with_props("hasAge")
    flat = flatten_ontology_tree(t, folded=set())
    uris = [l.uri for l in flat]
    assert BASE + "hasAge" in uris


def test_property_nodes_absent_when_section_folded():
    t = _owl_taxonomy_with_props("hasAge")
    flat = flatten_ontology_tree(t, folded={SECTION_PROPERTIES})
    uris = [l.uri for l in flat]
    assert BASE + "hasAge" not in uris


def test_property_child_node_type():
    t = _owl_taxonomy_with_props("hasAge")
    flat = flatten_ontology_tree(t, folded=set())
    prop_line = next(l for l in flat if l.uri == BASE + "hasAge")
    assert prop_line.node_type == "property"


def test_property_child_depth():
    t = _owl_taxonomy_with_props("hasAge")
    flat = flatten_ontology_tree(t, folded=set())
    prop_line = next(l for l in flat if l.uri == BASE + "hasAge")
    assert prop_line.depth == 1


def test_property_children_before_class_tree():
    t = _owl_taxonomy_with_props("hasAge")
    flat = flatten_ontology_tree(t, folded=set())
    prop_idx = next(i for i, l in enumerate(flat) if l.uri == BASE + "hasAge")
    class_idx = next(i for i, l in enumerate(flat) if l.uri == BASE + "Person")
    assert prop_idx < class_idx


def test_property_children_sorted_alphabetically():
    t = _owl_taxonomy_with_props("zebra", "apple", "mango")
    flat = flatten_ontology_tree(t, folded=set())
    prop_uris = [l.uri for l in flat if l.node_type == "property"]
    local_names = [u.rsplit("/", 1)[-1] for u in prop_uris]
    assert local_names == sorted(local_names)


def test_add_property_action_row_present_when_expanded():
    t = _owl_taxonomy()
    flat = flatten_ontology_tree(t, folded=set())
    uris = [l.uri for l in flat]
    assert _ACTION_ADD_PROPERTY in uris


def test_add_property_action_row_absent_when_folded():
    t = _owl_taxonomy()
    flat = flatten_ontology_tree(t, folded={SECTION_PROPERTIES})
    uris = [l.uri for l in flat]
    assert _ACTION_ADD_PROPERTY not in uris


def test_add_property_action_row_is_last_child_of_section():
    t = _owl_taxonomy_with_props("hasAge", "hasName")
    flat = flatten_ontology_tree(t, folded=set())
    action_idx = next(i for i, l in enumerate(flat) if l.uri == _ACTION_ADD_PROPERTY)
    # all property nodes must appear before the action row
    prop_indices = [i for i, l in enumerate(flat) if l.node_type == "property"]
    assert all(pi < action_idx for pi in prop_indices)


def test_add_property_action_row_is_action_flag():
    t = _owl_taxonomy()
    flat = flatten_ontology_tree(t, folded=set())
    action_line = next(l for l in flat if l.uri == _ACTION_ADD_PROPERTY)
    assert action_line.is_action is True
