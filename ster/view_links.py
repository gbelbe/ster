"""Links to ster's own views for a SPARQL result, and why one may not exist.

Shared by the TUI's query screen and by the MCP ``run_sparql`` tool, so the port,
the URL shape and the eligibility rules live in one place. A caller that builds
these itself works until the configured port changes.

Deliberately returns a **URL and a reason**, and never opens anything. The MCP
server runs inside ster's API process — which may be headless, on another
machine, or started days ago in a terminal nobody is watching — so opening a
browser there is a side effect in the wrong session, arriving through the one
tool that most advertises having none. The TUI opens browsers because it *is*
the foreground session; MCP is not, and cannot know what its caller can display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .model import Taxonomy
    from .sparql_query import QueryResult

MAP: Final = "map"
GRAPH: Final = "graph"
VIEWS: Final = (MAP, GRAPH)

# A SELECT returns columns; the graph view draws triples. Wrapping rows into
# triples would invent a graph the query never asked for, so the link is refused
# with a reason rather than handed over to render an empty canvas.
GRAPHABLE_QUERY_TYPES: Final = frozenset({"CONSTRUCT", "DESCRIBE"})


def _base() -> str:
    from .api_server import load_server_config  # noqa: PLC0415

    url, port = load_server_config()
    return f"{url}:{port}"


def map_url(sparql: str) -> str:
    """Address of the running server's map page, carrying *sparql* to run there.

    Same origin as the API, so the page's own re-runs post to ``/mcp`` without
    CORS; the token stays out of the URL and is embedded by the page, so it does
    not land in browser history.
    """
    from urllib.parse import quote  # noqa: PLC0415

    return f"{_base()}/map?q={quote(sparql)}"


def graph_url(sparql: str) -> str:
    """Address of the running server's graph page, drawing *sparql*'s triples."""
    from urllib.parse import quote  # noqa: PLC0415

    return f"{_base()}/viz?q={quote(sparql)}"


def is_graphable(result: QueryResult) -> bool:
    """True when *result* is triples the graph view can draw."""
    return bool(result.rows) and result.query_type in GRAPHABLE_QUERY_TYPES


def mappable_count(taxonomy: Taxonomy, result: QueryResult) -> int:
    """How many rows can be placed on a map.

    Counts a row that names an entity carrying geometry as well as one stating
    its own coordinates — detection lives in :mod:`ster.geo_results` and knows
    only WGS84, so it works for any ontology rather than one vocabulary.
    """
    from .geo_results import located_count  # noqa: PLC0415
    from .store import full_graph_rdflib  # noqa: PLC0415

    return located_count(full_graph_rdflib(taxonomy), result)


def link_for(
    taxonomy: Taxonomy, result: QueryResult, sparql: str, view: str
) -> tuple[str | None, str | None]:
    """``(url, unavailable_reason)`` for opening *result* as *view*.

    Exactly one is ever set. The reason is written for whoever asked — it names
    what is wrong *and* what would fix it, because "no" without a next step is
    the answer that gets retried verbatim.
    """
    if view not in VIEWS:
        return None, f"unknown view {view!r} — expected one of {', '.join(VIEWS)}"
    if not _server_running():
        return None, "ster's HTTP server is not running — start it with `ster serve <file>`"
    if view == GRAPH:
        if not is_graphable(result):
            return None, (
                f"{result.query_type} returns rows, not triples — "
                "use CONSTRUCT or DESCRIBE to draw a graph"
            )
        return graph_url(sparql), None
    if not mappable_count(taxonomy, result):
        return None, (
            "no row carries coordinates, and no entity named in one does either — "
            "return a place, or a lat/long pair, to map this"
        )
    return map_url(sparql), None


def _server_running() -> bool:
    from .api_server import is_running  # noqa: PLC0415

    return bool(is_running())


def annotate(
    payload: dict[str, Any], taxonomy: Taxonomy, result: QueryResult, sparql: str, view: str | None
) -> dict[str, Any]:
    """Add ``view_url``/``view_unavailable`` to *payload* when a view was asked for.

    The rows are returned either way: a view that cannot be built is not a query
    that failed, and an agent that asked for a nicety should not lose the answer
    it actually needed.
    """
    if not view:
        return payload
    url, reason = link_for(taxonomy, result, sparql, view)
    payload["view_url"] = url
    payload["view_unavailable"] = reason
    if url:
        payload["view_hint"] = (
            "Open this URL in a browser. With no browser available, report the URL "
            "as-is — it is reachable for as long as the ster server stays up."
        )
    return payload
