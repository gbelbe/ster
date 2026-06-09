"""Covers the viewer → TaxonomyService wiring for OWL reparent + SKOS move.

Exercises _confirm_owl_reparent / _confirm_move and their shared helpers
(_owner_path, _finish_mutation, _focus_tree_on, _post_save_effects, _service)
without a live terminal — TaxonomyViewer constructs fine without curses.
"""

from __future__ import annotations

import curses
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from ster import store
from ster.model import RDFClass, Taxonomy
from ster.nav.state import (
    ConfirmDeleteState,
    DeleteClassChoiceState,
    DetailState,
    MovePickState,
    OntologyRenameConfirmState,
    RenameUriConfirmState,
    SchemeCreateState,
)
from ster.nav.viewer import TaxonomyViewer

NS = "https://ex.org/t/"


def _owl_taxonomy() -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = "https://ex.org/t"
    t.owl_classes[f"{NS}Animal"] = RDFClass(uri=f"{NS}Animal")
    t.owl_classes[f"{NS}Mammal"] = RDFClass(uri=f"{NS}Mammal")
    t.owl_classes[f"{NS}Dog"] = RDFClass(uri=f"{NS}Dog", sub_class_of=[f"{NS}Animal"])
    return t


def _viewer(tmp_path: Path) -> TaxonomyViewer:
    tax = _owl_taxonomy()
    f = tmp_path / "onto.ttl"
    store.save(tax, f)
    v = TaxonomyViewer(tax, f, lang="en")
    v._workspace.taxonomies[f] = tax  # ensure the service authority is populated
    v.taxonomy = tax
    return v


