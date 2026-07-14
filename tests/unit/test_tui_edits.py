"""Unit tests for ster.tui.edits — field → Command dispatch (pure)."""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import (
    AddSchemaMedia,
    OntoRenameUri,
    OntoSetMetadata,
    OntoSetPrefix,
    OwlAddIndividualType,
    OwlAddProperty,
    OwlAddPropertyClass,
    OwlConvertClassToIndividual,
    OwlConvertIndividualToClass,
    OwlCreateIndividual,
    OwlCreateSubclass,
    OwlDeleteClass,
    OwlDeleteIndividual,
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
    SkosAddRelated,
    SkosCreateScheme,
    SkosMoveConcept,
    SkosSetDefinition,
    SkosSetLabel,
    SkosSetSchemeField,
    SkosSetScopeNote,
)
from ster.nav.logic import DetailField
from ster.tui.edits import (
    action_command,
    add_literal_value_command,
    add_object_value_command,
    context_actions,
    convert_choices,
    convert_command,
    create_scheme_command,
    delete_command,
    direct_command,
    edit_command,
    meta_input_command,
    meta_relation_command,
    ontology_rename_command,
    relation_command,
)


def _field(type_: str, **meta) -> DetailField:
    return DetailField(key="k", display="d", value="", editable=True, meta={"type": type_, **meta})


def test_rdf_label_maps_to_owl_set_label() -> None:
    f = _field("rdf_label", lang="fr")
    cmd = edit_command(f, "http://ex/C", Path("/t/o.ttl"), "Chien")
    assert isinstance(cmd, OwlSetLabel)
    assert (cmd.target_path, cmd.uri, cmd.lang, cmd.value) == (
        Path("/t/o.ttl"),
        "http://ex/C",
        "fr",
        "Chien",
    )


def test_rdf_label_defaults_lang_to_en() -> None:
    cmd = edit_command(_field("rdf_label"), "http://ex/C", Path("/t/o.ttl"), "Dog")
    assert isinstance(cmd, OwlSetLabel) and cmd.lang == "en"


def test_unsupported_field_returns_none() -> None:
    assert edit_command(_field("stat"), "http://ex/C", Path("/t/o.ttl"), "x") is None


# ── action_command (constructive action rows) ──────────────────────────────────

_P = Path("/t/o.ttl")
OVERVIEW = "__ster:overview__"


def test_add_rdf_comment_maps_to_owl_set_comment() -> None:
    cmd = action_command("add_rdf_comment", "http://ex/C", _P, "A dog.", lang="en")
    assert isinstance(cmd, OwlSetComment)
    assert (cmd.uri, cmd.lang, cmd.value) == ("http://ex/C", "en", "A dog.")


def test_new_subclass_maps_to_create_subclass_under_parent() -> None:
    cmd = action_command("new_subclass", "http://ex/Parent", _P, "http://ex/Child")
    assert isinstance(cmd, OwlCreateSubclass)
    assert (cmd.class_uri, cmd.parent_uri) == ("http://ex/Child", "http://ex/Parent")


def test_add_individual_maps_to_create_individual_typed_by_class() -> None:
    cmd = action_command("add_individual", "http://ex/Class", _P, "http://ex/Inst")
    assert isinstance(cmd, OwlCreateIndividual)
    assert (cmd.uri, cmd.class_uri) == ("http://ex/Inst", "http://ex/Class")


def test_unsupported_action_returns_none() -> None:
    assert action_command("class_to_individual", "http://ex/C", _P, "x") is None


# ── delete_command (destructive, mode-driven) ───────────────────────────────────


def test_delete_class_maps_to_owl_delete_class_with_mode() -> None:
    cmd = delete_command("delete_class", "http://ex/C", _P, "delete_all")
    assert isinstance(cmd, OwlDeleteClass)
    assert (cmd.class_uri, cmd.mode) == ("http://ex/C", "delete_all")


