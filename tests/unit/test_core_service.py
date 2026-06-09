"""Unit tests for ster.core.service.TaxonomyService (Phase 2 — OwlMoveClass slice)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from ster import store
from ster.core.commands import (
    OntoRenameUri,
    OwlDeleteClass,
    OwlMoveClass,
    RenameEntity,
    SkosAddRelated,
    SkosCreateScheme,
    SkosMoveConcept,
    SkosRemoveConcept,
    SkosRemoveDefinition,
    SkosRemoveLabel,
    SkosRemoveScopeNote,
    SkosSetDefinition,
    SkosSetLabel,
    SkosSetScopeNote,
)
from ster.core.service import TaxonomyService
from ster.core.validation import SkosValidatorAdapter
from ster.model import Concept, ConceptScheme, Label, LabelType, RDFClass, Taxonomy

NS = "https://ex.org/t/"
PATH = Path("/tmp/onto.ttl")


# ── fakes ─────────────────────────────────────────────────────────────────────


@dataclass
class _FakeWorkspace:
    taxonomies: dict[Path, Taxonomy] = field(default_factory=dict)


class _FakePersistence:
    def __init__(self) -> None:
        self.saved: list[tuple[Taxonomy, Path]] = []

    def save(self, taxonomy: Taxonomy, path: Path) -> None:
        self.saved.append((taxonomy, path))


def _taxonomy() -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = "https://ex.org/t"
    t.owl_classes[f"{NS}Animal"] = RDFClass(uri=f"{NS}Animal")
    t.owl_classes[f"{NS}Mammal"] = RDFClass(uri=f"{NS}Mammal")
    t.owl_classes[f"{NS}Dog"] = RDFClass(uri=f"{NS}Dog", sub_class_of=[f"{NS}Animal"])
    return t


def _service() -> tuple[TaxonomyService, _FakeWorkspace, _FakePersistence]:
    ws = _FakeWorkspace({PATH: _taxonomy()})
    pers = _FakePersistence()
    return TaxonomyService(ws, pers), ws, pers


def _skos_taxonomy() -> Taxonomy:
    """Scheme with two top concepts (Top, Other); Child sits under Top."""
    t = Taxonomy()
    scheme = ConceptScheme(uri=f"{NS}Scheme")
    t.schemes[scheme.uri] = scheme
    for name in ("Top", "Other"):
        c = Concept(
            uri=f"{NS}{name}",
            top_concept_of=scheme.uri,
            labels=[Label(lang="en", value=name, type=LabelType.PREF)],
        )
        t.concepts[c.uri] = c
        scheme.top_concepts.append(c.uri)
    child = Concept(uri=f"{NS}Child", broader=[f"{NS}Top"])
    t.concepts[child.uri] = child
    t.concepts[f"{NS}Top"].narrower.append(child.uri)
    return t


def _skos_service() -> tuple[TaxonomyService, _FakeWorkspace, _FakePersistence]:
    ws = _FakeWorkspace({PATH: _skos_taxonomy()})
    pers = _FakePersistence()
    return TaxonomyService(ws, pers), ws, pers


# ── apply semantics ─────────────────────────────────────────────────────────


def test_replace_sets_sole_parent() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal", replace=True))
    assert result.ok
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].sub_class_of == [f"{NS}Mammal"]


def test_add_appends_parent_polyhierarchy() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal", replace=False))
    assert result.ok
    assert set(ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].sub_class_of) == {
        f"{NS}Animal",
        f"{NS}Mammal",
    }


def test_detach_to_top_clears_parents() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", None, replace=True))
    assert result.ok
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].sub_class_of == []


def test_affected_uris_reports_source() -> None:
    svc, _, _ = _service()
    result = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal"))
    assert result.affected_uris == (f"{NS}Dog",)


# ── persistence + versioning ──────────────────────────────────────────────────


def test_success_persists_once_and_bumps_version() -> None:
    svc, ws, pers = _service()
    assert svc.version(PATH) == 0
    result = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal"))
    assert result.version == 1
    assert svc.version(PATH) == 1
    assert len(pers.saved) == 1
    assert pers.saved[0][1] == PATH


def test_success_swaps_in_a_new_object_leaving_original_isolated() -> None:
    svc, ws, _ = _service()
    original = ws.taxonomies[PATH]
    svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal", replace=True))
    # The committed authority is a fresh clone, and the original we held is untouched.
    assert ws.taxonomies[PATH] is not original
    assert original.owl_classes[f"{NS}Dog"].sub_class_of == [f"{NS}Animal"]


# ── failure (transaction rollback) ────────────────────────────────────────────


def test_unknown_class_fails_without_side_effects() -> None:
    svc, ws, pers = _service()
    original = ws.taxonomies[PATH]
    result = svc.execute(OwlMoveClass(PATH, f"{NS}Ghost", f"{NS}Mammal"))
    assert result.status == "failed"
    assert "Ghost" in (result.error or "")
    assert pers.saved == []  # nothing written
    assert svc.version(PATH) == 0  # version not bumped
    assert ws.taxonomies[PATH] is original  # authority not swapped


# ── optimistic concurrency control ─────────────────────────────────────────────


def test_stale_base_version_is_rejected() -> None:
    svc, _, pers = _service()
    result = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal"), base_version=99)
    assert result.status == "rejected"
    assert result.version == 0
    assert pers.saved == []


def test_matching_base_version_then_stale_retry() -> None:
    svc, _, _ = _service()
    first = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal"), base_version=0)
    assert first.ok and first.version == 1
    stale = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Animal"), base_version=0)
    assert stale.status == "rejected"
    assert stale.version == 1


# ── concurrency (per-file lock serializes writers) ─────────────────────────────


# ── SkosMoveConcept (SKOS) — second migrated command ──────────────────────────────


def test_move_concept_reparents_under_new_concept() -> None:
    svc, ws, pers = _skos_service()
    result = svc.execute(SkosMoveConcept(PATH, f"{NS}Child", f"{NS}Other"))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert tax.concepts[f"{NS}Child"].broader == [f"{NS}Other"]
    assert f"{NS}Child" in tax.concepts[f"{NS}Other"].narrower
    assert f"{NS}Child" not in tax.concepts[f"{NS}Top"].narrower
    assert len(pers.saved) == 1


def test_move_concept_to_top_detaches_to_scheme() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosMoveConcept(PATH, f"{NS}Child", None))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert tax.concepts[f"{NS}Child"].broader == []
    assert f"{NS}Child" in tax.schemes[f"{NS}Scheme"].top_concepts


def test_move_concept_circular_fails_without_side_effects() -> None:
    svc, ws, pers = _skos_service()
    original = ws.taxonomies[PATH]
    # Moving Top under its own descendant Child is circular.
    result = svc.execute(SkosMoveConcept(PATH, f"{NS}Top", f"{NS}Child"))
    assert result.status == "failed"
    assert pers.saved == []
    assert ws.taxonomies[PATH] is original
    assert svc.version(PATH) == 0


# ── SkosAddBroader / SkosAddRelated (polyhierarchy + related links) ────────────────


def test_add_broader_link_keeps_existing_parent() -> None:
    svc, ws, pers = _skos_service()
    result = svc.execute(SkosMoveConcept(PATH, f"{NS}Child", f"{NS}Other", replace=False))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert set(tax.concepts[f"{NS}Child"].broader) == {f"{NS}Top", f"{NS}Other"}
    assert f"{NS}Child" in tax.concepts[f"{NS}Other"].narrower
    assert len(pers.saved) == 1


def test_add_related_is_symmetric() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosAddRelated(PATH, f"{NS}Child", f"{NS}Other"))
    assert result.ok
    assert result.affected_uris == (f"{NS}Child", f"{NS}Other")
    tax = ws.taxonomies[PATH]
    assert f"{NS}Other" in tax.concepts[f"{NS}Child"].related
    assert f"{NS}Child" in tax.concepts[f"{NS}Other"].related


# ── field edits: SkosSetLabel / SkosSetDefinition / SkosSetScopeNote ──────────────────────


def test_set_label_pref_replaces_existing_language() -> None:
    svc, ws, pers = _skos_service()
    result = svc.execute(SkosSetLabel(PATH, f"{NS}Top", "en", "Apex", "pref"))
    assert result.ok
    prefs = [
        lbl.value
        for lbl in ws.taxonomies[PATH].concepts[f"{NS}Top"].labels
        if lbl.lang == "en" and lbl.type == LabelType.PREF
    ]
    assert prefs == ["Apex"]  # replaced, not duplicated
    assert len(pers.saved) == 1


def test_set_label_alt_adds_label() -> None:
    svc, ws, _ = _skos_service()
    svc.execute(SkosSetLabel(PATH, f"{NS}Top", "en", "Summit", "alt"))
    alts = [
        lbl.value
        for lbl in ws.taxonomies[PATH].concepts[f"{NS}Top"].labels
        if lbl.type == LabelType.ALT
    ]
    assert "Summit" in alts


def test_set_definition_sets_value() -> None:
    svc, ws, _ = _skos_service()
    svc.execute(SkosSetDefinition(PATH, f"{NS}Top", "en", "the root"))
    defs = [d.value for d in ws.taxonomies[PATH].concepts[f"{NS}Top"].definitions if d.lang == "en"]
    assert defs == ["the root"]


def test_set_scope_note_sets_value() -> None:
    svc, ws, _ = _skos_service()
    svc.execute(SkosSetScopeNote(PATH, f"{NS}Top", "en", "use for tops only"))
    notes = [
        n.value for n in ws.taxonomies[PATH].concepts[f"{NS}Top"].scope_notes if n.lang == "en"
    ]
    assert notes == ["use for tops only"]


_DUP_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix t: <https://ex.org/t/> .
t:Scheme a skos:ConceptScheme ; skos:hasTopConcept t:Top, t:Other .
t:Top a skos:Concept ; skos:inScheme t:Scheme ; skos:topConceptOf t:Scheme ;
      skos:prefLabel "Top"@en .
t:Other a skos:Concept ; skos:inScheme t:Scheme ; skos:topConceptOf t:Scheme ;
        skos:prefLabel "Other"@en .
"""


