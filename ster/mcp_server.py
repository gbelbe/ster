"""MCP (Model Context Protocol) wire layer for ster — read-only.

Speaks JSON-RPC 2.0. This module is deliberately **transport-free and
framework-free**: it turns one decoded JSON-RPC message into one reply dict (or
None for a notification), and nothing else. ``ster/api.py`` owns the HTTP route
that feeds it, because the ``fastapi only via ster.api`` import contract keeps
FastAPI out of every other module.

Only the handful of methods a read-only tools server needs are implemented —
``initialize``, ``tools/list``, ``tools/call`` — so this is a small, swappable
adapter: replacing it with the official ``mcp`` SDK should touch this file and
the route in ``api.py``, nothing else.

The tools themselves live in :mod:`ster.mcp_context`; this file only maps names
to arguments and shapes the reply.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Final

from . import mcp_context as ctx
from .mcp_views import ApiPost, open_view
from .model import Taxonomy
from .query_trace import Event, get_recorder
from .query_trace.agent import agent_of
from .view_links import VIEWS

SERVER_NAME = "ster"

# Hosts allowed to originate a browser request to the MCP endpoint. The MCP spec
# requires servers to validate Origin to prevent DNS rebinding: without it, a
# page the user visits could script requests against their local ster server and
# read the ontology. A non-browser client (agent CLI, curl) sends no Origin at
# all, which stays allowed — the header is only a defence against browsers.
_ALLOWED_ORIGIN_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


def origin_allowed(origin: str | None) -> bool:
    """True when *origin* may talk to the MCP endpoint."""
    if not origin:
        return True  # no Origin: not a browser-initiated request
    if origin == "null":
        return False  # sandboxed iframe / file:// document
    from urllib.parse import urlparse  # noqa: PLC0415

    try:
        host = urlparse(origin).hostname
    except ValueError:
        return False
    return (host or "") in _ALLOWED_ORIGIN_HOSTS


# Protocol versions we answer to. Version negotiation (MCP lifecycle): echo the
# client's version when we support it, otherwise reply with ours and let the
# client decide whether to proceed. Echoing *any* string would be wrong — it
# would claim support for a dialect we have never implemented.
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


def negotiate_version(requested: Any) -> str:
    """The protocol version to report back for *requested*."""
    if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return DEFAULT_PROTOCOL_VERSION


# JSON-RPC 2.0 error codes (see the spec's reserved range).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

_STRING = {"type": "string"}
_ARG_QUERY: Final = "query"
_ARG_QUESTION: Final = "question"
_QUESTION_MAX: Final = 10000  # characters of a step question, from _meta or from the argument
_VIEW_ENUM: Final = {**_STRING, "enum": list(VIEWS)}
_ARG_LIMIT: Final = "limit"
_LIMIT_SCHEMA = {"type": "integer", "minimum": 1, "maximum": 200}

# The key every tool and every parameter carries. Named once so the ratchet
# counts one spelling, and so the schema shape stays greppable.
_DESC: Final = "description"

# Shared by every tool that can bound a timeline: keeps only the *moments* that
# fall on or after/before these, not the entities a query or a URI names — an
# entity dated both in 1977 and in 2026 is still named either way, but only one
# of its two moments belongs on a timeline asked for "after 2025". Any
# xsd:date/dateTime/gYear form works ("2025", "2025-06", "2025-06-01T10:00:00");
# looser precision on one side of the comparison is fine.
_ARG_AFTER: Final = "after"
_ARG_BEFORE: Final = "before"
_DATE_RANGE_ARGS: Final[dict[str, Any]] = {
    _ARG_AFTER: {
        **_STRING,
        _DESC: (
            "Keep only timeline moments on or after this date/dateTime/year "
            "(e.g. '2025' or '2025-01-01'). Filters moments, not which entities "
            "are considered — an entity dated both before and after this bound "
            "still appears, with only its later moment shown."
        ),
    },
    _ARG_BEFORE: {
        **_STRING,
        _DESC: "Keep only timeline moments on or before this date. Set both for a between filter.",
    },
}


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Build one MCP tool declaration without repeating JSON-Schema scaffolding."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "inputSchema": schema}


TOOLS: list[dict[str, Any]] = [
    _tool(
        "get_overview",
        (
            "Orientation for the whole ontology/taxonomy: its URI and title, the number of "
            "schemes, concepts, classes, individuals and properties, the concept schemes, "
            "and every language present on labels."
        ),
        {"lang": _STRING},
    ),
    _tool(
        "get_entity",
        (
            "Full detail for one entity by URI: kind (concept/class/individual/property/"
            "scheme), labels, descriptions, parent and child entities, and rdf:types. "
            "Works for both SKOS concepts (broader/narrower) and OWL classes (subClassOf)."
        ),
        {"uri": _STRING, "lang": _STRING},
        ["uri"],
    ),
    _tool(
        "search_entities",
        (
            "Find entities whose label or URI contains the query (case-insensitive), across "
            "concepts, classes, individuals, properties and schemes. Use this to resolve a "
            "name the user mentions into a URI before calling get_entity."
        ),
        {_ARG_QUERY: _STRING, _ARG_LIMIT: _LIMIT_SCHEMA, "lang": _STRING},
        [_ARG_QUERY],
    ),
    _tool(
        "get_vocabulary",
        (
            "The predicates, types, prefixes and language tags this file actually uses. "
            "Call this before writing any SPARQL: it tells you whether labels are on "
            "skos:prefLabel or rdfs:label, whether the hierarchy is skos:broader or "
            "rdfs:subClassOf, and which language tags exist — the three things that "
            "otherwise get guessed wrong and return zero rows."
        ),
    ),
    _tool(
        "get_timeline",
        (
            "Everything the file dates, as instants and intervals ready to plot, plus the "
            "URL of ster's timeline page. Pass a URI to narrow it to the dated entities "
            "that point to it, or 'after'/'before' to keep only moments in a date range."
        ),
        {"uri": _STRING, _ARG_LIMIT: _LIMIT_SCHEMA, **_DATE_RANGE_ARGS},
    ),
    _tool(
        "run_sparql",
        (
            "Run a read-only SPARQL query (SELECT or ASK) against the open file and get "
            "columns plus rows. Update forms (INSERT/DELETE/DROP/CLEAR/LOAD) are refused. "
            "Use this for questions the other tools cannot answer directly, such as counting "
            "or filtering by an arbitrary predicate.\n"
            "Call get_vocabulary first and build the query from the predicates it reports — "
            "do not assume a vocabulary. At most 'limit' rows come back (default 200); "
            "'row_count' is always the full count and 'truncated' "
            "says when rows were cut — then aggregate (COUNT, GROUP BY), filter or add a "
            "LIMIT rather than listing. A query is stopped after 10 seconds and returns a "
            "'timeout' error: avoid unbounded joins and paths. If a "
            "query returns zero rows, re-check the vocabulary "
            "rather than guessing again; drop one triple pattern at a time to find the "
            "empty one. Avoid naming a variable after a write keyword (?add, ?copy, ?create, "
            "?move): the read-only guard matches those words and will refuse the query."
        ),
        {
            _ARG_QUERY: _STRING,
            _ARG_QUESTION: {
                "type": "string",
                "maxLength": _QUESTION_MAX,
                _DESC: (
                    "In one plain sentence, what this query looks for (for example 'Count the "
                    "open epics of the CCDP'), in the language of the user's question. It is "
                    "recorded in the query trace and shown as the step's title. Give it on "
                    "every call: most clients cannot set the _meta field that carries it "
                    "otherwise."
                ),
            },
            "view": {
                **_VIEW_ENUM,
                _DESC: (
                    "Show these results in ster's map, graph or timeline view. 'map' needs "
                    "rows carrying coordinates, or naming an entity that does; 'timeline' "
                    "needs rows naming dated entities; 'graph' needs a CONSTRUCT or "
                    "DESCRIBE, since it draws triples. When the view cannot be built the "
                    "rows still come back and 'view_unavailable' says why. On a caller "
                    "running on the same machine as ster, the page opens on its own — "
                    "'opened' says whether it did. Only when it did not (a remote caller, "
                    "or nothing on a screen anyone is watching) do you need to hand "
                    "'view_url' to the user as a link, rather than opening or "
                    "screenshotting it yourself."
                ),
            },
            "open": {
                "type": "boolean",
                _DESC: "false to get the link without opening a browser (default true).",
            },
            _ARG_LIMIT: {
                "type": "integer",
                "minimum": 1,
                "maximum": ctx.SPARQL_ROW_LIMIT_MAX,
                _DESC: (
                    f"Most rows to return (default {ctx.SPARQL_ROW_LIMIT}, at most "
                    f"{ctx.SPARQL_ROW_LIMIT_MAX}). Does not change row_count."
                ),
            },
            **_DATE_RANGE_ARGS,
        },
        [_ARG_QUERY],
    ),
    _tool(
        "open_view",
        (
            "Show a SPARQL query's result to the user in one of ster's views: 'map' "
            "(places), 'timeline' (dated things) or 'graph' (the triples of a CONSTRUCT "
            "or DESCRIBE). Opens the page in the user's browser when you run on the same "
            "machine as ster; otherwise returns the link for you to give them. Checks "
            "the result first and opens nothing when the view would be empty, saying "
            "why in 'view_unavailable'. Returns the url, whether it was opened, and how "
            "much the view shows. Build the query as for run_sparql. For 'timeline', "
            "'after'/'before' keep only moments in a date range — pass these instead of "
            "trying to bound dates in the SPARQL WHERE clause: the view resolves every "
            "moment of each entity the query names, so a FILTER on the query's own date "
            "variable narrows which entities are picked but not which of their moments "
            "are drawn, and a document dated both decades ago and this week would still "
            "show its old date."
        ),
        {
            "view": _VIEW_ENUM,
            _ARG_QUERY: _STRING,
            "open": {
                "type": "boolean",
                _DESC: "false to get the link without opening a browser (default true).",
            },
            **_DATE_RANGE_ARGS,
        },
        ["view", _ARG_QUERY],
    ),
    _tool(
        "get_query_trace",
        (
            "Inspect a recorded query trace by run ID. Returns the natural-language question, "
            "status, event count, and logical steps. Query tracing must be enabled."
        ),
        {"run_id": _STRING},
        ["run_id"],
    ),
    _tool(
        "export_query_trace",
        (
            "Export a recorded query trace as PROV-O TriG text. Use the returned graph to "
            "visualise the query process or connect it to the domain graph."
        ),
        {"run_id": _STRING},
        ["run_id"],
    ),
]


UNTRACED_META: Final = (
    "com.adeo/untraced"  # _meta key of a call that is only a health check: it leaves no trace
)
_SESSION_ID_MAX: Final = 256  # characters of the agent session id a call may carry


@dataclass(frozen=True)
class CallContext:  # pylint: disable=too-many-instance-attributes  # what one MCP call knows about its caller
    """What one MCP call knows beyond its arguments.

    *base_url* is the server address the request arrived on — the only address
    a link handed back to the caller is sure to reach, since ``ster serve --port``
    never reaches the saved config. None when the call did not come over HTTP
    (tests, TUI).
    """

    base_url: str | None = None
    # ster's own HTTP API, for tools that must go through it (open_view), and
    # a browser opener — set only when the caller is on this machine.
    api_post: ApiPost | None = None
    open_browser: Callable[[str], bool] | None = None
    agent_session_id: str | None = None
    agent_question: str | None = None
    agent_session_question: str | None = None
    token_usage: dict[str, int] | None = None
    # the HTTP User-Agent the call came with (set by the transport) and what that and its _meta say about the agent
    user_agent: str | None = None
    agent: dict[str, str] | None = None
    # a call that is only a health check: it answers like any other and leaves no trace
    untraced: bool = False


def _tool_get_overview(tax: Taxonomy, _call: CallContext, args: dict) -> Any:
    return ctx.overview(tax, args.get("lang", "en"))


def _tool_get_entity(tax: Taxonomy, _call: CallContext, args: dict) -> Any:
    return ctx.entity(tax, args["uri"], args.get("lang", "en"))


def _tool_search_entities(tax: Taxonomy, _call: CallContext, args: dict) -> Any:
    return ctx.search(tax, args[_ARG_QUERY], int(args.get(_ARG_LIMIT, 20)), args.get("lang", "en"))


def _tool_get_vocabulary(tax: Taxonomy, _call: CallContext, _args: dict) -> Any:
    return ctx.vocabulary(tax)


def _tool_get_timeline(tax: Taxonomy, _call: CallContext, args: dict) -> Any:
    return ctx.timeline(
        tax,
        args.get("uri", ""),
        int(args.get(_ARG_LIMIT, 200)),
        args.get(_ARG_AFTER),
        args.get(_ARG_BEFORE),
    )


def _question_argument(args: dict) -> str | None:
    """The step question a caller passed as an argument: text, at most _QUESTION_MAX characters, else None."""
    value = args.get(_ARG_QUESTION)
    if not isinstance(value, str) or not value.strip() or len(value) > _QUESTION_MAX:
        return None
    return value.strip()


def _tool_run_sparql(tax: Taxonomy, call: CallContext, args: dict) -> Any:
    # _meta, when the client could send it, wins; the argument is for the clients that cannot set _meta.
    call = replace(call, agent_question=call.agent_question or _question_argument(args))
    payload = ctx.run_sparql(
        tax,
        args[_ARG_QUERY],
        view=args.get("view"),
        base=call.base_url,
        after=args.get(_ARG_AFTER),
        before=args.get(_ARG_BEFORE),
        limit=int(args.get(_ARG_LIMIT, ctx.SPARQL_ROW_LIMIT)),
        agent_session_id=call.agent_session_id,
        agent_question=call.agent_question,
        token_usage=call.token_usage,
        agent_session_question=call.agent_session_question,
        agent=call.agent,
    )
    _add_question_metadata_notice(payload, call)
    # Opening is an MCP-transport concern (whether *this caller* is on ster's own
    # machine), so it lives here rather than in the shared sparql_payload/annotate
    # path the REST endpoint also runs — see test_the_shared_function_is_where_view_is_handled.
    url = payload.get("view_url")
    if url:
        wanted = args.get("open", True) is not False
        opened = bool(wanted and call.open_browser is not None and call.open_browser(url))
        payload["opened"] = opened
        if opened:
            payload.pop("view_hint", None)
    return payload


def _tool_open_view(_tax: Taxonomy, call: CallContext, args: dict) -> Any:
    # No taxonomy: the tool goes through the HTTP API, never the model.
    return open_view(args, call.api_post, call.open_browser)


def _tool_get_query_trace(_tax: Taxonomy, _call: CallContext, args: dict) -> Any:
    return ctx.query_trace(args["run_id"])


def _tool_export_query_trace(_tax: Taxonomy, _call: CallContext, args: dict) -> Any:
    return ctx.query_trace(args["run_id"], export=True)


# name → implementation. A registry, so adding a tool is one row plus one entry
# in TOOLS rather than another branch.
_IMPLS: dict[str, Callable[[Taxonomy, CallContext, dict], Any]] = {
    "get_overview": _tool_get_overview,
    "get_entity": _tool_get_entity,
    "search_entities": _tool_search_entities,
    "get_vocabulary": _tool_get_vocabulary,
    "get_timeline": _tool_get_timeline,
    "run_sparql": _tool_run_sparql,
    "open_view": _tool_open_view,
    "get_query_trace": _tool_get_query_trace,
    "export_query_trace": _tool_export_query_trace,
}

# Required arguments per tool, read from the schemas above so the two cannot
# disagree — a hand-kept copy had to name every tool a second time. Checked for
# a clear error before the impl indexes a dict.
_REQUIRED: dict[str, list[str]] = {
    tool["name"]: list(tool["inputSchema"].get("required", [])) for tool in TOOLS
}


def _ok(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _text_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    """Wrap a payload as an MCP tool result (JSON rendered into a text block)."""
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}],
        "isError": is_error,
    }


# Sent to every client at session start. The MCP spec treats this as a hint for
# the model, which makes it the one place a querying discipline reaches *any*
# agent — not just the ones that support a vendor-specific prompt or skill file.
INSTRUCTIONS = """\
ster serves one RDF file: a SKOS taxonomy, an OWL ontology, or both.