def test_delete_scheme_maps_to_skos_remove_scheme_with_cascade() -> None:
    from ster.core.commands import SkosRemoveScheme

    keep = delete_command("delete_scheme", "http://ex/S", _P, "scheme_only")
    assert isinstance(keep, SkosRemoveScheme)
    assert (keep.uri, keep.cascade) == ("http://ex/S", False)

    cascade = delete_command("delete_scheme", "http://ex/S", _P, "delete_all")
    assert isinstance(cascade, SkosRemoveScheme) and cascade.cascade is True


def test_unsupported_delete_returns_none() -> None:
    assert delete_command("delete_nonexistent", "http://ex/C", _P, "keep_all") is None


# ── relation_command (picker-driven) ────────────────────────────────────────────


def test_link_superclass_maps_to_additive_move_class() -> None:
    cmd = relation_command("link_superclass", "http://ex/C", _P, "http://ex/Parent")
    assert isinstance(cmd, OwlMoveClass)
    assert (cmd.source_uri, cmd.new_parent_uri, cmd.replace) == (
        "http://ex/C",
        "http://ex/Parent",
        False,
    )


def test_move_class_maps_to_replacing_move() -> None:
    cmd = relation_command("move_class", "http://ex/C", _P, "http://ex/Parent")
    assert isinstance(cmd, OwlMoveClass) and cmd.replace is True


def test_context_actions_per_kind() -> None:
    class_actions = [a for _, a in context_actions("class")]
    assert {"new_subclass", "move_class", "class_to_individual", "delete_class"} <= set(
        class_actions
    )
    assert "rename" not in class_actions  # URI edits go through "Edit class…", not "Rename URI"
    assert [a for _, a in context_actions("scheme")] == [
        "add_top_concept",
        "rename",
        "delete_scheme",
    ]
    assert "delete" in [a for _, a in context_actions("concept")]
    prop_actions = [a for _, a in context_actions("property")]
    assert "enforce_shacl" in prop_actions and "unenforce_shacl" in prop_actions  # SHACL rules
    assert context_actions("nonexistent") == []


def test_unsupported_relation_returns_none() -> None:
    assert relation_command("relate", "http://ex/C", _P, "http://ex/D") is None


# ── Phase 1/2: rename, individuals, meta-driven removes ─────────────────────────


def test_uri_row_maps_to_rename_entity() -> None:
    cmd = edit_command(_field("uri"), "http://ex/C", _P, "http://ex/D")
    assert isinstance(cmd, RenameEntity)
    assert (cmd.old_uri, cmd.new_uri) == ("http://ex/C", "http://ex/D")


def test_ind_label_maps_to_owl_set_label() -> None:
    cmd = edit_command(_field("ind_label", lang="fr"), "http://ex/i", _P, "Médor")
    assert isinstance(cmd, OwlSetLabel) and (cmd.lang, cmd.value) == ("fr", "Médor")


def test_add_ind_comment_maps_to_owl_set_comment() -> None:
    cmd = action_command("add_ind_comment", "http://ex/i", _P, "A good dog.")
    assert isinstance(cmd, OwlSetComment)


def test_add_ind_type_maps_to_add_individual_type() -> None:
    cmd = relation_command("add_ind_type", "http://ex/i", _P, "http://ex/Dog")
    assert isinstance(cmd, OwlAddIndividualType)
    assert (cmd.ind_uri, cmd.type_uri) == ("http://ex/i", "http://ex/Dog")


def test_delete_individual_maps_to_owl_delete_individual() -> None:
    cmd = delete_command("delete_individual", "http://ex/i", _P, "delete")
    assert isinstance(cmd, OwlDeleteIndividual) and cmd.uri == "http://ex/i"


def test_direct_remove_superclass() -> None:
    f = _field("action_del", action="remove_superclass", parent_uri="http://ex/P")
    cmd = direct_command(f, "http://ex/C", _P)
    assert isinstance(cmd, OwlRemoveSuperclass)
    assert (cmd.child_uri, cmd.parent_uri) == ("http://ex/C", "http://ex/P")


