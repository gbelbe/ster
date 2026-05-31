"""BDD step definitions for tests/features/ui/new_owl_property.feature."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Label, OWLProperty, RDFClass, Taxonomy
from ster.nav.logic import build_properties_section_fields

scenarios("../features/ui/new_owl_property.feature")


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {"fields": []}


@given("a taxonomy with no OWL properties")
def empty_taxonomy(ctx: dict[str, Any]) -> None:
    ctx["taxonomy"] = Taxonomy()


@when("I build the properties section detail panel")
def build_panel(ctx: dict[str, Any]) -> None:
    ctx["fields"] = build_properties_section_fields(ctx["taxonomy"], lang="en")


def _action_field(ctx: dict[str, Any]):
    matches = [f for f in ctx["fields"] if f.meta.get("action") == "create_owl_property"]
    assert matches, "No create_owl_property action field found"
    return matches[0]


@then('the panel contains a "create_owl_property" action field')
def panel_has_action(ctx: dict[str, Any]) -> None:
    _action_field(ctx)


@then('the action field key is "action:create_owl_property"')
def action_field_key(ctx: dict[str, Any]) -> None:
    assert _action_field(ctx).key == "action:create_owl_property"


@then('the action field meta type is "action_add"')
def action_field_meta_type(ctx: dict[str, Any]) -> None:
    assert _action_field(ctx).meta.get("type") == "action_add"


# ── commit dispatch tests ─────────────────────────────────────────────────────


@given(parsers.parse('a taxonomy with ontology URI "{uri}"'))
def given_taxonomy_with_ontology_uri(ctx: dict[str, Any], uri: str) -> None:
    t = Taxonomy()
    t.ontology_uri = uri
    ctx["taxonomy"] = t


@given(parsers.parse('a taxonomy with OWL class "{cls}"'))
def given_taxonomy_with_class(ctx: dict[str, Any], cls: str) -> None:
    t = Taxonomy()
    t.owl_classes[cls] = RDFClass(uri=cls, labels=[Label("en", cls.rsplit("#", 1)[-1])])
    ctx["taxonomy"] = t


@when(parsers.parse('I commit a new_owl_property_uri field with value "{uri}"'))
def when_commit_new_property(ctx: dict[str, Any], uri: str) -> None:
    t: Taxonomy = ctx["taxonomy"]
    if uri and uri not in t.owl_properties:
        t.owl_properties[uri] = OWLProperty(uri=uri)
    ctx["result_uri"] = uri


@when(
    parsers.parse(
        'I commit a new_owl_class_property_uri field with value "{uri}" and class_uri "{class_uri}"'
    )
)
def when_commit_class_property(ctx: dict[str, Any], uri: str, class_uri: str) -> None:
    from ster.operations import add_owl_property

    t: Taxonomy = ctx["taxonomy"]
    if uri not in t.owl_properties:
        add_owl_property(
            t,
            uri,
            "ObjectProperty",
            uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1],
            "en",
            class_uri if class_uri else None,
        )
    ctx["result_uri"] = uri


@then(parsers.parse('the taxonomy contains property "{uri}"'))
def then_property_exists(ctx: dict[str, Any], uri: str) -> None:
    assert uri in ctx["taxonomy"].owl_properties, (
        f"Property {uri!r} not found; have: {list(ctx['taxonomy'].owl_properties)}"
    )


@then(parsers.parse('property "{uri}" has domain "{domain}"'))
def then_property_has_domain(ctx: dict[str, Any], uri: str, domain: str) -> None:
    prop = ctx["taxonomy"].owl_properties[uri]
    assert domain in prop.domains, f"Expected domain {domain!r} in {prop.domains}"
