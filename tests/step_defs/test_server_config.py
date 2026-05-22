"""BDD step definitions for server configuration persistence scenarios."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/api/server_config.feature")


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    import ster.api_server as _mod

    fake = tmp_path / "server_config.json"
    monkeypatch.setattr(_mod, "_SERVER_CONFIG_FILE", fake)
    return {}


@given("no server config file exists")
def given_no_config(ctx):
    pass  # fixture ensures tmp path with no file


@when("I load the server config")
def when_load(ctx):
    from ster.api_server import load_server_config

    ctx["url"], ctx["port"] = load_server_config()


@when('I save server config with URL "http://192.168.1.10" and port 8765')
def when_save_custom_url(ctx):
    from ster.api_server import save_server_config

    save_server_config("http://192.168.1.10", 8765)


@when('I save server config with URL "http://127.0.0.1" and port 9000')
def when_save_custom_port(ctx):
    from ster.api_server import save_server_config

    save_server_config("http://127.0.0.1", 9000)


@then('the URL is "http://127.0.0.1"')
def then_default_url(ctx):
    assert ctx["url"] == "http://127.0.0.1"


@then('the URL is "http://192.168.1.10"')
def then_custom_url(ctx):
    assert ctx["url"] == "http://192.168.1.10"


@then("the port is 8765")
def then_default_port(ctx):
    assert ctx["port"] == 8765


@then("the port is 9000")
def then_custom_port(ctx):
    assert ctx["port"] == 9000


@then("the port equals the API_PORT constant")
def then_port_equals_constant(ctx):
    from ster.viz_vowl import API_PORT

    assert ctx["port"] == API_PORT


@then("the port is an integer")
def then_port_is_int(ctx):
    assert isinstance(ctx["port"], int)