Before writing SPARQL, call get_vocabulary. It reports the predicates, types,
prefixes and language tags this file actually uses. Ontologies differ in
vocabulary, so a query built on assumptions parses cleanly and returns nothing —
labels may be skos:prefLabel or rdfs:label, the hierarchy skos:broader or
rdfs:subClassOf, the labels tagged @fr and not @en.

A reliable order:
  1. get_overview      — how big this file is and what it holds
  2. get_vocabulary    — the predicates and prefixes to build the query from
  3. search_entities   — resolve each name to a real URI; never invent one
  4. run_sparql        — compose using only predicates you have now seen

For every MCP tool call, include both levels of natural-language context in MCP
request metadata:
  "_meta": {
    "com.adeo/agent-session-id": "stable-id-for-the-user-question",
    "com.adeo/agent-session-question": "the original user question",
    "com.adeo/agent-question": "the concise natural-language subquestion for this step"
  }
A client that cannot set _meta can pass the step question as run_sparql's "question"
argument instead.
Reuse the same agent-session-id and agent-session-question for every MCP call
made while answering one user question. Each call's agent-question should
describe only that call's subquestion; do not use one step's question as the
session question. If either question is not supplied, ster asks for it in the
tool response and the trace marks that context as missing.

If available, include token usage for the current agent step:
  "com.adeo/token-usage": {"input": 120, "output": 34, "total": 154}
