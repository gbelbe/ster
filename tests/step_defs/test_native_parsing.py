"""Step definitions for native RDF parsing.

Every scenario is an equivalence check: whatever the native path produces must
match what a plain rdflib parse produces, so the optimisation can never change
what ster shows the user.
"""

from __future__ import annotations

import pytest
import rdflib
from pytest_bdd import given, scenarios, then, when

from ster import store

scenarios("../features/perf/native_parsing.feature")

_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix gear: <https://example.org/gear#> .
gear:Scheme a skos:ConceptScheme .
gear:Tent a skos:Concept ; skos:prefLabel "Tent"@en, "Tente"@fr ; skos:inScheme gear:Scheme .
gear:DomeTent a skos:Concept ; skos:prefLabel "Dome"@en ; skos:broader gear:Tent .
gear:Shelter a owl:Class .
"""

# "geo" is one of the ~30 prefixes rdflib pre-binds (to GeoSPARQL). A file using
# it for wgs84 makes rdflib rebind as "geo1"; the native path must agree.
_TTL_PREFIX_CLASH = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix geo:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix ex:   <https://example.org/x#> .
ex:Place a skos:Concept ; skos:prefLabel "Place"@en ; geo:lat "1.0" .
"""

_XML = """\
<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:skos="http://www.w3.org/2004/02/skos/core#"
         xmlns:gear="https://example.org/gear#">
  <skos:Concept rdf:about="https://example.org/gear#Tent">
    <skos:prefLabel xml:lang="en">Tent</skos:prefLabel>
  </skos:Concept>
</rdf:RDF>
"""

_JSONLD = """\
{"@context": {"skos": "http://www.w3.org/2004/02/skos/core#"},
 "@id": "https://example.org/gear#Tent",
 "@type": "skos:Concept",
 "skos:prefLabel": {"@value": "Tent", "@language": "en"}}
"""

# Rejected by both parsers. The native path swallows its own parse errors to
# fall back, so this guards that a genuinely broken file still surfaces one.
_TTL_BROKEN = "@prefix ex: <https://example.org/> .\nex:A a ex:B\n"


@pytest.fixture
def ctx(tmp_path):
    return {"tmp_path": tmp_path}


def _write(ctx, name: str, text: str, fmt: str) -> None:
    path = ctx["tmp_path"] / name
    path.write_text(text, encoding="utf-8")
    ctx["path"] = path
    ctx["fmt"] = fmt


@given("a Turtle taxonomy file")
def given_ttl(ctx):
    _write(ctx, "sample.ttl", _TTL, "turtle")


@given("an RDF/XML ontology file")
def given_xml(ctx):
    _write(ctx, "sample.rdf", _XML, "xml")


@given('a Turtle file binding "geo" to a namespace rdflib reserves for another')
def given_clash(ctx):
    _write(ctx, "clash.ttl", _TTL_PREFIX_CLASH, "turtle")


@given("a JSON-LD taxonomy file")
def given_jsonld(ctx):
    _write(ctx, "sample.jsonld", _JSONLD, "json-ld")


@given("a malformed Turtle file")
def given_broken(ctx):
    _write(ctx, "broken.ttl", _TTL_BROKEN, "turtle")


@when("ster loads it")
def when_load(ctx):
    try:
        ctx["taxonomy"] = store.load(ctx["path"])
    except Exception as exc:  # noqa: BLE001 — asserted by the syntax-error step
        ctx["error"] = exc
        return
    graph = rdflib.Graph()
    graph.parse(str(ctx["path"]), format=ctx["fmt"])
    ctx["reference"] = store.graph_to_taxonomy(graph)


@then("the load fails with a syntax error")
def then_syntax_error(ctx):
    assert "error" in ctx, "a malformed file must not load silently"
    assert "taxonomy" not in ctx


@then("the taxonomy has the same entities as the rdflib parser produces")
def then_same_entities(ctx):
    got, want = ctx["taxonomy"], ctx["reference"]
    assert set(got.concepts) == set(want.concepts)
    assert set(got.owl_classes) == set(want.owl_classes)
    assert set(got.schemes) == set(want.schemes)
    for uri, concept in want.concepts.items():
        assert got.concepts[uri].pref_label("en") == concept.pref_label("en")
        assert sorted(got.concepts[uri].broader) == sorted(concept.broader)


@then("the namespace bindings match the rdflib parser exactly")
def then_same_namespaces(ctx):
    assert ctx["taxonomy"].namespace_bindings == ctx["reference"].namespace_bindings