def test_set_label_introducing_duplicate_pref_is_blocked(tmp_path) -> None:
    """The validation gate fires end-to-end: renaming Other's label to Top's is rejected."""
    f = tmp_path / "dup.ttl"
    f.write_text(_DUP_TTL)
    ws = _FakeWorkspace({f: store.load(f)})
    pers = _FakePersistence()
    svc = TaxonomyService(ws, pers, SkosValidatorAdapter())

    result = svc.execute(SkosSetLabel(f, f"{NS}Other", "en", "Top", "pref"))
    assert result.status == "failed"
    assert result.validation and any(i.code == "dup_pref_label" for i in result.validation.errors)
    assert pers.saved == []  # blocked before persist


# ── delete entity: SkosRemoveConcept / OwlDeleteClass ─────────────────────────


def test_remove_concept_deletes_leaf() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosRemoveConcept(PATH, f"{NS}Child"))
    assert result.ok
    assert f"{NS}Child" not in ws.taxonomies[PATH].concepts
    assert f"{NS}Child" not in ws.taxonomies[PATH].concepts[f"{NS}Top"].narrower


def test_remove_concept_cascade_removes_descendants() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosRemoveConcept(PATH, f"{NS}Top", cascade=True))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert f"{NS}Top" not in tax.concepts
    assert f"{NS}Child" not in tax.concepts  # descendant removed too


