"""The pane header row says what is in the pane, not what the border already says.

Each of the three left panes is drawn inside a titled border — "Mixed SKOS/OWL",
"Ontology", "Properties" — and its first row repeated that same word. The row
cannot simply go: it is the keyboard "panel layer" cursor position, the parent
node of everything in the pane, and the focus target after a delete. So it earns
its line instead, by counting what the border cannot.
"""

from __future__ import annotations

import pytest
import rdflib  # noqa: F401 — parity with the other tui data tests

from ster import store
from ster.tui import data

TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/x#> .

ex:S1 a skos:ConceptScheme ; rdfs:label "S1"@en .
ex:S2 a skos:ConceptScheme ; rdfs:label "S2"@en .
ex:A a skos:Concept ; skos:prefLabel "A"@en ; skos:inScheme ex:S1 .
ex:B a skos:Concept ; skos:prefLabel "B"@en ; skos:inScheme ex:S1 .
ex:C a skos:Concept ; skos:prefLabel "C"@en ; skos:inScheme ex:S2 .

ex:K1 a owl:Class ; rdfs:label "K1"@en .
ex:K2 a owl:Class ; rdfs:label "K2"@en .
ex:i1 a owl:NamedIndividual, ex:K1 ; rdfs:label "i1"@en .

ex:rel a owl:ObjectProperty ; rdfs:label "rel"@en .
ex:num a owl:DatatypeProperty ; rdfs:label "num"@en .
"""

EMPTY = "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<https://ex.org/o> a owl:Ontology .\n"


@pytest.fixture
def tax(tmp_path):
    src = tmp_path / "o.ttl"
    src.write_text(TTL, encoding="utf-8")
    return store.load(src)


@pytest.fixture
def empty(tmp_path):
    src = tmp_path / "e.ttl"
    src.write_text(EMPTY, encoding="utf-8")
    return store.load(src)


def test_the_mixed_pane_counts_schemes_and_concepts(tax) -> None:
    summary = data.pane_summary(tax, "tree")

    assert "2 schemes" in summary
    assert "3 concepts" in summary


def test_the_ontology_pane_counts_classes_and_individuals(tax) -> None:
    summary = data.pane_summary(tax, "ont-tree")

    assert "2 classes" in summary
    assert "1 individual" in summary


def test_the_properties_pane_counts_by_kind(tax) -> None:
    """Not "2 properties" — that echoes the border. The kinds are what differ."""
    summary = data.pane_summary(tax, "prop-tree")

    assert "1 object" in summary
    assert "1 datatype" in summary


def test_singulars_are_not_written_as_plurals(tmp_path) -> None:
    """ "1 schemes" is the kind of detail that makes a UI look unfinished."""
    src = tmp_path / "one.ttl"
    src.write_text(
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "@prefix ex: <https://example.org/x#> .\n"
        "ex:S a skos:ConceptScheme .\n"
        'ex:A a skos:Concept ; skos:prefLabel "A"@en ; skos:inScheme ex:S .\n',
        encoding="utf-8",
    )
    summary = data.pane_summary(store.load(src), "tree")

    assert "1 scheme" in summary and "1 schemes" not in summary
    assert "1 concept" in summary and "1 concepts" not in summary


@pytest.mark.parametrize("pane", ["tree", "ont-tree", "prop-tree"])
def test_an_empty_pane_says_so_rather_than_counting_zeroes(empty, pane) -> None:
    """A row of "0 classes · 0 individuals" is noise; the CTA below already nudges."""
    summary = data.pane_summary(empty, pane)

    assert summary
    assert "0" not in summary


@pytest.mark.parametrize("pane", ["tree", "ont-tree", "prop-tree"])
def test_the_summary_never_repeats_the_border_title(tax, pane) -> None:
    """The whole point: the row must not echo the word on the border above it."""
    titles = {"tree": "Mixed SKOS/OWL", "ont-tree": "Ontology", "prop-tree": "Properties"}
    summary = data.pane_summary(tax, pane)

    assert titles[pane].lower() not in summary.lower()


def test_an_unknown_pane_id_yields_nothing_rather_than_raising(tax) -> None:
    """Called from tree building, where an exception would blank the pane."""
    assert data.pane_summary(tax, "nope") == ""
