"""ster loads every supported RDF serialisation, picked from the file extension.

The same small ontology (an OWL class hierarchy + a SKOS scheme) is written in each format
and loaded back, so the extension → rdflib-format → parse path is exercised for all of them.
TriG (a dataset format) has its own merge behaviour and is covered in ``test_trig.py``.
"""

from __future__ import annotations

import pytest
from rdflib import Graph

from ster import store

E = "https://ex.org/"

BASE_TTL = """\
@prefix ex: <https://ex.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:Scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Hiking .
ex:Hiking a skos:Concept ; skos:inScheme ex:Scheme ; skos:prefLabel "Hiking"@en .
ex:Animal a owl:Class ; rdfs:label "Animal"@en .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:label "Dog"@en .
"""


@pytest.mark.parametrize(
    ("suffix", "rdflib_format"),
    [
        (".ttl", "turtle"),
        (".owl", "xml"),  # OWL is served as RDF/XML
        (".rdf", "xml"),
        (".n3", "n3"),
        (".jsonld", "json-ld"),
        (".json", "json-ld"),
    ],
)
def test_load_each_supported_format(tmp_path, suffix, rdflib_format) -> None:
    g = Graph()
    g.parse(data=BASE_TTL, format="turtle")
    src = tmp_path / f"onto{suffix}"
    src.write_text(g.serialize(format=rdflib_format), encoding="utf-8")

    tax = store.load(src)

    assert E + "Animal" in tax.owl_classes, suffix
    assert E + "Dog" in tax.owl_classes, suffix
    assert tax.owl_classes[E + "Dog"].sub_class_of == [E + "Animal"], suffix
    assert E + "Hiking" in tax.concepts, suffix
    assert E + "Scheme" in tax.schemes, suffix


@pytest.mark.parametrize("suffix", [".owl", ".n3", ".jsonld"])
def test_each_format_round_trips_through_save(tmp_path, suffix) -> None:
    """Load → save → reload keeps the entities (the save format follows the extension)."""
    g = Graph()
    g.parse(data=BASE_TTL, format="turtle")
    src = tmp_path / f"onto{suffix}"
    src.write_text(g.serialize(format=store._FORMAT_MAP[suffix]), encoding="utf-8")

    tax = store.load(src)
    store.save(tax, src)
    reloaded = store.load(src)

    assert E + "Animal" in reloaded.owl_classes and E + "Dog" in reloaded.owl_classes
    assert E + "Hiking" in reloaded.concepts
