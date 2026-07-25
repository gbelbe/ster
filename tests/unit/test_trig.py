"""Opening TriG (.trig) files.

TriG is an RDF *dataset* serialisation (named graphs + a default graph). ster models one
flat graph, so it reads a TriG into an rdflib Dataset and merges every graph — the entities
are viewed together, without their graph partition.
"""

from __future__ import annotations

from ster import store

E = "https://ex.org/"

TRIG = """\
@prefix ex: <https://ex.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:G1 { ex:Animal a owl:Class ; rdfs:label "Animal"@en . }
ex:G2 { ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:label "Dog"@en . }
ex:G3 { ex:Scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Hiking .
        ex:Hiking a skos:Concept ; skos:inScheme ex:Scheme ; skos:prefLabel "Hiking"@en . }
{ ex:loose a owl:Class ; rdfs:label "Loose"@en . }
"""


def test_trig_extension_maps_to_the_trig_format() -> None:
    assert store._FORMAT_MAP.get(".trig") == "trig"
    assert "trig" in store._DATASET_FORMATS


def test_load_trig_merges_every_named_and_default_graph(tmp_path) -> None:
    src = tmp_path / "o.trig"
    src.write_text(TRIG, encoding="utf-8")
    tax = store.load(src)
    # OWL classes from three different named graphs + the default graph
    assert E + "Animal" in tax.owl_classes
    assert E + "Dog" in tax.owl_classes
    assert E + "loose" in tax.owl_classes  # the default graph, too
    assert tax.owl_classes[E + "Dog"].sub_class_of == [E + "Animal"]  # cross-graph link kept
    # SKOS from a named graph
    assert E + "Hiking" in tax.concepts
    assert E + "Scheme" in tax.schemes


def test_trig_round_trips_through_save_and_reload(tmp_path) -> None:
    """Saving back to .trig produces a valid TriG that reloads with every entity (ster
    flattens the named graphs; the content survives even if the partition does not)."""
    src = tmp_path / "o.trig"
    src.write_text(TRIG, encoding="utf-8")
    tax = store.load(src)
    store.save(tax, src)
    reloaded = store.load(src)
    for uri in (E + "Animal", E + "Dog", E + "loose"):
        assert uri in reloaded.owl_classes
    assert E + "Hiking" in reloaded.concepts
