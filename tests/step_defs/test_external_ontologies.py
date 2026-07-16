"""BDD step definitions for adding and managing external ontologies."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/owl/external_ontologies.feature")

_FOAF_NS = "http://xmlns.com/foaf/0.1/"
_KAI_NS = "http://example.org/kai#"
_KAI_PERSON = f"{_KAI_NS}Person"


@pytest.fixture
def ctx():
    return {"taxonomy": None, "result": None}


# ── Common ontologies ─────────────────────────────────────────────────────────


@when("I retrieve the list of common ontologies")
def when_retrieve_common(ctx):
    from ster.ontology_imports import COMMON_ONTOLOGIES

    ctx["result"] = COMMON_ONTOLOGIES


@then("the list contains at least 4 entries")
def then_at_least_4(ctx):
    assert len(ctx["result"]) >= 4


@then("FOAF is in the list")
def then_foaf_in_list(ctx):
    assert any("FOAF" in entry[0] for entry in ctx["result"])


@then("Schema.org is in the list")
def then_schema_in_list(ctx):
    assert any("Schema" in entry[0] for entry in ctx["result"])


# ── add_namespace_to_taxonomy ─────────────────────────────────────────────────


@given("a taxonomy with no namespace bindings")  # type: ignore[no-redef]
def given_no_bindings_ext(ctx):
    from ster.model import Taxonomy

    ctx["taxonomy"] = Taxonomy()


@when('I add namespace "http://xmlns.com/foaf/0.1/" with prefix "foaf"')
def when_add_foaf_ns(ctx):
    from ster.ontology_imports import add_namespace_to_taxonomy

    add_namespace_to_taxonomy(_FOAF_NS, "foaf", ctx["taxonomy"])


@then('"foaf" maps to "http://xmlns.com/foaf/0.1/" in namespace_bindings')
def then_foaf_bound(ctx):
    assert ctx["taxonomy"].namespace_bindings.get("foaf") == _FOAF_NS


@given('a taxonomy with "foaf" already bound to "http://xmlns.com/foaf/0.1/"')
def given_foaf_already_bound(ctx):
    from ster.model import Taxonomy

    t = Taxonomy()
    t.namespace_bindings["foaf"] = _FOAF_NS
    ctx["taxonomy"] = t


@then("namespace_bindings has exactly 1 entry")
def then_one_binding(ctx):
    assert len(ctx["taxonomy"].namespace_bindings) == 1