Token counts are optional and are recorded for observability only.

Zero rows means an assumption was wrong, not that the answer is empty. Re-read
the vocabulary and drop one triple pattern at a time to find the one that
matches nothing.

This server never edits the file: SELECT and ASK only, and update forms are
refused. The one thing it does besides answering is showing a view — `view` on
run_sparql, or open_view — as a map, timeline or graph.

For a graph request, first resolve the named entity and construct a focused
semantic neighborhood rather than dumping every triple. Include the focus,
its types, class hierarchy, declared object-property links, the connected
entities' types, and readable labels. Include the domain and range definitions
of relationships used when the file is OWL. For SKOS, use its discovered
broader/narrower and related predicates instead. Keep the neighborhood bounded
(a few hierarchy levels and one relationship hop by default), and cap large
instance sets. Exclude provenance, source/build metadata, images, logos, URLs,
identifiers, coordinates, geometry, and other literal data unless the user
explicitly asks for them. Build graph queries with an explicit CONSTRUCT
allowlist; never use an unrestricted `?subject ?predicate ?object` pattern.

A view opens itself when it can: on a caller running on the same machine as
ster, `run_sparql`'s `view` and `open_view` open a browser tab on their own and
report `opened: true`. Nothing further is needed there — do not also open or
screenshot the page yourself. When `opened` comes back false (a remote caller,
or nothing on a screen anyone is watching), hand the user `view_url` as a link
instead; opening would do nothing there.