def test_delete_owl_class() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OwlDeleteClass(PATH, f"{NS}Dog", "keep_all"))
    assert result.ok
    assert f"{NS}Dog" not in ws.taxonomies[PATH].owl_classes


# ── SkosCreateScheme ───────────────────────────────────────────────────────────


def test_create_scheme_adds_scheme() -> None:
    svc, ws, pers = _skos_service()
    result = svc.execute(SkosCreateScheme(PATH, f"{NS}Scheme2", {"en": "Second"}, "", ("en",)))
    assert result.ok
    assert result.affected_uris == (f"{NS}Scheme2",)
    assert f"{NS}Scheme2" in ws.taxonomies[PATH].schemes
    assert len(pers.saved) == 1


# ── OntoRenameUri (ontology-level) ─────────────────────────────────────────────


def test_onto_rename_uri_propagates_to_local_entities() -> None:
    svc, ws, _ = _service()  # OWL taxonomy: ontology_uri https://ex.org/t, classes under .../t/
    result = svc.execute(OntoRenameUri(PATH, "https://new.org/onto", "/"))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert tax.ontology_uri == "https://new.org/onto"
    assert "https://new.org/onto/Dog" in tax.owl_classes
    assert "https://ex.org/t/Dog" not in tax.owl_classes


# ── RenameEntity (cross-layer) ─────────────────────────────────────────────────


def test_rename_entity_renames_concept() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(RenameEntity(PATH, f"{NS}Child", f"{NS}Renamed"))
    assert result.ok
    assert result.affected_uris == (f"{NS}Renamed",)
    tax = ws.taxonomies[PATH]
    assert f"{NS}Renamed" in tax.concepts
    assert f"{NS}Child" not in tax.concepts


