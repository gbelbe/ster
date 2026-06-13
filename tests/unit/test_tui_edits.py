"""Unit tests for ster.tui.edits — field → Command dispatch (pure)."""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import OwlSetLabel
from ster.nav.logic import DetailField
from ster.tui.edits import edit_command


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
