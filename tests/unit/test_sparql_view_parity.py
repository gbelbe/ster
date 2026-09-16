"""Both transports offer the same thing, because neither owns it.

`/api/sparql_query` and the MCP `run_sparql` tool call one function. That is the
stated design — the endpoint's own docstring says "MCP is a transport; the logic
belongs here" — and `view` is handled in that function so the two cannot drift.

This is the test that would have caught the first version of the feature, which
put `view` in the MCP tool alone.
"""

from __future__ import annotations

import inspect

from ster import mcp_context
from ster.api import QueryIn
from ster.mcp_server import TOOLS


def _run_sparql_tool() -> dict:
    return next(tool for tool in TOOLS if tool["name"] == "run_sparql")


def test_the_mcp_tool_accepts_a_view():
    properties = _run_sparql_tool()["inputSchema"]["properties"]

    assert "view" in properties
    assert set(properties["view"]["enum"]) == {"map", "graph"}


def test_the_rest_endpoint_accepts_the_same_view():
    assert "view" in QueryIn.model_fields


def test_view_is_optional_on_both():
    """Neither transport may require it: the rows are the point."""
    assert "view" not in _run_sparql_tool()["inputSchema"]["required"]
    assert QueryIn.model_fields["view"].default is None


def test_the_shared_function_is_where_view_is_handled():
    """Not in either caller. `run_sparql` forwards and does nothing else, which
    is what keeps the two transports honest."""
    assert "view" in inspect.signature(mcp_context.sparql_payload).parameters
    body = inspect.getsource(mcp_context.run_sparql)

    assert "sparql_payload(taxonomy, query, view)" in body
    assert "annotate" not in body, "the alias must not grow logic of its own"


def test_the_tool_description_states_both_preconditions():
    """An agent choosing `view` should not have to discover the rules by being
    refused."""
    description = _run_sparql_tool()["inputSchema"]["properties"]["view"]["description"]

    assert "coordinates" in description
    assert "CONSTRUCT" in description
    assert "view_unavailable" in description
