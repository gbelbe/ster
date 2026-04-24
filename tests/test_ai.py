"""Tests for ster/ai.py — config, pure helpers, prompt builders, mocked LLM calls."""

from __future__ import annotations

import json
import subprocess
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

import ster.ai as ai_module
from ster.ai import (
    _build_alt_labels_prompt,
    _build_concept_names_prompt,
    _build_sparql_prompt,
    _call,
    _extract_sparql_body,
    _is_label,
    _load_config,
    _parse_alt_labels,
    _parse_sparql,
    _repair_sparql,
    _safe_stderr,
    _save_config,
    _try_copy_to_clipboard,
    _validate_sparql_syntax,
    _validated_sparql,
    available_plugins,
    generate_sparql,
    generate_sparql_from_prompt,
    get_config,
    get_model,
    get_model_for,
    get_saved_model,
    is_available,
    is_configured,
    is_copypaste,
    render_generate_sparql_prompt,
    render_suggest_alt_labels_prompt,
    render_suggest_concept_names_prompt,
    save_copypaste,
    save_model,
    save_model_for,
    suggest_alt_labels,
    suggest_alt_labels_from_prompt,
    suggest_concept_names,
    suggest_concept_names_from_prompt,
    suggest_definition,
)

# ── config helpers ────────────────────────────────────────────────────────────


def test_load_config_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", tmp_path / "nonexistent.json")
    assert _load_config() == {}


def test_load_config_with_valid_json(tmp_path, monkeypatch):
    cfg_file = tmp_path / "ai.json"
    cfg_file.write_text(json.dumps({"model": "gpt-4o"}))
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    assert _load_config() == {"model": "gpt-4o"}


def test_load_config_corrupted_json(tmp_path, monkeypatch):
    cfg_file = tmp_path / "ai.json"
    cfg_file.write_text("NOT JSON!!!")
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    assert _load_config() == {}


def test_save_config_creates_parent_dir(tmp_path, monkeypatch):
    # Parent directory does not exist yet → _save_config must create it (line 51)
    cfg_file = tmp_path / "newdir" / "subdir" / "ai.json"
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    _save_config({"model": "test"})
    assert cfg_file.exists()
    assert json.loads(cfg_file.read_text()) == {"model": "test"}


def test_get_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "ai.json"
    cfg_file.write_text(json.dumps({"model": "claude-3"}))
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    assert get_config()["model"] == "claude-3"


def test_save_model(tmp_path, monkeypatch):
    cfg_file = tmp_path / "ai.json"
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    save_model("my-model")
    assert _load_config()["model"] == "my-model"


def test_save_model_for(tmp_path, monkeypatch):
    cfg_file = tmp_path / "ai.json"
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    save_model_for("suggest", "llm-fast")
    assert _load_config()["models"]["suggest"] == "llm-fast"


def test_get_saved_model(tmp_path, monkeypatch):
    cfg_file = tmp_path / "ai.json"
    cfg_file.write_text(json.dumps({"model": "saved-model"}))
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    assert get_saved_model() == "saved-model"


def test_get_saved_model_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", tmp_path / "nope.json")
    assert get_saved_model() is None


# ── is_copypaste ──────────────────────────────────────────────────────────────


def test_is_copypaste_env_var_true(monkeypatch, tmp_path):
    monkeypatch.setenv("STER_COPYPASTE", "1")
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", tmp_path / "ai.json")
    assert is_copypaste() is True


def test_is_copypaste_env_var_false(monkeypatch, tmp_path):
    monkeypatch.setenv("STER_COPYPASTE", "0")
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", tmp_path / "ai.json")
    assert is_copypaste() is False


def test_is_copypaste_env_var_yes(monkeypatch, tmp_path):
    monkeypatch.setenv("STER_COPYPASTE", "yes")
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", tmp_path / "ai.json")
    assert is_copypaste() is True


