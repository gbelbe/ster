"""Characterization (golden) baselines for representative TTL mutations.

These pin the *current* end-to-end behaviour — load fixture, apply the existing
``operations.*`` path, ``store.save``, reload — so the upcoming extraction of a
shared TaxonomyService (see docs/architecture/core-service.md) can be proven
behaviour-preserving. They assert observable structure, not byte output, so
they survive serialization-format churn but catch semantic regressions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import operations, store

_FIXTURE_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix t: <https://ex.org/t/> .

<https://ex.org/t> a owl:Ontology .

t:Animal a owl:Class ; rdfs:label "Animal"@en .
t:Mammal a owl:Class ; rdfs:label "Mammal"@en .
t:Dog a owl:Class ; rdfs:label "Dog"@en ; rdfs:subClassOf t:Animal .

t:Scheme a skos:ConceptScheme ; skos:hasTopConcept t:Top .
t:Top a skos:Concept ; skos:inScheme t:Scheme ; skos:topConceptOf t:Scheme ;
      skos:prefLabel "Top"@en .
t:Child a skos:Concept ; skos:inScheme t:Scheme ; skos:broader t:Top ;
        skos:prefLabel "Child"@en .
"""

NS = "https://ex.org/t/"


@pytest.fixture
def loaded(tmp_path: Path):
    """Load the fixture and return (taxonomy, save_path) for a round-trip."""
    src = tmp_path / "onto.ttl"
    src.write_text(_FIXTURE_TTL)
    return store.load(src), src


def _save_reload(tax, path: Path):
    store.save(tax, path)
    return store.load(path)


# ── 1. move a class under a different superclass (OWL rdfs:subClassOf) ─────────


def test_add_subclass_of_baseline(loaded) -> None:
    tax, path = loaded
    operations.add_subclass_of(tax, f"{NS}Dog", f"{NS}Mammal")
    reloaded = _save_reload(tax, path)
    parents = set(reloaded.owl_classes[f"{NS}Dog"].sub_class_of)
    assert parents == {f"{NS}Animal", f"{NS}Mammal"}  # polyhierarchy preserved on disk


def test_move_class_via_service_matches_inline_baseline(tmp_path: Path) -> None:
    """The OwlMoveClass command through TaxonomyService must equal the inline op path."""
    from dataclasses import dataclass, field

    from ster.core.commands import OwlMoveClass
    from ster.core.service import TaxonomyService

    # Baseline: the existing inline path (operations.add_subclass_of) → save → reload.
    base_path = tmp_path / "baseline.ttl"
    base_path.write_text(_FIXTURE_TTL)
    base_tax = store.load(base_path)
    operations.add_subclass_of(base_tax, f"{NS}Dog", f"{NS}Mammal")
    baseline = set(_save_reload(base_tax, base_path).owl_classes[f"{NS}Dog"].sub_class_of)

    # Service path: same intent via a OwlMoveClass command (replace=False == additive).
    svc_path = tmp_path / "service.ttl"
    svc_path.write_text(_FIXTURE_TTL)

    @dataclass
    class _WS:
        taxonomies: dict = field(default_factory=dict)

    class _Store:
        def save(self, taxonomy, path):
            store.save(taxonomy, path)

    ws = _WS({svc_path: store.load(svc_path)})
    svc = TaxonomyService(ws, _Store())
    result = svc.execute(OwlMoveClass(svc_path, f"{NS}Dog", f"{NS}Mammal", replace=False))
    assert result.ok
    via_service = set(store.load(svc_path).owl_classes[f"{NS}Dog"].sub_class_of)

    assert via_service == baseline  # equivalence: front-end-agnostic, same on-disk result


# ── 2. add a concept ──────────────────────────────────────────────────────────


def test_move_concept_via_service_matches_inline_baseline(tmp_path: Path) -> None:
    """SkosMoveConcept through TaxonomyService must equal operations.move_concept on disk."""
    from dataclasses import dataclass, field

    from ster.core.commands import SkosMoveConcept
    from ster.core.service import TaxonomyService

    base_path = tmp_path / "baseline.ttl"
    base_path.write_text(_FIXTURE_TTL)
    base_tax = store.load(base_path)
    operations.move_concept(base_tax, f"{NS}Child", None)  # detach Child to top
    baseline = set(_save_reload(base_tax, base_path).concepts[f"{NS}Child"].broader)

    svc_path = tmp_path / "service.ttl"
    svc_path.write_text(_FIXTURE_TTL)

    @dataclass
    class _WS:
        taxonomies: dict = field(default_factory=dict)

    class _Store:
        def save(self, taxonomy, path):
            store.save(taxonomy, path)

    ws = _WS({svc_path: store.load(svc_path)})
    svc = TaxonomyService(ws, _Store())
    assert svc.execute(SkosMoveConcept(svc_path, f"{NS}Child", None)).ok
    via_service = set(store.load(svc_path).concepts[f"{NS}Child"].broader)

    assert via_service == baseline == set()  # both detached Child to the scheme top


def test_add_concept_baseline(loaded) -> None:
    tax, path = loaded
    operations.add_concept(tax, f"{NS}Kid", {"en": "Kid"}, parent_handle=f"{NS}Top")
    reloaded = _save_reload(tax, path)
    assert f"{NS}Kid" in reloaded.concepts
    assert f"{NS}Top" in reloaded.concepts[f"{NS}Kid"].broader


# ── 3. set a label ────────────────────────────────────────────────────────────


def test_set_label_baseline(loaded) -> None:
    tax, path = loaded
    operations.set_label(tax, f"{NS}Top", "fr", "Sommet")
    reloaded = _save_reload(tax, path)
    fr = [lbl.value for lbl in reloaded.concepts[f"{NS}Top"].labels if lbl.lang == "fr"]
    assert "Sommet" in fr


# ── 4. remove a concept ───────────────────────────────────────────────────────


def test_remove_concept_baseline(loaded) -> None:
    tax, path = loaded
    operations.remove_concept(tax, f"{NS}Child")
    reloaded = _save_reload(tax, path)
    assert f"{NS}Child" not in reloaded.concepts
    assert f"{NS}Child" not in reloaded.concepts[f"{NS}Top"].narrower  # back-ref cleaned


# ── 5. rename a concept URI ───────────────────────────────────────────────────


def test_rename_uri_baseline(loaded) -> None:
    tax, path = loaded
    operations.rename_uri(tax, f"{NS}Child", f"{NS}Renamed")
    reloaded = _save_reload(tax, path)
    assert f"{NS}Renamed" in reloaded.concepts
    assert f"{NS}Child" not in reloaded.concepts
    assert f"{NS}Top" in reloaded.concepts[f"{NS}Renamed"].broader  # hierarchy preserved
