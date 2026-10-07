"""BDD step definitions for tests/features/cli/mcp_option.feature."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from typer.testing import CliRunner

from ster import plugins, query_trace
from ster.plugins import state

scenarios("../features/cli/mcp_option.feature")


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    prefs = tmp_path / "prefs.json"
    monkeypatch.setattr("ster.nav.prefs._prefs_path", lambda: prefs)
    monkeypatch.setattr(state, "_overrides", {})
    monkeypatch.setattr(state, "_env_read", False)
    monkeypatch.delenv("STER_PLUGIN_MCP", raising=False)
    monkeypatch.delenv("STER_QUERY_TRACE", raising=False)
    monkeypatch.setattr(query_trace.recorder, "_recorder", query_trace.NoOpTraceRecorder())
    file = tmp_path / "f.ttl"
    file.write_text("@prefix : <https://example.org/o#> .\n", encoding="utf-8")
    return {"prefs": prefs, "file": file, "mp": monkeypatch}


@given("the saved plugin choices are the defaults")
def defaults(ctx: dict[str, Any]) -> None:
    assert not ctx["prefs"].exists()


@given("the MCP plugin is saved as on")  # noqa: V103
def saved_on(ctx: dict[str, Any]) -> None:
    ctx["prefs"].write_text(json.dumps({"plugin.mcp.enabled": True}))


@given(parsers.parse('the environment says STER_PLUGIN_MCP is "{value}"'))
def env(ctx: dict[str, Any], value: str) -> None:
    ctx["mp"].setenv("STER_PLUGIN_MCP", value)


@when(parsers.parse('ster serve is launched on a file with "{option}"'))
def serve(ctx: dict[str, Any], option: str) -> None:
    from ster.cli import app

    ctx["mp"].setattr("ster.api_server.serve", lambda *a, **k: None)  # do not block on a server
    args = ["serve", str(ctx["file"]), *option.split()]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output


@when("ster serve is launched on a file without the option")  # noqa: V103
def serve_plain(ctx: dict[str, Any]) -> None:
    serve(ctx, "")


@when(parsers.parse('ster show is launched on a file with "{option}"'))
def show(ctx: dict[str, Any], option: str) -> None:
    from ster.cli import app

    ctx["mp"].setattr("ster.cli._viewer._open_viewer", lambda *a, **k: None)
    result = CliRunner().invoke(app, ["show", str(ctx["file"]), *option.split()])
    assert result.exit_code == 0, result.output


@when("the person unticks MCP in Config")  # noqa: V103
def untick(ctx: dict[str, Any]) -> None:
    plugins.set_enabled("mcp", False)


@then("the MCP plugin is on for that run")  # noqa: V103
def is_on(ctx: dict[str, Any]) -> None:
    assert plugins.is_enabled("mcp") is True


@then("the MCP plugin is off for that run")  # noqa: V103
def is_off(ctx: dict[str, Any]) -> None:
    assert plugins.is_enabled("mcp") is False


@then(parsers.parse("the saved choice is still {state_word}"))
def saved(ctx: dict[str, Any], state_word: str) -> None:
    saved_value = (
        json.loads(ctx["prefs"].read_text()).get("plugin.mcp.enabled", False)
        if ctx["prefs"].exists()
        else False
    )
    assert saved_value is (state_word == "on")


@then("a server built for that file records traces beside it")
def records(ctx: dict[str, Any]) -> None:
    from ster.api import SSEBroadcaster, create_app
    from ster.model import Taxonomy

    create_app(Taxonomy(), "tok", SSEBroadcaster(), lambda _t: None, file_path=ctx["file"])
    recorder = query_trace.get_recorder()
    assert recorder.enabled() is True
    assert recorder.directory == ctx["file"].parent / ".ster" / "query-traces"  # type: ignore[attr-defined]
