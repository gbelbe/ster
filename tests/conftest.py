"""Shared fixtures for all test modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import store
from ster.model import Concept, ConceptScheme, Definition, Label, Taxonomy

BASE = "https://example.org/test/"


@pytest.fixture(autouse=True)
def _isolate_analysis_cache(tmp_path_factory, monkeypatch):
    """Redirect the on-disk analysis cache to a per-test tmp dir.

    Without this, tests read/write the developer's real
    ~/.cache/ster/analysis_cache.json: every viewer-save test re-serialised the
    whole accumulated blob (~900ms once it grew to thousands of dead pytest
    tmp-path entries) and polluted it further. Isolating it keeps the suite fast
    and side-effect-free. See tests/unit/test_analysis_cache_isolation.py.
    """
    cache = tmp_path_factory.mktemp("ster-analysis-cache") / "analysis_cache.json"
    monkeypatch.setattr("ster.analysis_cache._cache_path", lambda: cache)


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path_factory, monkeypatch):
    """Redirect every on-disk preference file to a per-test tmp dir.

    Without this, tests read (and *write*) the developer's real
    ~/.config/ster/*.json — theme, configured languages, the metadata-property
    catalogs, the plugin config. That both pollutes real config and makes tests
    order-dependent: e.g. the annotation picker's options come from
    ``load_metadata_props()``, so a leaked catalog changes what predicates are
    offered. Isolating the prefs makes every test see the clean defaults.
    """
    from ster.nav import prefs
    from ster.plugins.semanticlint import config as sl_config

    d = tmp_path_factory.mktemp("ster-prefs")
    for attr in (
        "_prefs_path",
        "_lang_prefs_path",
        "_configured_langs_path",
        "_metadata_props_path",
        "_entity_metadata_props_path",
    ):
        monkeypatch.setattr(prefs, attr, lambda a=attr: d / f"{a}.json")
    monkeypatch.setattr(sl_config, "_config_path", lambda: d / "quality.json")


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
