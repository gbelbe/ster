"""BDD step definitions for ontology import discovery."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/owl/ontology_imports.feature")

_FOAF_NS = "http://xmlns.com/foaf/0.1/"
_FOAF_PERSON = f"{_FOAF_NS}Person"
_FOAF_AGENT = f"{_FOAF_NS}Agent"
_FOAF_KNOWS = f"{_FOAF_NS}knows"
_SCHEMA_NS = "https://schema.org/"
_SCHEMA_PERSON = f"{_SCHEMA_NS}Person"
_KAI_NS = "http://example.org/kai#"
_KAI_PERSON = f"{_KAI_NS}Person"
_KAI_KNOWS = f"{_KAI_NS}knows"

_FOAF_RDF = """\
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .

foaf:Person a owl:Class .
foaf:Agent  a owl:Class .
foaf:knows  a owl:ObjectProperty ;
    rdfs:domain foaf:Person ;
    rdfs:label  "knows" .
"""


def _make_taxonomy(
    class_uris=None,
    subclass_of=None,
    individual_types=None,
    property_uris=None,
    property_domains=None,
):
    taxonomy = MagicMock()
    owl_classes = {}
    for uri in class_uris or []:
        cls = MagicMock()
        cls.sub_class_of = (subclass_of or {}).get(uri, [])
        owl_classes[uri] = cls
    taxonomy.owl_classes = owl_classes

    owl_individuals = {}
    for i, t_uri in enumerate(individual_types or []):
        ind = MagicMock()
        ind.types = [t_uri]
        owl_individuals[f"{_KAI_NS}ind{i}"] = ind
    taxonomy.owl_individuals = owl_individuals

    owl_properties = {}
    for p_uri in property_uris or []:
        prop = MagicMock()
        prop.uri = p_uri
        prop.prop_type = "ObjectProperty"
        prop.domains = (property_domains or {}).get(p_uri, [])
        prop.labels = []
        owl_properties[p_uri] = prop
    taxonomy.owl_properties = owl_properties

    return taxonomy


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx(tmp_path):
    return {
        "cache_dir": tmp_path,
        "taxonomy": None,
        "uri": None,
        "result": None,
        "graph": None,
        "raises": None,
        "urlopen_mock": None,
    }


# ── Background ────────────────────────────────────────────────────────────────


@given('a local taxonomy with a class "kai:Person"')
def given_kai_person_taxonomy(ctx):
    ctx["taxonomy"] = _make_taxonomy(class_uris=[_KAI_PERSON])


# ── Scenario: subClassOf ──────────────────────────────────────────────────────


@given('"kai:Person" is declared as "rdfs:subClassOf foaf:Person"')
def given_subclass_of_foaf(ctx):
    ctx["taxonomy"] = _make_taxonomy(
        class_uris=[_KAI_PERSON],
        subclass_of={_KAI_PERSON: [_FOAF_PERSON]},
    )


@when("I scan for external class references")
def when_scan_external_refs(ctx):
    from ster.ontology_imports import find_external_class_refs

    ctx["result"] = find_external_class_refs(ctx["taxonomy"])


@then('the result includes the URI for "foaf:Person"')
def then_result_has_foaf_person(ctx):
    assert _FOAF_PERSON in ctx["result"]


# ── Scenario: rdf:type individual ────────────────────────────────────────────


@given('an individual typed as "schema:Person"')
def given_individual_schema_person(ctx):
    ctx["taxonomy"] = _make_taxonomy(individual_types=[_SCHEMA_PERSON])


@then('the result includes the URI for "schema:Person"')
def then_result_has_schema_person(ctx):
    assert _SCHEMA_PERSON in ctx["result"]


# ── Scenario: local only ──────────────────────────────────────────────────────


@given("all classes and individuals reference only local URIs")
def given_all_local(ctx):
    ctx["taxonomy"] = _make_taxonomy(
        class_uris=[_KAI_PERSON],
        subclass_of={_KAI_PERSON: []},
        individual_types=[_KAI_PERSON],
    )


@then("the result is empty")
def then_result_empty(ctx):
    assert ctx["result"] == set()


# ── Scenario: namespace URL derivation ───────────────────────────────────────


@given('the URI "http://xmlns.com/foaf/0.1/Person"')
def given_foaf_uri(ctx):
    ctx["uri"] = _FOAF_PERSON


@given('the URI "https://schema.org/Person"')
def given_schema_uri(ctx):
    ctx["uri"] = _SCHEMA_PERSON


@when("I derive the namespace URL")
def when_derive_ns(ctx):
    from ster.ontology_imports import namespace_url_from_uri

    ctx["result"] = namespace_url_from_uri(ctx["uri"])


@then('the namespace URL is "http://xmlns.com/foaf/0.1/"')
def then_ns_foaf(ctx):
    assert ctx["result"] == _FOAF_NS


@then('the namespace URL is "https://schema.org/"')
def then_ns_schema(ctx):
    assert ctx["result"] == _SCHEMA_NS


# ── Scenario: cache hit ───────────────────────────────────────────────────────


def _foaf_cache_filename() -> str:
    import hashlib

    ns = _FOAF_NS
    key = hashlib.md5(ns.encode(), usedforsecurity=False).hexdigest()[:8]
    slug = ns.replace("https://", "").replace("http://", "").replace("/", "_")
    return f"{slug}{key}.ttl"


@given('a cached ontology for "http://xmlns.com/foaf/0.1/"')
def given_cached_foaf(ctx):
    cache_file = ctx["cache_dir"] / _foaf_cache_filename()
    cache_file.write_text(_FOAF_RDF, encoding="utf-8")


@given('no cached ontology for "http://xmlns.com/foaf/0.1/"')
def given_no_cache_foaf(ctx):
    pass  # cache_dir is empty by default


@when('I fetch the ontology for "http://xmlns.com/foaf/0.1/"')
def when_fetch_foaf(ctx):
    from ster.ontology_imports import fetch_ontology

    if ctx.get("urlopen_mock"):
        ctx["graph"] = fetch_ontology(_FOAF_NS, cache_dir=ctx["cache_dir"])
    else:
        with patch("ster.ontology_imports.urllib.request.urlopen") as mock_open:
            ctx["urlopen_mock"] = mock_open
            ctx["graph"] = fetch_ontology(_FOAF_NS, cache_dir=ctx["cache_dir"])


@then("the cached graph is returned")
def then_cached_graph_returned(ctx):
    assert ctx["graph"] is not None
    assert len(ctx["graph"]) > 0


@then("no HTTP request is made")
def then_no_http(ctx):
    if ctx.get("urlopen_mock"):
        ctx["urlopen_mock"].assert_not_called()


@then("the graph is returned")
def then_graph_returned(ctx):
    assert ctx["graph"] is not None
    assert len(ctx["graph"]) > 0


@then("the graph is written to the cache")
def then_graph_written(ctx):
    cache_files = list(ctx["cache_dir"].glob("*.ttl"))
    assert len(cache_files) == 1


# ── Scenario: unreachable URL ─────────────────────────────────────────────────


@given('the URL "http://xmlns.com/foaf/0.1/" is reachable and returns RDF')
def given_url_reachable(ctx):
    response = MagicMock()
    response.read.return_value = _FOAF_RDF.encode()
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    patcher = patch("ster.ontology_imports.urllib.request.urlopen", return_value=response)
    mock = patcher.start()
    ctx["urlopen_mock"] = mock
    ctx["_patcher"] = patcher


@given('the URL "http://xmlns.com/foaf/0.1/" is not reachable')
def given_url_unreachable(ctx):
    import urllib.error

    patcher = patch(
        "ster.ontology_imports.urllib.request.urlopen",
        side_effect=urllib.error.URLError("timeout"),
    )
    mock = patcher.start()
    ctx["urlopen_mock"] = mock
    ctx["_patcher"] = patcher


@then("an empty graph is returned")
def then_empty_graph(ctx):
    assert ctx["graph"] is not None
    assert len(ctx["graph"]) == 0


@then("no exception is raised")
def then_no_exception(ctx):
    assert ctx.get("raises") is None


# ── Scenario: properties by domain ───────────────────────────────────────────


@given('an external ontology defining "foaf:knows" with domain "foaf:Person"')
def given_foaf_knows_person_domain(ctx):
    import rdflib

    g = rdflib.Graph()
    g.parse(data=_FOAF_RDF, format="turtle")
    ctx["ext_graph"] = g
    ctx["class_uri"] = _FOAF_PERSON
    ctx["superclasses"] = set()


@given('an external ontology defining "foaf:knows" with domain "foaf:Agent"')
def given_foaf_knows_agent_domain(ctx):
    import rdflib

    g = rdflib.Graph()
    g.parse(data=_FOAF_RDF, format="turtle")
    FOAF = rdflib.Namespace(_FOAF_NS)
    g.remove((FOAF.knows, rdflib.RDFS.domain, None))
    g.add((FOAF.knows, rdflib.RDFS.domain, FOAF.Agent))
    ctx["ext_graph"] = g
    ctx["class_uri"] = _FOAF_PERSON
    ctx["superclasses"] = {_FOAF_AGENT}


@given('an external ontology defining "foaf:knows" with no domain')
def given_foaf_knows_no_domain(ctx):
    import rdflib

    g = rdflib.Graph()
    g.parse(data=_FOAF_RDF, format="turtle")
    FOAF = rdflib.Namespace(_FOAF_NS)
    g.remove((FOAF.knows, rdflib.RDFS.domain, None))
    ctx["ext_graph"] = g
    ctx["class_uri"] = _FOAF_PERSON
    ctx["superclasses"] = set()


@when('I get properties for "foaf:Person" with no superclasses')
def when_get_props_no_super(ctx):
    from ster.ontology_imports import get_properties_for_class

    ctx["result"] = get_properties_for_class(
        ctx["ext_graph"], ctx["class_uri"], superclasses=ctx["superclasses"]
    )


@when('I get properties for "foaf:Person" with superclass "foaf:Agent"')
def when_get_props_with_agent(ctx):
    from ster.ontology_imports import get_properties_for_class

    ctx["result"] = get_properties_for_class(
        ctx["ext_graph"], ctx["class_uri"], superclasses=ctx["superclasses"]
    )


@then('"foaf:knows" is included in the result')
def then_foaf_knows_in_result(ctx):
    uris = [p.uri for p in ctx["result"]]
    assert _FOAF_KNOWS in uris


# ── Scenario: merged suggest ──────────────────────────────────────────────────


@given('a local taxonomy with property "kai:knows" for "kai:Person"')
def given_local_kai_knows(ctx):
    ctx["taxonomy"] = _make_taxonomy(
        class_uris=[_KAI_PERSON],
        subclass_of={_KAI_PERSON: [_FOAF_PERSON]},
        property_uris=[_KAI_KNOWS],
        property_domains={_KAI_KNOWS: [_KAI_PERSON]},
    )


@given('an external ontology defining "foaf:knows" for "foaf:Person"')
def given_ext_foaf_knows(ctx):
    response = MagicMock()
    response.read.return_value = _FOAF_RDF.encode()
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    patcher = patch("ster.ontology_imports.urllib.request.urlopen", return_value=response)
    patcher.start()
    ctx["_patchers"] = ctx.get("_patchers", []) + [patcher]


@given('"kai:Person" is declared as "rdfs:subClassOf foaf:Person"')  # type: ignore[no-redef]
def given_subclass_of_foaf_merge(ctx):
    if ctx["taxonomy"] is None:
        ctx["taxonomy"] = _make_taxonomy(
            class_uris=[_KAI_PERSON],
            subclass_of={_KAI_PERSON: [_FOAF_PERSON]},
        )
    else:
        # Ensure the existing taxonomy's KAI_PERSON class has the subclassOf set
        existing_cls = ctx["taxonomy"].owl_classes.get(_KAI_PERSON)
        if existing_cls:
            existing_cls.sub_class_of = [_FOAF_PERSON]


@when('I suggest properties for an individual of type "kai:Person"')
def when_suggest_props(ctx):
    from ster.ontology_imports import suggest_external_properties

    ctx["result"] = suggest_external_properties(
        ctx["taxonomy"],
        individual_types=[_KAI_PERSON],
        cache_dir=ctx["cache_dir"],
    )


@then('the result contains "kai:knows"')
def then_has_kai_knows(ctx):
    uris = [p.uri for p in ctx["result"]]
    assert _KAI_KNOWS in uris


@then('the result contains "foaf:knows"')
def then_has_foaf_knows(ctx):
    uris = [p.uri for p in ctx["result"]]
    assert _FOAF_KNOWS in uris


@then("there are no duplicate URIs")
def then_no_duplicates(ctx):
    uris = [p.uri for p in ctx["result"]]
    assert len(uris) == len(set(uris))
