"""BDD step definitions for server setup UI scenarios."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/api/server_setup_ui.feature")

NS = "https://example.org/onto#"


def _make_workspace():
    from ster.model import RDFClass, Taxonomy
    from ster.workspace import TaxonomyWorkspace

    tax = Taxonomy()
    tax.owl_classes[NS + "Animal"] = RDFClass(uri=NS + "Animal")
    ws = TaxonomyWorkspace.__new__(TaxonomyWorkspace)
    ws.taxonomies = {Path("/tmp/test.ttl"): tax}
    return ws


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
def ctx():
    return {"workspace": _make_workspace()}


@given("a workspace with a single taxonomy")
def given_workspace(ctx):
    pass  # set by fixture


@when("I build the global overview fields")
def when_build_fields(ctx):
    from ster.nav.logic import build_global_fields

    ctx["fields"] = build_global_fields(
        ctx["workspace"],
        None,
        "en",
        server_url="http://127.0.0.1",
        server_port=8765,
        show_token=False,
        pending_restart=False,
    )


@when("I build the global overview fields with a pending restart")
def when_build_fields_pending(ctx):
    from ster.nav.logic import build_global_fields

    ctx["fields"] = build_global_fields(
        ctx["workspace"],
        None,
        "en",
        server_url="http://127.0.0.1",
        server_port=8765,
        show_token=False,
        pending_restart=True,
    )


@then('a section labelled "Local Server Configuration" is present')
def then_server_setup_section(ctx):
    labels = [f.display for f in ctx["fields"] if f.meta.get("type") == "separator"]
    assert "Local Server Configuration" in labels


@then('a section labelled "LLM Setup" is present')
def then_llm_setup_section(ctx):
    labels = [f.display for f in ctx["fields"] if f.meta.get("type") == "separator"]
    assert "LLM Setup" in labels


@then('no section is labelled exactly "Setup"')
def then_no_bare_setup(ctx):
    labels = [f.display for f in ctx["fields"] if f.meta.get("type") == "separator"]
    assert "Setup" not in labels


@then('the Local Server Configuration section contains a field showing "http://127.0.0.1"')
def then_url_field(ctx):
    section = _fields_in_section(ctx["fields"], "Local Server Configuration")
    assert any(f.value == "http://127.0.0.1" for f in section)


@then('the Local Server Configuration section contains a field showing "8765"')
def then_port_field(ctx):
    section = _fields_in_section(ctx["fields"], "Local Server Configuration")
    assert any(f.value == "8765" for f in section)


@then('the Local Server Configuration section contains a field labelled "bearer token"')
def then_bearer_token_field(ctx):
    section = _fields_in_section(ctx["fields"], "Local Server Configuration")
    assert any(f.display == "bearer token" for f in section)


@then('the LLM Setup section contains a field with action "pick_lang"')
def then_pick_lang_in_llm(ctx):
    section = _fields_in_section(ctx["fields"], "LLM Setup")
    assert any(f.meta.get("action") == "pick_lang" for f in section)


@then('the LLM Setup section contains a field with action "open_ai_config"')
def then_ai_config_in_llm(ctx):
    section = _fields_in_section(ctx["fields"], "LLM Setup")
    assert any(f.meta.get("action") == "open_ai_config" for f in section)


@then("the Local Server Configuration section contains a restart warning field")
def then_restart_warning_present(ctx):
    section = _fields_in_section(ctx["fields"], "Local Server Configuration")
    assert any("restart" in f.key for f in section)


@then("the Local Server Configuration section contains no restart warning field")
def then_no_restart_warning(ctx):
    section = _fields_in_section(ctx["fields"], "Local Server Configuration")
    assert not any("restart" in f.key for f in section)
