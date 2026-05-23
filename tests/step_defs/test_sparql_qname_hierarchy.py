"""Step definitions for sparql_qname_hierarchy.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import RDFClass, Taxonomy
from ster.sparql_query import build_uri_index, qname_level_candidates

scenarios("../features/ui/sparql_qname_hierarchy.feature")

_NS = "https://ex.org/kai/"


@pytest.fixture
def ctx() -> dict:
    return {}


@given(
    'a taxonomy with namespace "kai" and a three-level class tree: Thing at root, Digital child of Thing, AnalogDevice at root, Switch child of Digital'
)
def given_hierarchy_taxonomy(ctx: dict) -> None:
    tax = Taxonomy()
    tax.namespace_bindings["kai"] = _NS
    tax.owl_classes[_NS + "Thing"] = RDFClass(uri=_NS + "Thing")
    tax.owl_classes[_NS + "Digital"] = RDFClass(uri=_NS + "Digital", sub_class_of=[_NS + "Thing"])
    tax.owl_classes[_NS + "Switch"] = RDFClass(uri=_NS + "Switch", sub_class_of=[_NS + "Digital"])
    tax.owl_classes[_NS + "AnalogDevice"] = RDFClass(uri=_NS + "AnalogDevice")
    ctx["idx"] = build_uri_index(tax)


@then('"Thing" appears in the "roots" bucket for "kai"')
def then_thing_in_roots(ctx: dict) -> None:
    assert "Thing" in ctx["idx"]["kai"]["roots"]


@then('"AnalogDevice" appears in the "roots" bucket for "kai"')
def then_analog_in_roots(ctx: dict) -> None:
    assert "AnalogDevice" in ctx["idx"]["kai"]["roots"]


@then('"Digital" does not appear in the "roots" bucket for "kai"')
def then_digital_not_in_roots(ctx: dict) -> None:
    assert "Digital" not in ctx["idx"]["kai"]["roots"]


@then('"Switch" does not appear in the "roots" bucket for "kai"')
def then_switch_not_in_roots(ctx: dict) -> None:
    assert "Switch" not in ctx["idx"]["kai"]["roots"]


@then('the children of "Thing" in "kai" contains "Digital"')
def then_thing_has_digital(ctx: dict) -> None:
    assert "Digital" in ctx["idx"]["kai"]["children"]["Thing"]


@then('the children of "Digital" in "kai" contains "Switch"')
def then_digital_has_switch(ctx: dict) -> None:
    assert "Switch" in ctx["idx"]["kai"]["children"]["Digital"]


@then('"AnalogDevice" has no children in "kai"')
def then_analog_no_children(ctx: dict) -> None:
    assert "AnalogDevice" not in ctx["idx"]["kai"]["children"]


@then('"Switch" has no children in "kai"')
def then_switch_no_children(ctx: dict) -> None:
    assert "Switch" not in ctx["idx"]["kai"]["children"]


@when('level candidates are requested for prefix "kai" at root with filter ""')
def when_root_no_filter(ctx: dict) -> None:
    ctx["results"] = qname_level_candidates(ctx["idx"], "kai", "", "", "class")


@when('level candidates are requested for prefix "kai" under parent "Thing" with filter ""')
def when_thing_children(ctx: dict) -> None:
    ctx["results"] = qname_level_candidates(ctx["idx"], "kai", "Thing", "", "class")


@when('level candidates are requested for prefix "kai" at root with filter "An"')
def when_root_filter_an(ctx: dict) -> None:
    ctx["results"] = qname_level_candidates(ctx["idx"], "kai", "", "An", "class")


@then('the candidates include "Thing" and "AnalogDevice"')
def then_thing_and_analog(ctx: dict) -> None:
    names = [n for n, _ in ctx["results"]]
    assert "Thing" in names
    assert "AnalogDevice" in names


@then('"Digital" is not in the candidates')
def then_digital_absent(ctx: dict) -> None:
    names = [n for n, _ in ctx["results"]]
    assert "Digital" not in names


@then('"Switch" is not in the candidates')
def then_switch_absent(ctx: dict) -> None:
    names = [n for n, _ in ctx["results"]]
    assert "Switch" not in names


@then('the candidates include "Digital"')
def then_digital_present(ctx: dict) -> None:
    names = [n for n, _ in ctx["results"]]
    assert "Digital" in names


@then('"Thing" is not in the candidates')
def then_thing_absent(ctx: dict) -> None:
    names = [n for n, _ in ctx["results"]]
    assert "Thing" not in names


@then('"Thing" is flagged has_children=True')
def then_thing_has_children(ctx: dict) -> None:
    by_name = dict(ctx["results"])
    assert by_name["Thing"] is True


@then('"AnalogDevice" is flagged has_children=False')
def then_analog_no_children_flag(ctx: dict) -> None:
    by_name = dict(ctx["results"])
    assert by_name["AnalogDevice"] is False


@then('the candidates include "AnalogDevice"')
def then_analog_present(ctx: dict) -> None:
    names = [n for n, _ in ctx["results"]]
    assert "AnalogDevice" in names


@then('"Thing" is not in the candidates')  # type: ignore[no-redef]
def then_thing_absent2(ctx: dict) -> None:
    names = [n for n, _ in ctx["results"]]
    assert "Thing" not in names