def test_is_copypaste_from_config_true(monkeypatch, tmp_path):
    monkeypatch.delenv("STER_COPYPASTE", raising=False)
    cfg_file = tmp_path / "ai.json"
    cfg_file.write_text(json.dumps({"copypaste": True}))
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    assert is_copypaste() is True


def test_is_copypaste_from_config_false(monkeypatch, tmp_path):
    monkeypatch.delenv("STER_COPYPASTE", raising=False)
    cfg_file = tmp_path / "ai.json"
    cfg_file.write_text(json.dumps({"copypaste": False}))
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    assert is_copypaste() is False


# ── save_copypaste ────────────────────────────────────────────────────────────


def test_save_copypaste_true(tmp_path, monkeypatch):
    cfg_file = tmp_path / "ai.json"
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    save_copypaste(True)
    assert _load_config()["copypaste"] is True


def test_save_copypaste_false(tmp_path, monkeypatch):
    cfg_file = tmp_path / "ai.json"
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    save_copypaste(False)
    assert _load_config()["copypaste"] is False


# ── _try_copy_to_clipboard ────────────────────────────────────────────────────


def test_try_copy_darwin_success(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    with patch("subprocess.run", return_value=None):
        assert _try_copy_to_clipboard("hello") is True


def test_try_copy_darwin_failure(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "pbcopy")):
        assert _try_copy_to_clipboard("hello") is False


def test_try_copy_unknown_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "freebsd13")
    assert _try_copy_to_clipboard("hello") is False


# ── is_available ──────────────────────────────────────────────────────────────


def test_is_available_false_when_llm_not_installed(monkeypatch):
    saved = sys.modules.get("llm", ...)
    sys.modules["llm"] = None  # type: ignore[assignment]
    try:
        assert is_available() is False
    finally:
        if saved is ...:
            sys.modules.pop("llm", None)
        else:
            sys.modules["llm"] = saved


def test_is_available_true_when_llm_installed(monkeypatch):
    fake_llm = types.ModuleType("llm")
    monkeypatch.setitem(sys.modules, "llm", fake_llm)
    assert is_available() is True


# ── is_configured ─────────────────────────────────────────────────────────────


