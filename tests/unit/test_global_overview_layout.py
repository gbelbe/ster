"""Unit tests for the refactored global overview panel layout."""

from __future__ import annotations

from ster.model import RDFClass, Taxonomy
from ster.nav.logic import build_global_fields
from ster.workspace import TaxonomyWorkspace

NS = "https://example.org/onto#"


def _workspace() -> TaxonomyWorkspace:
    from pathlib import Path

    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    ws = TaxonomyWorkspace.__new__(TaxonomyWorkspace)
    ws.taxonomies = {Path("/tmp/test.ttl"): tax}
    return ws


def _fields(pending_restart: bool = False):
    return build_global_fields(
        _workspace(),
        None,
        "en",
        server_url="http://127.0.0.1",
        server_port=8765,
        show_token=False,
        pending_restart=pending_restart,
    )


def _section_keys(fields) -> list[str]:
    return [f.key for f in fields if f.meta.get("type") == "separator"]


def _section_labels(fields) -> list[str]:
    return [f.display for f in fields if f.meta.get("type") == "separator"]


def _fields_in_section(fields, section_label: str):
    """Return fields that belong to the named section (up to the next separator)."""
    result = []
    inside = False
    for f in fields:
        if f.meta.get("type") == "separator":
            if f.display == section_label:
                inside = True
                continue
            elif inside:
                break
        if inside:
            result.append(f)
    return result


def test_server_setup_section_present():
    assert "Server Setup" in _section_labels(_fields())


def test_llm_setup_section_present():
    assert "LLM Setup" in _section_labels(_fields())


def test_no_bare_setup_section():
    assert "Setup" not in _section_labels(_fields())


def test_server_url_field_default():
    section = _fields_in_section(_fields(), "Server Setup")
    values = [f.value for f in section]
    assert "http://127.0.0.1" in values


def test_server_port_field_default():
    section = _fields_in_section(_fields(), "Server Setup")
    values = [f.value for f in section]
    assert "8765" in values


def test_bearer_token_field_present():
    section = _fields_in_section(_fields(), "Server Setup")
    labels = [f.display for f in section]
    assert "bearer token" in labels


def test_language_field_in_llm_setup():
    section = _fields_in_section(_fields(), "LLM Setup")
    actions = [f.meta.get("action") for f in section]
    assert "pick_lang" in actions


def test_ai_config_field_in_llm_setup():
    section = _fields_in_section(_fields(), "LLM Setup")
    actions = [f.meta.get("action") for f in section]
    assert "open_ai_config" in actions


def test_restart_warning_when_pending():
    section = _fields_in_section(_fields(pending_restart=True), "Server Setup")
    keys = [f.key for f in section]
    assert any("restart" in k for k in keys)


def test_no_restart_warning_when_not_pending():
    section = _fields_in_section(_fields(pending_restart=False), "Server Setup")
    keys = [f.key for f in section]
    assert not any("restart" in k for k in keys)
