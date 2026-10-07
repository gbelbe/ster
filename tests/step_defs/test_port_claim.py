"""Step definitions for features/server/port_claim.feature."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import _version
from ster.viz_vowl import _claim, _server
from ster.viz_vowl._claim import BLOCKED, FREE, REUSE, claim_port

scenarios("../features/server/port_claim.feature")


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"holder": None, "served": None, "freed": [], "confirm": None}
    monkeypatch.setattr(_server, "port_holder", lambda host=None, port=None: state["holder"])
    monkeypatch.setattr(
        _claim,
        "server_overview",
        lambda *a, **k: {"file": state["served"]} if state["served"] else None,
    )
    monkeypatch.setattr(_claim, "server_build", lambda *a, **k: _version.__version__)
    monkeypatch.setattr("ster.api_server.load_token", lambda: "tok")
    monkeypatch.setattr(
        _server, "free_port", lambda pid, *a, **k: state["freed"].append(pid) or True
    )
    return state


@given("nothing holds the server port")
def nothing_holds(ctx: dict[str, Any]) -> None:
    ctx["holder"] = None


@given(parsers.parse('a ster server of the same build is serving "{name}"'))
def same_build_server(ctx: dict[str, Any], name: str) -> None:
    ctx["holder"] = (321, f"ster serve {name}")
    ctx["served"] = str(Path("/project", name).resolve())


@given(parsers.parse('a ster server is serving "{name}"'))
def other_server(ctx: dict[str, Any], name: str) -> None:
    ctx["holder"] = (321, f"ster serve {name}")
    ctx["served"] = str(Path("/project", name).resolve())


@given("another ster session is open on the server port")
def editor_holds(ctx: dict[str, Any]) -> None:
    ctx["holder"] = (321, "/venv/bin/ster edit tax.ttl")
    ctx["served"] = str(Path("/project/tax.ttl").resolve())


@given("an unrelated process holds the server port")
def foreign_holds(ctx: dict[str, Any]) -> None:
    ctx["holder"] = (321, "postgres -D /data")


@when(parsers.parse('a view is opened for "{name}"'))
def open_view(ctx: dict[str, Any], name: str) -> None:
    ctx["claim"] = claim_port(Path("/project", name))


@when(parsers.parse('a view is opened for "{name}" and the replacement is confirmed'))
def open_view_confirmed(ctx: dict[str, Any], name: str) -> None:
    ctx["claim"] = claim_port(Path("/project", name), confirm=lambda _q: True)


@then("the view opens on a fresh server")
def fresh_server(ctx: dict[str, Any]) -> None:
    assert ctx["claim"].outcome == FREE


@then("that server is reused and nothing is closed")
def reused(ctx: dict[str, Any]) -> None:
    assert ctx["claim"].outcome == REUSE
    assert ctx["freed"] == []


@then("the old server is closed and a fresh one starts")
def replaced(ctx: dict[str, Any]) -> None:
    assert ctx["claim"].outcome == FREE
    assert ctx["freed"] == [321]


@then("the user is told to close that session first")
def told_to_close(ctx: dict[str, Any]) -> None:
    assert ctx["claim"].outcome == BLOCKED
    assert "close it first to release the port" in ctx["claim"].message


@then("the user is told what holds the port")
def told_what_holds(ctx: dict[str, Any]) -> None:
    assert ctx["claim"].outcome == BLOCKED
    assert "postgres" in ctx["claim"].message


@then("nothing is closed")
def nothing_closed(ctx: dict[str, Any]) -> None:
    assert ctx["freed"] == []
