"""An anonymous class expression is shown on the class that has it.

ster models a superclass as a named URI, so ``Shop subClassOf [ … ]`` has no row
of its own. The statement now survives a save — it is kept verbatim and read
back — but surviving is not the same as being visible, and a restriction the
reader cannot see is a restriction they will delete by accident somewhere else.

So it appears under Hierarchy, in the form an OWL author would have written it:
``sells some Paint``, not three triples about a blank node.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from ster import store
from ster.nav.logic._rdf_class import build_rdf_class_detail

NS = "https://example.org/#"

TTL = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix ex:   <https://example.org/#> .

ex:O a owl:Ontology ; rdfs:label "R"@en .
ex:Shop a owl:Class ; rdfs:label "Shop"@en ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty ex:sells ; owl:someValuesFrom ex:Paint ] ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty ex:staff ; owl:minCardinality "2"^^xsd:nonNegativeInteger ] ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty ex:sells ; owl:allValuesFrom ex:Paint ] .
ex:Plain a owl:Class ; rdfs:label "Plain"@en .
ex:sells a owl:ObjectProperty ; rdfs:label "sells"@en .
ex:Paint a owl:Class ; rdfs:label "Paint"@en .
"""


@pytest.fixture
def tax(tmp_path: Path):
    src = tmp_path / "r.ttl"
    src.write_text(TTL, encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return store.load(str(src))


def _expressions(tax, uri: str) -> list[str]:
    return [
        f.value
        for f in build_rdf_class_detail(tax, uri, "en")
        if f.meta.get("type") == "class_expression"
    ]


def test_a_restriction_reads_the_way_an_owl_author_writes_it(tax) -> None:
    assert "sells some Paint" in _expressions(tax, NS + "Shop")


def test_a_cardinality_reads_as_a_cardinality(tax) -> None:
    assert "staff min 2" in _expressions(tax, NS + "Shop")


def test_only_is_not_confused_with_some(tax) -> None:
    """allValuesFrom and someValuesFrom mean opposite things; both are shown."""
    found = _expressions(tax, NS + "Shop")

    assert "sells only Paint" in found
    assert "sells some Paint" in found


def test_the_property_and_filler_use_their_labels(tax) -> None:
    """A reader should see "sells", not "#sells"."""
    assert all("#" not in e for e in _expressions(tax, NS + "Shop"))


def test_a_class_without_expressions_gains_no_rows(tax) -> None:
    assert _expressions(tax, NS + "Plain") == []


def test_the_rows_are_not_editable(tax) -> None:
    """Shown, not editable — offering an edit ster cannot honour is worse than
    offering none."""
    rows = [
        f
        for f in build_rdf_class_detail(tax, NS + "Shop", "en")
        if f.meta.get("type") == "class_expression"
    ]

    assert rows and not any(f.editable for f in rows)
