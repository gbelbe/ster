"""BDD step definitions for tests/features/owl/uri_quality.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when
from rdflib import RDF, Graph, URIRef
from rdflib.namespace import OWL, RDFS
from semanticlint.checks.base import CheckConfig, Severity

scenarios("../features/owl/uri_quality.feature")


@pytest.fixture
def ctx():
    return {"graph": None, "violations": None}


# ── Given ─────────────────────────────────────────────────────────────────────


@given('an OWL graph with a class whose URI starts with "file://"')
def given_file_class(ctx):
    g = Graph()
    g.add((URIRef("file:///Users/me/onto.owl#Person"), RDF.type, OWL.Class))
    ctx["graph"] = g
    ctx["subject"] = "file:///Users/me/onto.owl#Person"


@given('an OWL graph with a property whose URI starts with "file://"')
def given_file_property(ctx):
    g = Graph()
    g.add((URIRef("file:///Users/me/onto.owl#hasProp"), RDF.type, OWL.ObjectProperty))
    ctx["graph"] = g
    ctx["subject"] = "file:///Users/me/onto.owl#hasProp"


@given('an OWL graph with an individual whose URI starts with "file://"')
def given_file_individual(ctx):
    g = Graph()
    g.add((URIRef("file:///Users/me/onto.owl#alice"), RDF.type, OWL.NamedIndividual))
    ctx["graph"] = g
    ctx["subject"] = "file:///Users/me/onto.owl#alice"


@given('an OWL graph with a class whose URI starts with "https://"')
def given_https_class(ctx):
    g = Graph()
    g.add((URIRef("https://example.org/onto#Person"), RDF.type, OWL.Class))
    ctx["graph"] = g


@given('an OWL graph with a class whose URI starts with "urn:"')
def given_urn_class(ctx):
    g = Graph()
    g.add((URIRef("urn:example:Person"), RDF.type, OWL.Class))
    ctx["graph"] = g
    ctx["subject"] = "urn:example:Person"


@given("an OWL graph that only declares built-in OWL class relationships")
def given_builtin_only(ctx):
    g = Graph()
    g.add((OWL.Class, RDFS.subClassOf, RDFS.Resource))
    ctx["graph"] = g


@given('an OWL graph with 3 classes whose URIs start with "file://"')
def given_three_file_classes(ctx):
    g = Graph()
    for name in ("A", "B", "C"):
        g.add((URIRef(f"file:///Users/me/onto.owl#{name}"), RDF.type, OWL.Class))
    ctx["graph"] = g


@given('an OWL graph with 2 classes whose URIs start with "https://"')
def given_two_https_classes(ctx):
    g = Graph()
    for name in ("A", "B"):
        g.add((URIRef(f"https://example.org/onto#{name}"), RDF.type, OWL.Class))
    ctx["graph"] = g


# ── When ──────────────────────────────────────────────────────────────────────


@when("I run the URI quality checks")
def when_run_checks(ctx):
    from ster.ster_checks import FileSchemeURICheck, NonHTTPSchemeURICheck

    cfg = CheckConfig()
    violations = FileSchemeURICheck().run(ctx["graph"], cfg)
    violations += NonHTTPSchemeURICheck().run(ctx["graph"], cfg)
    ctx["violations"] = violations


# ── Then ──────────────────────────────────────────────────────────────────────


@then("a URI001 error is reported for that entity")
def then_uri001_error(ctx):
    v = ctx["violations"]
    assert any(x.check_id == "URI001" and x.severity == Severity.ERROR for x in v), (
        f"No URI001 error in {v}"
    )


@then("a URI002 warning is reported for that entity")
def then_uri002_warning(ctx):
    v = ctx["violations"]
    assert any(x.check_id == "URI002" and x.severity == Severity.WARNING for x in v), (
        f"No URI002 warning in {v}"
    )


@then("no URI001 or URI002 violation is reported")
def then_no_violation(ctx):
    v = ctx["violations"]
    assert not any(x.check_id in ("URI001", "URI002") for x in v), f"Unexpected violations: {v}"


@then("3 URI001 errors are reported")
def then_three_uri001(ctx):
    errors = [x for x in ctx["violations"] if x.check_id == "URI001"]
    assert len(errors) == 3, f"Expected 3 URI001 errors, got {len(errors)}: {errors}"