Driving a browser to navigate and screenshot the page is the expensive path —
real image tokens, several round trips — and earns its cost only when the page
itself must be seen: verifying a render, debugging a layout, describing what's
on screen. Not for delivering a view that already opened itself, or a link
handed back in its place.
"""


def _handle_initialize(params: dict, _tax: Taxonomy, _call: CallContext) -> dict[str, Any]:
    from ._version import __version__

    return {
        "protocolVersion": negotiate_version(params.get("protocolVersion")),
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": __version__},
        "instructions": INSTRUCTIONS,
    }


def _handle_tools_list(_params: dict, _tax: Taxonomy, _call: CallContext) -> dict[str, Any]:
    return {"tools": TOOLS}


def _handle_tools_call(params: dict, tax: Taxonomy, call: CallContext) -> dict[str, Any]:
    # Normalise to str: a missing or null name becomes "", which matches no tool
    # and falls through to the unknown_tool result below.
    name = str(params.get("name") or "")
    impl = _IMPLS.get(name)
    if impl is None:
        return _text_result({"error": "unknown_tool", "tool": name}, is_error=True)
    args = params.get("arguments") or {}
    missing = next((arg for arg in _REQUIRED.get(name, []) if not args.get(arg)), None)
    if missing:
        return _text_result({"error": "missing_argument", "argument": missing}, is_error=True)
    try:
        if name == "run_sparql":
            return _text_result(impl(tax, call, args))
        if call.untraced:
            return _text_result(impl(tax, call, args))
        return _text_result(_traced_tool_call(name, impl, tax, call, args))
    # A fault inside one tool is reported as an error result; it must not take
    # down the whole JSON-RPC session.
    except Exception as exc:  # noqa: BLE001
        return _text_result({"error": "tool_failed", "message": str(exc)}, is_error=True)


def _traced_tool_call(
    name: str,
    impl: Callable[[Taxonomy, CallContext, dict], Any],
    tax: Taxonomy,
    call: CallContext,
    args: dict,
) -> Any:
    """Record non-SPARQL MCP tools as complete logical query sessions."""
    recorder = get_recorder()
    trace = recorder.start_run(
        json.dumps({"tool": name, "arguments": args}, ensure_ascii=False),
        transport="mcp",
        tool=name,
        agent_session_id=call.agent_session_id,
        agent_question=call.agent_question,
        agent_session_question=call.agent_session_question,
        token_usage=call.token_usage,
        agent=call.agent,
    )
    step_id = name
    recorder.record(
        Event(
            "step_planned",
            trace.run_id,
            trace.trace_id,
            2,
            step_id=step_id,
            payload={"objective": f"Execute MCP tool {name}."},
        )
    )
    recorder.record(Event("step_started", trace.run_id, trace.trace_id, 3, step_id=step_id))
    try:
        result = impl(tax, call, args)
    except Exception as exc:
        recorder.record(
            Event(
                "step_failed",
                trace.run_id,
                trace.trace_id,
                4,
                step_id=step_id,
                payload={"status": "failed", "error": str(exc)},
            )
        )
        recorder.finish(trace, status="failed", error=str(exc))
        raise
    payload = _tool_result_payload(result)
    recorder.record(
        Event(
            "step_completed",
            trace.run_id,
            trace.trace_id,
            4,
            step_id=step_id,
            payload={"status": "completed", "token_usage": call.token_usage, **payload},
        )
    )
    recorder.finish(trace, status="completed", row_count=payload.get("row_count"))
    if isinstance(result, dict):
        _add_question_metadata_notice(result, call)
    return result


def _add_question_metadata_notice(payload: dict[str, Any], call: CallContext) -> None:
    """Tell an MCP caller which independent question metadata is missing."""
    if call.agent_question:
        payload["agent_question"] = call.agent_question
    else:
        payload["agent_question_required"] = True
        payload["agent_question_hint"] = (
            "Before the next MCP call, provide this step's concise natural-language "
            "subquestion in _meta.com.adeo/agent-question (run_sparql also takes it as its "
            "'question' argument, for clients that cannot set _meta)."
        )
    if call.agent_session_question:
        payload["agent_session_question"] = call.agent_session_question
    else:
        payload["agent_session_question_required"] = True
        payload["agent_session_question_hint"] = (
            "Before the next MCP call, provide the global user goal "
            "in _meta.com.adeo/agent-session-question."
        )
    missing = [
        label
        for label, value in (
            ("step question", call.agent_question),
            ("global user goal", call.agent_session_question),
        )
        if not value
    ]
    if missing:
        payload["warning"] = (
            "The query was executed, but the trace is missing "
            + " and ".join(missing)
            + "; provide both question fields to make the trace readable."
        )


def _tool_result_payload(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"result": result}
    payload: dict[str, Any] = {}
    if "columns" in result:
        payload["columns"] = result["columns"]
    if "rows" in result:
        payload["result_rows"] = result["rows"]
        payload["row_count"] = result.get("row_count", len(result["rows"]))
    elif isinstance(result.get("items"), list):
        payload["result_rows"] = result["items"]
        payload["row_count"] = len(result["items"])
    else:
        payload["result"] = result
    return payload


_METHODS: dict[str, Callable[[dict, Taxonomy, CallContext], dict[str, Any]]] = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


def handle_message(
    message: Any,
    taxonomy: Taxonomy,
    *,
    call: CallContext | None = None,
) -> dict[str, Any] | None:
    """Turn one decoded JSON-RPC *message* into its reply.

    *call* carries what the transport knows about this call — the address it
    arrived on, and what ``open_view`` needs (see CallContext). Without it (tests,
    the TUI) the call knows nothing beyond its arguments.

    Returns None for notifications (no ``id``), which take no reply — the caller
    should answer with an empty HTTP 202.
    """
    if not isinstance(message, dict):
        return _err(None, INVALID_REQUEST, "Request must be a JSON object.")

    method = message.get("method")
    msg_id = message.get("id")
    if not isinstance(method, str):
        return _err(msg_id, INVALID_REQUEST, "Missing method.")
    if msg_id is None:  # a notification, e.g. notifications/initialized
        return None

    handler = _METHODS.get(method)
    if handler is None:
        return _err(msg_id, METHOD_NOT_FOUND, f"Unknown method: {method}")
    # `or {}` would be wrong here: a falsy non-object (``[]``, ``""``) would be
    # coerced to a dict and skip the type check below.
    params = message.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _err(msg_id, INVALID_PARAMS, "params must be an object.")
    metadata = params.get("_meta") or {}
    agent_session_id = _meta_text(metadata, "com.adeo/agent-session-id", _SESSION_ID_MAX)
    agent_question = _meta_text(metadata, "com.adeo/agent-question", _QUESTION_MAX)
    agent_session_question = _meta_text(metadata, "com.adeo/agent-session-question", _QUESTION_MAX)
    token_usage = _normalise_token_usage(metadata.get("com.adeo/token-usage"))
    call = replace(
        call or CallContext(),
        agent_session_id=agent_session_id,
        agent_question=agent_question,
        agent_session_question=agent_session_question,
        token_usage=token_usage,
        agent=agent_of(call.user_agent if call else None, metadata),
        untraced=metadata.get(UNTRACED_META) is True,
    )
    return _ok(msg_id, handler(params, taxonomy, call))


def _meta_text(metadata: dict, key: str, limit: int) -> str | None:
    """The text a caller put under *key* in its request metadata, or None when it is missing, not text or too long."""
    value = metadata.get(key)
    return value if isinstance(value, str) and len(value) <= limit else None


def _normalise_token_usage(value: Any) -> dict[str, Any] | None:
    """Accept common token field aliases and preserve estimate metadata."""
    if not isinstance(value, dict):
        return None
    aliases = {"input_tokens": "input", "output_tokens": "output", "total_tokens": "total"}
    usage: dict[str, Any] = {}
    for canonical, alias in aliases.items():
        candidate = value.get(canonical, value.get(alias))
        if candidate is not None:
            if not isinstance(candidate, int) or candidate < 0:
                return None
            usage[canonical] = candidate
    if not usage:
        return None
    for key in ("source", "estimated", "model", "estimator"):
        if key in value:
            usage[key] = value[key]
    usage["estimated"] = bool(usage.get("estimated", usage.get("source") == "estimated"))
    usage.setdefault("source", "estimated" if usage["estimated"] else "provider")
    return usage
