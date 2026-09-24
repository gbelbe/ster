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
from dataclasses import dataclass
from typing import Any, Final

from . import mcp_context as ctx
from .mcp_views import ApiPost, open_view
from .model import Taxonomy
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
INTERNAL_ERROR = -32603

_STRING = {"type": "string"}
_ARG_QUERY: Final = "query"
_VIEW_ENUM: Final = {**_STRING, "enum": list(VIEWS)}
_ARG_LIMIT: Final = "limit"
_LIMIT_SCHEMA = {"type": "integer", "minimum": 1, "maximum": 200}


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


# The key every tool and every parameter carries. Named once so the ratchet
# counts one spelling, and so the schema shape stays greppable.
_DESC: Final = "description"

TOOLS: list[dict[str, Any]] = [
    _tool(
        "get_current_context",
        (
            "What the user is looking at right now in ster: the focused entity with its "
            "labels, descriptions, parents and children, plus its ancestor chain, its "
            "siblings, and an overview of the whole file. When nothing is focused (no TUI "
            "attached), returns the file overview alone. Call this first to orient yourself."
        ),
        {"lang": _STRING},
    ),
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
            "that point to it."
        ),
        {"uri": _STRING, _ARG_LIMIT: _LIMIT_SCHEMA},
    ),
    _tool(
        "run_sparql",
        (
            "Run a read-only SPARQL query (SELECT or ASK) against the open file and get "
            "columns plus rows. Update forms (INSERT/DELETE/DROP/CLEAR/LOAD) are refused. "
            "Use this for questions the other tools cannot answer directly, such as counting "
            "or filtering by an arbitrary predicate.\n"
            "Call get_vocabulary first and build the query from the predicates it reports — "
            "do not assume a vocabulary. Always include a LIMIT: results are not capped and "
            "there is no timeout. If a query returns zero rows, re-check the vocabulary "
            "rather than guessing again; drop one triple pattern at a time to find the "
            "empty one. Avoid naming a variable after a write keyword (?add, ?copy, ?create, "
            "?move): the read-only guard matches those words and will refuse the query."
        ),
        {
            _ARG_QUERY: _STRING,
            "view": {
                **_VIEW_ENUM,
                _DESC: (
                    "Also return a URL opening these results in ster's map, graph or "
                    "timeline view. 'map' needs rows carrying coordinates, or naming an "
                    "entity that does; 'timeline' needs rows naming dated entities; "
                    "'graph' needs a CONSTRUCT or DESCRIBE, since it draws triples. When "
                    "the view cannot be built the rows still come back and "
                    "'view_unavailable' says why. This one call already carries both the "
                    "answer and the link — give the URL to the user as a link rather than "
                    "opening or screenshotting it yourself, which costs far more than the "
                    "question was worth. Reach for open_view instead only when the user "
                    "needs the page opened for them, not just linked."
                ),
            },
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
            "much the view shows. Build the query as for run_sparql."
        ),
        {
            "view": _VIEW_ENUM,
            _ARG_QUERY: _STRING,
            "open": {
                "type": "boolean",
                _DESC: "false to get the link without opening a browser (default true).",
            },
        },
        ["view", _ARG_QUERY],
    ),
]


@dataclass(frozen=True)
class CallContext:
    """What one MCP call knows beyond its arguments.

    *selection* is the entity focused in an attached TUI. *base_url* is the
    server address the request arrived on — the only address a link handed back
    to the caller is sure to reach, since ``ster serve --port`` never reaches
    the saved config. None when the call did not come over HTTP (tests, TUI).
    """

    selection: str | None = None
    base_url: str | None = None
    # ster's own HTTP API, for tools that must go through it (open_view), and
    # a browser opener — set only when the caller is on this machine.
    api_post: ApiPost | None = None
    open_browser: Callable[[str], bool] | None = None


def _tool_get_current_context(tax: Taxonomy, call: CallContext, args: dict) -> Any:
    return ctx.current_context(tax, call.selection, args.get("lang", "en"))