def test_direct_remove_ind_type() -> None:
    f = _field("action_del", action="remove_ind_type", type_uri="http://ex/Dog")
    cmd = direct_command(f, "http://ex/i", _P)
    assert isinstance(cmd, OwlRemoveIndividualType)
    assert (cmd.ind_uri, cmd.type_uri) == ("http://ex/i", "http://ex/Dog")


def test_direct_command_none_for_non_direct_row() -> None:
    assert direct_command(_field("rdf_label"), "http://ex/C", _P) is None


# ── Phase 3: ontology overview metadata + prefix ────────────────────────────────


def test_ont_title_maps_to_set_metadata() -> None:
    cmd = edit_command(_field("ont_title"), "__ster:overview__", _P, "Zoo Ontology")
    assert isinstance(cmd, OntoSetMetadata)
    assert (cmd.field_name, cmd.value) == ("title", "Zoo Ontology")


def test_ont_description_maps_to_set_metadata() -> None:
    cmd = edit_command(_field("ont_description"), "__ster:overview__", _P, "About animals")
    assert isinstance(cmd, OntoSetMetadata) and cmd.field_name == "description"


def test_ont_label_maps_to_set_metadata() -> None:
    cmd = edit_command(_field("ont_label"), "__ster:overview__", _P, "Zoo")
    assert isinstance(cmd, OntoSetMetadata) and cmd.field_name == "label"


def test_edit_ontology_prefix_maps_to_set_prefix() -> None:
    cmd = action_command("edit_ontology_prefix", "__ster:overview__", _P, "zoo")
    assert isinstance(cmd, OntoSetPrefix) and cmd.new_prefix == "zoo"


# ── Phase 4/5: SKOS concepts + schemes ──────────────────────────────────────────


def test_pref_maps_to_skos_set_label() -> None:
    cmd = edit_command(_field("pref", lang="en"), "http://ex/c", _P, "Apex")
    assert isinstance(cmd, SkosSetLabel) and (cmd.kind, cmd.value) == ("pref", "Apex")


def test_def_maps_to_skos_set_definition() -> None:
    cmd = edit_command(_field("def", lang="en"), "http://ex/c", _P, "Root.")
    assert isinstance(cmd, SkosSetDefinition) and cmd.value == "Root."


def test_scope_note_maps_to_skos_set_scope_note() -> None:
    cmd = edit_command(_field("scope_note", lang="en"), "http://ex/c", _P, "scope")
    assert isinstance(cmd, SkosSetScopeNote)


def test_scheme_title_maps_to_set_scheme_field() -> None:
    cmd = edit_command(_field("scheme_title", lang="en"), "http://ex/s", _P, "Cat")
    assert isinstance(cmd, SkosSetSchemeField) and cmd.field_name == "title"


def test_add_narrower_maps_to_add_concept_under_parent() -> None:
    cmd = action_command("add_narrower", "http://ex/p", _P, "http://ex/c")
    assert isinstance(cmd, SkosAddConcept)
    assert (cmd.uri, cmd.parent_handle) == ("http://ex/c", "http://ex/p")


def test_add_top_concept_maps_to_add_concept_under_scheme() -> None:
    cmd = action_command("add_top_concept", "http://ex/s", _P, "http://ex/c")
    assert isinstance(cmd, SkosAddConcept) and cmd.parent_handle == "http://ex/s"


def test_add_alt_label_action_maps_to_skos_set_label_alt() -> None:
    cmd = action_command("add_alt_label", "http://ex/c", _P, "Apex")
    assert isinstance(cmd, SkosSetLabel) and cmd.kind == "alt"


def test_link_broader_maps_to_additive_move_concept() -> None:
    cmd = relation_command("link_broader", "http://ex/c", _P, "http://ex/p")
    assert isinstance(cmd, SkosMoveConcept) and cmd.replace is False


