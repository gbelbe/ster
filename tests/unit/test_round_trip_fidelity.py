"""Opening a file and saving it gives the file back.

Not "mostly back". A tool that quietly drops what it does not understand is a
tool nobody can trust with a file they care about, and RDF is full of things one
editor's model does not cover: OWL class expressions, provenance records,
vocabularies it has never heard of.

Three things were being lost before these tests existed:

  * every ``owl:Restriction`` — eight of twelve triples in a two-restriction
    file, because a blank-node class expression had nowhere to live in the model
  * every entity whose ``rdf:type`` the model does not know — 98 triples of
    PROV records from a real ontology, including the provenance it exists for
  * and one triple was *added*: a ``dcterms:title`` back-filled from
    ``rdfs:label`` on load, then written out as though the author had said it

The measure is isomorphism, not text: reordering, prefix changes and blank-node
relabelling are all fine. Only meaning has to survive.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
import rdflib
from rdflib.compare import graph_diff, isomorphic, to_isomorphic

from ster import store

# ── corpora ──────────────────────────────────────────────────────────────────
# Written out rather than fetched: a test that needs the network is a test that
# fails on a train. Each one is the smallest file that exercises its hazard.

OWL_RESTRICTIONS = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix ex:   <https://example.org/#> .

ex:O a owl:Ontology ; rdfs:label "Restrictions"@en .
ex:Shop a owl:Class ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty ex:sells ; owl:someValuesFrom ex:Paint ] ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty ex:staff ; owl:minCardinality "2"^^xsd:nonNegativeInteger ] .
ex:sells a owl:ObjectProperty .
ex:Paint a owl:Class .
"""

UNKNOWN_ENTITY_TYPES = """
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix prov:  <http://www.w3.org/ns/prov#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix ex:    <https://example.org/#> .

ex:O a owl:Ontology ; rdfs:label "Provenance"@en .
ex:Shop a owl:Class ; rdfs:label "Shop"@en ; prov:wasDerivedFrom ex:src .

ex:src a prov:Entity ;
    rdfs:label "A source someone cited"@en ;
    prov:atLocation <https://example.org/sitemap.xml> ;
    dcterms:rights "CC-BY-4.0" .

ex:build a prov:Activity ; prov:used ex:src .
"""

COLLECTIONS_AND_LISTS = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/#> .

ex:O a owl:Ontology ; rdfs:label "Unions"@en .
ex:Either a owl:Class ; owl:unionOf ( ex:A ex:B ) .
ex:A a owl:Class .
ex:B a owl:Class .
"""

LITERAL_SHAPES = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <https://example.org/#> .

ex:O a owl:Ontology ; rdfs:label "Literals"@en .
ex:S a skos:ConceptScheme ; rdfs:label "S"@en .
ex:c a skos:Concept ; skos:inScheme ex:S ;
    skos:prefLabel "Ville"@fr , "City"@en , "都市"@ja ;
    ex:count "007"^^xsd:integer ;
    ex:when "2026-09-07"^^xsd:date ;
    ex:note "line one\\nline two" ;
    ex:plain "no language tag" .
"""

CORPORA = {
    "owl restrictions": OWL_RESTRICTIONS,
    "unknown entity types": UNKNOWN_ENTITY_TYPES,
    "collections and lists": COLLECTIONS_AND_LISTS,
    "literal shapes": LITERAL_SHAPES,
}


def _round_trip(ttl: str, tmp_path: Path) -> tuple[rdflib.Graph, rdflib.Graph]:
    src = tmp_path / "in.ttl"
    src.write_text(ttl, encoding="utf-8")
    before = rdflib.Graph()
    before.parse(src)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        taxonomy = store.load(str(src))
        out = tmp_path / "out.ttl"
        store.save(taxonomy, str(out))

    after = rdflib.Graph()
    after.parse(out)
    return before, after


def _describe(before: rdflib.Graph, after: rdflib.Graph) -> str:
    _, lost, added = graph_diff(to_isomorphic(before), to_isomorphic(after))
    lines = [f"{len(lost)} lost, {len(added)} added"]
    for label, part in (("lost", lost), ("added", added)):
        for triple in sorted(part, key=str)[:6]:
            lines.append(f"  {label}: " + " ".join(str(t)[:44] for t in triple))
    return "\n".join(lines)


@pytest.mark.parametrize("name", sorted(CORPORA))
def test_a_file_survives_being_opened_and_saved(name: str, tmp_path: Path) -> None:
    """The whole contract, one corpus at a time."""
    before, after = _round_trip(CORPORA[name], tmp_path)

    assert isomorphic(before, after), f"{name} did not survive:\n{_describe(before, after)}"


def test_nothing_is_invented(tmp_path: Path) -> None:
    """A tool that adds assertions the author never made is worse than a lossy
    one: the file now says something untrue and nothing marks it."""
    before, after = _round_trip(UNKNOWN_ENTITY_TYPES, tmp_path)
    _, _lost, added = graph_diff(to_isomorphic(before), to_isomorphic(after))

    assert not added, f"triples appeared that nobody wrote:\n{_describe(before, after)}"


def test_a_label_is_not_silently_promoted_to_a_title(tmp_path: Path) -> None:
    """Back-filling dcterms:title from rdfs:label wrote a claim into the file.

    Presenting a label as a title where none exists is a display decision, and
    it belongs at the point of display — not written into someone's data.
    """
    before, after = _round_trip(UNKNOWN_ENTITY_TYPES, tmp_path)
    title = rdflib.URIRef("http://purl.org/dc/terms/title")

    assert (None, title, None) not in before, "corpus should have no title to begin with"
    assert (None, title, None) not in after, "a dcterms:title was written that nobody asked for"


def test_the_real_ontology_survives(tmp_path: Path) -> None:
    """The regression that started this: 98 triples lost from a working file."""
    real = Path(__file__).resolve().parents[2] / "ster" / "taxonomy.ttl"
    before, after = _round_trip(real.read_text(encoding="utf-8"), tmp_path)

    assert isomorphic(before, after), _describe(before, after)
