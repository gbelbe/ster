"""BDD step definitions for tests/features/mcp/run_sparql_question.feature."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import mcp_server as ms
from ster import query_trace
from ster.model import Concept, Label, LabelType, Taxonomy
from ster.query_trace.jsonl import read_events

scenarios("../features/mcp/run_sparql_question.feature")

NS = "https://example.org/zoo#"
QUERY = "SELECT (COUNT(?s) AS ?n) WHERE { ?s ?p ?o }"


@pytest.fixture
def ctx(tmp_path: Path) -> dict[str, Any]:
    yield {"dir": tmp_path}
    query_trace.configure(False)


@given("a graph with a few concepts")
def graph(ctx: dict[str, Any]) -> None:
    tax = Taxonomy()
    for name in ("Animal", "Dog"):
        tax.concepts[NS + name] = Concept(
            uri=NS + name, labels=[Label(lang="en", value=name, type=LabelType.PREF)]
        )
    ctx["taxonomy"] = tax


@given("query tracing is on")  # noqa: V103
def tracing(ctx: dict[str, Any]) -> None:
    query_trace.configure(True, str(ctx["dir"]))


def _call(
    ctx: dict[str, Any], arguments: dict[str, Any], meta: dict[str, Any] | None = None
) -> None:
    params: dict[str, Any] = {"name": "run_sparql", "arguments": {"query": QUERY, **arguments}}
    if meta:
        params["_meta"] = meta
    reply = ms.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}, ctx["taxonomy"]
    )
    assert reply is not None and reply["result"]["isError"] is False
    import json

    ctx["answer"] = json.loads(reply["result"]["content"][0]["text"])


@when(parsers.parse('an agent runs a query with the question "{question}"'))  # noqa: V103
def with_question(ctx: dict[str, Any], question: str) -> None:
    _call(ctx, {"question": question})


@when(  # noqa: V103
    parsers.parse(
        'an agent runs a query with the question "{question}" and the metadata question "{meta}"'
    )
)
def with_both(ctx: dict[str, Any], question: str, meta: str) -> None:
    _call(ctx, {"question": question}, {"com.adeo/agent-question": meta})


@when("an agent runs a query with no question")
def without(ctx: dict[str, Any]) -> None:
    _call(ctx, {})


@when(parsers.parse("an agent runs a query with the unusable question {value}"))  # noqa: V103
def unusable(ctx: dict[str, Any], value: str) -> None:
    arguments = {
        '"   "': {"question": "   "},
        "42": {"question": 42},
        "too-long": {"question": "x" * (ms._QUESTION_MAX + 1)},
    }[value]
    _call(ctx, arguments)


@then(parsers.parse('run_sparql declares an optional "{name}" argument'))
def declared(name: str) -> None:
    tool = next(t for t in ms.TOOLS if t["name"] == "run_sparql")
    assert name in tool["inputSchema"]["properties"]
    assert name not in tool["inputSchema"].get("required", [])
    assert tool["inputSchema"]["properties"][name]["type"] == "string"


def _recorded(ctx: dict[str, Any]) -> str | None:
    [journal] = ctx["dir"].glob("run-*.jsonl")
    return next(read_events(journal)).payload["agent_question"]


@then(parsers.parse('the trace of that call records the question "{question}"'))
def records(ctx: dict[str, Any], question: str) -> None:
    assert _recorded(ctx) == question


@then("the trace of that call has no question")  # noqa: V103
def records_none(ctx: dict[str, Any]) -> None:
    assert _recorded(ctx) is None


@then("the answer does not ask for the question again")  # noqa: V103
def not_asked(ctx: dict[str, Any]) -> None:
    assert "agent_question_required" not in ctx["answer"]


@then("the answer asks for the question, naming the argument")
def asked(ctx: dict[str, Any]) -> None:
    assert ctx["answer"]["agent_question_required"] is True
    assert "'question' argument" in ctx["answer"]["agent_question_hint"]
