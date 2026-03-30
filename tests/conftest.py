"""Shared fixtures for all test modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import store
from ster.model import Concept, ConceptScheme, Definition, Label, Taxonomy

BASE = "https://example.org/test/"

MINIMAL_TURTLE = """\
@prefix skos:    <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix t:       <https://example.org/test/> .

t:Scheme a skos:ConceptScheme ;
    dcterms:title "Test Taxonomy"@en , "Taxonomie de Test"@fr ;
    skos:hasTopConcept t:Top .

t:Top a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:topConceptOf t:Scheme ;
    skos:prefLabel "Top Concept"@en , "Concept Principal"@fr ;
    skos:definition "The root concept."@en ;
    skos:narrower t:Child1 , t:Child2 .

t:Child1 a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:prefLabel "Child One"@en , "Enfant Un"@fr ;
    skos:broader t:Top ;
    skos:narrower t:Grandchild .

t:Child2 a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:prefLabel "Child Two"@en , "Enfant Deux"@fr ;
    skos:altLabel "Second child"@en ;
    skos:broader t:Top .

t:Grandchild a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:prefLabel "Grandchild"@en ;
    skos:broader t:Child1 .
"""


@pytest.fixture
def minimal_turtle() -> str:
    return MINIMAL_TURTLE


@pytest.fixture
def tmp_ttl(tmp_path: Path, minimal_turtle: str) -> Path:
    """Write minimal turtle to a temp file and return the path."""
    p = tmp_path / "test.ttl"
    p.write_text(minimal_turtle, encoding="utf-8")
    return p


@pytest.fixture
def taxonomy(tmp_ttl: Path) -> Taxonomy:
    """Load the minimal taxonomy from disk."""
    return store.load(tmp_ttl)


@pytest.fixture
def simple_taxonomy() -> Taxonomy:
    """Build a minimal Taxonomy in memory (no disk I/O)."""
    t = Taxonomy()
    scheme = ConceptScheme(
        uri=BASE + "Scheme",
        labels=[Label(lang="en", value="Test Taxonomy")],
        top_concepts=[BASE + "Top"],
        base_uri=BASE,
    )
    top = Concept(
        uri=BASE + "Top",
        labels=[
            Label(lang="en", value="Top Concept"),
            Label(lang="fr", value="Concept Principal"),
        ],
        definitions=[Definition(lang="en", value="The root.")],
        narrower=[BASE + "Child1", BASE + "Child2"],
        top_concept_of=BASE + "Scheme",
    )
    child1 = Concept(
        uri=BASE + "Child1",
        labels=[Label(lang="en", value="Child One")],
        broader=[BASE + "Top"],
        narrower=[BASE + "Grandchild"],
    )
    child2 = Concept(
        uri=BASE + "Child2",
        labels=[Label(lang="en", value="Child Two")],
        broader=[BASE + "Top"],
    )
    grandchild = Concept(
        uri=BASE + "Grandchild",
        labels=[Label(lang="en", value="Grandchild")],
        broader=[BASE + "Child1"],
    )
    t.schemes[scheme.uri] = scheme
    for c in (top, child1, child2, grandchild):
        t.concepts[c.uri] = c
    from ster.handles import assign_handles

    assign_handles(t)
    return t