def test_reparent_replace_routes_through_service_and_saves(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v._state = MovePickState(source_uri=f"{NS}Dog")
    v._confirm_owl_reparent(f"{NS}Mammal", replace=True)

    # model updated (authority swapped + re-synced) …
    assert v.taxonomy.owl_classes[f"{NS}Dog"].sub_class_of == [f"{NS}Mammal"]
    # … and persisted to disk
    assert store.load(v.file_path).owl_classes[f"{NS}Dog"].sub_class_of == [f"{NS}Mammal"]
    assert isinstance(v._state, DetailState)


def test_reparent_add_keeps_existing_parent(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v._state = MovePickState(source_uri=f"{NS}Dog")
    v._confirm_owl_reparent(f"{NS}Mammal", replace=False)
    assert set(v.taxonomy.owl_classes[f"{NS}Dog"].sub_class_of) == {f"{NS}Animal", f"{NS}Mammal"}


def test_reparent_unknown_class_is_a_noop(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v._state = MovePickState(source_uri=f"{NS}Ghost")
    v._confirm_owl_reparent(f"{NS}Mammal", replace=True)
    assert isinstance(v._state, DetailState)
    # nothing changed on the real class
    assert v.taxonomy.owl_classes[f"{NS}Dog"].sub_class_of == [f"{NS}Animal"]


def test_finish_mutation_shows_validation_error(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    issue = SimpleNamespace(severity="error", message="Dog cannot be a Mammal")
    result = SimpleNamespace(
        ok=False, validation=SimpleNamespace(errors=[issue], warnings=[]), error=None
    )
    v._finish_mutation(result, f"{NS}Dog", v.file_path, v._bcdf)
    assert v._status == "Dog cannot be a Mammal"
    assert isinstance(v._state, DetailState)


def test_finish_mutation_shows_plain_error_when_no_validation(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    result = SimpleNamespace(ok=False, validation=None, error="domain boom")
    v._finish_mutation(result, f"{NS}Dog", v.file_path, v._bcdf)
    assert v._status == "domain boom"


def test_finish_mutation_appends_warning_count_on_success(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    warn = SimpleNamespace(severity="warning", message="consider a label")
    result = SimpleNamespace(
        ok=True, validation=SimpleNamespace(errors=[], warnings=[warn]), error=None
    )
    v._finish_mutation(result, f"{NS}Dog", v.file_path, v._bcdf)
    assert "1 warning(s)" in v._status


# ── SKOS concept move wiring (Phase 4a) ───────────────────────────────────────

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


def _skos_viewer(tmp_path: Path) -> TaxonomyViewer:
    f = tmp_path / "skos.ttl"
    f.write_text(_SKOS_TTL)
    tax = store.load(f)
    v = TaxonomyViewer(tax, f, lang="en")
    v._workspace.taxonomies[f] = tax
    v.taxonomy = tax
    return v


def test_concept_move_routes_through_service_and_saves(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._state = MovePickState(source_uri=f"{NS}Child")
    v._confirm_move(f"{NS}Other")
    assert v.taxonomy.concepts[f"{NS}Child"].broader == [f"{NS}Other"]
    assert store.load(v.file_path).concepts[f"{NS}Child"].broader == [f"{NS}Other"]
    assert isinstance(v._state, DetailState)


def test_add_related_routes_through_service_and_saves(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._state = MovePickState(source_uri=f"{NS}Child")
    v._confirm_related(f"{NS}Other")
    assert f"{NS}Other" in v.taxonomy.concepts[f"{NS}Child"].related
    assert f"{NS}Other" in store.load(v.file_path).concepts[f"{NS}Child"].related


def test_add_broader_link_routes_through_service_and_saves(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._state = MovePickState(source_uri=f"{NS}Child")
    v._confirm_link(f"{NS}Other")
    assert set(v.taxonomy.concepts[f"{NS}Child"].broader) == {f"{NS}Top", f"{NS}Other"}


def test_concept_field_edit_sets_pref_label_via_service(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._detail_uri = f"{NS}Child"
    field = SimpleNamespace(meta={"type": "pref", "lang": "en"})
    v._commit_concept_field(field, "Puppy")
    prefs = [lbl.value for lbl in v.taxonomy.concepts[f"{NS}Child"].labels if lbl.lang == "en"]
    assert "Puppy" in prefs
    saved = [lbl.value for lbl in store.load(v.file_path).concepts[f"{NS}Child"].labels]
    assert "Puppy" in saved  # persisted to disk


def test_concept_field_edit_sets_definition(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._detail_uri = f"{NS}Child"
    v._commit_concept_field(SimpleNamespace(meta={"type": "def", "lang": "en"}), "a young dog")
    defs = [d.value for d in v.taxonomy.concepts[f"{NS}Child"].definitions if d.lang == "en"]
    assert defs == ["a young dog"]


def test_concept_field_edit_sets_scope_note(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._detail_uri = f"{NS}Child"
    v._commit_concept_field(SimpleNamespace(meta={"type": "scope_note", "lang": "en"}), "puppies")
    notes = [n.value for n in v.taxonomy.concepts[f"{NS}Child"].scope_notes if n.lang == "en"]
    assert notes == ["puppies"]


def test_concept_field_edit_unknown_type_is_noop(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._detail_uri = f"{NS}Child"
    before = list(v.taxonomy.concepts[f"{NS}Child"].labels)
    v._commit_concept_field(SimpleNamespace(meta={"type": "bogus", "lang": "en"}), "x")
    assert v.taxonomy.concepts[f"{NS}Child"].labels == before


def test_finish_field_edit_shows_validation_error(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    issue = SimpleNamespace(severity="error", message="duplicate label")
    result = SimpleNamespace(
        ok=False, validation=SimpleNamespace(errors=[issue], warnings=[]), error=None
    )
    v._finish_field_edit(result, f"{NS}Child", v.file_path)
    assert v._status == "duplicate label"


def test_finish_field_edit_shows_plain_error(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    result = SimpleNamespace(ok=False, validation=None, error="nope")
    v._finish_field_edit(result, f"{NS}Child", v.file_path)
    assert v._status == "nope"


def test_finish_field_edit_appends_warnings_on_success(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    warn = SimpleNamespace(severity="warning", message="style")
    result = SimpleNamespace(
        ok=True, validation=SimpleNamespace(errors=[], warnings=[warn]), error=None
    )
    v._finish_field_edit(result, f"{NS}Child", v.file_path)
    assert "1 warning(s)" in v._status


# ── coverage for picker/media helpers pulled into the diff by insertions ──────


def test_reparent_stages_git_when_manager_present(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v._git_manager = MagicMock()  # exercise the git-stage branch of _post_save_effects
    v._state = MovePickState(source_uri=f"{NS}Dog")
    v._confirm_owl_reparent(f"{NS}Mammal", replace=True)
    v._git_manager.stage_file.assert_called()


def test_build_owl_class_candidates_excludes_self_and_descendants(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v._rebuild()
    cands = v._build_owl_class_candidates(f"{NS}Animal")
    uris = [u for u, _ in cands]
    assert "__TOP__" in uris
    assert f"{NS}Animal" not in uris  # self excluded


def test_on_move_pick_navigation_keys(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    ms = MovePickState(
        source_uri=f"{NS}Child",
        candidates=[(f"{NS}Top", "Top"), (f"{NS}Other", "Other")],
    )
    v._state = ms
    v._on_move_pick(curses.KEY_DOWN, 20)
    assert ms.cursor == 1
    v._on_move_pick(curses.KEY_UP, 20)
    assert ms.cursor == 0
    v._on_move_pick(curses.KEY_NPAGE, 20)
    v._on_move_pick(curses.KEY_PPAGE, 20)
    v._on_move_pick(ord("o"), 20)  # printable → filter
    assert ms.filter_text == "o"
    v._on_move_pick(curses.KEY_BACKSPACE, 20)
    assert ms.filter_text == ""
    v._on_move_pick(27, 20)  # Esc → back to detail
    assert isinstance(v._state, DetailState)


def test_on_move_pick_enter_confirms_move(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._state = MovePickState(
        source_uri=f"{NS}Child", candidates=[(f"{NS}Other", "Other")], cursor=0
    )
    v._on_move_pick(curses.KEY_ENTER, 20)
    assert v.taxonomy.concepts[f"{NS}Child"].broader == [f"{NS}Other"]


def test_commit_schema_media_appends_image(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._detail_uri = f"{NS}Child"
    field = SimpleNamespace(meta={"type": "schema_image_input"})
    v._commit_schema_media(field, "https://img.example/x.png")
    assert "https://img.example/x.png" in v.taxonomy.concepts[f"{NS}Child"].schema_images


def test_delete_field_removes_pref_label_via_service(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._detail_uri = f"{NS}Top"
    v._detail_fields = v._bdf(f"{NS}Top")
    field = SimpleNamespace(meta={"type": "pref", "lang": "en"}, value="Top")
    v._delete_field(field)
    labels = [lbl.value for lbl in v.taxonomy.concepts[f"{NS}Top"].labels]
    assert "Top" not in labels
    assert "Top" not in [lbl.value for lbl in store.load(v.file_path).concepts[f"{NS}Top"].labels]


def test_delete_field_unknown_type_is_noop(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._detail_uri = f"{NS}Top"
    field = SimpleNamespace(meta={"type": "bogus", "lang": "en"}, value="x")
    v._delete_field(field)  # no command built → no error, no change
    assert v.taxonomy.concepts[f"{NS}Top"].labels


def test_rename_uri_confirm_routes_through_service(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._state = RenameUriConfirmState(
        old_uri=f"{NS}Child", new_uri=f"{NS}Pup", ref_count=1, kind="concept"
    )
    v._on_rename_uri_confirm(ord("y"))
    assert f"{NS}Pup" in v.taxonomy.concepts
    assert f"{NS}Child" not in v.taxonomy.concepts
    assert f"{NS}Pup" in store.load(v.file_path).concepts
    assert isinstance(v._state, DetailState)


def test_confirm_delete_removes_concept_via_service(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._detail_uri = f"{NS}Child"
    v._state = ConfirmDeleteState(uri=f"{NS}Child")
    v._on_confirm_delete(ord("y"))
    assert f"{NS}Child" not in v.taxonomy.concepts
    assert f"{NS}Child" not in store.load(v.file_path).concepts


def test_delete_class_confirm_removes_class_via_service(tmp_path: Path) -> None:
    v = _viewer(tmp_path)  # OWL taxonomy
    v._state = DeleteClassChoiceState(class_uri=f"{NS}Dog", confirming=True, cursor=0)
    v._on_delete_class_confirm(ord("y"))
    assert f"{NS}Dog" not in v.taxonomy.owl_classes
    assert f"{NS}Dog" not in store.load(v.file_path).owl_classes


def test_ontology_rename_confirm_routes_through_service(tmp_path: Path) -> None:
    v = _viewer(tmp_path)  # OWL taxonomy, ontology_uri https://ex.org/t
    v._state = OntologyRenameConfirmState(
        old_base="https://ex.org/t/", new_base="https://new.org/t/", entity_count=3
    )
    v._on_ontology_rename_confirm(ord("y"))
    assert v.taxonomy.ontology_uri == "https://new.org/t"
    assert "https://new.org/t/Dog" in v.taxonomy.owl_classes
    assert "https://new.org/t/Dog" in store.load(v.file_path).owl_classes
    assert isinstance(v._state, DetailState)


def test_submit_scheme_create_routes_through_service(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._state = SchemeCreateState(
        fields=[
            SimpleNamespace(meta={"field": "title"}, value="Second Scheme"),
            SimpleNamespace(meta={"field": "uri"}, value=f"{NS}Scheme2"),
            SimpleNamespace(meta={"field": "base_uri"}, value=""),
        ]
    )
    v._submit_scheme_create()
    assert f"{NS}Scheme2" in v.taxonomy.schemes
    assert f"{NS}Scheme2" in store.load(v.file_path).schemes
    assert isinstance(v._state, DetailState)
