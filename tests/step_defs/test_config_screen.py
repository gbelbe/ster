"""BDD step definitions for the standalone config screen scenarios."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/ui/config_screen.feature")


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


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    import ster.api_server as srv

    cfg_file = tmp_path / "server_config.json"
    monkeypatch.setattr(srv, "_SERVER_CONFIG_FILE", cfg_file)

    token_file = tmp_path / "api_token"
    token_file.write_text("test-secret-token")
    monkeypatch.setattr(srv, "_TOKEN_FILE", token_file)

    return {"tmp_path": tmp_path, "monkeypatch": monkeypatch, "fields": []}


# ── Given ─────────────────────────────────────────────────────────────────────


@given('a server configured at URL "http://127.0.0.1" and port 8765')
def given_default_server_config(ctx):
    import ster.api_server as srv

    srv.save_server_config("http://127.0.0.1", 8765)
    ctx["server_url"] = "http://127.0.0.1"
    ctx["server_port"] = 8765


# ── When ──────────────────────────────────────────────────────────────────────


@when("I build the config screen fields")
def when_build_fields(ctx):
    from ster.nav.logic import build_global_fields

    ctx["fields"] = build_global_fields(
        None,
        None,
        "en",
        server_url=ctx["server_url"],
        server_port=ctx["server_port"],
    )


@when("I build the config screen fields with show_token false")
def when_build_fields_token_hidden(ctx):
    from ster.nav.logic import build_global_fields

    ctx["fields"] = build_global_fields(
        None,
        None,
        "en",
        server_url=ctx["server_url"],
        server_port=ctx["server_port"],
        show_token=False,
    )


@when("I build the config screen fields with show_token true")
def when_build_fields_token_visible(ctx):
    from ster.nav.logic import build_global_fields

    ctx["fields"] = build_global_fields(
        None,
        None,
        "en",
        server_url=ctx["server_url"],
        server_port=ctx["server_port"],
        show_token=True,
    )


@when("I build the config screen fields with a pending restart")
def when_build_fields_pending_restart(ctx):
    from ster.nav.logic import build_global_fields

    ctx["fields"] = build_global_fields(
        None,
        None,
        "en",
        server_url=ctx["server_url"],
        server_port=ctx["server_port"],
        pending_restart=True,
    )


@when("I build the config screen fields without a pending restart")
def when_build_fields_no_pending_restart(ctx):
    from ster.nav.logic import build_global_fields

    ctx["fields"] = build_global_fields(
        None,
        None,
        "en",
        server_url=ctx["server_url"],
        server_port=ctx["server_port"],
        pending_restart=False,
    )


@when('the user saves server URL "http://192.168.1.10" via config screen')
def when_save_url(ctx):
    import ster.api_server as srv

    srv.save_server_config("http://192.168.1.10", ctx["server_port"])


@when('the user saves server port "9999" via config screen')
def when_save_port(ctx):
    import ster.api_server as srv

    srv.save_server_config(ctx["server_url"], 9999)


# ── Then ──────────────────────────────────────────────────────────────────────


@then('a section labelled "Server Setup" is present')
def then_server_setup_section(ctx):
    labels = [f.display for f in ctx["fields"] if f.meta.get("type") == "separator"]
    assert "Server Setup" in labels


@then('a section labelled "LLM Setup" is present')
def then_llm_setup_section(ctx):
    labels = [f.display for f in ctx["fields"] if f.meta.get("type") == "separator"]
    assert "LLM Setup" in labels


@then('the Server Setup section contains a field showing "http://127.0.0.1"')
def then_url_shown(ctx):
    section = _fields_in_section(ctx["fields"], "Server Setup")
    assert any(f.value == "http://127.0.0.1" for f in section)


@then('the Server Setup section contains a field showing "8765"')
def then_port_shown(ctx):
    section = _fields_in_section(ctx["fields"], "Server Setup")
    assert any(f.value == "8765" for f in section)


@then("the Server Setup section contains a bearer token field with hidden value")
def then_token_hidden(ctx):
    section = _fields_in_section(ctx["fields"], "Server Setup")
    token_field = next((f for f in section if f.display == "bearer token"), None)
    assert token_field is not None
    assert token_field.value == "***"


@then("the Server Setup section contains a bearer token field with visible value")
def then_token_visible(ctx):
    section = _fields_in_section(ctx["fields"], "Server Setup")
    token_field = next((f for f in section if f.display == "bearer token"), None)
    assert token_field is not None
    assert token_field.value != "***"
    assert len(token_field.value) > 0


@then("the Server Setup section contains a restart warning field")
def then_restart_warning_present(ctx):
    section = _fields_in_section(ctx["fields"], "Server Setup")
    assert any("restart" in f.key for f in section)


@then("the Server Setup section contains no restart warning field")
def then_no_restart_warning(ctx):
    section = _fields_in_section(ctx["fields"], "Server Setup")
    assert not any("restart" in f.key for f in section)


@then('load_server_config returns URL "http://192.168.1.10"')
def then_url_persisted(ctx):
    import ster.api_server as srv

    url, _ = srv.load_server_config()
    assert url == "http://192.168.1.10"


@then("load_server_config returns port 9999")
def then_port_persisted(ctx):
    import ster.api_server as srv

    _, port = srv.load_server_config()
    assert port == 9999
