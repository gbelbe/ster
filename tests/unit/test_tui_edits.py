"""Unit tests for ster.tui.edits — field → Command dispatch (pure)."""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import (
    OwlCreateIndividual,
    OwlCreateSubclass,
    OwlDeleteClass,
    OwlMoveClass,
    OwlSetComment,
    OwlSetLabel,
)
from ster.nav.logic import DetailField
from ster.tui.edits import action_command, delete_command, edit_command, relation_command


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
    assert delete_command("delete_individual", "http://ex/C", _P, "keep_all") is None


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
