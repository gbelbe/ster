"""Unit tests for ster.core.service.TaxonomyService (Phase 2 — OwlMoveClass slice)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from ster import store
from ster.core.commands import (
    AddSchemaMedia,
    ChangeSet,
    OntoRenameUri,
    OntoSetMetadata,
    OntoSetPrefix,
    OwlAddExternalSuperclass,
    OwlAddIndividualType,
    OwlAddProperty,
    OwlAddPropertyClass,
    OwlConvertClassToIndividual,
    OwlConvertIndividualToClass,
    OwlCreateIndividual,
    OwlCreateSubclass,
    OwlDeleteClass,
    OwlDeleteIndividual,
    OwlDeleteProperty,
    OwlMoveClass,
    OwlRemoveIndividualLiteral,
    OwlRemoveIndividualType,
    OwlRemoveIndividualValue,
    OwlRemovePropertyClass,
    OwlRemoveSuperclass,
    OwlSetComment,
    OwlSetIndividualLiteral,
    OwlSetIndividualValue,
    OwlSetLabel,
    OwlSetNote,
    RemoveSchemaMedia,
    RenameEntity,
    SkosAddConcept,
    SkosAddMappingLink,
    SkosAddRelated,
    SkosCreateScheme,
    SkosMoveConcept,
    SkosRemoveConcept,
    SkosRemoveDefinition,
    SkosRemoveLabel,
    SkosRemoveMappingLink,
    SkosRemoveScopeNote,
    SkosSetDefinition,
    SkosSetLabel,
    SkosSetSchemeField,
    SkosSetScopeNote,
)
from ster.core.service import TaxonomyService
from ster.core.validation import SkosValidatorAdapter
from ster.model import (
    Concept,
    ConceptScheme,
    Label,
    LabelType,
    OWLIndividual,
    OWLProperty,
    RDFClass,
    Taxonomy,
)

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


# ── SkosSetSchemeField (one command, dispatch-table over the 6 scheme fields) ───


def _scheme(ws: _FakeWorkspace) -> ConceptScheme:
    return ws.taxonomies[PATH].schemes[f"{NS}Scheme"]


def test_set_scheme_title_upserts_pref_label() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosSetSchemeField(PATH, f"{NS}Scheme", "title", "Animals", "en"))
    assert result.ok
    assert _scheme(ws).title("en") == "Animals"


def test_set_scheme_desc_sets_description() -> None:
    svc, ws, _ = _skos_service()
    svc.execute(SkosSetSchemeField(PATH, f"{NS}Scheme", "desc", "all the animals", "en"))
    assert [(d.lang, d.value) for d in _scheme(ws).descriptions] == [("en", "all the animals")]


def test_set_scheme_base_uri() -> None:
    svc, ws, _ = _skos_service()
    svc.execute(SkosSetSchemeField(PATH, f"{NS}Scheme", "base_uri", "https://ex.org/a/"))
    assert _scheme(ws).base_uri == "https://ex.org/a/"


def test_set_scheme_creator_and_created() -> None:
    svc, ws, _ = _skos_service()
    svc.execute(SkosSetSchemeField(PATH, f"{NS}Scheme", "creator", "Ada"))
    svc.execute(SkosSetSchemeField(PATH, f"{NS}Scheme", "created", "2026-06-11"))
    assert _scheme(ws).creator == "Ada"
    assert _scheme(ws).created == "2026-06-11"


def test_set_scheme_languages_parses_csv() -> None:
    svc, ws, _ = _skos_service()
    svc.execute(SkosSetSchemeField(PATH, f"{NS}Scheme", "languages", " en , fr ,, nl "))
    assert _scheme(ws).languages == ["en", "fr", "nl"]


def test_set_scheme_field_unknown_field_is_noop() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosSetSchemeField(PATH, f"{NS}Scheme", "bogus", "x"))
    assert result.ok
    assert _scheme(ws).creator == ""


def test_set_scheme_field_unknown_scheme_is_noop() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosSetSchemeField(PATH, f"{NS}Ghost", "title", "x", "en"))
    assert result.ok
    assert f"{NS}Ghost" not in ws.taxonomies[PATH].schemes


# ── OwlDeleteProperty (declaration only vs clear-values-then-delete) ───────────


def _service_with_property() -> tuple[TaxonomyService, _FakeWorkspace, _FakePersistence]:
    svc, ws, pers = _service()
    tax = ws.taxonomies[PATH]
    tax.owl_properties[f"{NS}hasColor"] = OWLProperty(
        uri=f"{NS}hasColor", prop_type="DatatypeProperty"
    )
    tax.owl_individuals[f"{NS}d"] = OWLIndividual(
        uri=f"{NS}d", property_values=[(f"{NS}hasColor", f"{NS}red")]
    )
    return svc, ws, pers


def test_delete_property_declaration_only_keeps_values() -> None:
    svc, ws, _ = _service_with_property()
    result = svc.execute(OwlDeleteProperty(PATH, f"{NS}hasColor", clear_values=False))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert f"{NS}hasColor" not in tax.owl_properties
    assert tax.owl_individuals[f"{NS}d"].property_values == [(f"{NS}hasColor", f"{NS}red")]


def test_delete_property_clear_values_strips_them_first() -> None:
    svc, ws, _ = _service_with_property()
    result = svc.execute(OwlDeleteProperty(PATH, f"{NS}hasColor", clear_values=True))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert f"{NS}hasColor" not in tax.owl_properties
    assert tax.owl_individuals[f"{NS}d"].property_values == []


# ── OntoRenameUri (ontology-level) ─────────────────────────────────────────────


def test_onto_rename_uri_propagates_to_local_entities() -> None:
    svc, ws, _ = _service()  # OWL taxonomy: ontology_uri https://ex.org/t, classes under .../t/
    result = svc.execute(OntoRenameUri(PATH, "https://new.org/onto", "/"))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert tax.ontology_uri == "https://new.org/onto"
    assert "https://new.org/onto/Dog" in tax.owl_classes
    assert "https://ex.org/t/Dog" not in tax.owl_classes


# ── OntoSetMetadata (ontology label / title / description) ──────────────────────


def test_set_ontology_label() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OntoSetMetadata(PATH, "label", "My Ontology"))
    assert result.ok
    assert ws.taxonomies[PATH].ontology_label == "My Ontology"


def test_set_ontology_title_and_description() -> None:
    svc, ws, _ = _service()
    svc.execute(OntoSetMetadata(PATH, "title", "Title"))
    svc.execute(OntoSetMetadata(PATH, "description", "A description"))
    tax = ws.taxonomies[PATH]
    assert tax.ontology_title == "Title"
    assert tax.ontology_description == "A description"


def test_set_ontology_metadata_blank_clears_to_none() -> None:
    svc, ws, _ = _service()
    svc.execute(OntoSetMetadata(PATH, "label", "X"))
    svc.execute(OntoSetMetadata(PATH, "label", ""))
    assert ws.taxonomies[PATH].ontology_label is None


def test_set_ontology_metadata_unknown_field_is_noop() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OntoSetMetadata(PATH, "bogus", "x"))
    assert result.ok
    assert ws.taxonomies[PATH].ontology_label is None


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


# ── ChangeSet (atomic batch transaction) ───────────────────────────────────────


def test_changeset_applies_all_commands_atomically() -> None:
    svc, ws, pers = _skos_service()
    cs = ChangeSet(
        PATH,
        (
            SkosSetDefinition(PATH, f"{NS}Top", "en", "the top"),
            SkosSetDefinition(PATH, f"{NS}Child", "en", "a child"),
        ),
    )
    result = svc.execute(cs)
    assert result.ok
    assert svc.version(PATH) == 1  # one version bump for the whole batch
    assert len(pers.saved) == 1  # persisted once
    tax = ws.taxonomies[PATH]
    assert any(d.value == "the top" for d in tax.concepts[f"{NS}Top"].definitions)
    assert any(d.value == "a child" for d in tax.concepts[f"{NS}Child"].definitions)


def test_changeset_rolls_back_entirely_when_one_command_fails() -> None:
    svc, ws, pers = _skos_service()
    cs = ChangeSet(
        PATH,
        (
            SkosSetDefinition(PATH, f"{NS}Top", "en", "applied first"),
            SkosRemoveConcept(PATH, f"{NS}DoesNotExist"),  # raises ConceptNotFoundError
        ),
    )
    result = svc.execute(cs)
    assert result.status == "failed"
    assert svc.version(PATH) == 0  # no bump
    assert pers.saved == []  # nothing persisted
    # the first command's effect was rolled back with the batch
    assert ws.taxonomies[PATH].concepts[f"{NS}Top"].definitions == []


# ── SkosAddConcept ──────────────────────────────────────────────────────────────


def test_add_concept_as_scheme_top_concept() -> None:
    svc, ws, pers = _skos_service()
    result = svc.execute(
        SkosAddConcept(PATH, f"{NS}New", {"en": "New"}, parent_handle=f"{NS}Scheme")
    )
    assert result.ok
    assert result.affected_uris == (f"{NS}New",)
    tax = ws.taxonomies[PATH]
    assert f"{NS}New" in tax.concepts
    assert f"{NS}New" in tax.schemes[f"{NS}Scheme"].top_concepts
    assert len(pers.saved) == 1


def test_add_concept_under_a_parent_concept() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosAddConcept(PATH, f"{NS}Pup", {"en": "Pup"}, parent_handle=f"{NS}Top"))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert tax.concepts[f"{NS}Pup"].broader == [f"{NS}Top"]
    assert f"{NS}Pup" in tax.concepts[f"{NS}Top"].narrower


# ── OwlAddProperty (bare vs domain-typed) ──────────────────────────────────────


def test_add_property_bare_matches_default_owl_property() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OwlAddProperty(PATH, f"{NS}rel", "ObjectProperty", "", "en"))
    assert result.ok
    prop = ws.taxonomies[PATH].owl_properties[f"{NS}rel"]
    assert prop.prop_type == "ObjectProperty"
    assert prop.labels == [] and prop.domains == [] and prop.ranges == []


def test_add_property_with_domain_and_range() -> None:
    svc, ws, _ = _service()
    result = svc.execute(
        OwlAddProperty(PATH, f"{NS}eats", "ObjectProperty", "eats", "en", f"{NS}Dog", f"{NS}Animal")
    )
    assert result.ok
    prop = ws.taxonomies[PATH].owl_properties[f"{NS}eats"]
    assert prop.domains == [f"{NS}Dog"]
    assert prop.ranges == [f"{NS}Animal"]
    assert any(lbl.value == "eats" for lbl in prop.labels)


# ── OwlCreateSubclass (create class + link, swallowing bad links) ──────────────


def test_create_subclass_creates_and_links() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OwlCreateSubclass(PATH, f"{NS}Puppy", f"{NS}Dog"))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert tax.owl_classes[f"{NS}Puppy"].sub_class_of == [f"{NS}Dog"]


def test_create_subclass_no_parent_is_a_root() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OwlCreateSubclass(PATH, f"{NS}Thing", None))
    assert result.ok
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Thing"].sub_class_of == []


def test_create_subclass_swallows_missing_parent() -> None:
    svc, ws, _ = _service()
    # parent does not exist → the link is skipped, but the class is still created
    result = svc.execute(OwlCreateSubclass(PATH, f"{NS}Orphan", f"{NS}Ghost"))
    assert result.ok
    assert f"{NS}Orphan" in ws.taxonomies[PATH].owl_classes
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Orphan"].sub_class_of == []


# ── OwlSetLabel / OwlSetComment (rdfs:label / rdfs:comment, upsert by lang) ─────


def _owl_entities_service() -> tuple[TaxonomyService, _FakeWorkspace]:
    """Taxonomy with one class, one individual, one property — each label-bearing."""
    t = Taxonomy()
    t.ontology_uri = "https://ex.org/t"
    t.owl_classes[f"{NS}Dog"] = RDFClass(uri=f"{NS}Dog", labels=[Label(lang="en", value="Dog")])
    t.owl_individuals[f"{NS}Rex"] = OWLIndividual(uri=f"{NS}Rex", types=[f"{NS}Dog"])
    t.owl_properties[f"{NS}hasColor"] = OWLProperty(uri=f"{NS}hasColor")
    ws = _FakeWorkspace({PATH: t})
    return TaxonomyService(ws, _FakePersistence()), ws


def test_set_owl_label_replaces_existing_lang_on_class() -> None:
    svc, ws = _owl_entities_service()
    result = svc.execute(OwlSetLabel(PATH, f"{NS}Dog", "en", "Hound"))
    assert result.ok
    labels = ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].labels
    assert [(l.lang, l.value) for l in labels] == [("en", "Hound")]


def test_set_owl_label_appends_new_lang_on_individual() -> None:
    svc, ws = _owl_entities_service()
    result = svc.execute(OwlSetLabel(PATH, f"{NS}Rex", "fr", "Rex"))
    assert result.ok
    labels = ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].labels
    assert ("fr", "Rex") in [(l.lang, l.value) for l in labels]


def test_set_owl_comment_on_property() -> None:
    svc, ws = _owl_entities_service()
    result = svc.execute(OwlSetComment(PATH, f"{NS}hasColor", "en", "the colour"))
    assert result.ok
    comments = ws.taxonomies[PATH].owl_properties[f"{NS}hasColor"].comments
    assert [(c.lang, c.value) for c in comments] == [("en", "the colour")]


def test_set_owl_label_missing_entity_is_noop() -> None:
    svc, ws = _owl_entities_service()
    result = svc.execute(OwlSetLabel(PATH, f"{NS}Ghost", "en", "x"))
    # unknown uri: command succeeds but changes nothing (matches the inline handler)
    assert result.ok
    assert f"{NS}Ghost" not in ws.taxonomies[PATH].owl_classes


# ── OwlCreateIndividual (create an individual, optionally typed) ────────────────


def test_create_individual_typed() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OwlCreateIndividual(PATH, f"{NS}Rex", f"{NS}Dog"))
    assert result.ok
    assert ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].types == [f"{NS}Dog"]


def test_create_individual_untyped() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OwlCreateIndividual(PATH, f"{NS}Thing", None))
    assert result.ok
    assert ws.taxonomies[PATH].owl_individuals[f"{NS}Thing"].types == []


def test_create_individual_existing_is_noop() -> None:
    svc, ws, _ = _service()
    svc.execute(OwlCreateIndividual(PATH, f"{NS}Rex", f"{NS}Dog"))
    # second create with a different type must not retype the existing individual
    result = svc.execute(OwlCreateIndividual(PATH, f"{NS}Rex", f"{NS}Mammal"))
    assert result.ok
    assert ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].types == [f"{NS}Dog"]


# ── OwlSetIndividualLiteral (edit a literal property value) ─────────────────────


def _service_with_individual_literal() -> tuple[TaxonomyService, _FakeWorkspace]:
    t = Taxonomy()
    t.ontology_uri = "https://ex.org/t"
    ind = OWLIndividual(uri=f"{NS}Rex", literal_values=[(f"{NS}age", "3", "")])
    t.owl_individuals[ind.uri] = ind
    ws = _FakeWorkspace({PATH: t})
    return TaxonomyService(ws, _FakePersistence()), ws


def test_set_individual_literal_replaces_existing() -> None:
    svc, ws = _service_with_individual_literal()
    result = svc.execute(OwlSetIndividualLiteral(PATH, f"{NS}Rex", f"{NS}age", "3", "4", ""))
    assert result.ok
    assert ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].literal_values == [(f"{NS}age", "4", "")]


def test_set_individual_literal_appends_when_no_match() -> None:
    svc, ws = _service_with_individual_literal()
    # old value "9" matches no existing triple → the new triple is appended
    result = svc.execute(OwlSetIndividualLiteral(PATH, f"{NS}Rex", f"{NS}age", "9", "5", ""))
    assert result.ok
    vals = ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].literal_values
    assert (f"{NS}age", "5", "") in vals


def test_set_individual_literal_missing_individual_is_noop() -> None:
    svc, ws = _service_with_individual_literal()
    result = svc.execute(OwlSetIndividualLiteral(PATH, f"{NS}Ghost", f"{NS}age", "3", "4", ""))
    assert result.ok
    assert f"{NS}Ghost" not in ws.taxonomies[PATH].owl_individuals


# ── AddSchemaMedia / RemoveSchemaMedia (cross-layer schema.org media) ───────────


def test_add_schema_media_image_on_class() -> None:
    svc, ws, _ = _service()
    result = svc.execute(AddSchemaMedia(PATH, f"{NS}Dog", "image", "https://ex.org/dog.png"))
    assert result.ok
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].schema_images == ["https://ex.org/dog.png"]


def test_add_schema_media_dedups() -> None:
    svc, ws, _ = _service()
    svc.execute(AddSchemaMedia(PATH, f"{NS}Dog", "url", "https://ex.org/d"))
    svc.execute(AddSchemaMedia(PATH, f"{NS}Dog", "url", "https://ex.org/d"))
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].schema_urls == ["https://ex.org/d"]


def test_add_schema_media_unknown_kind_is_noop() -> None:
    svc, ws, _ = _service()
    result = svc.execute(AddSchemaMedia(PATH, f"{NS}Dog", "bogus", "x"))
    assert result.ok
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].schema_images == []


def test_remove_schema_media_video() -> None:
    svc, ws, _ = _service()
    svc.execute(AddSchemaMedia(PATH, f"{NS}Dog", "video", "https://ex.org/v.mp4"))
    result = svc.execute(RemoveSchemaMedia(PATH, f"{NS}Dog", "video", "https://ex.org/v.mp4"))
    assert result.ok
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].schema_videos == []


def test_remove_schema_media_missing_url_is_noop() -> None:
    svc, ws, _ = _service()
    result = svc.execute(RemoveSchemaMedia(PATH, f"{NS}Dog", "image", "https://ex.org/none.png"))
    assert result.ok
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].schema_images == []


# ── OwlAddPropertyClass / OwlRemovePropertyClass (property domain & range) ──────


def test_add_property_domain_and_range() -> None:
    svc, ws, _ = _service_with_property()
    svc.execute(OwlAddPropertyClass(PATH, f"{NS}hasColor", "domain", f"{NS}Dog"))
    svc.execute(OwlAddPropertyClass(PATH, f"{NS}hasColor", "range", f"{NS}Animal"))
    prop = ws.taxonomies[PATH].owl_properties[f"{NS}hasColor"]
    assert prop.domains == [f"{NS}Dog"]
    assert prop.ranges == [f"{NS}Animal"]


def test_add_property_class_dedups() -> None:
    svc, ws, _ = _service_with_property()
    svc.execute(OwlAddPropertyClass(PATH, f"{NS}hasColor", "domain", f"{NS}Dog"))
    svc.execute(OwlAddPropertyClass(PATH, f"{NS}hasColor", "domain", f"{NS}Dog"))
    assert ws.taxonomies[PATH].owl_properties[f"{NS}hasColor"].domains == [f"{NS}Dog"]


def test_add_property_class_unknown_slot_is_noop() -> None:
    svc, ws, _ = _service_with_property()
    result = svc.execute(OwlAddPropertyClass(PATH, f"{NS}hasColor", "bogus", f"{NS}Dog"))
    assert result.ok
    prop = ws.taxonomies[PATH].owl_properties[f"{NS}hasColor"]
    assert prop.domains == [] and prop.ranges == []


def test_remove_property_domain() -> None:
    svc, ws, _ = _service_with_property()
    svc.execute(OwlAddPropertyClass(PATH, f"{NS}hasColor", "domain", f"{NS}Dog"))
    result = svc.execute(OwlRemovePropertyClass(PATH, f"{NS}hasColor", "domain", f"{NS}Dog"))
    assert result.ok
    assert ws.taxonomies[PATH].owl_properties[f"{NS}hasColor"].domains == []


def test_remove_property_class_absent_is_noop() -> None:
    svc, ws, _ = _service_with_property()
    result = svc.execute(OwlRemovePropertyClass(PATH, f"{NS}hasColor", "range", f"{NS}Ghost"))
    assert result.ok
    assert ws.taxonomies[PATH].owl_properties[f"{NS}hasColor"].ranges == []


# ── _trigger_action removes: superclass / individual / value / literal / type ───


def _service_with_rich_individual() -> tuple[TaxonomyService, _FakeWorkspace]:
    t = _taxonomy()  # Animal, Mammal, Dog(sub_class_of Animal)
    t.owl_individuals[f"{NS}Rex"] = OWLIndividual(
        uri=f"{NS}Rex",
        types=[f"{NS}Dog", f"{NS}Mammal"],
        property_values=[(f"{NS}owner", f"{NS}Ann")],
        literal_values=[(f"{NS}age", "3", "")],
    )
    ws = _FakeWorkspace({PATH: t})
    return TaxonomyService(ws, _FakePersistence()), ws


def test_remove_superclass_detaches_one_parent() -> None:
    svc, ws, _ = _service()
    result = svc.execute(OwlRemoveSuperclass(PATH, f"{NS}Dog", f"{NS}Animal"))
    assert result.ok
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].sub_class_of == []


def test_delete_individual_removes_it() -> None:
    svc, ws = _service_with_rich_individual()
    result = svc.execute(OwlDeleteIndividual(PATH, f"{NS}Rex"))
    assert result.ok
    assert f"{NS}Rex" not in ws.taxonomies[PATH].owl_individuals


def test_remove_individual_property_value() -> None:
    svc, ws = _service_with_rich_individual()
    result = svc.execute(OwlRemoveIndividualValue(PATH, f"{NS}Rex", f"{NS}owner", f"{NS}Ann"))
    assert result.ok
    assert ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].property_values == []


def test_remove_individual_literal() -> None:
    svc, ws = _service_with_rich_individual()
    result = svc.execute(OwlRemoveIndividualLiteral(PATH, f"{NS}Rex", f"{NS}age", "3", ""))
    assert result.ok
    assert ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].literal_values == []


def test_remove_individual_type() -> None:
    svc, ws = _service_with_rich_individual()
    result = svc.execute(OwlRemoveIndividualType(PATH, f"{NS}Rex", f"{NS}Mammal"))
    assert result.ok
    assert ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].types == [f"{NS}Dog"]


def test_remove_individual_ops_missing_individual_are_noops() -> None:
    svc, ws = _service_with_rich_individual()
    assert svc.execute(OwlRemoveIndividualType(PATH, f"{NS}Ghost", f"{NS}Dog")).ok
    assert svc.execute(OwlRemoveIndividualValue(PATH, f"{NS}Ghost", f"{NS}o", f"{NS}v")).ok
    assert svc.execute(OwlRemoveIndividualLiteral(PATH, f"{NS}Ghost", f"{NS}age", "3", "")).ok
    assert f"{NS}Ghost" not in ws.taxonomies[PATH].owl_individuals


# ── add_prop_value / add_ind_type confirm paths (OwlSetIndividualValue / Type) ──


def test_add_individual_type_dedups() -> None:
    svc, ws = _service_with_rich_individual()  # Rex types [Dog, Mammal]
    svc.execute(OwlAddIndividualType(PATH, f"{NS}Rex", f"{NS}Animal"))
    svc.execute(OwlAddIndividualType(PATH, f"{NS}Rex", f"{NS}Animal"))
    assert ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].types == [
        f"{NS}Dog",
        f"{NS}Mammal",
        f"{NS}Animal",
    ]


def test_set_individual_value_appends_new_pair() -> None:
    svc, ws = _service_with_rich_individual()  # Rex owner Ann
    result = svc.execute(OwlSetIndividualValue(PATH, f"{NS}Rex", f"{NS}owner", f"{NS}Bob"))
    assert result.ok
    assert (f"{NS}owner", f"{NS}Bob") in ws.taxonomies[PATH].owl_individuals[
        f"{NS}Rex"
    ].property_values


def test_set_individual_value_replaces_old_pair() -> None:
    svc, ws = _service_with_rich_individual()
    result = svc.execute(
        OwlSetIndividualValue(PATH, f"{NS}Rex", f"{NS}owner", f"{NS}Bob", old_val_uri=f"{NS}Ann")
    )
    assert result.ok
    vals = ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].property_values
    assert vals == [(f"{NS}owner", f"{NS}Bob")]


def test_set_individual_value_dedups_when_present() -> None:
    svc, ws = _service_with_rich_individual()
    svc.execute(OwlSetIndividualValue(PATH, f"{NS}Rex", f"{NS}owner", f"{NS}Ann"))
    assert ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].property_values == [
        (f"{NS}owner", f"{NS}Ann")
    ]


# ── SkosAddMappingLink / SkosRemoveMappingLink (one directional cross-scheme link) ──


def test_add_mapping_link_appends_to_concept() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosAddMappingLink(PATH, f"{NS}Child", "exact_match", f"{NS}Other"))
    assert result.ok
    assert ws.taxonomies[PATH].concepts[f"{NS}Child"].exact_match == [f"{NS}Other"]


def test_add_mapping_link_dedups() -> None:
    svc, ws, _ = _skos_service()
    svc.execute(SkosAddMappingLink(PATH, f"{NS}Child", "broad_match", f"{NS}Other"))
    svc.execute(SkosAddMappingLink(PATH, f"{NS}Child", "broad_match", f"{NS}Other"))
    assert ws.taxonomies[PATH].concepts[f"{NS}Child"].broad_match == [f"{NS}Other"]


def test_remove_mapping_link() -> None:
    svc, ws, _ = _skos_service()
    svc.execute(SkosAddMappingLink(PATH, f"{NS}Child", "exact_match", f"{NS}Other"))
    result = svc.execute(SkosRemoveMappingLink(PATH, f"{NS}Child", "exact_match", f"{NS}Other"))
    assert result.ok
    assert ws.taxonomies[PATH].concepts[f"{NS}Child"].exact_match == []


def test_mapping_link_unknown_attr_is_noop() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosAddMappingLink(PATH, f"{NS}Child", "bogus_match", f"{NS}Other"))
    assert result.ok
    assert ws.taxonomies[PATH].concepts[f"{NS}Child"].exact_match == []


def test_mapping_link_unknown_concept_is_noop() -> None:
    svc, ws, _ = _skos_service()
    result = svc.execute(SkosAddMappingLink(PATH, f"{NS}Ghost", "exact_match", f"{NS}Other"))
    assert result.ok
    assert f"{NS}Ghost" not in ws.taxonomies[PATH].concepts


# ── class ↔ individual conversion (punning) ─────────────────────────────────────


def test_convert_class_to_individual_carries_supertypes() -> None:
    svc, ws, _ = _service()  # Dog sub_class_of Animal
    result = svc.execute(OwlConvertClassToIndividual(PATH, f"{NS}Dog"))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert f"{NS}Dog" not in tax.owl_classes
    assert tax.owl_individuals[f"{NS}Dog"].types == [f"{NS}Animal"]


def test_convert_class_to_individual_reattaches_affected() -> None:
    svc, ws, _ = _service()
    ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"] = OWLIndividual(
        uri=f"{NS}Rex", types=[f"{NS}Dog"]
    )
    result = svc.execute(
        OwlConvertClassToIndividual(PATH, f"{NS}Dog", reattach_to=(f"{NS}Animal",))
    )
    assert result.ok
    assert ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"].types == [f"{NS}Animal"]


def test_convert_class_to_individual_deletes_affected_without_reattach() -> None:
    svc, ws, _ = _service()
    ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"] = OWLIndividual(
        uri=f"{NS}Rex", types=[f"{NS}Dog"]
    )
    result = svc.execute(OwlConvertClassToIndividual(PATH, f"{NS}Dog"))
    assert result.ok
    assert f"{NS}Rex" not in ws.taxonomies[PATH].owl_individuals


def test_convert_class_to_individual_scrubs_references() -> None:
    svc, ws, _ = _service()
    tax = ws.taxonomies[PATH]
    tax.owl_classes[f"{NS}Puppy"] = RDFClass(uri=f"{NS}Puppy", sub_class_of=[f"{NS}Dog"])
    tax.owl_properties[f"{NS}p"] = OWLProperty(uri=f"{NS}p", domains=[f"{NS}Dog"])
    svc.execute(OwlConvertClassToIndividual(PATH, f"{NS}Dog"))
    tax = ws.taxonomies[PATH]
    assert tax.owl_classes[f"{NS}Puppy"].sub_class_of == []
    assert tax.owl_properties[f"{NS}p"].domains == []


def test_convert_individual_to_class_carries_types() -> None:
    svc, ws, _ = _service()
    ws.taxonomies[PATH].owl_individuals[f"{NS}Rex"] = OWLIndividual(
        uri=f"{NS}Rex", types=[f"{NS}Dog"]
    )
    result = svc.execute(OwlConvertIndividualToClass(PATH, f"{NS}Rex"))
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert f"{NS}Rex" not in tax.owl_individuals
    assert tax.owl_classes[f"{NS}Rex"].sub_class_of == [f"{NS}Dog"]


def test_convert_individual_to_class_strips_pointing_values() -> None:
    svc, ws, _ = _service()
    tax = ws.taxonomies[PATH]
    tax.owl_individuals[f"{NS}Rex"] = OWLIndividual(uri=f"{NS}Rex", types=[f"{NS}Dog"])
    tax.owl_individuals[f"{NS}Ann"] = OWLIndividual(
        uri=f"{NS}Ann", property_values=[(f"{NS}owns", f"{NS}Rex")]
    )
    svc.execute(OwlConvertIndividualToClass(PATH, f"{NS}Rex"))
    assert ws.taxonomies[PATH].owl_individuals[f"{NS}Ann"].property_values == []


def test_convert_unknown_entity_is_noop() -> None:
    svc, ws, _ = _service()
    assert svc.execute(OwlConvertClassToIndividual(PATH, f"{NS}Ghost")).ok
    assert svc.execute(OwlConvertIndividualToClass(PATH, f"{NS}Ghost")).ok


# ── OwlSetNote / OwlAddExternalSuperclass / OntoSetPrefix (final sweep) ──────────


def test_set_owl_note_and_clear() -> None:
    svc, ws, _ = _service()
    svc.execute(OwlSetNote(PATH, f"{NS}Dog", "a note"))
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].note == "a note"
    svc.execute(OwlSetNote(PATH, f"{NS}Dog", ""))
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].note == ""


def test_add_external_superclass_stubs_class_and_namespace() -> None:
    svc, ws, _ = _service()
    ext = "https://schema.org/Thing"
    result = svc.execute(
        OwlAddExternalSuperclass(PATH, f"{NS}Dog", ext, "https://schema.org/", "schema")
    )
    assert result.ok
    tax = ws.taxonomies[PATH]
    assert ext in tax.owl_classes[f"{NS}Dog"].sub_class_of
    assert ext in tax.owl_classes  # stubbed
    assert tax.namespace_bindings.get("schema") == "https://schema.org/"


def test_set_ontology_prefix_binds_when_absent() -> None:
    svc, ws, _ = _service()  # ontology_uri https://ex.org/t (no prefix bound)
    result = svc.execute(OntoSetPrefix(PATH, "ex"))
    assert result.ok
    assert "ex" in ws.taxonomies[PATH].namespace_bindings


def test_set_ontology_prefix_renames_existing() -> None:
    svc, ws, _ = _service()
    ws.taxonomies[PATH].namespace_bindings["old"] = "https://ex.org/t/"
    svc.execute(OntoSetPrefix(PATH, "neo"))
    binds = ws.taxonomies[PATH].namespace_bindings
    assert "neo" in binds and "old" not in binds


def test_execute_persist_false_swaps_authority_without_writing() -> None:
    """persist=False mutates + swaps the in-memory authority but skips the disk write, so
    the TUI can persist on a background worker (snappy edits on large ontologies)."""
    svc, ws, pers = _service()
    result = svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal"), persist=False)
    assert result.ok
    assert ws.taxonomies[PATH].owl_classes[f"{NS}Dog"].sub_class_of == [f"{NS}Mammal"]  # swapped
    assert pers.saved == []  # nothing written to disk


def test_execute_persists_by_default() -> None:
    svc, _ws, pers = _service()
    assert svc.execute(OwlMoveClass(PATH, f"{NS}Dog", f"{NS}Mammal")).ok
    assert len(pers.saved) == 1  # default persist=True writes
