"""BDD step definitions for tests/features/ui/new_owl_property.feature."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import Taxonomy
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
