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
from typing import Any

from . import mcp_context as ctx
from .model import Taxonomy

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

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_current_context",
        "description": (
            "What the user is looking at right now in ster: the focused entity with its "
            "labels, descriptions, parents and children, plus its ancestor chain, its "
            "siblings, and an overview of the whole file. When nothing is focused (no TUI "
            "attached), returns the file overview alone. Call this first to orient yourself."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"lang": _STRING},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_overview",
        "description": (
            "Orientation for the whole ontology/taxonomy: its URI and title, the number of "
            "schemes, concepts, classes, individuals and properties, the concept schemes, "
            "and every language present on labels."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"lang": _STRING},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_entity",
        "description": (
            "Full detail for one entity by URI: kind (concept/class/individual/property/"
            "scheme), labels, descriptions, parent and child entities, and rdf:types. "
            "Works for both SKOS concepts (broader/narrower) and OWL classes (subClassOf)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"uri": _STRING, "lang": _STRING},
            "required": ["uri"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_entities",
        "description": (
            "Find entities whose label or URI contains the query (case-insensitive), across "
            "concepts, classes, individuals, properties and schemes. Use this to resolve a "
            "name the user mentions into a URI before calling get_entity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _STRING,
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "lang": _STRING,
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_sparql",
        "description": (
            "Run a read-only SPARQL query (SELECT or ASK) against the open file and get "
            "columns plus rows. Update forms (INSERT/DELETE/DROP/CLEAR/LOAD) are refused. "
            "Use this for questions the other tools cannot answer directly, such as counting "
            "or filtering by an arbitrary predicate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": _STRING},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


def _tool_get_current_context(tax: Taxonomy, selection: str | None, args: dict) -> Any:
    return ctx.current_context(tax, selection, args.get("lang", "en"))


def _tool_get_overview(tax: Taxonomy, _selection: str | None, args: dict) -> Any:
    return ctx.overview(tax, args.get("lang", "en"))


def _tool_get_entity(tax: Taxonomy, _selection: str | None, args: dict) -> Any:
    return ctx.entity(tax, args["uri"], args.get("lang", "en"))


def _tool_search_entities(tax: Taxonomy, _selection: str | None, args: dict) -> Any:
    return ctx.search(tax, args["query"], int(args.get("limit", 20)), args.get("lang", "en"))


def _tool_run_sparql(tax: Taxonomy, _selection: str | None, args: dict) -> Any:
    return ctx.run_sparql(tax, args["query"])


# name → implementation. A registry, so adding a tool is one row plus one entry
# in TOOLS rather than another branch.
_IMPLS: dict[str, Callable[[Taxonomy, str | None, dict], Any]] = {
    "get_current_context": _tool_get_current_context,
    "get_overview": _tool_get_overview,
    "get_entity": _tool_get_entity,
    "search_entities": _tool_search_entities,
    "run_sparql": _tool_run_sparql,
}

# Required argument per tool, for a clear error before the impl indexes a dict.
_REQUIRED = {"get_entity": "uri", "search_entities": "query", "run_sparql": "query"}


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


def _handle_initialize(params: dict, _tax: Taxonomy, _sel: str | None) -> dict[str, Any]:
    from ._version import __version__

    return {
        "protocolVersion": negotiate_version(params.get("protocolVersion")),
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": __version__},
    }


def _handle_tools_list(_params: dict, _tax: Taxonomy, _sel: str | None) -> dict[str, Any]:
    return {"tools": TOOLS}


def _handle_tools_call(params: dict, tax: Taxonomy, selection: str | None) -> dict[str, Any]:
    # Normalise to str: a missing or null name becomes "", which matches no tool
    # and falls through to the unknown_tool result below.
    name = str(params.get("name") or "")
    impl = _IMPLS.get(name)
    if impl is None:
        return _text_result({"error": "unknown_tool", "tool": name}, is_error=True)
    args = params.get("arguments") or {}
    required = _REQUIRED.get(name)
    if required and not args.get(required):
        return _text_result({"error": "missing_argument", "argument": required}, is_error=True)
    try:
        return _text_result(impl(tax, selection, args))
    except Exception as exc:  # noqa: BLE001 — a tool fault must not kill the session
        return _text_result({"error": "tool_failed", "message": str(exc)}, is_error=True)


_METHODS: dict[str, Callable[[dict, Taxonomy, str | None], dict[str, Any]]] = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


def handle_message(
    message: Any,
    taxonomy: Taxonomy,
    selection: str | None = None,
) -> dict[str, Any] | None:
    """Turn one decoded JSON-RPC *message* into its reply.

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
    return _ok(msg_id, handler(params, taxonomy, selection))