def _tool_get_overview(tax: Taxonomy, _call: CallContext, args: dict) -> Any:
    return ctx.overview(tax, args.get("lang", "en"))


def _tool_get_entity(tax: Taxonomy, _call: CallContext, args: dict) -> Any:
    return ctx.entity(tax, args["uri"], args.get("lang", "en"))


def _tool_search_entities(tax: Taxonomy, _call: CallContext, args: dict) -> Any:
    return ctx.search(tax, args[_ARG_QUERY], int(args.get(_ARG_LIMIT, 20)), args.get("lang", "en"))


def _tool_get_vocabulary(tax: Taxonomy, _call: CallContext, _args: dict) -> Any:
    return ctx.vocabulary(tax)


def _tool_get_timeline(tax: Taxonomy, _call: CallContext, args: dict) -> Any:
    return ctx.timeline(tax, args.get("uri", ""), int(args.get(_ARG_LIMIT, 200)))


def _tool_run_sparql(tax: Taxonomy, call: CallContext, args: dict) -> Any:
    return ctx.run_sparql(tax, args[_ARG_QUERY], args.get("view"), call.base_url)


def _tool_open_view(_tax: Taxonomy, call: CallContext, args: dict) -> Any:
    # No taxonomy: the tool goes through the HTTP API, never the model.
    return open_view(args, call.api_post, call.open_browser)


# name → implementation. A registry, so adding a tool is one row plus one entry
# in TOOLS rather than another branch.
_IMPLS: dict[str, Callable[[Taxonomy, CallContext, dict], Any]] = {
    "get_current_context": _tool_get_current_context,
    "get_overview": _tool_get_overview,
    "get_entity": _tool_get_entity,
    "search_entities": _tool_search_entities,
    "get_vocabulary": _tool_get_vocabulary,
    "get_timeline": _tool_get_timeline,
    "run_sparql": _tool_run_sparql,
    "open_view": _tool_open_view,
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

Zero rows means an assumption was wrong, not that the answer is empty. Re-read
the vocabulary and drop one triple pattern at a time to find the one that
matches nothing.

This server never edits the file: SELECT and ASK only, and update forms are
refused. The one thing it does besides answering is open_view, which can open a
browser tab on the user's machine to show a result as a map, timeline or graph.

Getting a view in front of the user costs three different amounts, in this
order of preference:
  1. On the same machine as ster and a display: open it — open_view (it
     already checks this and opens nothing if it can't), or webbrowser.open()
     on the URL run_sparql's `view` returned. webbrowser.open() dispatches to
     the right command for the platform on its own (open / start / xdg-open) —
     call it directly rather than hard-coding one platform's command.
  2. Not on that machine, or nothing would be on a screen anyone is looking
     at: hand back the link as text. Opening would do nothing there.
  3. Driving a browser to navigate and screenshot the page is the expensive
     path — real image tokens, several round trips — and earns its cost only
     when the page itself must be seen: verifying a render, debugging a
     layout, describing what's on screen. Not for delivering a link that
     open_view or a plain webbrowser.open() already produced.
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
        return _text_result(impl(tax, call, args))
    # A fault inside one tool is reported as an error result; it must not take
    # down the whole JSON-RPC session.
    except Exception as exc:  # noqa: BLE001
        return _text_result({"error": "tool_failed", "message": str(exc)}, is_error=True)


_METHODS: dict[str, Callable[[dict, Taxonomy, CallContext], dict[str, Any]]] = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


def handle_message(
    message: Any,
    taxonomy: Taxonomy,
    selection: str | None = None,
    *,
    base_url: str | None = None,
    api_post: ApiPost | None = None,
    open_browser: Callable[[str], bool] | None = None,
) -> dict[str, Any] | None:
    """Turn one decoded JSON-RPC *message* into its reply.

    *base_url* is the address the request arrived on, for links in the reply;
    *api_post* and *open_browser* are what ``open_view`` needs (see CallContext).

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
    call = CallContext(selection, base_url, api_post, open_browser)
    return _ok(msg_id, handler(params, taxonomy, call))
