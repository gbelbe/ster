"""BDD step definitions for tests/features/sparql/sparql_triple_context.feature."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster.sparql_query import _sparql_context_at_cursor

scenarios("../features/sparql/sparql_triple_context.feature")


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {"buffer": "", "result": ""}


@given(parsers.parse('a SPARQL buffer "{buffer}"'))
def sparql_buffer(buffer: str, ctx: dict[str, Any]) -> None:
    ctx["buffer"] = buffer


@when("_sparql_context_at_cursor is called at end of buffer")
def call_context_at_cursor(ctx: dict[str, Any]) -> None:
    buf = ctx["buffer"]
    ctx["result"] = _sparql_context_at_cursor(buf, len(buf))


@then(parsers.parse('the context is "{expected}"'))
def context_is(expected: str, ctx: dict[str, Any]) -> None:
    assert ctx["result"] == expected, f"Expected {expected!r}, got {ctx['result']!r}"
