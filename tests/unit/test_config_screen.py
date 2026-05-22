"""Unit tests for the standalone config screen field builder."""

from __future__ import annotations

from ster.nav.logic import build_global_fields


def _fields_in_section(fields, section_label: str):
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


def _section_labels(fields):
    return [f.display for f in fields if f.meta.get("type") == "separator"]


# ── Section presence ──────────────────────────────────────────────────────────


def test_config_fields_has_server_setup_section():
    fields = build_global_fields(None, None, "en", server_url="http://127.0.0.1", server_port=8765)
    assert "Server Setup" in _section_labels(fields)


def test_config_fields_has_llm_setup_section():
    fields = build_global_fields(None, None, "en", server_url="http://127.0.0.1", server_port=8765)
    assert "LLM Setup" in _section_labels(fields)


# ── Server URL and port display ───────────────────────────────────────────────


def test_config_fields_shows_current_url():
    fields = build_global_fields(None, None, "en", server_url="http://127.0.0.1", server_port=8765)
    section = _fields_in_section(fields, "Server Setup")
    assert any(f.value == "http://127.0.0.1" for f in section)


def test_config_fields_shows_current_port():
    fields = build_global_fields(None, None, "en", server_url="http://127.0.0.1", server_port=8765)
    section = _fields_in_section(fields, "Server Setup")
    assert any(f.value == "8765" for f in section)


def test_config_fields_url_and_port_are_editable():
    fields = build_global_fields(
        None, None, "en", server_url="http://192.168.1.5", server_port=9000
    )
    section = _fields_in_section(fields, "Server Setup")
    actions = {f.meta.get("action") for f in section}
    assert "edit_server_url" in actions
    assert "edit_server_port" in actions


# ── Bearer token ──────────────────────────────────────────────────────────────


def test_config_fields_has_bearer_token_field():
    fields = build_global_fields(None, None, "en", server_url="http://127.0.0.1", server_port=8765)
    section = _fields_in_section(fields, "Server Setup")
    assert any(f.display == "bearer token" for f in section)


def test_config_fields_token_hidden_by_default():
    fields = build_global_fields(
        None, None, "en", server_url="http://127.0.0.1", server_port=8765, show_token=False
    )
    section = _fields_in_section(fields, "Server Setup")
    token_field = next(f for f in section if f.display == "bearer token")
    assert token_field.value == "***"


def test_config_fields_token_visible_when_revealed(tmp_path, monkeypatch):
    import ster.api_server as srv

    token_file = tmp_path / "api_token"
    token_file.write_text("my-secret-token")
    monkeypatch.setattr(srv, "_TOKEN_FILE", token_file)

    fields = build_global_fields(
        None, None, "en", server_url="http://127.0.0.1", server_port=8765, show_token=True
    )
    section = _fields_in_section(fields, "Server Setup")
    token_field = next(f for f in section if f.display == "bearer token")
    assert token_field.value == "my-secret-token"


# ── Restart warning ───────────────────────────────────────────────────────────


def test_config_fields_restart_warning_present_after_change():
    fields = build_global_fields(
        None, None, "en", server_url="http://127.0.0.1", server_port=8765, pending_restart=True
    )
    section = _fields_in_section(fields, "Server Setup")
    assert any("restart" in f.key for f in section)


def test_config_fields_restart_warning_absent_at_rest():
    fields = build_global_fields(
        None, None, "en", server_url="http://127.0.0.1", server_port=8765, pending_restart=False
    )
    section = _fields_in_section(fields, "Server Setup")
    assert not any("restart" in f.key for f in section)


# ── Config persistence ────────────────────────────────────────────────────────


def test_save_url_persists_to_config(tmp_path, monkeypatch):
    import ster.api_server as srv

    cfg_file = tmp_path / "server_config.json"
    monkeypatch.setattr(srv, "_SERVER_CONFIG_FILE", cfg_file)

    srv.save_server_config("http://192.168.1.10", 8765)
    url, _ = srv.load_server_config()
    assert url == "http://192.168.1.10"


def test_save_port_persists_to_config(tmp_path, monkeypatch):
    import ster.api_server as srv

    cfg_file = tmp_path / "server_config.json"
    monkeypatch.setattr(srv, "_SERVER_CONFIG_FILE", cfg_file)

    srv.save_server_config("http://127.0.0.1", 9999)
    _, port = srv.load_server_config()
    assert port == 9999
