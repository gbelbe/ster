"""Unit tests for ster.tui.edits — field → Command dispatch (pure)."""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import (
    OntoSetMetadata,
    OntoSetPrefix,
    OwlAddIndividualType,
    OwlCreateIndividual,
    OwlCreateSubclass,
    OwlDeleteClass,
    OwlDeleteIndividual,
    OwlMoveClass,
    OwlRemoveIndividualType,
    OwlRemoveSuperclass,
    OwlSetComment,
    OwlSetLabel,
    RenameEntity,
)
from ster.nav.logic import DetailField
from ster.tui.edits import (
    action_command,
    delete_command,
    direct_command,
    edit_command,
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


def test_unsupported_delete_returns_none() -> None:
    assert delete_command("delete_property", "http://ex/C", _P, "keep_all") is None


# ── relation_command (picker-driven) ────────────────────────────────────────────


def test_link_superclass_maps_to_additive_move_class() -> None:
    cmd = relation_command("link_superclass", "http://ex/C", _P, "http://ex/Parent")
    assert isinstance(cmd, OwlMoveClass)
    assert (cmd.source_uri, cmd.new_parent_uri, cmd.replace) == (
        "http://ex/C",
        "http://ex/Parent",
        False,
    )


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
