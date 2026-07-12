"""BDD step definitions for tests/features/owl/class_properties.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.nav.logic import build_rdf_class_detail
from ster.operations import (
    add_owl_property,
    clear_property_values,
    delete_owl_property,
)

scenarios("../features/owl/class_properties.feature")

BASE = "https://example.org/onto/"


@pytest.fixture
def ctx():
    return {"taxonomy": None, "fields": None, "result": None, "error": None}


# ── Given steps ───────────────────────────────────────────────────────────────


@given(
    parsers.parse(
        'a taxonomy with class "{cls_name}" having property "{prop_name}" with domain "{domain_name}"'
    )
)
def given_taxonomy_class_with_property(ctx, cls_name, prop_name, domain_name):
    t = Taxonomy()
    t.owl_classes[BASE + cls_name] = RDFClass(uri=BASE + cls_name, labels=[Label("en", cls_name)])
    t.owl_properties[BASE + prop_name] = OWLProperty(
        uri=BASE + prop_name,
        labels=[Label("en", prop_name)],
        domains=[BASE + domain_name],
    )
    ctx["taxonomy"] = t
    ctx["class_uri"] = BASE + cls_name


@given(parsers.parse('a taxonomy with class "{cls_name}" and no properties'))
def given_taxonomy_class_no_properties(ctx, cls_name):
    t = Taxonomy()
    t.owl_classes[BASE + cls_name] = RDFClass(uri=BASE + cls_name, labels=[Label("en", cls_name)])
    ctx["taxonomy"] = t
    ctx["class_uri"] = BASE + cls_name


@given(parsers.parse('a taxonomy with class "{cls_name}" subClassOf "{parent_name}"'))
def given_subclass_taxonomy(ctx, cls_name, parent_name):
    t = Taxonomy()
    t.owl_classes[BASE + parent_name] = RDFClass(
        uri=BASE + parent_name, labels=[Label("en", parent_name)]
    )
    t.owl_classes[BASE + cls_name] = RDFClass(
        uri=BASE + cls_name,
        labels=[Label("en", cls_name)],
        sub_class_of=[BASE + parent_name],
    )
    ctx["taxonomy"] = t
    ctx["class_uri"] = BASE + cls_name


@given(parsers.parse('class "{cls_name}" has property "{prop_name}" with domain "{domain_name}"'))
def given_class_has_property_with_domain(ctx, cls_name, prop_name, domain_name):
    ctx["taxonomy"].owl_properties[BASE + prop_name] = OWLProperty(
        uri=BASE + prop_name,
        labels=[Label("en", prop_name)],
        domains=[BASE + domain_name],
    )


@given(parsers.parse('a 3-level class hierarchy with "{cls3}" under "{cls2}" under "{cls1}"'))
def given_three_level_chain(ctx, cls3, cls2, cls1):
    t = Taxonomy()
    for name in (cls1, cls2, cls3):
        t.owl_classes[BASE + name] = RDFClass(uri=BASE + name, labels=[Label("en", name)])
    t.owl_classes[BASE + cls2].sub_class_of = [BASE + cls1]
    t.owl_classes[BASE + cls3].sub_class_of = [BASE + cls2]
    ctx["taxonomy"] = t
    ctx["class_uri"] = BASE + cls3


@given(parsers.parse('"{cls1}" has class property "{p1}" and "{cls2}" has class property "{p2}"'))
def given_two_class_properties(ctx, cls1, p1, cls2, p2):
    for cls_name, prop_name in ((cls1, p1), (cls2, p2)):
        ctx["taxonomy"].owl_properties[BASE + prop_name] = OWLProperty(
            uri=BASE + prop_name,
            labels=[Label("en", prop_name)],
            domains=[BASE + cls_name],
        )


@given(parsers.parse('class "{cls_name}" has property "{prop_name}"'))
def given_class_has_property(ctx, cls_name, prop_name):
    ctx["taxonomy"].owl_properties[BASE + prop_name] = OWLProperty(
        uri=BASE + prop_name,
        labels=[Label("en", prop_name)],
        domains=[BASE + cls_name],
    )


@given(parsers.parse('a taxonomy with classes "{c}" "{a}" "{b}" "{base}"'))
def given_four_classes(ctx, c, a, b, base):
    t = Taxonomy()
    for name in (c, a, b, base):
        t.owl_classes[BASE + name] = RDFClass(uri=BASE + name, labels=[Label("en", name)])
    ctx["taxonomy"] = t
    ctx["class_uri"] = BASE + c


@given(parsers.parse('"{a}" subClassOf "{base}" and "{b}" subClassOf "{base2}"'))
def given_two_subclasses(ctx, a, base, b, base2):
    ctx["taxonomy"].owl_classes[BASE + a].sub_class_of = [BASE + base]
    ctx["taxonomy"].owl_classes[BASE + b].sub_class_of = [BASE + base2]


@given(parsers.parse('"{c}" subClassOf "{a}" and "{c2}" subClassOf "{b}"'))
def given_diamond_top(ctx, c, a, c2, b):
    uri = BASE + c
    existing = list(ctx["taxonomy"].owl_classes[uri].sub_class_of)
    ctx["taxonomy"].owl_classes[uri].sub_class_of = existing + [BASE + a, BASE + b]


@given(parsers.parse('a taxonomy with class "{child}" subClassOf "{parent}"'))
def given_child_parent(ctx, child, parent):
    t = Taxonomy()
    t.owl_classes[BASE + parent] = RDFClass(uri=BASE + parent, labels=[Label("en", parent)])
    t.owl_classes[BASE + child] = RDFClass(
        uri=BASE + child,
        labels=[Label("en", child)],
        sub_class_of=[BASE + parent],
    )
    ctx["taxonomy"] = t
    ctx["class_uri"] = BASE + child


@given(parsers.parse('class "{cls_name}" also has property "{prop_name}" as a direct domain'))
def given_direct_domain_added(ctx, cls_name, prop_name):
    prop = ctx["taxonomy"].owl_properties.get(BASE + prop_name)
    if prop and BASE + cls_name not in prop.domains:
        prop.domains.append(BASE + cls_name)


@given(parsers.parse('a taxonomy with class "{cls_name}" and class "{other}"'))
def given_two_classes(ctx, cls_name, other):
    t = Taxonomy()
    for name in (cls_name, other):
        t.owl_classes[BASE + name] = RDFClass(uri=BASE + name, labels=[Label("en", name)])
    ctx["taxonomy"] = t
    ctx["class_uri"] = BASE + cls_name


@given(parsers.parse('a taxonomy with property "{prop_name}" already declared'))
def given_property_already_exists(ctx, prop_name):
    t = Taxonomy()
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal", labels=[Label("en", "Animal")])
    t.owl_properties[BASE + prop_name] = OWLProperty(
        uri=BASE + prop_name, labels=[Label("en", prop_name)]
    )
    ctx["taxonomy"] = t
    ctx["class_uri"] = BASE + "Animal"


@given(parsers.parse('a taxonomy with property "{prop_name}" and no individuals using it'))
def given_property_no_individuals(ctx, prop_name):
    t = Taxonomy()
    t.owl_properties[BASE + prop_name] = OWLProperty(
        uri=BASE + prop_name, labels=[Label("en", prop_name)]
    )
    ctx["taxonomy"] = t
    ctx["prop_uri"] = BASE + prop_name


@given(parsers.parse('a taxonomy with property "{prop_name}"'))
def given_property_only(ctx, prop_name):
    t = Taxonomy()
    t.owl_properties[BASE + prop_name] = OWLProperty(
        uri=BASE + prop_name, labels=[Label("en", prop_name)]
    )
    ctx["taxonomy"] = t
    ctx["prop_uri"] = BASE + prop_name


@given(parsers.parse('individual "{ind_name}" has a value for property "{prop_name}"'))
def given_individual_has_value(ctx, ind_name, prop_name):
    prop_uri = BASE + prop_name
    ind = OWLIndividual(uri=BASE + ind_name, labels=[Label("en", ind_name)])
    ind.property_values = [(prop_uri, BASE + "SomeValue")]
    ctx["taxonomy"].owl_individuals[BASE + ind_name] = ind


@given(parsers.parse('a taxonomy with properties "{p1}" and "{p2}"'))
def given_two_properties(ctx, p1, p2):
    t = Taxonomy()
    for name in (p1, p2):
        t.owl_properties[BASE + name] = OWLProperty(uri=BASE + name, labels=[Label("en", name)])
    ctx["taxonomy"] = t
    ctx["prop_uri"] = BASE + p1
    ctx["prop2_uri"] = BASE + p2


@given(parsers.parse('individual "{ind_name}" has values for both "{p1}" and "{p2}"'))
def given_individual_has_two_values(ctx, ind_name, p1, p2):
    ind = OWLIndividual(uri=BASE + ind_name, labels=[Label("en", ind_name)])
    ind.property_values = [(BASE + p1, BASE + "Val1"), (BASE + p2, BASE + "Val2")]
    ctx["taxonomy"].owl_individuals[BASE + ind_name] = ind


# ── When steps ────────────────────────────────────────────────────────────────


@when(parsers.parse('I build the class detail for "{cls_name}"'))
def when_build_class_detail(ctx, cls_name):
    ctx["fields"] = build_rdf_class_detail(ctx["taxonomy"], BASE + cls_name, "en")


@when(
    parsers.parse(
        'I invoke add_owl_property with uri "{prop_name}" label "{label}" domain "{domain}"'
    )
)
def when_add_property_no_range(ctx, prop_name, label, domain):
    try:
        ctx["result"] = add_owl_property(
            ctx["taxonomy"], BASE + prop_name, "ObjectProperty", label, "en", BASE + domain
        )
        ctx["error"] = None
    except ValueError as e:
        ctx["result"] = None
        ctx["error"] = e


@when(
    parsers.parse(
        'I invoke add_owl_property with uri "{prop_name}" label "{label}" domain "{domain}" range "{range_cls}"'
    )
)
def when_add_property_with_range(ctx, prop_name, label, domain, range_cls):
    ctx["result"] = add_owl_property(
        ctx["taxonomy"],
        BASE + prop_name,
        "ObjectProperty",
        label,
        "en",
        BASE + domain,
        BASE + range_cls,
    )
    ctx["error"] = None


@when(parsers.parse('I invoke delete_owl_property for "{prop_name}"'))
def when_delete_property(ctx, prop_name):
    ctx["impacted"] = delete_owl_property(ctx["taxonomy"], BASE + prop_name)


@when(parsers.parse('I invoke clear_property_values for "{prop_name}"'))
def when_clear_property_values(ctx, prop_name):
    clear_property_values(ctx["taxonomy"], BASE + prop_name)


# ── Then steps ────────────────────────────────────────────────────────────────


@then(parsers.parse('the detail panel contains a "{section}" section'))
def then_panel_has_section(ctx, section):
    sep_labels = [f.display for f in ctx["fields"] if f.meta.get("type") == "separator"]
    assert section in sep_labels, f"Section {section!r} not found; got {sep_labels}"


@then(parsers.parse('"{prop_name}" appears as a direct property row'))
def then_direct_property_row(ctx, prop_name):
    nav_fields = [f for f in ctx["fields"] if f.meta.get("type") == "class_prop_nav"]
    assert any(f.meta.get("uri") == BASE + prop_name for f in nav_fields), (
        f"No class_prop_nav row for {prop_name}"
    )


@then(parsers.parse('the detail panel contains an "{action}" action row'))
def then_has_action_row(ctx, action):
    actions = [f for f in ctx["fields"] if f.meta.get("action") == action]
    assert actions, f"No action row with action={action!r}"


@then(parsers.parse('the detail panel shows "{prop_name}" as inherited from "{parent_name}"'))
def then_inherited_from(ctx, prop_name, parent_name):
    # Inherited rows are grouped under an "inherited from <parent>:" sub-header; the row
    # carries its parent in meta (the display is just the property label).
    inherited = [f for f in ctx["fields"] if f.meta.get("type") == "inherited_prop"]
    assert any(
        f.meta.get("uri") == BASE + prop_name and f.meta.get("parent_uri") == BASE + parent_name
        for f in inherited
    ), f"No inherited row for {prop_name} from {parent_name}"


@then("the inherited row has no edit action")
def then_inherited_not_editable(ctx):
    inherited = [f for f in ctx["fields"] if f.meta.get("type") == "inherited_prop"]
    assert inherited, "no inherited_prop fields found"
    for f in inherited:
        assert not f.editable, f"Field {f.key!r} is editable but should not be"


@then(parsers.parse('"{prop_name}" appears only once as an inherited property row'))
def then_no_duplicate_inherited(ctx, prop_name):
    inherited = [f for f in ctx["fields"] if f.meta.get("type") == "inherited_prop"]
    matching = [f for f in inherited if f.meta.get("uri") == BASE + prop_name]
    assert len(matching) == 1, f"Expected 1 inherited row for {prop_name}, got {len(matching)}"


@then(parsers.parse('"{prop_name}" does not appear as an inherited property row'))
def then_not_inherited(ctx, prop_name):
    inherited = [f for f in ctx["fields"] if f.meta.get("type") == "inherited_prop"]
    assert not any(f.meta.get("uri") == BASE + prop_name for f in inherited), (
        f"{prop_name} unexpectedly appears as inherited"
    )


@then(parsers.parse('a new OWLProperty "{prop_name}" exists in the taxonomy'))
def then_property_exists(ctx, prop_name):
    assert BASE + prop_name in ctx["taxonomy"].owl_properties


@then(parsers.parse('its domain is "{cls_name}"'))
def then_domain_is(ctx, cls_name):
    prop = ctx["result"]
    assert BASE + cls_name in prop.domains


@then(parsers.parse('the property "{prop_name}" has domain "{domain}" and range "{range_cls}"'))
def then_domain_and_range(ctx, prop_name, domain, range_cls):
    prop = ctx["taxonomy"].owl_properties[BASE + prop_name]
    assert BASE + domain in prop.domains
    assert BASE + range_cls in prop.ranges


@then("a ValueError is raised")
def then_value_error_raised(ctx):
    assert ctx.get("error") is not None, "Expected ValueError but none was raised"
    assert isinstance(ctx["error"], ValueError)


@then("the property is removed from the taxonomy")
def then_property_removed(ctx):
    prop_uri = ctx["prop_uri"]
    assert prop_uri not in ctx["taxonomy"].owl_properties


@then("the returned impacted list is empty")
def then_impacted_empty(ctx):
    assert ctx["impacted"] == []


@then(parsers.parse('the returned impacted list contains "{ind_name}"'))
def then_impacted_contains(ctx, ind_name):
    assert BASE + ind_name in ctx["impacted"]


@then(parsers.parse('"{ind_name}" has no property values for "{prop_name}"'))
def then_no_property_value(ctx, ind_name, prop_name):
    ind = ctx["taxonomy"].owl_individuals[BASE + ind_name]
    assert all(p != BASE + prop_name for p, _ in ind.property_values)


@then(parsers.parse('"{ind_name}" still has a property value for "{prop_name}"'))
def then_still_has_property_value(ctx, ind_name, prop_name):
    ind = ctx["taxonomy"].owl_individuals[BASE + ind_name]
    assert any(p == BASE + prop_name for p, _ in ind.property_values)
