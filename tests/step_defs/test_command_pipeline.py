"""BDD step definitions for tests/features/core/command_pipeline.feature.

Drives chained commands through a real TaxonomyService (real store persistence +
SkosValidatorAdapter) against an on-disk TTL, so each step exercises the full
pipeline: clone → apply → validate → atomic save → swap → version bump.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store
from ster.core.commands import (
    OwlMoveClass,
    RenameEntity,
    SkosMoveConcept,
    SkosRemoveConcept,
    SkosSetLabel,
)
from ster.core.service import TaxonomyService
from ster.core.validation import SkosValidatorAdapter

scenarios("../features/core/command_pipeline.feature")

NS = "https://ex.org/t/"

_SKOS_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix t: <https://ex.org/t/> .
t:Scheme a skos:ConceptScheme ; skos:hasTopConcept t:Top, t:Other .
t:Top a skos:Concept ; skos:inScheme t:Scheme ; skos:topConceptOf t:Scheme ;
      skos:prefLabel "Top"@en .
t:Other a skos:Concept ; skos:inScheme t:Scheme ; skos:topConceptOf t:Scheme ;
        skos:prefLabel "Other"@en .
t:Child a skos:Concept ; skos:inScheme t:Scheme ; skos:broader t:Top ;
        skos:prefLabel "Child"@en .
"""

_OWL_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix t: <https://ex.org/t/> .
<https://ex.org/t> a owl:Ontology .
t:Animal a owl:Class ; rdfs:label "Animal"@en .
t:Mammal a owl:Class ; rdfs:label "Mammal"@en .
t:Dog a owl:Class ; rdfs:label "Dog"@en ; rdfs:subClassOf t:Animal .
"""


def _u(name: str) -> str:
    return NS + name


@dataclass
class _Workspace:
    taxonomies: dict = field(default_factory=dict)


class _StorePersistence:
    def save(self, taxonomy, path) -> None:
        store.save(taxonomy, path)


@pytest.fixture
def ctx(tmp_path: Path) -> dict:
    return {"tmp_path": tmp_path, "result": None}


def _setup(ctx: dict, ttl: str) -> None:
    path = ctx["tmp_path"] / "onto.ttl"
    path.write_text(ttl)
    ws = _Workspace({path: store.load(path)})
    ctx["path"] = path
    ctx["svc"] = TaxonomyService(ws, _StorePersistence(), SkosValidatorAdapter())
    ctx["ws"] = ws


def _live(ctx: dict):
    return ctx["ws"].taxonomies[ctx["path"]]


def _reloaded(ctx: dict):
    return store.load(ctx["path"])


# ── given ─────────────────────────────────────────────────────────────────────


@given(parsers.parse('an ontology file with concepts "{a}", "{b}" and "{c}" under "{a2}"'))
def given_skos_file(ctx: dict, a: str, b: str, c: str, a2: str) -> None:
    _setup(ctx, _SKOS_TTL)


@given(parsers.parse('an ontology file with classes "{a}", "{b}" and "{c}" under "{a2}"'))
def given_owl_file(ctx: dict, a: str, b: str, c: str, a2: str) -> None:
    _setup(ctx, _OWL_TTL)


# ── when ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I rename "{old}" to "{new}"'))
def when_rename(ctx: dict, old: str, new: str) -> None:
    ctx["result"] = ctx["svc"].execute(RenameEntity(ctx["path"], _u(old), _u(new)))


@when(parsers.parse('I move concept "{uri}" under "{parent}"'))
def when_move(ctx: dict, uri: str, parent: str) -> None:
    ctx["result"] = ctx["svc"].execute(SkosMoveConcept(ctx["path"], _u(uri), _u(parent)))


@when(parsers.parse('I move concept "{uri}" under "{parent}" based on version {ver:d}'))
def when_move_versioned(ctx: dict, uri: str, parent: str, ver: int) -> None:
    ctx["result"] = ctx["svc"].execute(
        SkosMoveConcept(ctx["path"], _u(uri), _u(parent)), base_version=ver
    )


@when(parsers.parse('I reparent class "{uri}" under "{parent}"'))
def when_reparent(ctx: dict, uri: str, parent: str) -> None:
    ctx["result"] = ctx["svc"].execute(OwlMoveClass(ctx["path"], _u(uri), _u(parent), replace=True))


@when(parsers.parse('I set the "{lang}" pref label of "{uri}" to "{value}"'))
def when_set_label(ctx: dict, lang: str, uri: str, value: str) -> None:
    ctx["result"] = ctx["svc"].execute(SkosSetLabel(ctx["path"], _u(uri), lang, value, "pref"))


@when(parsers.parse('I delete concept "{uri}"'))
def when_delete(ctx: dict, uri: str) -> None:
    ctx["result"] = ctx["svc"].execute(SkosRemoveConcept(ctx["path"], _u(uri)))


# ── then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('concept "{new}" exists and "{old}" does not'))
def then_renamed(ctx: dict, new: str, old: str) -> None:
    concepts = _live(ctx).concepts
    assert _u(new) in concepts and _u(old) not in concepts


@then(parsers.parse('concept "{uri}" is a child of "{parent}"'))
def then_child_of(ctx: dict, uri: str, parent: str) -> None:
    assert _u(parent) in _live(ctx).concepts[_u(uri)].broader


@then(parsers.parse('the saved file has "{value}" as the "{lang}" pref label of "{uri}"'))
def then_saved_label(ctx: dict, value: str, lang: str, uri: str) -> None:
    labels = [lb.value for lb in _reloaded(ctx).concepts[_u(uri)].labels if lb.lang == lang]
    assert value in labels


@then(parsers.parse('concept "{uri}" does not exist'))
def then_not_exist(ctx: dict, uri: str) -> None:
    assert _u(uri) not in _live(ctx).concepts


@then(parsers.parse('the saved file does not contain "{name}"'))
def then_file_lacks(ctx: dict, name: str) -> None:
    assert _u(name) not in _reloaded(ctx).concepts


@then(parsers.parse("the file version is {ver:d}"))
def then_version(ctx: dict, ver: int) -> None:
    assert ctx["svc"].version(ctx["path"]) == ver


@then(parsers.parse('class "{uri}" is a subclass of "{parent}"'))
def then_subclass(ctx: dict, uri: str, parent: str) -> None:
    assert _u(parent) in _live(ctx).owl_classes[_u(uri)].sub_class_of


@then(parsers.parse('class "{uri}" does not exist'))
def then_class_gone(ctx: dict, uri: str) -> None:
    assert _u(uri) not in _live(ctx).owl_classes


@then("the last command was blocked")
def then_blocked(ctx: dict) -> None:
    r = ctx["result"]
    assert r.status == "failed" and r.validation and r.validation.errors


@then("the last command was rejected")
def then_rejected(ctx: dict) -> None:
    assert ctx["result"].status == "rejected"