def test_move_concept_maps_to_replacing_move() -> None:
    cmd = relation_command("move", "http://ex/c", _P, "http://ex/p")
    assert isinstance(cmd, SkosMoveConcept) and cmd.replace is True


def test_add_related_maps_to_skos_add_related() -> None:
    cmd = relation_command("add_related", "http://ex/c", _P, "http://ex/o")
    assert isinstance(cmd, SkosAddRelated)


def test_delete_concept_cascade_and_keep() -> None:
    assert delete_command("delete", "http://ex/c", _P, "cascade").cascade is True
    assert delete_command("delete", "http://ex/c", _P, "keep").cascade is False


# ── Phase 6: OWL properties (domain / range / labels / comments / delete) ───────


def test_add_prop_domain_maps_to_add_property_class_domain() -> None:
    cmd = relation_command("add_prop_domain", "http://ex/p", _P, "http://ex/C")
    assert isinstance(cmd, OwlAddPropertyClass)
    assert (cmd.prop_uri, cmd.slot, cmd.class_uri) == ("http://ex/p", "domain", "http://ex/C")


def test_add_prop_range_maps_to_add_property_class_range() -> None:
    cmd = relation_command("add_prop_range", "http://ex/p", _P, "http://ex/C")
    assert isinstance(cmd, OwlAddPropertyClass) and cmd.slot == "range"


def test_remove_prop_domain_maps_to_remove_property_class() -> None:
    f = _field("action", action="remove_prop_domain", domain_uri="http://ex/C")
    cmd = direct_command(f, "http://ex/p", _P)
    assert isinstance(cmd, OwlRemovePropertyClass)
    assert (cmd.slot, cmd.class_uri) == ("domain", "http://ex/C")


def test_remove_prop_range_maps_to_remove_property_class() -> None:
    f = _field("action", action="remove_prop_range", range_uri="http://ex/C")
    cmd = direct_command(f, "http://ex/p", _P)
    assert isinstance(cmd, OwlRemovePropertyClass) and cmd.slot == "range"


def test_add_prop_label_maps_to_owl_set_label() -> None:
    cmd = action_command("add_prop_label", "http://ex/p", _P, "owns", lang="fr")
    assert isinstance(cmd, OwlSetLabel) and (cmd.lang, cmd.value) == ("fr", "owns")


def test_add_prop_comment_maps_to_owl_set_comment() -> None:
    cmd = action_command("add_prop_comment", "http://ex/p", _P, "links a pet to its owner")
    assert isinstance(cmd, OwlSetComment)


def test_delete_property_declaration_only_vs_strip_values() -> None:
    assert delete_command("delete_property", "http://ex/p", _P, "decl").clear_values is False
    assert delete_command("delete_property", "http://ex/p", _P, "strip").clear_values is True


# ── Phase 7: schema media, notes, individual-value removal ──────────────────────


def test_add_schema_media_maps_by_kind() -> None:
    img = action_command("add_schema_image", "http://ex/i", _P, "http://img")
    assert isinstance(img, AddSchemaMedia) and (img.kind, img.url) == ("image", "http://img")
    assert action_command("add_schema_video", "http://ex/i", _P, "http://v").kind == "video"
    assert action_command("add_schema_url", "http://ex/i", _P, "http://u").kind == "url"


def test_remove_schema_media_maps_by_kind() -> None:
    f = _field("action", action="remove_schema_image", url="http://img")
    cmd = direct_command(f, "http://ex/i", _P)
    assert isinstance(cmd, RemoveSchemaMedia) and (cmd.kind, cmd.url) == ("image", "http://img")


