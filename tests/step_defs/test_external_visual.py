"""BDD step definitions for external ontology visual distinction."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/owl/external_visual.feature")

_FOAF_NS = "http://xmlns.com/foaf/0.1/"
_FOAF_PERSON = f"{_FOAF_NS}Person"
_KAI_NS = "http://example.org/kai#"
_KAI_PERSON = f"{_KAI_NS}Person"


def _make_taxonomy(class_uris=None, namespace_bindings=None):
    t = MagicMock()
    owl_classes = {}
    for uri in class_uris or []:
        cls = MagicMock()
        cls.sub_class_of = []
        owl_classes[uri] = cls
    t.owl_classes = owl_classes
    t.owl_individuals = {}
    t.namespace_bindings = namespace_bindings or {}
    return t


@pytest.fixture
def ctx():
    return {"taxonomy": None, "result": None}


# ── Background ────────────────────────────────────────────────────────────────


@given('a taxonomy with local class "kai:Person" and external "foaf:Person" in namespace_bindings')
def given_taxonomy_with_external(ctx):
    ctx["taxonomy"] = _make_taxonomy(
        class_uris=[_KAI_PERSON, _FOAF_PERSON],
        namespace_bindings={"foaf": _FOAF_NS},
    )


# ── is_external_uri scenarios ─────────────────────────────────────────────────


@when('I call is_external_uri for "foaf:Person"')
def when_check_foaf_external(ctx):
    from ster.ontology_imports import is_external_uri

    ctx["result"] = is_external_uri(_FOAF_PERSON, ctx["taxonomy"])


@when('I call is_external_uri for "kai:Person"')
def when_check_kai_external(ctx):
    from ster.ontology_imports import is_external_uri

    ctx["result"] = is_external_uri(_KAI_PERSON, ctx["taxonomy"])


@when('I call is_external_uri for "owl:Class"')
def when_check_owl_external(ctx):
    from ster.ontology_imports import is_external_uri

    ctx["result"] = is_external_uri("http://www.w3.org/2002/07/owl#Class", ctx["taxonomy"])


@then("the result is True")
def then_result_true(ctx):
    assert ctx["result"] is True


@then("the result is False")
def then_result_false(ctx):
    assert ctx["result"] is False


# ── prefix_label scenarios ────────────────────────────────────────────────────


@when('I call prefix_label for "foaf:Person"')
def when_prefix_label_foaf(ctx):
    from ster.ontology_imports import prefix_label

    ctx["result"] = prefix_label(_FOAF_PERSON, ctx["taxonomy"])


@then('the label is "foaf:Person"')
def then_label_foaf_person(ctx):
    assert ctx["result"] == "foaf:Person"


@given("a taxonomy with no namespace bindings")
def given_no_bindings(ctx):
    ctx["taxonomy"] = _make_taxonomy()


@when('I call prefix_label for "http://unknown.org/ns#Thing"')
def when_prefix_label_unknown(ctx):
    from ster.ontology_imports import prefix_label

    ctx["result"] = prefix_label("http://unknown.org/ns#Thing", ctx["taxonomy"])


@then('the label is "Thing"')
def then_label_thing(ctx):
    assert ctx["result"] == "Thing"


# ── build_graph scenarios ─────────────────────────────────────────────────────


@given('a taxonomy where "foaf:Person" is in owl_classes and namespace_bindings')
def given_taxonomy_with_foaf_class(ctx):
    from ster.model import RDFClass, Taxonomy

    t = Taxonomy()
    t.namespace_bindings = {"foaf": _FOAF_NS}
    t.owl_classes[_KAI_PERSON] = RDFClass(uri=_KAI_PERSON)
    t.owl_classes[_FOAF_PERSON] = RDFClass(uri=_FOAF_PERSON)
    ctx["taxonomy"] = t


@when("I call build_graph")
def when_build_graph(ctx):
    from ster.viz import build_graph

    ctx["result"] = build_graph(ctx["taxonomy"])


@then('the node for "foaf:Person" has type "external-class"')
def then_foaf_external_class(ctx):
    node = next(n for n in ctx["result"]["nodes"] if n["id"] == _FOAF_PERSON)
    assert node["type"] == "external-class"


@then('the node for "kai:Person" has type "class"')
def then_kai_class(ctx):
    node = next(n for n in ctx["result"]["nodes"] if n["id"] == _KAI_PERSON)
    assert node["type"] == "class"
