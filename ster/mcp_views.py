"""The MCP ``open_view`` tool: show a query's result in ster's graph, map or timeline.

A client of ster's HTTP API, not a second implementation of it. The tool asks
``POST /api/sparql_query`` for the view, exactly as a page or a script would, so
the read-only guard, authentication and the rules for what each view can draw
all apply once, in the API. What the tool adds is only the decision the API
cannot make: open a browser, or hand back the link.

A browser is opened only for a caller on the same machine as ster. The API
process may be headless, or on a server the agent reaches over the network, and
a window opened there is one nobody asking can see; such a caller gets the link
to pass on. ``api.py`` decides which case applies from the request and gives
this module an opener only in the first.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from typing import Any, Final

from .view_links import GRAPH, MAP, TIMELINE, VIEWS

# (path, json body) -> (HTTP status, decoded JSON body)
ApiPost = Callable[[str, dict[str, Any]], tuple[int, dict[str, Any]]]

# The query travels in the page URL. Browsers and proxies start refusing URLs
# somewhere past 8 KB, and a link that fails to load is worse than a clear no.
MAX_QUERY_CHARS: Final = 8000

_NOUN: Final = {MAP: "place", TIMELINE: "moment", GRAPH: "triple"}

_LINK_HINT: Final = (
    "No browser was opened here: give this link to the user. It works for as "
    "long as the ster server stays up."
)


def open_in_browser(url: str) -> bool:
    """Open *url* in the system browser; False when there is none to open.

    The one place ster's MCP layer touches ``webbrowser``, so tests replace it
    and nothing else.
    """
    return bool(webbrowser.open(url))


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": code, "message": message}


def _refusal(view: str, query: str, api_post: ApiPost | None) -> dict[str, Any] | None:
    """Why the API should not even be asked, or None."""
    if view not in VIEWS:
        return _error("unknown_view", f"unknown view {view!r} — expected one of {', '.join(VIEWS)}")
    if len(query) > MAX_QUERY_CHARS:
        return _error(
            "query_too_long",
            f"the query is {len(query)} characters; a view link carries at most "
            f"{MAX_QUERY_CHARS} — shorten it (fewer VALUES, fewer OPTIONALs)",
        )
    if api_post is None:
        return _error("no_api", "open_view works only through ster's HTTP server (`ster serve`)")
    return None


def _ask_api(api_post: ApiPost, view: str, query: str) -> dict[str, Any]:
    status, body = api_post("/api/sparql_query", {"query": query, "view": view})
    if status != 200:
        return _error(
            "api_error", f"/api/sparql_query answered {status}: {body.get('detail', body)}"
        )
    return body


def open_view(
    args: dict[str, Any],
    api_post: ApiPost | None,
    open_browser: Callable[[str], bool] | None,
) -> dict[str, Any]:
    """Show *args*' query as *args*' view, and say what happened.

    *open_browser* is None when the caller is not on this machine. The result
    always carries the link when there is one, so an agent that could not have
    a window opened for it still has something to hand the user.
    """
    view = str(args.get("view") or "")
    query = str(args.get("query") or "")
    refused = _refusal(view, query, api_post)
    if refused is not None:
        return refused
    assert api_post is not None  # _refusal answered for None
    body = _ask_api(api_post, view, query)
    if "error" in body:
        return body

    url = body.get("view_url")
    if not url:
        return {
            "view": view,
            "url": None,
            "opened": False,
            "view_unavailable": body.get("view_unavailable"),
        }

    wanted = args.get("open", True) is not False
    opened = bool(wanted and open_browser is not None and open_browser(url))
    count = int(body.get("view_count") or 0)
    result: dict[str, Any] = {
        "view": view,
        "url": url,
        "opened": opened,
        "count": count,
        "summary": f"{count} {_NOUN[view]}{'' if count == 1 else 's'}",
    }
    if not opened:
        result["hint"] = _LINK_HINT
    return result