def test_edit_note_sets_note_and_delete_note_clears_it() -> None:
    cmd = action_command("edit_note", "http://ex/i", _P, "# Heading")
    assert isinstance(cmd, OwlSetNote) and cmd.note == "# Heading"
    f = _field("action", action="delete_note")
    clear = direct_command(f, "http://ex/i", _P)
    assert isinstance(clear, OwlSetNote) and clear.note == ""


def test_remove_prop_value_maps_to_remove_individual_value() -> None:
    f = _field("action", action="remove_prop_value", prop_uri="http://ex/p", val_uri="http://ex/o")
    cmd = direct_command(f, "http://ex/i", _P)
    assert isinstance(cmd, OwlRemoveIndividualValue)
    assert (cmd.prop_uri, cmd.val_uri) == ("http://ex/p", "http://ex/o")


def test_remove_literal_value_maps_to_remove_individual_literal() -> None:
    f = _field(
        "action",
        action="remove_literal_value",
        prop_uri="http://ex/p",
        val_str="7",
        lang_or_dt="^^xsd:integer",
    )
    cmd = direct_command(f, "http://ex/i", _P)
    assert isinstance(cmd, OwlRemoveIndividualLiteral)
    assert (cmd.val_str, cmd.lang_or_dt) == ("7", "^^xsd:integer")


# ── Phase 8: class ↔ individual punning conversions ─────────────────────────────


def test_individual_to_class_is_a_single_confirm() -> None:
    assert convert_choices("individual_to_class", ()) == [("Convert to an OWL class", "go")]
    cmd = convert_command("individual_to_class", "http://ex/i", _P, "go", ())
    assert isinstance(cmd, OwlConvertIndividualToClass) and cmd.uri == "http://ex/i"


def test_class_to_individual_offers_reattach_only_when_it_has_parents() -> None:
    assert convert_choices("class_to_individual", ()) == [
        ("Delete instances typed by this class", "delete")
    ]
    with_parents = convert_choices("class_to_individual", ("http://ex/P",))
    assert ("Re-type instances to its parent class(es)", "reattach") in with_parents


def test_class_to_individual_reattach_passes_parents_else_none() -> None:
    parents = ("http://ex/P",)
    keep = convert_command("class_to_individual", "http://ex/C", _P, "reattach", parents)
    assert isinstance(keep, OwlConvertClassToIndividual) and keep.reattach_to == parents
    drop = convert_command("class_to_individual", "http://ex/C", _P, "delete", parents)
    assert drop.reattach_to is None


def test_unsupported_conversion_returns_none() -> None:
    assert convert_command("concept_to_class", "http://ex/c", _P, "go", ()) is None


# ── Phase 9: create OWL class / property from the overview ──────────────────────


def test_create_owl_class_makes_a_top_level_class() -> None:
    cmd = action_command("create_owl_class", OVERVIEW, _P, "http://ex/New")
    assert isinstance(cmd, OwlCreateSubclass)
    assert (cmd.class_uri, cmd.parent_uri) == ("http://ex/New", None)


def test_create_owl_property_makes_a_bare_object_property() -> None:
    cmd = action_command("create_owl_property", OVERVIEW, _P, "http://ex/rel", lang="en")
    assert isinstance(cmd, OwlAddProperty)
    assert (cmd.uri, cmd.prop_type, cmd.domain_uri, cmd.range_uri) == (
        "http://ex/rel",
        "ObjectProperty",
        None,
        None,
    )


# ── Phase 10: editing existing individual values (meta-aware) ───────────────────


def test_edit_literal_value_replaces_in_place_using_meta() -> None:
    f = _field(
        "action", action="edit_literal_value", prop_uri="http://ex/age", val_str="7", lang_or_dt=""
    )
    cmd = meta_input_command(f, "http://ex/i", _P, "8")
    assert isinstance(cmd, OwlSetIndividualLiteral)
    assert (cmd.prop_uri, cmd.old_value, cmd.new_value) == ("http://ex/age", "7", "8")


