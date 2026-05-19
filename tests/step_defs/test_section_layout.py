"""BDD step definitions for tests/features/owl/section_layout.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import Concept, ConceptScheme, Label, LabelType, OWLProperty, RDFClass, Taxonomy
from ster.nav.logic import (
    _ACTION_ADD_PROPERTY,
    SECTION_PROPERTIES,
    flatten_mixed_tree,
    flatten_ontology_tree,
    flatten_tree,
)

scenarios("../features/owl/section_layout.feature")

BASE = "https://example.org/onto/"


@pytest.fixture
def ctx():
    return {"taxonomy": None, "flat": None, "folded": set()}


# ── Given ─────────────────────────────────────────────────────────────────────


@given('an OWL-only taxonomy with class "Person"')
def given_owl_only(ctx):
    t = Taxonomy()
    t.owl_classes[BASE + "Person"] = RDFClass(uri=BASE + "Person", labels=[Label("en", "Person")])
    ctx["taxonomy"] = t


@given('a SKOS-only taxonomy with concept "Animal"')
def given_skos_only(ctx):
    t = Taxonomy()
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
    ctx["taxonomy"] = t


@given('a mixed taxonomy with class "Person" and concept "Animal"')
def given_mixed(ctx):
    t = Taxonomy()
    t.owl_classes[BASE + "Person"] = RDFClass(uri=BASE + "Person", labels=[Label("en", "Person")])
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
    ctx["taxonomy"] = t


# ── When ──────────────────────────────────────────────────────────────────────


@when("I flatten the tree for display")
def when_flatten(ctx):
    t = ctx["taxonomy"]
    has_owl = bool(t.owl_classes)
    has_skos = bool(t.schemes or t.concepts)
    if has_owl and not has_skos:
        ctx["flat"] = flatten_ontology_tree(t, folded=set())
    elif has_skos and not has_owl:
        ctx["flat"] = flatten_tree(t, folded=set())
    else:
        ctx["flat"] = flatten_mixed_tree(t, folded=set())


@when("I flatten the tree with the Properties section folded")
def when_flatten_folded(ctx):
    ctx["flat"] = flatten_ontology_tree(ctx["taxonomy"], folded={SECTION_PROPERTIES})


@when("I flatten the tree with the Properties section unfolded")
def when_flatten_unfolded(ctx):
    ctx["flat"] = flatten_ontology_tree(ctx["taxonomy"], folded=set())


# ── Then ──────────────────────────────────────────────────────────────────────


@then("the flat list contains a Properties section node")
def then_has_properties_section(ctx):
    uris = [l.uri for l in ctx["flat"]]
    assert SECTION_PROPERTIES in uris, f"SECTION_PROPERTIES not found; got {uris}"


@then("the flat list has no Properties section node")
def then_no_properties_section(ctx):
    uris = [l.uri for l in ctx["flat"]]
    assert SECTION_PROPERTIES not in uris


@then("the Properties section appears before any class node")
def then_section_before_classes(ctx):
    flat = ctx["flat"]
    prop_idx = next(i for i, l in enumerate(flat) if l.uri == SECTION_PROPERTIES)
    class_indices = [i for i, l in enumerate(flat) if l.node_type == "class"]
    assert all(prop_idx < ci for ci in class_indices), (
        f"Properties section at {prop_idx} but class nodes at {class_indices}"
    )


@then("class nodes appear before concept nodes in the flat list")
def then_classes_before_concepts(ctx):
    flat = ctx["flat"]
    class_indices = [i for i, l in enumerate(flat) if l.node_type == "class"]
    concept_indices = [i for i, l in enumerate(flat) if l.node_type == "concept"]
    assert class_indices and concept_indices, "Expected both class and concept nodes"
    assert max(class_indices) < min(concept_indices), (
        f"Class nodes at {class_indices}, concept nodes at {concept_indices}"
    )


@then("the Properties section node has is_folded True")
def then_section_is_folded(ctx):
    section = next(l for l in ctx["flat"] if l.uri == SECTION_PROPERTIES)
    assert section.is_folded is True


@then("the Properties section node has is_folded False")
def then_section_is_not_folded(ctx):
    section = next(l for l in ctx["flat"] if l.uri == SECTION_PROPERTIES)
    assert section.is_folded is False


@given('an OWL-only taxonomy with class "Person" and property "hasAge"')
def given_owl_with_property(ctx):
    t = Taxonomy()
    t.owl_classes[BASE + "Person"] = RDFClass(uri=BASE + "Person", labels=[Label("en", "Person")])
    t.owl_properties[BASE + "hasAge"] = OWLProperty(
        uri=BASE + "hasAge", labels=[Label("en", "hasAge")]
    )
    ctx["taxonomy"] = t


@then('the flat list contains a property node for "hasAge"')
def then_has_property_node(ctx):
    uris = [l.uri for l in ctx["flat"]]
    assert BASE + "hasAge" in uris, f"hasAge not found in {uris}"


@then('the flat list has no property node for "hasAge"')
def then_no_property_node(ctx):
    uris = [l.uri for l in ctx["flat"]]
    assert BASE + "hasAge" not in uris


@then('the property node for "hasAge" appears before any class node')
def then_property_before_classes(ctx):
    flat = ctx["flat"]
    prop_idx = next(i for i, l in enumerate(flat) if l.uri == BASE + "hasAge")
    class_indices = [i for i, l in enumerate(flat) if l.node_type == "class"]
    assert all(prop_idx < ci for ci in class_indices)


@then("the flat list contains an Add property action row")
def then_has_add_property_action(ctx):
    uris = [l.uri for l in ctx["flat"]]
    assert _ACTION_ADD_PROPERTY in uris, "Add property action row not found"


@when('I build a fully expanded flat tree and search for "hasAge"')
def when_search_expanded(ctx):
    flat = flatten_ontology_tree(ctx["taxonomy"], folded=set())
    ctx["flat"] = flat
    import re

    pattern = re.compile("hasAge", re.IGNORECASE)
    prop_uri = next((l.uri for l in flat if l.node_type == "property"), None)
    local = prop_uri.rsplit("/", 1)[-1] if prop_uri else ""
    prop = ctx["taxonomy"].owl_properties.get(prop_uri or "")
    search_text = "  ".join([local] + ([lbl.value for lbl in prop.labels] if prop else []))
    ctx["search_match"] = bool(prop_uri and pattern.search(search_text))


@when("I build a flat tree with Properties section collapsed")
def when_build_collapsed(ctx):
    from ster.nav.logic import SECTION_PROPERTIES as SP

    ctx["flat"] = flatten_ontology_tree(ctx["taxonomy"], folded={SP})


@then('the search matches include the property node for "hasAge"')
def then_search_found_property(ctx):
    assert ctx["search_match"], "Search did not find the property node for hasAge"
