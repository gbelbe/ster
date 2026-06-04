"""BDD step definitions for editing the ontology domain and prefix."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy

scenarios("../features/owl/edit_domain_and_prefix.feature")


@pytest.fixture
def ctx():
    return {}


@given(parsers.parse('an ontology based at "{ont}" with prefix "{prefix}" and 4 local entities'))
def given_ontology(ctx, ont, prefix):
    t = Taxonomy()
    t.ontology_uri = ont
    t.namespace_bindings[prefix] = ont + "#"
    for name in ("Animal", "Dog"):
        u = f"{ont}#{name}"
        t.owl_classes[u] = RDFClass(uri=u, labels=[Label("en", name)])
    rex = f"{ont}#Rex"
    t.owl_individuals[rex] = OWLIndividual(
        uri=rex, labels=[Label("en", "Rex")], types=[f"{ont}#Dog"]
    )
    p = f"{ont}#hasMaster"
    t.owl_properties[p] = OWLProperty(uri=p, labels=[Label("en", "hasMaster")])
    ctx["tax"] = t
    ctx["entities_before"] = set(t.owl_classes) | set(t.owl_individuals) | set(t.owl_properties)


@when(parsers.parse('I change the ontology domain to "{domain}"'))
def when_change_domain(ctx, domain):
    from ster.operations import rename_ontology_domain

    rename_ontology_domain(ctx["tax"], domain)


@when(parsers.parse('I count changes for a domain change to "{domain}"'))
def when_count_domain(ctx, domain):
    from ster.operations import count_domain_rename_changes

    _, _, ctx["count"] = count_domain_rename_changes(ctx["tax"], domain)


@when(parsers.parse('I rename the prefix "{old}" to "{new}"'))
def when_rename_prefix(ctx, old, new):
    from ster.operations import rename_prefix

    ctx["count"] = rename_prefix(ctx["tax"], old, new)


@then(parsers.parse('the ontology URI is "{uri}"'))
def then_ontology_uri(ctx, uri):
    assert ctx["tax"].ontology_uri == uri


@then(parsers.parse('all 4 local entities are under "{base}"'))
def then_entities_under(ctx, base):
    t = ctx["tax"]
    allu = list(t.owl_classes) + list(t.owl_individuals) + list(t.owl_properties)
    assert len(allu) == 4
    assert all(u.startswith(base) for u in allu)


@then(parsers.parse("the change count is {n:d}"))
def then_change_count(ctx, n):
    assert ctx["count"] == n


@then(parsers.parse('the prefix bound to the ontology is "{prefix}"'))
def then_prefix_bound(ctx, prefix):
    from ster.operations import ontology_prefix

    assert ontology_prefix(ctx["tax"]) == prefix


@then("the entity URIs are unchanged")
def then_uris_unchanged(ctx):
    t = ctx["tax"]
    now = set(t.owl_classes) | set(t.owl_individuals) | set(t.owl_properties)
    assert now == ctx["entities_before"]


@then(parsers.parse("the prefix rename count is {n:d}"))
def then_prefix_count(ctx, n):
    assert ctx["count"] == n
