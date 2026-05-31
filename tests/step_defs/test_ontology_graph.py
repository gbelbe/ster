"""BDD step definitions for tests/features/owl/ontology_graph.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.viz_vowl import build_focused_vowl_graph, build_query_result_graph, build_vowl_graph

scenarios("../features/owl/ontology_graph.feature")

NS = "https://example.org/onto#"
OWL_THING = "http://www.w3.org/2002/07/owl#Thing"


def _uri(name: str) -> str:
    return NS + name


@pytest.fixture
def ctx() -> dict:
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given("an empty taxonomy")
def given_empty(ctx: dict) -> None:
    ctx["tax"] = Taxonomy()


@given(parsers.parse('a taxonomy with OWL class "{cls}"'))
def given_one_class(ctx: dict, cls: str) -> None:
    tax = Taxonomy()
    tax.owl_classes[_uri(cls)] = RDFClass(uri=_uri(cls), labels=[Label("en", cls)])
    ctx["tax"] = tax


@given(parsers.parse('a taxonomy with OWL classes "{a}" and "{b}"'))
def given_two_classes(ctx: dict, a: str, b: str) -> None:
    tax = Taxonomy()
    for name in (a, b):
        tax.owl_classes[_uri(name)] = RDFClass(uri=_uri(name), labels=[Label("en", name)])
    ctx["tax"] = tax


@given(parsers.parse('a taxonomy with OWL classes "{a}", "{b}", and "{c}"'))
def given_three_classes(ctx: dict, a: str, b: str, c: str) -> None:
    tax = Taxonomy()
    for name in (a, b, c):
        tax.owl_classes[_uri(name)] = RDFClass(uri=_uri(name), labels=[Label("en", name)])
    ctx["tax"] = tax


@given(parsers.parse('a taxonomy with OWL class "{cls}" and individual "{ind}" typed as "{cls2}"'))
def given_class_and_individual(ctx: dict, cls: str, ind: str, cls2: str) -> None:
    tax = Taxonomy()
    tax.owl_classes[_uri(cls)] = RDFClass(uri=_uri(cls), labels=[Label("en", cls)])
    tax.owl_individuals[_uri(ind)] = OWLIndividual(
        uri=_uri(ind), labels=[Label("en", ind)], types=[_uri(cls2)]
    )
    ctx["tax"] = tax


@given(parsers.parse('a taxonomy with OWL classes "{a}" and "{b}" subclass of "{a2}"'))
def given_two_with_subclass(ctx: dict, a: str, b: str, a2: str) -> None:
    tax = Taxonomy()
    tax.owl_classes[_uri(a)] = RDFClass(uri=_uri(a), labels=[Label("en", a)])
    tax.owl_classes[_uri(b)] = RDFClass(
        uri=_uri(b), labels=[Label("en", b)], sub_class_of=[_uri(a2)]
    )
    ctx["tax"] = tax


@given(parsers.parse('a taxonomy with OWL classes "{a}", "{b}" subclass of "{c}", "{d}"'))
def given_three_classes_with_sub(ctx: dict, a: str, b: str, c: str, d: str) -> None:
    tax = Taxonomy()
    tax.owl_classes[_uri(a)] = RDFClass(uri=_uri(a), labels=[Label("en", a)])
    tax.owl_classes[_uri(b)] = RDFClass(
        uri=_uri(b), labels=[Label("en", b)], sub_class_of=[_uri(c)]
    )
    tax.owl_classes[_uri(d)] = RDFClass(uri=_uri(d), labels=[Label("en", d)])
    ctx["tax"] = tax


@given(
    parsers.parse(
        'a taxonomy with OWL classes "{a}", "{b}" subclass of "{c}", "{d}" subclass of "{e}"'
    )
)
def given_three_with_two_subs(ctx: dict, a: str, b: str, c: str, d: str, e: str) -> None:
    tax = Taxonomy()
    tax.owl_classes[_uri(a)] = RDFClass(uri=_uri(a), labels=[Label("en", a)])
    tax.owl_classes[_uri(b)] = RDFClass(
        uri=_uri(b), labels=[Label("en", b)], sub_class_of=[_uri(c)]
    )
    tax.owl_classes[_uri(d)] = RDFClass(
        uri=_uri(d), labels=[Label("en", d)], sub_class_of=[_uri(e)]
    )
    ctx["tax"] = tax


@given(parsers.parse('a taxonomy with "{a}", "{b}" subclass of "{c}", "{d}" subclass of "{e}"'))
def given_transitive_chain(ctx: dict, a: str, b: str, c: str, d: str, e: str) -> None:
    tax = Taxonomy()
    tax.owl_classes[_uri(a)] = RDFClass(uri=_uri(a), labels=[Label("en", a)])
    tax.owl_classes[_uri(b)] = RDFClass(
        uri=_uri(b), labels=[Label("en", b)], sub_class_of=[_uri(c)]
    )
    tax.owl_classes[_uri(d)] = RDFClass(
        uri=_uri(d), labels=[Label("en", d)], sub_class_of=[_uri(e)]
    )
    ctx["tax"] = tax


@given(parsers.parse('"{child}" is a subclass of "{parent}"'))
def given_subclass(ctx: dict, child: str, parent: str) -> None:
    tax: Taxonomy = ctx["tax"]
    if _uri(child) not in tax.owl_classes:
        tax.owl_classes[_uri(child)] = RDFClass(uri=_uri(child), labels=[Label("en", child)])
    tax.owl_classes[_uri(child)].sub_class_of.append(_uri(parent))


@given(parsers.parse('an object property "{prop}" from "{domain}" to "{range_}"'))
def given_object_property(ctx: dict, prop: str, domain: str, range_: str) -> None:
    tax: Taxonomy = ctx["tax"]
    tax.owl_properties[_uri(prop)] = OWLProperty(
        uri=_uri(prop),
        labels=[Label("en", prop)],
        prop_type="ObjectProperty",
        domains=[_uri(domain)],
        ranges=[_uri(range_)],
    )


@given(
    parsers.parse(
        'a taxonomy with OWL class "{cls}" and a datatype property "{prop}" from "{domain}"'
    )
)
def given_datatype_property(ctx: dict, cls: str, prop: str, domain: str) -> None:
    tax = Taxonomy()
    tax.owl_classes[_uri(cls)] = RDFClass(uri=_uri(cls), labels=[Label("en", cls)])
    tax.owl_properties[_uri(prop)] = OWLProperty(
        uri=_uri(prop),
        labels=[Label("en", prop)],
        prop_type="DatatypeProperty",
        domains=[_uri(domain)],
        ranges=["http://www.w3.org/2001/XMLSchema#string"],
    )
    ctx["tax"] = tax


@given(parsers.parse('a taxonomy with OWL class "{cls}" whose parent is "owl:Thing"'))
def given_owl_thing_parent(ctx: dict, cls: str) -> None:
    tax = Taxonomy()
    tax.owl_classes[_uri(cls)] = RDFClass(
        uri=_uri(cls), labels=[Label("en", cls)], sub_class_of=[OWL_THING]
    )
    ctx["tax"] = tax


# ── When ──────────────────────────────────────────────────────────────────────


@when("I build the full ontology graph")
def when_build_full(ctx: dict) -> None:
    ctx["result"] = build_vowl_graph(ctx["tax"])


@when(parsers.parse('I build a focused graph on "{root}"'))
def when_build_focused(ctx: dict, root: str) -> None:
    ctx["result"] = build_focused_vowl_graph(ctx["tax"], _uri(root))


@when(parsers.parse('I build a query result graph matching only "{cls}"'))
def when_build_query_result(ctx: dict, cls: str) -> None:
    ctx["result"] = build_query_result_graph(ctx["tax"], {_uri(cls)})


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse("the graph has {n:d} nodes"))
def then_node_count(ctx: dict, n: int) -> None:
    assert len(ctx["result"]["nodes"]) == n


@then(parsers.parse("the graph has {n:d} edges"))
def then_edge_count(ctx: dict, n: int) -> None:
    assert len(ctx["result"]["edges"]) == n


@then(parsers.parse('the graph layout is "{layout}"'))
def then_layout(ctx: dict, layout: str) -> None:
    assert ctx["result"]["layout"] == layout


@then(parsers.parse('the graph contains a node for "{name}" of type "{ntype}"'))
def then_node_type(ctx: dict, name: str, ntype: str) -> None:
    nodes = {n["id"]: n for n in ctx["result"]["nodes"]}
    assert _uri(name) in nodes, f"{_uri(name)!r} not in {list(nodes)}"
    assert nodes[_uri(name)]["type"] == ntype


@then(parsers.parse('the graph contains a node for "{name}"'))
def then_node_present(ctx: dict, name: str) -> None:
    ids = {n["id"] for n in ctx["result"]["nodes"]}
    assert _uri(name) in ids, f"{_uri(name)!r} not found; ids={ids}"


@then(parsers.parse('the graph does not contain a node for "{name}"'))
def then_node_absent(ctx: dict, name: str) -> None:
    ids = {n["id"] for n in ctx["result"]["nodes"]}
    assert _uri(name) not in ids


@then(parsers.parse('the graph contains a "{etype}" edge from "{src}" to "{tgt}"'))
def then_edge_src_tgt(ctx: dict, etype: str, src: str, tgt: str) -> None:
    found = [
        e
        for e in ctx["result"]["edges"]
        if e["type"] == etype and e["source"] == _uri(src) and e["target"] == _uri(tgt)
    ]
    assert found, f"No {etype} edge from {src!r} to {tgt!r}; edges={ctx['result']['edges']}"


@then(parsers.parse('the graph contains an "{etype}" edge from "{src}" to "{tgt}"'))
def then_edge_src_tgt_indef(ctx: dict, etype: str, src: str, tgt: str) -> None:
    then_edge_src_tgt(ctx, etype, src, tgt)


@then(parsers.parse('that edge has label "{label}"'))
def then_last_edge_label(ctx: dict, label: str) -> None:
    # Checks the most recently matched edge type has the given label
    found = [e for e in ctx["result"]["edges"] if e.get("label") == label]
    assert found, f"No edge with label {label!r}"


@then(parsers.parse('the graph contains an "{etype}" edge from "{src}"'))
def then_edge_from(ctx: dict, etype: str, src: str) -> None:
    found = [e for e in ctx["result"]["edges"] if e["type"] == etype and e["source"] == _uri(src)]
    assert found, f"No {etype} edge from {src!r}"


@then(parsers.parse('the graph contains a "{etype}" edge from "{src}"'))
def then_edge_from_def(ctx: dict, etype: str, src: str) -> None:
    then_edge_from(ctx, etype, src)


@then(parsers.parse('the graph contains no "{etype}" edge to "{tgt}"'))
def then_no_edge_to(ctx: dict, etype: str, tgt: str) -> None:
    bad = [e for e in ctx["result"]["edges"] if e["type"] == etype and e["target"] == tgt]
    assert not bad, f"Unexpected {etype} edge to {tgt!r}"