def test_edit_prop_value_replaces_object_using_meta() -> None:
    f = _field("action", action="edit_prop_value", prop_uri="http://ex/owns", val_uri="http://ex/a")
    cmd = meta_relation_command(f, "http://ex/i", _P, "http://ex/b")
    assert isinstance(cmd, OwlSetIndividualValue)
    assert (cmd.prop_uri, cmd.new_val_uri, cmd.old_val_uri) == (
        "http://ex/owns",
        "http://ex/b",
        "http://ex/a",
    )


def test_meta_commands_none_for_unknown_action() -> None:
    f = _field("action", action="something_else")
    assert meta_input_command(f, "http://ex/i", _P, "x") is None
    assert meta_relation_command(f, "http://ex/i", _P, "http://ex/b") is None


# ── Phase 11: concept prefLabel / definition in a new language ──────────────────


def test_add_pref_label_maps_to_skos_set_label_pref() -> None:
    cmd = action_command("add_pref_label", "http://ex/c", _P, "Sommet", lang="fr")
    assert isinstance(cmd, SkosSetLabel) and (cmd.kind, cmd.lang) == ("pref", "fr")


def test_add_def_maps_to_skos_set_definition() -> None:
    cmd = action_command("add_def", "http://ex/c", _P, "Une définition.", lang="fr")
    assert isinstance(cmd, SkosSetDefinition) and (cmd.lang, cmd.value) == ("fr", "Une définition.")


# ── Phase 12: add a class property / add a new individual value ─────────────────


def test_add_class_property_creates_property_with_class_as_domain() -> None:
    f = _field(
        "action_add",
        action="add_class_property",
        class_uri="http://ex/Animal",
        prop_type="DatatypeProperty",
        range_uri="http://www.w3.org/2001/XMLSchema#integer",
    )
    cmd = meta_input_command(f, "http://ex/Animal", _P, "http://ex/weight", lang="en")
    assert isinstance(cmd, OwlAddProperty)
    assert (cmd.uri, cmd.prop_type, cmd.domain_uri, cmd.range_uri, cmd.label) == (
        "http://ex/weight",
        "DatatypeProperty",
        "http://ex/Animal",
        "http://www.w3.org/2001/XMLSchema#integer",
        "weight",
    )


def test_add_object_value_command_has_no_old_value() -> None:
    cmd = add_object_value_command("http://ex/i", _P, "http://ex/owns", "http://ex/o")
    assert isinstance(cmd, OwlSetIndividualValue)
    assert (cmd.prop_uri, cmd.new_val_uri, cmd.old_val_uri) == ("http://ex/owns", "http://ex/o", "")


def test_add_literal_value_command_has_no_old_value() -> None:
    cmd = add_literal_value_command("http://ex/i", _P, "http://ex/age", "9")
    assert isinstance(cmd, OwlSetIndividualLiteral)
    assert (cmd.prop_uri, cmd.old_value, cmd.new_value) == ("http://ex/age", "", "9")


# ── Phase 13: create a SKOS concept scheme ──────────────────────────────────────


def test_create_scheme_command_titles_in_lang_and_derives_base_uri() -> None:
    cmd = create_scheme_command(_P, "https://ex.org/sk/Cat", "Catalogue", "en")
    assert isinstance(cmd, SkosCreateScheme)
    assert (cmd.uri, cmd.labels, cmd.languages) == (
        "https://ex.org/sk/Cat",
        {"en": "Catalogue"},
        ("en",),
    )
    assert cmd.base_uri == "https://ex.org/sk/"


def test_create_scheme_base_uri_falls_back_to_hash_namespace() -> None:
    cmd = create_scheme_command(_P, "https://ex.org/onto#Themes", "Themes", "fr")
    assert cmd.base_uri == "https://ex.org/onto#"


# ── Phase 14: ontology base-URI / domain rename ─────────────────────────────────


