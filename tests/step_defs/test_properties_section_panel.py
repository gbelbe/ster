"""BDD step definitions for tests/features/owl/properties_section_panel.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import Label, OWLProperty, Taxonomy
from ster.nav.logic import build_properties_section_fields

scenarios("../features/owl/properties_section_panel.feature")

BASE = "https://example.org/onto/"


@pytest.fixture
def ctx():
    return {"taxonomy": None, "fields": None}


# ── Given ─────────────────────────────────────────────────────────────────────


@given("an OWL taxonomy with 2 properties")
def given_two_props(ctx):
    t = Taxonomy()
    for name in ("propA", "propB"):
        t.owl_properties[BASE + name] = OWLProperty(uri=BASE + name, labels=[Label("en", name)])
    ctx["taxonomy"] = t


@given("an OWL taxonomy with 1 data property and 1 object property")
def given_data_and_object(ctx):
    t = Taxonomy()
    t.owl_properties[BASE + "dp"] = OWLProperty(
        uri=BASE + "dp", prop_type="DatatypeProperty", labels=[Label("en", "dp")]
    )
    t.owl_properties[BASE + "op"] = OWLProperty(
        uri=BASE + "op", prop_type="ObjectProperty", labels=[Label("en", "op")]
    )
    ctx["taxonomy"] = t


@given("an OWL taxonomy where all 2 properties have labels")
def given_all_labeled(ctx):
    t = Taxonomy()
    for name in ("propA", "propB"):
        t.owl_properties[BASE + name] = OWLProperty(uri=BASE + name, labels=[Label("en", name)])
    ctx["taxonomy"] = t


@given("an OWL taxonomy where 1 of 2 properties has a label")
def given_partial_labeled(ctx):
    t = Taxonomy()
    t.owl_properties[BASE + "propA"] = OWLProperty(
        uri=BASE + "propA", labels=[Label("en", "propA")]
    )
    t.owl_properties[BASE + "propB"] = OWLProperty(uri=BASE + "propB", labels=[])
    ctx["taxonomy"] = t


@given("an OWL taxonomy where 1 of 2 properties has a domain")
def given_partial_domain(ctx):
    t = Taxonomy()
    t.owl_properties[BASE + "propA"] = OWLProperty(
        uri=BASE + "propA", labels=[Label("en", "propA")], domains=[BASE + "SomeClass"]
    )
    t.owl_properties[BASE + "propB"] = OWLProperty(
        uri=BASE + "propB", labels=[Label("en", "propB")]
    )
    ctx["taxonomy"] = t


@given("an OWL taxonomy where 1 of 2 properties has a range")
def given_partial_range(ctx):
    t = Taxonomy()
    t.owl_properties[BASE + "propA"] = OWLProperty(
        uri=BASE + "propA", labels=[Label("en", "propA")], ranges=[BASE + "SomeClass"]
    )
    t.owl_properties[BASE + "propB"] = OWLProperty(
        uri=BASE + "propB", labels=[Label("en", "propB")]
    )
    ctx["taxonomy"] = t


@given('an OWL taxonomy with properties "zebra" and "apple"')
def given_zebra_apple(ctx):
    t = Taxonomy()
    for name in ("zebra", "apple"):
        t.owl_properties[BASE + name] = OWLProperty(uri=BASE + name, labels=[Label("en", name)])
    ctx["taxonomy"] = t


@given("an OWL taxonomy with no properties")
def given_no_props(ctx):
    ctx["taxonomy"] = Taxonomy()


# ── When ──────────────────────────────────────────────────────────────────────


@when("I build the properties section fields")
def when_build(ctx):
    ctx["fields"] = build_properties_section_fields(ctx["taxonomy"], lang="en")


# ── Then ──────────────────────────────────────────────────────────────────────


def _stat_values(fields):
    return [f.value for f in fields if f.meta.get("type") == "stat"]


def _nav_fields(fields):
    return [f for f in fields if f.meta.get("type") == "navigate_property"]


@then("a stat field shows count 2")
def then_count_2(ctx):
    assert "2" in _stat_values(ctx["fields"]), f"No stat '2' in {_stat_values(ctx['fields'])}"


@then("a stat field shows count 0")
def then_count_0(ctx):
    assert "0" in _stat_values(ctx["fields"]), f"No stat '0' in {_stat_values(ctx['fields'])}"


@then("a stat field shows data count 1")
def then_data_1(ctx):
    stats = _stat_values(ctx["fields"])
    assert any("1" in s and "data" in s.lower() or s == "1" for s in stats), (
        f"No data count 1 in {stats}"
    )


@then("a stat field shows object count 1")
def then_obj_1(ctx):
    stats = _stat_values(ctx["fields"])
    assert any("1" in s and "object" in s.lower() or s == "1" for s in stats), (
        f"No object count 1 in {stats}"
    )


@then("a stat field shows label coverage 100")
def then_lbl_100(ctx):
    stats = _stat_values(ctx["fields"])
    assert any("100%" in s for s in stats), f"No 100% in {stats}"


@then("a stat field shows label coverage 50")
def then_lbl_50(ctx):
    stats = _stat_values(ctx["fields"])
    assert any("50%" in s for s in stats), f"No 50% in {stats}"


@then("a stat field shows domain coverage 50")
def then_domain_50(ctx):
    stats = _stat_values(ctx["fields"])
    assert any("50%" in s for s in stats), f"No 50% in {stats}"


@then("a stat field shows range coverage 50")
def then_range_50(ctx):
    stats = _stat_values(ctx["fields"])
    assert any("50%" in s for s in stats), f"No 50% in {stats}"


@then("2 fields have meta type navigate_property")
def then_two_nav(ctx):
    assert len(_nav_fields(ctx["fields"])) == 2


@then("0 fields have meta type navigate_property")
def then_zero_nav(ctx):
    assert len(_nav_fields(ctx["fields"])) == 0


@then("each navigate_property field has a uri key in its meta")
def then_nav_has_uri(ctx):
    for f in _nav_fields(ctx["fields"]):
        assert "uri" in f.meta, f"Missing 'uri' in meta for {f.key}"


@then('the navigate_property items appear in order "apple" then "zebra"')
def then_apple_before_zebra(ctx):
    nav = _nav_fields(ctx["fields"])
    labels = [f.display for f in nav]
    assert labels.index("apple") < labels.index("zebra"), f"Order was {labels}"


@then("all navigate_property fields are not editable")
def then_not_editable(ctx):
    for f in _nav_fields(ctx["fields"]):
        assert not f.editable, f"Field {f.key} is editable"
