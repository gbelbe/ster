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
    CreateState,
    DeleteClassChoiceState,
    DetailState,
    MovePickState,
    OntologyRenameConfirmState,
    PropertyImpactState,
    RenameUriConfirmState,
    SchemeCreateState,
    TreeState,
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


def test_save_context_definition_routes_through_service(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._save_context_definition(f"{NS}Child", "a young dog")
    defs = [d.value for d in v.taxonomy.concepts[f"{NS}Child"].definitions if d.lang == "en"]
    assert defs == ["a young dog"]
    saved = store.load(v.file_path).concepts[f"{NS}Child"].definitions
    assert any(d.value == "a young dog" for d in saved)


def test_save_context_definition_empty_or_missing_is_noop(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._save_context_definition(f"{NS}Child", "")  # empty → no-op
    v._save_context_definition(f"{NS}Ghost", "x")  # unknown concept → no-op
    assert v.taxonomy.concepts[f"{NS}Child"].definitions == []


def test_save_context_scheme_description_by_uri(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._save_context_scheme_description(f"{NS}Scheme", "all the animals")
    descs = [d.value for d in v.taxonomy.schemes[f"{NS}Scheme"].descriptions]
    assert "all the animals" in descs


def test_save_context_scheme_description_falls_back_to_primary(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._save_context_scheme_description(None, "primary scheme desc")
    descs = [d.value for d in v.taxonomy.schemes[f"{NS}Scheme"].descriptions]
    assert "primary scheme desc" in descs


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


def test_perform_property_delete_routes_through_service(tmp_path: Path) -> None:
    from ster.model import OWLIndividual, OWLProperty

    v = _viewer(tmp_path)  # OWL taxonomy
    prop = f"{NS}hasColor"
    v.taxonomy.owl_properties[prop] = OWLProperty(uri=prop, prop_type="DatatypeProperty")
    v.taxonomy.owl_individuals[f"{NS}d"] = OWLIndividual(
        uri=f"{NS}d", property_values=[(prop, f"{NS}red")]
    )
    store.save(v.taxonomy, v.file_path)
    v._perform_property_delete(prop, clear_values=True)
    assert prop not in v.taxonomy.owl_properties
    assert prop not in store.load(v.file_path).owl_properties
    assert v.taxonomy.owl_individuals[f"{NS}d"].property_values == []


def test_property_impact_confirm_deletes_via_service(tmp_path: Path) -> None:
    from ster.model import OWLProperty

    v = _viewer(tmp_path)
    prop = f"{NS}hasColor"
    v.taxonomy.owl_properties[prop] = OWLProperty(uri=prop, prop_type="ObjectProperty")
    store.save(v.taxonomy, v.file_path)
    v._state = PropertyImpactState(prop_uri=prop, return_to_uri=prop, cursor=0)
    v._on_property_impact_confirm(ord("\n"))  # Enter on "keep values, delete declaration"
    assert prop not in v.taxonomy.owl_properties
    assert prop not in store.load(v.file_path).owl_properties
    assert isinstance(v._state, TreeState)


def test_perform_property_delete_surfaces_service_error(tmp_path: Path) -> None:
    from ster.model import OWLProperty

    v = _viewer(tmp_path)
    prop = f"{NS}hasColor"
    v.taxonomy.owl_properties[prop] = OWLProperty(uri=prop, prop_type="ObjectProperty")
    failed = SimpleNamespace(ok=False, error="cannot delete", validation=None)
    v._service = lambda: SimpleNamespace(execute=lambda _cmd: failed)  # type: ignore[method-assign]
    v._perform_property_delete(prop, clear_values=False)
    assert v._status == "cannot delete"
    assert isinstance(v._state, TreeState)


def test_delete_property_no_impact_routes_through_service(tmp_path: Path) -> None:
    from ster.model import OWLProperty

    v = _viewer(tmp_path)
    prop = f"{NS}orphanProp"  # declared but used by no individual → no impact dialog
    v.taxonomy.owl_properties[prop] = OWLProperty(uri=prop, prop_type="ObjectProperty")
    store.save(v.taxonomy, v.file_path)
    v._detail_uri = prop
    v._trigger_action("delete_property")
    assert prop not in v.taxonomy.owl_properties
    assert prop not in store.load(v.file_path).owl_properties


def test_delete_class_no_subclasses_routes_through_service(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    # Mammal has no subclasses and no typed individuals → direct keep_all delete
    v._detail_uri = f"{NS}Mammal"
    v._trigger_action("delete_class")
    assert f"{NS}Mammal" not in v.taxonomy.owl_classes
    assert f"{NS}Mammal" not in store.load(v.file_path).owl_classes


def test_commit_new_property_bare_routes_through_service(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    f = SimpleNamespace(meta={"type": "new_owl_property_uri"})
    v._commit_new_property(f, f"{NS}likes")
    assert f"{NS}likes" in v.taxonomy.owl_properties
    assert f"{NS}likes" in store.load(v.file_path).owl_properties


def test_commit_new_property_domain_typed_routes_through_service(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    f = SimpleNamespace(
        meta={
            "type": "new_owl_class_property_uri",
            "prop_type": "ObjectProperty",
            "class_uri": f"{NS}Dog",
            "range_uri": f"{NS}Animal",
        }
    )
    v._commit_new_property(f, f"{NS}chases")
    prop = v.taxonomy.owl_properties[f"{NS}chases"]
    assert prop.domains == [f"{NS}Dog"]
    assert prop.ranges == [f"{NS}Animal"]


def test_delete_class_with_subclasses_opens_choice_dialog(tmp_path: Path) -> None:
    v = _viewer(tmp_path)  # Dog is a subclass of Animal
    v._detail_uri = f"{NS}Animal"
    v._trigger_action("delete_class")
    assert isinstance(v._state, DeleteClassChoiceState)
    assert f"{NS}Dog" in v._state.subclass_uris
    assert f"{NS}Animal" in v.taxonomy.owl_classes  # not deleted — dialog shown first


def test_submit_create_requires_a_name(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v._state = CreateState(
        parent_uri=None, fields=[SimpleNamespace(meta={"field": "name"}, value="  ")], step="form"
    )
    v._submit_create()
    assert v._state.error == "Concept name is required"


def test_commit_new_subclass_routes_through_service(tmp_path: Path) -> None:
    from ster.nav.logic import DetailField
    from ster.nav.state import EditState

    v = _viewer(tmp_path)  # has Animal, Mammal, Dog
    field = DetailField(
        "x", "x", "", editable=True, meta={"type": "new_subclass_uri", "parent_uri": f"{NS}Dog"}
    )
    v._detail_uri = f"{NS}Dog"  # commit routes via _commit_owl_class_edit (parent is a class)
    v._detail_fields = [field]
    v._field_cursor = 0
    v._state = EditState(buffer=f"{NS}Puppy", field=field, return_to=DetailState())
    v._commit_edit()
    assert v.taxonomy.owl_classes[f"{NS}Puppy"].sub_class_of == [f"{NS}Dog"]
    assert f"{NS}Puppy" in store.load(v.file_path).owl_classes


def test_commit_new_property_surfaces_service_error(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    failed = SimpleNamespace(ok=False, error="boom", validation=None)
    v._service = lambda: SimpleNamespace(execute=lambda _c: failed)  # type: ignore[method-assign]
    f = SimpleNamespace(meta={"type": "new_owl_property_uri"})
    v._commit_new_property(f, f"{NS}likes")
    assert v._status == "boom"


def test_commit_new_subclass_surfaces_service_error(tmp_path: Path) -> None:
    from ster.nav.logic import DetailField
    from ster.nav.state import EditState

    v = _viewer(tmp_path)
    v._detail_uri = f"{NS}Dog"
    field = DetailField(
        "x", "x", "", editable=True, meta={"type": "new_subclass_uri", "parent_uri": f"{NS}Dog"}
    )
    v._detail_fields = [field]
    v._field_cursor = 0
    v._state = EditState(buffer=f"{NS}Puppy", field=field, return_to=DetailState())
    failed = SimpleNamespace(ok=False, error="nope", validation=None)
    v._service = lambda: SimpleNamespace(execute=lambda _c: failed)  # type: ignore[method-assign]
    v._commit_edit()
    assert v._status == "nope"


# ── OWL class / individual / property label & comment edits (OwlSetLabel/Comment) ──


def _field(ftype: str, lang: str = "en") -> SimpleNamespace:
    return SimpleNamespace(meta={"type": ftype, "lang": lang})


def test_commit_owl_class_label_routes_through_service(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v._detail_uri = f"{NS}Dog"
    v._commit_owl_class_edit(_field("rdf_label"), "Hound")
    labels = [(lbl.lang, lbl.value) for lbl in v.taxonomy.owl_classes[f"{NS}Dog"].labels]
    assert ("en", "Hound") in labels
    saved = store.load(v.file_path).owl_classes[f"{NS}Dog"].labels
    assert ("en", "Hound") in [(lbl.lang, lbl.value) for lbl in saved]


def test_commit_individual_comment_routes_through_service(tmp_path: Path) -> None:
    from ster.model import OWLIndividual

    v = _viewer(tmp_path)
    v.taxonomy.owl_individuals[f"{NS}Rex"] = OWLIndividual(uri=f"{NS}Rex", types=[f"{NS}Dog"])
    v._detail_uri = f"{NS}Rex"
    v._commit_individual_edit(_field("ind_comment"), "a good dog")
    comments = [(c.lang, c.value) for c in v.taxonomy.owl_individuals[f"{NS}Rex"].comments]
    assert ("en", "a good dog") in comments


def test_commit_property_label_routes_through_service(tmp_path: Path) -> None:
    from ster.model import OWLProperty

    v = _viewer(tmp_path)
    v.taxonomy.owl_properties[f"{NS}hasColor"] = OWLProperty(uri=f"{NS}hasColor")
    v._detail_uri = f"{NS}hasColor"
    v._commit_property_edit(_field("prop_label"), "has colour")
    labels = [(lbl.lang, lbl.value) for lbl in v.taxonomy.owl_properties[f"{NS}hasColor"].labels]
    assert ("en", "has colour") in labels


def test_commit_promoted_class_label_rebuilds_promoted_fields(tmp_path: Path) -> None:
    from ster.model import Concept, ConceptScheme, Label

    v = _viewer(tmp_path)
    # Promote Dog: same URI exists as both an OWL class and a SKOS concept.
    scheme = ConceptScheme(uri=f"{NS}Scheme")
    v.taxonomy.schemes[scheme.uri] = scheme
    v.taxonomy.concepts[f"{NS}Dog"] = Concept(
        uri=f"{NS}Dog",
        top_concept_of=scheme.uri,
        labels=[Label(lang="en", value="Dog")],
    )
    scheme.top_concepts.append(f"{NS}Dog")
    assert v.taxonomy.node_type(f"{NS}Dog") == "promoted"
    v._detail_uri = f"{NS}Dog"
    v._commit_owl_class_edit(_field("rdf_label"), "Hound")
    labels = [(lbl.lang, lbl.value) for lbl in v.taxonomy.owl_classes[f"{NS}Dog"].labels]
    assert ("en", "Hound") in labels


def test_commit_owl_label_surfaces_service_error(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v._detail_uri = f"{NS}Dog"
    failed = SimpleNamespace(ok=False, error="boom", validation=None)
    v._service = lambda: SimpleNamespace(execute=lambda _c: failed)  # type: ignore[method-assign]
    v._commit_owl_class_edit(_field("rdf_label"), "Hound")
    assert v._status == "boom"


def test_commit_new_individual_routes_through_service(tmp_path: Path) -> None:
    from ster.nav.logic import DetailField
    from ster.nav.state import EditState

    v = _viewer(tmp_path)
    field = DetailField(
        "x",
        "x",
        "",
        editable=True,
        meta={"type": "new_owl_individual_uri", "class_uri": f"{NS}Dog"},
    )
    v._detail_uri = f"{NS}Dog"  # individual is created from a class detail panel
    v._detail_fields = [field]
    v._field_cursor = 0
    v._state = EditState(buffer=f"{NS}Rex", field=field, return_to=DetailState())
    v._commit_edit()  # full dispatch through _commit_edit
    assert v.taxonomy.owl_individuals[f"{NS}Rex"].types == [f"{NS}Dog"]
    assert f"{NS}Rex" in store.load(v.file_path).owl_individuals
    assert v._detail_uri == f"{NS}Rex"
    assert isinstance(v._state, DetailState)


def test_commit_new_individual_surfaces_service_error(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    failed = SimpleNamespace(ok=False, error="nope", validation=None)
    v._service = lambda: SimpleNamespace(execute=lambda _c: failed)  # type: ignore[method-assign]
    f = SimpleNamespace(meta={"type": "new_owl_individual_uri", "class_uri": f"{NS}Dog"})
    v._commit_new_individual(f, f"{NS}Rex")
    assert v._status == "nope"


def test_commit_ontology_label_routes_through_service(tmp_path: Path) -> None:
    from ster.nav.logic import _ontology_sentinel

    v = _viewer(tmp_path)
    v._detail_uri = _ontology_sentinel(None)
    v._commit_ontology_edit(SimpleNamespace(meta={"type": "ont_label"}), "My Ontology")
    assert v.taxonomy.ontology_label == "My Ontology"
    assert store.load(v.file_path).ontology_label == "My Ontology"


def test_commit_ontology_unknown_field_is_noop(tmp_path: Path) -> None:
    from ster.nav.logic import _ontology_sentinel

    v = _viewer(tmp_path)
    v._detail_uri = _ontology_sentinel(None)
    v._commit_ontology_edit(SimpleNamespace(meta={"type": "bogus"}), "x")
    assert v.taxonomy.ontology_label is None


def test_commit_new_ontology_class_routes_through_service(tmp_path: Path) -> None:
    from ster.nav.logic import _ontology_sentinel

    v = _viewer(tmp_path)
    v._detail_uri = _ontology_sentinel(None)
    v._commit_ontology_edit(SimpleNamespace(meta={"type": "new_owl_class_uri"}), f"{NS}Plant")
    assert f"{NS}Plant" in v.taxonomy.owl_classes
    assert f"{NS}Plant" in store.load(v.file_path).owl_classes
    assert v._detail_uri == f"{NS}Plant"
    assert isinstance(v._state, DetailState)


def test_add_individual_type_routes_through_service(tmp_path: Path) -> None:
    from ster.model import OWLIndividual

    v = _viewer(tmp_path)
    v.taxonomy.owl_individuals[f"{NS}Rex"] = OWLIndividual(uri=f"{NS}Rex", types=[f"{NS}Dog"])
    store.save(v.taxonomy, v.file_path)
    v._add_individual_type(f"{NS}Rex", f"{NS}Animal")
    assert f"{NS}Animal" in v.taxonomy.owl_individuals[f"{NS}Rex"].types
    assert f"{NS}Animal" in store.load(v.file_path).owl_individuals[f"{NS}Rex"].types
    assert v._detail_uri == f"{NS}Rex"
    assert isinstance(v._state, DetailState)


def test_set_individual_value_routes_through_service(tmp_path: Path) -> None:
    from ster.model import OWLIndividual

    v = _viewer(tmp_path)
    v.taxonomy.owl_individuals[f"{NS}Rex"] = OWLIndividual(
        uri=f"{NS}Rex", property_values=[(f"{NS}owner", f"{NS}Ann")]
    )
    store.save(v.taxonomy, v.file_path)
    # replace the existing owner pair
    v._set_individual_value(f"{NS}Rex", f"{NS}owner", f"{NS}Bob", old_val_uri=f"{NS}Ann")
    vals = v.taxonomy.owl_individuals[f"{NS}Rex"].property_values
    assert vals == [(f"{NS}owner", f"{NS}Bob")]
    assert store.load(v.file_path).owl_individuals[f"{NS}Rex"].property_values == [
        (f"{NS}owner", f"{NS}Bob")
    ]


def _two_file_mapping_viewer(tmp_path: Path):
    """A workspace with two single-concept schemes in separate files (a.ttl, b.ttl)."""
    from ster.model import Concept, ConceptScheme, Label, LabelType

    def _mk(base: str, name: str) -> Taxonomy:
        t = Taxonomy()
        sch = ConceptScheme(uri=base + "scheme")
        t.schemes[sch.uri] = sch
        c = Concept(
            uri=base + name,
            top_concept_of=sch.uri,
            labels=[Label(lang="en", value=name, type=LabelType.PREF)],
        )
        sch.top_concepts.append(c.uri)
        t.concepts[c.uri] = c
        return t

    a_base, b_base = "https://a.org/", "https://b.org/"
    ta, tb = _mk(a_base, "Dog"), _mk(b_base, "Mammal")
    pa, pb = tmp_path / "a.ttl", tmp_path / "b.ttl"
    store.save(ta, pa)
    store.save(tb, pb)
    v = TaxonomyViewer(ta, pa, lang="en")
    v._workspace.taxonomies[pa] = ta
    v._workspace.taxonomies[pb] = tb
    v.taxonomy = ta
    return v, a_base, b_base, pa, pb


def test_apply_mapping_cross_file_add_with_inverse(tmp_path: Path) -> None:
    v, a, b, pa, pb = _two_file_mapping_viewer(tmp_path)
    ok = v._apply_mapping_links(a + "Dog", "exact_match", b + "Mammal", add=True, with_inverse=True)
    assert ok
    assert store.load(pa).concepts[a + "Dog"].exact_match == [b + "Mammal"]
    assert store.load(pb).concepts[b + "Mammal"].exact_match == [a + "Dog"]  # inverse on file B


def test_apply_mapping_remove_with_inverse(tmp_path: Path) -> None:
    v, a, b, pa, pb = _two_file_mapping_viewer(tmp_path)
    v._apply_mapping_links(a + "Dog", "exact_match", b + "Mammal", add=True, with_inverse=True)
    ok = v._apply_mapping_links(
        a + "Dog", "exact_match", b + "Mammal", add=False, with_inverse=True
    )
    assert ok
    assert store.load(pa).concepts[a + "Dog"].exact_match == []
    assert store.load(pb).concepts[b + "Mammal"].exact_match == []


def test_apply_mapping_source_not_found(tmp_path: Path) -> None:
    v, a, b, pa, pb = _two_file_mapping_viewer(tmp_path)
    ok = v._apply_mapping_links(
        a + "Ghost", "exact_match", b + "Mammal", add=True, with_inverse=True
    )
    assert ok is False
    assert "not found" in v._status.lower()


def test_confirm_mapping_adds_link(tmp_path: Path) -> None:
    from ster.nav.state import MapConceptPickState

    v, a, b, pa, pb = _two_file_mapping_viewer(tmp_path)
    v._state = MapConceptPickState(source_uri=a + "Dog", map_type="exactMatch")
    v._confirm_mapping(b + "Mammal")
    assert store.load(pa).concepts[a + "Dog"].exact_match == [b + "Mammal"]
    assert isinstance(v._state, DetailState)


def test_confirm_mapping_target_not_found(tmp_path: Path) -> None:
    from ster.nav.state import MapConceptPickState

    v, a, b, pa, pb = _two_file_mapping_viewer(tmp_path)
    v._state = MapConceptPickState(source_uri=a + "Dog", map_type="exactMatch")
    v._confirm_mapping(a + "Nonexistent")
    assert store.load(pa).concepts[a + "Dog"].exact_match == []
    assert "not found" in v._status.lower()


def test_remove_mapping_field_drops_both_sides(tmp_path: Path) -> None:
    v, a, b, pa, pb = _two_file_mapping_viewer(tmp_path)
    v._apply_mapping_links(a + "Dog", "exact_match", b + "Mammal", add=True, with_inverse=True)
    v._detail_uri = a + "Dog"
    f = SimpleNamespace(meta={"attr": "exact_match", "uri": b + "Mammal"})
    v._remove_mapping_field(f)
    assert store.load(pa).concepts[a + "Dog"].exact_match == []
    assert store.load(pb).concepts[b + "Mammal"].exact_match == []


def test_repair_mapping_field_forward_only(tmp_path: Path) -> None:
    v, a, b, pa, pb = _two_file_mapping_viewer(tmp_path)
    # a broken link: source asserts it but the inverse on B is absent
    v.taxonomy.concepts[a + "Dog"].exact_match.append(b + "Mammal")
    store.save(v.taxonomy, pa)
    v._detail_uri = a + "scheme"
    f = SimpleNamespace(
        meta={"source_uri": a + "Dog", "attr": "exact_match", "target_uri": b + "Mammal"}
    )
    v._repair_mapping_field(f)
    assert store.load(pa).concepts[a + "Dog"].exact_match == []
    # B was never touched (forward-only repair)
    assert store.load(pb).concepts[b + "Mammal"].exact_match == []


def test_set_note_via_service(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v._detail_uri = f"{NS}Dog"
    v._set_note(f"{NS}Dog", "a helpful note")
    assert v.taxonomy.owl_classes[f"{NS}Dog"].note == "a helpful note"
    assert store.load(v.file_path).owl_classes[f"{NS}Dog"].note == "a helpful note"


def test_delete_note_via_trigger_action(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v.taxonomy.owl_classes[f"{NS}Dog"].note = "remove me"
    store.save(v.taxonomy, v.file_path)
    v._detail_uri = f"{NS}Dog"
    v._trigger_action("delete_note")
    assert v.taxonomy.owl_classes[f"{NS}Dog"].note == ""
    assert store.load(v.file_path).owl_classes[f"{NS}Dog"].note == ""


def test_apply_ext_superclass_routes_through_service(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    ext = "https://schema.org/Thing"
    v._detail_uri = f"{NS}Dog"
    v._apply_ext_superclass(f"{NS}Dog", ext)
    assert ext in v.taxonomy.owl_classes[f"{NS}Dog"].sub_class_of
    assert ext in v.taxonomy.owl_classes  # stubbed
    assert ext in store.load(v.file_path).owl_classes[f"{NS}Dog"].sub_class_of
    assert isinstance(v._state, DetailState)


def test_initialize_ontology_via_service(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v._initialize_ontology("https://new.example.org/onto", "#", "My Ontology")
    assert v.taxonomy.ontology_label == "My Ontology"
    assert "new.example.org/onto" in (v.taxonomy.ontology_uri or "")
    assert store.load(v.file_path).ontology_label == "My Ontology"


def test_do_class_to_individual_routes_through_service(tmp_path: Path) -> None:
    v = _viewer(tmp_path)  # Dog sub_class_of Animal
    v._detail_uri = f"{NS}Dog"
    v._do_class_to_individual(f"{NS}Dog")
    assert f"{NS}Dog" not in v.taxonomy.owl_classes
    assert v.taxonomy.owl_individuals[f"{NS}Dog"].types == [f"{NS}Animal"]
    assert f"{NS}Dog" in store.load(v.file_path).owl_individuals
    assert isinstance(v._state, DetailState)


def test_do_individual_to_class_routes_through_service(tmp_path: Path) -> None:
    from ster.model import OWLIndividual

    v = _viewer(tmp_path)
    v.taxonomy.owl_individuals[f"{NS}Rex"] = OWLIndividual(uri=f"{NS}Rex", types=[f"{NS}Dog"])
    store.save(v.taxonomy, v.file_path)
    v._detail_uri = f"{NS}Rex"
    v._do_individual_to_class(f"{NS}Rex")
    assert f"{NS}Rex" not in v.taxonomy.owl_individuals
    assert v.taxonomy.owl_classes[f"{NS}Rex"].sub_class_of == [f"{NS}Dog"]
    assert f"{NS}Rex" in store.load(v.file_path).owl_classes


def test_remove_superclass_via_trigger_action(tmp_path: Path) -> None:
    v = _viewer(tmp_path)  # Dog sub_class_of Animal
    v._detail_uri = f"{NS}Dog"
    v._trigger_action("remove_superclass", {"parent_uri": f"{NS}Animal"})
    assert v.taxonomy.owl_classes[f"{NS}Dog"].sub_class_of == []
    assert store.load(v.file_path).owl_classes[f"{NS}Dog"].sub_class_of == []


def test_delete_individual_via_trigger_action(tmp_path: Path) -> None:
    from ster.model import OWLIndividual
    from ster.nav.state import TreeState

    v = _viewer(tmp_path)
    v.taxonomy.owl_individuals[f"{NS}Rex"] = OWLIndividual(uri=f"{NS}Rex", types=[f"{NS}Dog"])
    store.save(v.taxonomy, v.file_path)
    v._rebuild()
    v._detail_uri = f"{NS}Rex"
    v._trigger_action("delete_individual")
    assert f"{NS}Rex" not in v.taxonomy.owl_individuals
    assert f"{NS}Rex" not in store.load(v.file_path).owl_individuals
    assert isinstance(v._state, TreeState)


def test_remove_individual_value_and_type_via_trigger_action(tmp_path: Path) -> None:
    from ster.model import OWLIndividual

    v = _viewer(tmp_path)
    v.taxonomy.owl_individuals[f"{NS}Rex"] = OWLIndividual(
        uri=f"{NS}Rex",
        types=[f"{NS}Dog", f"{NS}Animal"],
        property_values=[(f"{NS}owner", f"{NS}Ann")],
        literal_values=[(f"{NS}age", "3", "")],
    )
    store.save(v.taxonomy, v.file_path)
    v._detail_uri = f"{NS}Rex"
    v._trigger_action("remove_prop_value", {"prop_uri": f"{NS}owner", "val_uri": f"{NS}Ann"})
    v._trigger_action(
        "remove_literal_value", {"prop_uri": f"{NS}age", "val_str": "3", "lang_or_dt": ""}
    )
    v._trigger_action("remove_ind_type", {"type_uri": f"{NS}Animal"})
    ind = v.taxonomy.owl_individuals[f"{NS}Rex"]
    assert ind.property_values == []
    assert ind.literal_values == []
    assert ind.types == [f"{NS}Dog"]


def test_add_property_class_routes_through_service(tmp_path: Path) -> None:
    from ster.model import OWLProperty

    v = _viewer(tmp_path)
    v.taxonomy.owl_properties[f"{NS}rel"] = OWLProperty(uri=f"{NS}rel")
    v._add_property_class(f"{NS}rel", "domain", f"{NS}Dog")
    assert v.taxonomy.owl_properties[f"{NS}rel"].domains == [f"{NS}Dog"]
    assert store.load(v.file_path).owl_properties[f"{NS}rel"].domains == [f"{NS}Dog"]
    assert v._detail_uri == f"{NS}rel"
    assert isinstance(v._state, DetailState)


def test_remove_property_class_via_trigger_action(tmp_path: Path) -> None:
    from ster.model import OWLProperty

    v = _viewer(tmp_path)
    v.taxonomy.owl_properties[f"{NS}rel"] = OWLProperty(uri=f"{NS}rel", ranges=[f"{NS}Animal"])
    store.save(v.taxonomy, v.file_path)
    v._detail_uri = f"{NS}rel"
    v._trigger_action("remove_prop_range", {"range_uri": f"{NS}Animal"})
    assert v.taxonomy.owl_properties[f"{NS}rel"].ranges == []
    assert store.load(v.file_path).owl_properties[f"{NS}rel"].ranges == []


def test_commit_schema_image_routes_through_service(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v._detail_uri = f"{NS}Dog"
    f = SimpleNamespace(meta={"type": "schema_image_input"})
    v._commit_schema_media(f, "https://ex.org/dog.png")
    assert v.taxonomy.owl_classes[f"{NS}Dog"].schema_images == ["https://ex.org/dog.png"]
    assert store.load(v.file_path).owl_classes[f"{NS}Dog"].schema_images == [
        "https://ex.org/dog.png"
    ]


def test_remove_schema_media_via_trigger_action(tmp_path: Path) -> None:
    v = _viewer(tmp_path)
    v.taxonomy.owl_classes[f"{NS}Dog"].schema_urls.append("https://ex.org/d")
    store.save(v.taxonomy, v.file_path)
    v._detail_uri = f"{NS}Dog"
    v._trigger_action("remove_schema_url", {"url": "https://ex.org/d"})
    assert v.taxonomy.owl_classes[f"{NS}Dog"].schema_urls == []
    assert store.load(v.file_path).owl_classes[f"{NS}Dog"].schema_urls == []


def test_commit_scheme_title_routes_through_service(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._detail_uri = f"{NS}Scheme"
    f = SimpleNamespace(meta={"type": "scheme_title", "lang": "en"})
    v._commit_scheme_edit(f, "Animals")
    assert v.taxonomy.schemes[f"{NS}Scheme"].title("en") == "Animals"
    assert store.load(v.file_path).schemes[f"{NS}Scheme"].title("en") == "Animals"


def test_commit_scheme_field_unknown_type_is_noop(tmp_path: Path) -> None:
    v = _skos_viewer(tmp_path)
    v._detail_uri = f"{NS}Scheme"
    before = v.taxonomy.schemes[f"{NS}Scheme"].creator
    v._commit_scheme_edit(SimpleNamespace(meta={"type": "bogus", "lang": "en"}), "x")
    assert v.taxonomy.schemes[f"{NS}Scheme"].creator == before


def test_commit_individual_literal_routes_through_service(tmp_path: Path) -> None:
    from ster.model import OWLIndividual

    v = _viewer(tmp_path)
    v.taxonomy.owl_individuals[f"{NS}Rex"] = OWLIndividual(
        uri=f"{NS}Rex", types=[f"{NS}Dog"], literal_values=[(f"{NS}age", "3", "")]
    )
    v._detail_uri = f"{NS}Rex"
    f = SimpleNamespace(
        meta={
            "type": "ind_lit_val_edit",
            "prop_uri": f"{NS}age",
            "old_val_str": "3",
            "lang_or_dt": "",
        }
    )
    v._commit_individual_edit(f, "4")
    vals = v.taxonomy.owl_individuals[f"{NS}Rex"].literal_values
    assert (f"{NS}age", "4", "") in vals
    assert (f"{NS}age", "3", "") not in vals