def test_rename_entity_renames_owl_class() -> None:
    svc, ws, _ = _service()  # OWL taxonomy
    result = svc.execute(RenameEntity(PATH, f"{NS}Dog", f"{NS}Canine"))
    assert result.ok
    assert f"{NS}Canine" in ws.taxonomies[PATH].owl_classes
    assert f"{NS}Dog" not in ws.taxonomies[PATH].owl_classes


def test_rename_entity_collision_fails_without_side_effects() -> None:
    svc, ws, pers = _skos_service()
    original = ws.taxonomies[PATH]
    result = svc.execute(RenameEntity(PATH, f"{NS}Child", f"{NS}Other"))  # Other exists
    assert result.status == "failed"
    assert pers.saved == []
    assert ws.taxonomies[PATH] is original


# ── remove field: SkosRemoveLabel / SkosRemoveDefinition / SkosRemoveScopeNote ────────────


def test_remove_label_removes_matching() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosRemoveLabel(PATH, f"{NS}Top", "en", "Top", "pref"))
    assert result.ok
    labels = [lbl.value for lbl in ws.taxonomies[PATH].concepts[f"{NS}Top"].labels]
    assert "Top" not in labels


def test_remove_definition_clears_language() -> None:
    svc, ws, _ = _skos_service()
    svc.execute(SkosSetDefinition(PATH, f"{NS}Top", "en", "the root"))
    svc.execute(SkosRemoveDefinition(PATH, f"{NS}Top", "en"))
    assert ws.taxonomies[PATH].concepts[f"{NS}Top"].definitions == []


def test_remove_scope_note_removes_matching() -> None:
    svc, ws, _ = _skos_service()
    svc.execute(SkosSetScopeNote(PATH, f"{NS}Top", "en", "note"))
    svc.execute(SkosRemoveScopeNote(PATH, f"{NS}Top", "en", "note"))
    assert ws.taxonomies[PATH].concepts[f"{NS}Top"].scope_notes == []


# ── validation gate (Phase 3 — delta, block on newly introduced errors) ───────


def _validator(fn):
    """Build a Validator port whose check(tax) delegates to fn(tax) -> issues list."""
    from ster.validator import ValidationIssue

    class _V:
        def check(self, taxonomy):
            return tuple(fn(taxonomy, ValidationIssue))

    return _V()


def _service_with_validator(fn):
    ws = _FakeWorkspace({PATH: _taxonomy()})
    pers = _FakePersistence()
    return TaxonomyService(ws, pers, _validator(fn)), ws, pers


def test_newly_introduced_error_blocks_and_does_not_persist() -> None:
    # Error appears only once the change is applied (Dog gains Mammal).
    def fn(tax, Issue):
        if f"{NS}Mammal" in tax.owl_classes[f"{NS}Dog"].sub_class_of:
            return [Issue("error", "bad_reparent", f"{NS}Dog", "Dog cannot be a Mammal")]
        return []

    svc, ws, pers = _service_with_validator(fn)
    original = ws.taxonomies[PATH]
    result = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal", replace=True))
    assert result.status == "failed"
    assert result.validation and result.validation.errors
    assert pers.saved == []  # blocked before persist
    assert svc.version(PATH) == 0
    assert ws.taxonomies[PATH] is original  # authority untouched


def test_preexisting_error_does_not_block() -> None:
    # Same error present before AND after — not introduced by this change → allowed.
    def fn(tax, Issue):
        return [Issue("error", "legacy", f"{NS}Animal", "pre-existing problem elsewhere")]

    svc, _, pers = _service_with_validator(fn)
    result = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal", replace=True))
    assert result.ok  # delta is empty → no block
    assert len(pers.saved) == 1


def test_introduced_warning_is_reported_but_commits() -> None:
    def fn(tax, Issue):
        if f"{NS}Mammal" in tax.owl_classes[f"{NS}Dog"].sub_class_of:
            return [Issue("warning", "style", f"{NS}Dog", "consider a label")]
        return []

    svc, _, pers = _service_with_validator(fn)
    result = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal", replace=True))
    assert result.ok
    assert result.validation and result.validation.warnings
    assert not result.validation.errors
    assert len(pers.saved) == 1  # warnings do not block


def test_concurrent_executes_do_not_lose_updates() -> None:
    svc, _, pers = _service()
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert svc.version(PATH) == 8  # every commit counted, no lost update
    assert len(pers.saved) == 8
