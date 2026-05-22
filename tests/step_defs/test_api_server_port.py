"""BDD step definitions for the fixed API server port scenarios."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/api/server_port.feature")

_EXTENSION_DIR = Path(__file__).parent.parent.parent / "kai-extension"


@pytest.fixture
def ctx():
    return {}


@given("the ster viz_vowl module")
def given_viz_vowl(ctx):
    pass  # import happens in the When step


@given("the kai extension popup.js source")
def given_popup_js(ctx):
    ctx["popup_js"] = (_EXTENSION_DIR / "popup.js").read_text()


@when("I read the API_PORT constant")
def when_read_api_port(ctx):
    from ster.viz_vowl import API_PORT

    ctx["api_port"] = API_PORT


@when("I read the DEFAULT_API_URL constant")
def when_read_default_api_url(ctx):
    src = ctx["popup_js"]
    for line in src.splitlines():
        line = line.strip()
        if line.startswith("const DEFAULT_API_URL"):
            # extract value from: const DEFAULT_API_URL = "...";
            ctx["default_api_url"] = line.split("=", 1)[1].strip().rstrip(";").strip('"')
            return
    ctx["default_api_url"] = None


@then("API_PORT equals 8765")
def then_api_port_8765(ctx):
    assert ctx["api_port"] == 8765


@then('the server URL resolves to "http://127.0.0.1:8765/"')
def then_server_url(ctx):
    assert f"http://127.0.0.1:{ctx['api_port']}/" == "http://127.0.0.1:8765/"


@then('DEFAULT_API_URL equals "http://127.0.0.1:8765"')
def then_default_api_url(ctx):
    assert ctx["default_api_url"] == "http://127.0.0.1:8765"