def test_is_configured_via_copypaste(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", tmp_path / "ai.json")
    monkeypatch.setattr(ai_module, "is_copypaste", lambda: True)
    assert is_configured() is True


def test_is_configured_false_without_llm(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", tmp_path / "ai.json")
    monkeypatch.setattr(ai_module, "is_copypaste", lambda: False)
    # llm not installed → False
    saved = sys.modules.get("llm", ...)
    sys.modules["llm"] = None  # type: ignore[assignment]
    try:
        assert is_configured() is False
    finally:
        if saved is ...:
            sys.modules.pop("llm", None)
        else:
            sys.modules["llm"] = saved


# ── available_plugins ─────────────────────────────────────────────────────────


def test_available_plugins_returns_all_when_none_installed():
    plugins = available_plugins(set())
    assert len(plugins) > 0
    assert all(len(p) == 3 for p in plugins)


def test_available_plugins_filters_installed():
    all_plugins = available_plugins(set())
    module_ids = {p[0] for p in all_plugins}
    # If we say one is installed, it should be filtered out
    if module_ids:
        one = next(iter(module_ids))
        filtered = available_plugins({one})
        filtered_ids = {p[0] for p in filtered}
        assert one not in filtered_ids


# ── get_model_for ─────────────────────────────────────────────────────────────


def test_get_model_for_raises_when_llm_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", tmp_path / "ai.json")
    saved = sys.modules.get("llm", ...)
    sys.modules["llm"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="llm.*package"):
            get_model_for("default")
    finally:
        if saved is ...:
            sys.modules.pop("llm", None)
        else:
            sys.modules["llm"] = saved


def test_get_model_for_raises_when_no_model_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", tmp_path / "ai.json")
    fake_llm = types.ModuleType("llm")
    monkeypatch.setitem(sys.modules, "llm", fake_llm)
    with pytest.raises(RuntimeError, match="No LLM model"):
        get_model_for("default")


def test_get_model_for_raises_when_model_load_fails(tmp_path, monkeypatch):
    cfg_file = tmp_path / "ai.json"
    cfg_file.write_text(json.dumps({"model": "bad-model"}))
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", cfg_file)
    fake_llm = types.ModuleType("llm")

    def fail_get_model(model_id: str):
        raise Exception("model not found")

    fake_llm.get_model = fail_get_model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llm", fake_llm)
    with pytest.raises(RuntimeError, match="Could not load"):
        get_model_for("default")


def test_get_model_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_module, "_CONFIG_PATH", tmp_path / "ai.json")
    with pytest.raises(RuntimeError):
        get_model()


# ── _is_label ─────────────────────────────────────────────────────────────────


def test_is_label_empty_string():
    assert _is_label("") is False
    assert _is_label("   ") is False


def test_is_label_ends_with_colon():
    assert _is_label("Category:") is False


def test_is_label_too_long():
    assert _is_label("x" * 81) is False


def test_is_label_preamble():
    assert _is_label("Sure, here are the concepts:") is False
    assert _is_label("Here are some suggestions") is False


def test_is_label_valid():
    assert _is_label("Hydraulic Turbine") is True
    assert _is_label("Marine Engine") is True


def test_is_label_numbered_line_stripped():
    # _is_label receives the line after numbering is stripped by the caller
    assert _is_label("Widget Component") is True


# ── _safe_stderr ──────────────────────────────────────────────────────────────


def test_safe_stderr_redirects_and_restores():
    import sys

    original = sys.stderr
    with _safe_stderr():
        inside = sys.stderr
        assert inside is not original
    assert sys.stderr is original


# ── _call ─────────────────────────────────────────────────────────────────────


def test_call_copypaste_mode(monkeypatch):
    monkeypatch.setattr(ai_module, "is_copypaste", lambda: True)
    monkeypatch.setattr(ai_module, "_copypaste_interact", lambda t: "paste response")
    assert _call("prompt", "task") == "paste response"


def test_call_llm_mode(monkeypatch):
    mock_model = MagicMock()
    mock_model.prompt.return_value.text.return_value = "llm response"
    monkeypatch.setattr(ai_module, "is_copypaste", lambda: False)
    monkeypatch.setattr(ai_module, "get_model_for", lambda task: mock_model)
    result = _call("my prompt", "my_task")
    assert result == "llm response"


# ── prompt builders ───────────────────────────────────────────────────────────


def test_build_concept_names_prompt_with_parent():
    result = _build_concept_names_prompt(
        "Tech Tax", "Technology taxonomy", "Software", "en", 10, None, "Software systems"
    )
    assert "Software" in result
    assert "en" in result
    assert "10" in result


def test_build_concept_names_prompt_without_parent():
    result = _build_concept_names_prompt("Tech Tax", "", None, "fr", 20, None, "")
    assert "top-level" in result.lower() or "direct children" in result.lower()
    assert "fr" in result


def test_build_concept_names_prompt_with_excludes():
    result = _build_concept_names_prompt("T", "", None, "en", 5, ["AlreadyThere", "Skip"], "")
    assert "AlreadyThere" in result or "NOT repeat" in result


def test_build_concept_names_prompt_desc_line():
    result = _build_concept_names_prompt("T", "A description here", None, "en", 5, None, "")
    assert "A description here" in result


def test_render_suggest_concept_names_prompt():
    result = render_suggest_concept_names_prompt("My Tax", "Desc", None, "en", n=10)
    assert len(result) > 0
    assert "en" in result


def test_build_alt_labels_prompt_with_definition():
    result = _build_alt_labels_prompt(
        "Pump", "Marine", "Hydraulic systems", "en", "A device that moves fluid"
    )
    assert "Pump" in result
    assert "A device that moves fluid" in result


def test_build_alt_labels_prompt_without_definition():
    result = _build_alt_labels_prompt("Pump", "Marine", "Hydraulic systems", "en")
    assert "Pump" in result
    assert "Marine" in result


def test_render_suggest_alt_labels_prompt():
    result = render_suggest_alt_labels_prompt("Valve", "Marine", "Desc", "en")
    assert "Valve" in result


def test_build_sparql_prompt_with_uris():
    result = _build_sparql_prompt("Tax", "Desc", ["http://ex.org/s1"], "find all concepts")
    assert "find all concepts" in result
    assert "http://ex.org/s1" in result


def test_build_sparql_prompt_no_uris():
    result = _build_sparql_prompt("Tax", "", [], "find all")
    assert "find all" in result


def test_render_generate_sparql_prompt():
    result = render_generate_sparql_prompt("Tax", "Desc", [], "find things")
    assert "find things" in result


# ── _parse_alt_labels ─────────────────────────────────────────────────────────


def test_parse_alt_labels_numbered_list():
    text = "1. Synonym A\n2. Alternative B\n3. Another C"
    result = _parse_alt_labels(text)
    assert "Synonym A" in result
    assert "Alternative B" in result


def test_parse_alt_labels_caps_at_five():
    text = "\n".join(f"{i}. Label {i}" for i in range(1, 10))
    result = _parse_alt_labels(text)
    assert len(result) <= 5


def test_parse_alt_labels_skips_preamble():
    text = "Sure, here are the alt labels:\n1. Valve\n2. Stopcock"
    result = _parse_alt_labels(text)
    # The preamble line should be filtered out
    assert not any("Sure" in r for r in result)


# ── _parse_sparql ─────────────────────────────────────────────────────────────


def test_parse_sparql_with_markdown_fence():
    text = "Here is your query:\n```sparql\nSELECT ?s WHERE { ?s a skos:Concept }\n```"
    result = _parse_sparql(text)
    assert "SELECT ?s WHERE" in result


def test_parse_sparql_adds_standard_prefixes():
    text = "SELECT ?s WHERE { ?s a skos:Concept }"
    result = _parse_sparql(text)
    assert "PREFIX skos:" in result


def test_parse_sparql_no_duplicate_prefixes():
    text = (
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\nSELECT ?s WHERE { ?s a skos:Concept }"
    )
    result = _parse_sparql(text)
    assert result.count("PREFIX skos:") == 1


# ── _extract_sparql_body ──────────────────────────────────────────────────────


def test_extract_sparql_body_from_select():
    text = "Here is your query:\nSELECT ?s WHERE { ?s a skos:Concept }"
    result = _extract_sparql_body(text)
    assert result.startswith("SELECT")


def test_extract_sparql_body_from_prefix():
    text = "Preamble text\nPREFIX skos: <x>\nSELECT ?s WHERE { ?s a skos:Concept }"
    result = _extract_sparql_body(text)
    assert result.startswith("PREFIX")


def test_extract_sparql_body_no_keyword_returns_full():
    text = "This text has no SPARQL keyword at all."
    result = _extract_sparql_body(text)
    assert result == text.strip()


# ── _validate_sparql_syntax ───────────────────────────────────────────────────


def test_validate_sparql_syntax_valid():
    query = (
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\nSELECT ?s WHERE { ?s a skos:Concept }"
    )
    assert _validate_sparql_syntax(query) == ""


def test_validate_sparql_syntax_invalid():
    result = _validate_sparql_syntax("NOT VALID SPARQL {{{{ ???")
    assert isinstance(result, str)
    assert len(result) > 0


# ── _validated_sparql ─────────────────────────────────────────────────────────


def test_validated_sparql_valid_query():
    valid = (
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\nSELECT ?s WHERE { ?s a skos:Concept }"
    )
    result = _validated_sparql(valid)
    assert result == valid


def test_validated_sparql_repairs(monkeypatch):
    call_count = [0]

    def mock_validate(q: str) -> str:
        call_count[0] += 1
        return "" if call_count[0] > 1 else "syntax error"

    monkeypatch.setattr(ai_module, "_validate_sparql_syntax", mock_validate)
    monkeypatch.setattr(ai_module, "_repair_sparql", lambda q, e: "REPAIRED")
    result = _validated_sparql("BAD QUERY")
    assert result == "REPAIRED"


def test_validated_sparql_copypaste_skips_repair(monkeypatch):
    monkeypatch.setattr(ai_module, "is_copypaste", lambda: True)
    monkeypatch.setattr(ai_module, "_validate_sparql_syntax", lambda q: "error")
    repair_calls = []
    monkeypatch.setattr(ai_module, "_repair_sparql", lambda q, e: repair_calls.append(True) or q)
    _validated_sparql("BAD QUERY")
    assert not repair_calls


# ── suggest_concept_names (mocked _call) ──────────────────────────────────────


def test_suggest_concept_names_mock_call(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "1. Widget A\n2. Widget B\n3. Gadget")
    result = suggest_concept_names("Tax", "Desc", None, "en", n=5)
    assert "Widget A" in result
    assert "Widget B" in result


def test_suggest_concept_names_with_excludes(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "1. Widget A\n2. Skip Me")
    result = suggest_concept_names("Tax", "Desc", None, "en", exclude=["Skip Me"])
    assert "Skip Me" not in result


def test_suggest_concept_names_with_parent(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "1. SubWidget\n2. SubGadget")
    result = suggest_concept_names("Tax", "", "Parent", "en", n=3, parent_definition="Parent def")
    assert len(result) > 0


def test_suggest_concept_names_from_prompt(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "1. Item A\n2. Item B")
    result = suggest_concept_names_from_prompt("some prompt text")
    assert "Item A" in result


# ── suggest_alt_labels (mocked _call) ────────────────────────────────────────


def test_suggest_alt_labels(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "1. Synonym A\n2. Synonym B")
    result = suggest_alt_labels("Pump", "Marine", "Hydraulic", "en")
    assert len(result) > 0


def test_suggest_alt_labels_from_prompt(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "1. Synonym A\n2. Alt B")
    result = suggest_alt_labels_from_prompt("some prompt")
    assert len(result) > 0


# ── suggest_definition (mocked _call) ────────────────────────────────────────


def test_suggest_definition_with_parent(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "A hydraulic pump definition.")
    result = suggest_definition("Pump", "Marine", "Hydraulic", "ParentLabel", "en")
    assert "pump" in result.lower()


def test_suggest_definition_no_parent(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "A top-level definition.")
    result = suggest_definition("Widget", "Tech", "Technology", None, "en")
    assert len(result) > 0


def test_suggest_definition_with_parent_definition(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "Child concept definition.")
    result = suggest_definition("SubWidget", "Tax", "Desc", "Parent", "en", "Parent is a thing")
    assert len(result) > 0


# ── _repair_sparql (mocked _call) ────────────────────────────────────────────


def test_repair_sparql(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "SELECT ?s WHERE { ?s a skos:Concept }")
    result = _repair_sparql("SELECT WHERE {{{", "syntax error near {{{")
    assert "SELECT" in result or "PREFIX" in result


# ── generate_sparql (mocked _call) ───────────────────────────────────────────


def test_generate_sparql(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "SELECT ?s WHERE { ?s a skos:Concept }")
    result = generate_sparql("Tax", "Desc", ["http://ex.org/s"], "find concepts")
    assert "SELECT" in result or "PREFIX" in result


def test_generate_sparql_from_prompt(monkeypatch):
    monkeypatch.setattr(ai_module, "_call", lambda p, t: "SELECT ?s WHERE { ?s a skos:Concept }")
    result = generate_sparql_from_prompt("find all concepts in the taxonomy")
    assert len(result) > 0