def test_ontology_rename_command_parses_slash_separator() -> None:
    cmd = ontology_rename_command(_P, "https://ex.org/zoo/")
    assert isinstance(cmd, OntoRenameUri)
    assert (cmd.new_uri, cmd.new_sep) == ("https://ex.org/zoo", "/")


def test_ontology_rename_command_parses_hash_separator() -> None:
    cmd = ontology_rename_command(_P, "https://ex.org/zoo#")
    assert (cmd.new_uri, cmd.new_sep) == ("https://ex.org/zoo", "#")


def test_ontology_rename_command_defaults_to_hash_when_no_separator() -> None:
    cmd = ontology_rename_command(_P, "https://ex.org/zoo")
    assert (cmd.new_uri, cmd.new_sep) == ("https://ex.org/zoo", "#")


# ── Phase 15: generic annotation edit / remove ──────────────────────────────────

DCT = "http://purl.org/dc/terms/"


def test_ont_annotation_edit_maps_to_onto_set_annotation() -> None:
    from ster.core.commands import OntoSetAnnotation

    f = _field("ont_annotation", predicate=DCT + "creator", value_index=0)
    cmd = edit_command(f, "__ster:overview__", _P, "Bob")
    assert isinstance(cmd, OntoSetAnnotation)
    assert (cmd.predicate, cmd.new_value) == (DCT + "creator", "Bob")


def test_ont_annotation_remove_maps_to_onto_remove_annotation() -> None:
    from ster.core.commands import OntoRemoveAnnotation
    from ster.tui.edits import direct_command

    f = _field(
        "action_del", action="remove_ont_annotation", predicate=DCT + "creator", value="Alice"
    )
    cmd = direct_command(f, "__ster:overview__", _P)
    assert isinstance(cmd, OntoRemoveAnnotation)
    assert (cmd.predicate, cmd.value) == (DCT + "creator", "Alice")


# ── long-text detection + comment editing (multi-line Markdown editor) ──────────


def test_is_long_text_for_comments_definitions_notes_and_literals() -> None:
    from ster.nav.logic import DetailField
    from ster.tui.edits import is_long_text

    def _f(meta):
        return DetailField("k", "d", "v", editable=True, meta=meta)

    assert is_long_text(_f({"type": "rdf_comment"}))
    assert is_long_text(_f({"type": "def"}))
    assert is_long_text(_f({"type": "ont_description"}))
    assert is_long_text(_f({"action": "edit_literal_value"}))
    assert is_long_text(_f({"action": "add_prop_comment"}))
    # short identifiers stay single-line
    assert not is_long_text(_f({"type": "rdf_label"}))
    assert not is_long_text(_f({"type": "uri"}))


def test_edit_command_now_wires_comment_types() -> None:
    """Regression: rdfs:comment rows were editable=True but had no edit_command (a no-op).
    They now map to OwlSetComment."""
    from ster.core.commands import OwlSetComment
    from ster.nav.logic import DetailField

    for ctype in ("rdf_comment", "ind_comment", "prop_comment"):
        f = DetailField("k", "comment", "old", editable=True, meta={"type": ctype, "lang": "en"})
        cmd = edit_command(f, "u", Path("o.ttl"), "new text")
        assert isinstance(cmd, OwlSetComment) and cmd.value == "new text" and cmd.lang == "en"


def test_is_prose_excludes_literal_values() -> None:
    from ster.nav.logic import DetailField
    from ster.tui.edits import is_long_text, is_prose

    def _f(meta):
        return DetailField("k", "d", "v", editable=True, meta=meta)

    assert is_prose(_f({"type": "rdf_comment"})) and is_prose(_f({"type": "def"}))
    assert is_prose(_f({"action": "add_scope_note"}))
    # literal values are long-text but NOT prose (a literal may be a bare URL to keep)
    lit = _f({"type": "ind_lit_val", "action": "edit_literal_value"})
    assert is_long_text(lit) and not is_prose(lit)
    assert not is_prose(_f({"type": "rdf_label"}))
