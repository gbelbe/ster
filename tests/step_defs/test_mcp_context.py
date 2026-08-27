"""Step definitions for the read-only MCP context feature."""

from __future__ import annotations

import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import mcp_server as ms
from ster.model import Concept, Label, LabelType, RDFClass, Taxonomy

scenarios("../features/mcp/mcp_context.feature")

NS = "https://example.org/zoo#"


def _lbl(value: str, lang: str = "en") -> Label:
    return Label(lang=lang, value=value, type=LabelType.PREF)


@pytest.fixture
def ctx(tmp_path) -> dict:
    return {"tmp_path": tmp_path, "selection": None, "reply": None}


@given("a zoo taxonomy open in ster")
def given_zoo(ctx):
    ttl = ctx["tmp_path"] / "zoo.ttl"
    ttl.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        f'<{NS}Enclosure> a owl:Class ; rdfs:label "Enclosure"@en .\n',
        encoding="utf-8",
    )
    tax = Taxonomy()
    tax.file_path = ttl
    tax.concepts[NS + "Animal"] = Concept(
        uri=NS + "Animal", labels=[_lbl("Animal")], narrower=[NS + "Mammal"]
    )
    tax.concepts[NS + "Mammal"] = Concept(
        uri=NS + "Mammal",
        labels=[_lbl("Mammal")],
        broader=[NS + "Animal"],
        narrower=[NS + "Cat", NS + "Dog"],
    )
    tax.concepts[NS + "Dog"] = Concept(
        uri=NS + "Dog", labels=[_lbl("Dog")], broader=[NS + "Mammal"]
    )
    tax.concepts[NS + "Cat"] = Concept(
        uri=NS + "Cat", labels=[_lbl("Cat")], broader=[NS + "Mammal"]
    )
    tax.owl_classes[NS + "Enclosure"] = RDFClass(uri=NS + "Enclosure", labels=[_lbl("Enclosure")])
    ctx["tax"] = tax


SKOS_TTL = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
<{NS}Animal> a skos:Concept ; skos:prefLabel "Animal"@en, "Animal"@fr .
<{NS}Mammal> a skos:Concept ; skos:prefLabel "Mammal"@en, "Mammifère"@fr ;
    skos:broader <{NS}Animal> .
"""

RDFS_ONLY_TTL = f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{NS}Enclosure> a owl:Class ; rdfs:label "Enclosure"@en .
<{NS}Aviary> a owl:Class ; rdfs:label "Aviary"@en ; rdfs:subClassOf <{NS}Enclosure> .
"""


def _retarget(ctx, ttl_text: str) -> None:
    """Point the open taxonomy at a purpose-built file for the vocabulary probe.

    The shared Background keeps its concepts in memory rather than on disk;
    get_vocabulary reads the file, so these scenarios need their own source.
    """
    path = ctx["tmp_path"] / "vocab.ttl"
    path.write_text(ttl_text, encoding="utf-8")
    ctx["tax"].file_path = path


@given("a SKOS file whose labels carry English and French")
def given_skos_file(ctx):
    _retarget(ctx, SKOS_TTL)


@given("an OWL file whose labels use only rdfs:label")
def given_rdfs_only_file(ctx):
    _retarget(ctx, RDFS_ONLY_TTL)


@given(parsers.parse('the user has focused the concept "{name}"'))
def given_focused(ctx, name):
    ctx["selection"] = NS + name


@given("no entity is focused")
def given_nothing_focused(ctx):
    ctx["selection"] = None


def _rpc(ctx, method: str, params: dict | None = None):
    ctx["reply"] = ms.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        ctx["tax"],
        ctx["selection"],
    )
    return ctx["reply"]


def _payload(ctx):
    return json.loads(ctx["reply"]["result"]["content"][0]["text"])


@when(parsers.parse('the agent calls "{tool}"'))
def when_call_tool(ctx, tool):
    _rpc(ctx, "tools/call", {"name": tool, "arguments": {}})


@when(parsers.parse('the agent asks for the entity "{name}"'))
def when_get_entity(ctx, name):
    _rpc(ctx, "tools/call", {"name": "get_entity", "arguments": {"uri": NS + name}})


@when(parsers.parse('the agent searches for "{query}"'))
def when_search(ctx, query):
    _rpc(ctx, "tools/call", {"name": "search_entities", "arguments": {"query": query}})


@when(parsers.parse('the agent runs the SPARQL query "{query}"'))
def when_sparql(ctx, query):
    _rpc(ctx, "tools/call", {"name": "run_sparql", "arguments": {"query": query}})


@when("the agent lists the tools")
def when_list_tools(ctx):
    _rpc(ctx, "tools/list")


@then(parsers.parse('the focused entity is labelled "{label}"'))
def then_focused_label(ctx, label):
    assert _payload(ctx)["focused"]["label"] == label


@then(parsers.parse('the ancestor chain is "{chain}"'))
def then_ancestors(ctx, chain):
    got = [a["label"] for a in _payload(ctx)["ancestors"]]
    assert got == [p.strip() for p in chain.split(",")]


@then("no entity is reported as focused")
def then_no_focus(ctx):
    assert _payload(ctx)["focused"] is None


@then(parsers.parse("the overview counts {count:d} concepts"))
def then_overview_counts(ctx, count):
    payload = _payload(ctx)
    overview = payload.get("overview", payload)
    assert overview["counts"]["concepts"] == count


@then(parsers.parse('the entity is labelled "{label}"'))
def then_entity_label(ctx, label):
    assert _payload(ctx)["label"] == label


@then(parsers.parse('its children are "{children}"'))
def then_children(ctx, children):
    got = sorted(c["label"] for c in _payload(ctx)["children"])
    assert got == sorted(p.strip() for p in children.split(","))


@then(parsers.parse('the search returns "{label}"'))
def then_search_returns(ctx, label):
    assert [h["label"] for h in _payload(ctx)] == [label]


@then(parsers.parse("the query returns {count:d} row"))
def then_query_rows(ctx, count):
    assert _payload(ctx)["row_count"] == count


@then("the query is refused as read-only")
def then_refused(ctx):
    assert _payload(ctx)["error"] == "read_only"


@then(parsers.parse('the tool list includes "{name}"'))
def then_tool_listed(ctx, name):
    assert name in {t["name"] for t in ctx["reply"]["result"]["tools"]}


@when("the agent initializes the session")
def when_initialize(ctx):
    _rpc(ctx, "initialize")


@then(parsers.parse('the server instructions mention "{needle}"'))
def then_instructions_mention(ctx, needle):
    assert needle in ctx["reply"]["result"]["instructions"]


@then(parsers.parse('the vocabulary reports the shape "{shape}"'))
def then_vocab_shape(ctx, shape):
    assert _payload(ctx)["shape"] == shape


@then(parsers.parse('the vocabulary reports "{term}" as a label predicate'))
def then_vocab_label_predicate(ctx, term):
    assert term in _payload(ctx)["label_predicates"]


@then(parsers.parse('the vocabulary does not report "{term}" as a label predicate'))
def then_vocab_not_label_predicate(ctx, term):
    assert term not in _payload(ctx)["label_predicates"]


@then(parsers.parse('the vocabulary reports "{term}" as a hierarchy predicate'))
def then_vocab_hierarchy_predicate(ctx, term):
    assert term in _payload(ctx)["hierarchy_predicates"]


@then(parsers.parse('the vocabulary lists the language "{lang}"'))
def then_vocab_language(ctx, lang):
    assert lang in _payload(ctx)["languages"]
