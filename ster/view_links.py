"""Links to ster's own views for a SPARQL result, and why one may not exist.

Shared by the TUI's query screen and by the MCP ``run_sparql`` tool, so the port,
the URL shape and the eligibility rules live in one place. A caller that builds
these itself works until the configured port changes.

Deliberately returns a **URL and a reason**, and never opens anything. The API
process may be headless, on another machine, or started days ago in a terminal
nobody is watching, so whether a window can be opened is for the caller to
decide: the TUI opens one because it *is* the foreground session, and the MCP
``open_view`` tool does only for an agent on the same machine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .model import Taxonomy
    from .sparql_query import QueryResult

MAP: Final = "map"
GRAPH: Final = "graph"
TIMELINE: Final = "timeline"


@dataclass(frozen=True)
class DateRange:
    """An optional [*after*, *before*] bound, timeline-only today.

    A plain pair of strings would do the same job; named so ``assess``'s
    signature reads as intent and a future view (a Gantt export, a "recent
    changes" filter) has somewhere to receive the same two bounds without
    inventing its own spelling of them.
    """

    after: str | None = None
    before: str | None = None


_NO_RANGE: Final = DateRange()

# A SELECT returns columns; the graph view draws triples. Wrapping rows into
# triples would invent a graph the query never asked for, so the link is refused
# with a reason rather than handed over to render an empty canvas.
GRAPHABLE_QUERY_TYPES: Final = frozenset({"CONSTRUCT", "DESCRIBE"})


def _base(base: str | None = None) -> str:
    """*base* when a request named the server's address, else the saved config.

    A request that arrived over HTTP knows the address its caller used — which
    is right under ``ster serve --port`` too, where the saved config is not.
    """
    if base:
        return base.rstrip("/")
    from .api_server import load_server_config  # noqa: PLC0415

    url, port = load_server_config()
    return f"{url}:{port}"


def map_url(sparql: str, focus: str | None = None, base: str | None = None) -> str:
    """Address of the running server's map page, carrying *sparql* to run there.

    Same origin as the API, so the page's own re-runs post to ``/mcp`` without
    CORS; the token stays out of the URL and is embedded by the page, so it does
    not land in browser history.
    """
    from urllib.parse import quote  # noqa: PLC0415

    page = f"{_base(base)}/map?q={quote(sparql)}"
    return page + (f"&focus={quote(focus)}" if focus else "")


def graph_url(sparql: str, base: str | None = None) -> str:
    """Address of the running server's graph page, drawing *sparql*'s triples."""
    from urllib.parse import quote  # noqa: PLC0415

    return f"{_base(base)}/viz?q={quote(sparql)}"


def timeline_url(sparql: str, base: str | None = None, date_range: DateRange = _NO_RANGE) -> str:
    """Address of the running server's timeline page, dating *sparql*'s rows.

    *date_range* rides in the query string, the same way *sparql* does, so the
    link is the whole request: opening it later, or handing it to someone else,
    reproduces the bounded view rather than the unbounded one a bare ``?q=``
    would reopen.
    """
    from urllib.parse import quote  # noqa: PLC0415

    url = f"{_base(base)}/timeline?q={quote(sparql)}"
    if date_range.after:
        url += f"&after={quote(date_range.after)}"
    if date_range.before:
        url += f"&before={quote(date_range.before)}"
    return url


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


def dated_count(taxonomy: Taxonomy, result: QueryResult, date_range: DateRange = _NO_RANGE) -> int:
    """How many moments the timeline would draw for the entities *result* names.

    The same resolution ``POST /api/timeline`` runs for the page, so the count
    is what the reader will see rather than a guess at it — *date_range*
    included, so a bounded query does not get counted as if it were not.
    """
    from .store import full_graph_rdflib  # noqa: PLC0415
    from .time_shapes import timeline_items  # noqa: PLC0415
    from .viz_shared import is_uri  # noqa: PLC0415

    uris = list(dict.fromkeys(cell for row in result.rows for cell in row if is_uri(str(cell))))
    if not uris:
        return 0
    graph = full_graph_rdflib(taxonomy)
    return len(timeline_items(graph, uris, date_range.after, date_range.before))


def _triple_count(_taxonomy: Taxonomy, result: QueryResult) -> int:
    return len(result.rows) if result.query_type in GRAPHABLE_QUERY_TYPES else 0


def _why_no_graph(result: QueryResult) -> str:
    if result.query_type not in GRAPHABLE_QUERY_TYPES:
        return (
            f"{result.query_type} returns rows, not triples — "
            "use CONSTRUCT or DESCRIBE to draw a graph"
        )
    return f"the {result.query_type} produced no triples — loosen its WHERE clause"


def _why_no_map(_result: QueryResult) -> str:
    return (
        "no row carries coordinates, and no entity named in one does either — "
        "return a place, or a lat/long pair, to map this"
    )


def _why_no_timeline(_result: QueryResult) -> str:
    return (
        "no entity named in the rows carries a date — return things with an "
        "xsd:date, xsd:dateTime or xsd:gYear value to put them on a timeline"
    )


@dataclass(frozen=True)
class _View:
    """What one view needs: how much a result would show in it, why nothing
    would, and the page that draws it.

    Every view's ``count``/``url`` takes a :class:`DateRange`, even the two that
    ignore it — one shape for all three, so a fourth view gains the parameter by
    construction rather than by remembering to add it.
    """

    count: Callable[[Taxonomy, QueryResult, DateRange], int]
    why_empty: Callable[[QueryResult], str]
    url: Callable[[str, str | None, DateRange], str]


# One row per view, so a new view is a row here rather than another branch.
_VIEWS: Final[dict[str, _View]] = {
    GRAPH: _View(
        lambda tax, result, _rng: _triple_count(tax, result),
        _why_no_graph,
        lambda q, base, _rng: graph_url(q, base=base),
    ),
    MAP: _View(
        lambda tax, result, _rng: mappable_count(tax, result),
        _why_no_map,
        lambda q, base, _rng: map_url(q, base=base),
    ),
    TIMELINE: _View(dated_count, _why_no_timeline, timeline_url),
}
VIEWS: Final = tuple(sorted(_VIEWS))


@dataclass(frozen=True)
class ViewLink:
    """A view of a result: its URL and size, or why it cannot be drawn."""

    url: str | None
    reason: str | None
    count: int


def assess(
    taxonomy: Taxonomy,
    result: QueryResult,
    sparql: str,
    view: str,
    base: str | None = None,
    date_range: DateRange = _NO_RANGE,
) -> ViewLink:
    """How *result* would look as *view*: a link with a count, or a reason.

    *base* is the server address a request arrived on. A request that arrived
    proves the server is up, so the running check is only for callers with no
    request (the TUI) — asking for the background server alone told every agent
    on ``ster serve``, which starts none, that the server answering it was down.

    The reason is written for whoever asked — it names what is wrong *and* what
    would fix it, because "no" without a next step is the answer that gets
    retried verbatim.
    """
    spec = _VIEWS.get(view)
    if spec is None:
        return ViewLink(None, f"unknown view {view!r} — expected one of {', '.join(VIEWS)}", 0)
    if base is None and not _server_running():
        reason = "ster's HTTP server is not running — start it with `ster serve <file>`"
        return ViewLink(None, reason, 0)
    count = spec.count(taxonomy, result, date_range)
    if not count:
        return ViewLink(None, spec.why_empty(result), 0)
    return ViewLink(spec.url(sparql, base, date_range), None, count)


def link_for(
    taxonomy: Taxonomy,
    result: QueryResult,
    sparql: str,
    view: str,
    base: str | None = None,
    date_range: DateRange = _NO_RANGE,
) -> tuple[str | None, str | None]:
    """``(url, unavailable_reason)`` for opening *result* as *view*; exactly one is set."""
    link = assess(taxonomy, result, sparql, view, base, date_range)
    return link.url, link.reason


def _server_running() -> bool:
    from .api_server import is_running  # noqa: PLC0415

    return bool(is_running())


def annotate(
    payload: dict[str, Any],
    taxonomy: Taxonomy,
    result: QueryResult,
    sparql: str,
    view: str | None,
    base: str | None = None,
    date_range: DateRange = _NO_RANGE,
) -> dict[str, Any]:
    """Add ``view_url``/``view_unavailable``/``view_count`` when a view was asked for.

    The rows are returned either way: a view that cannot be built is not a query
    that failed, and an agent that asked for a nicety should not lose the answer
    it actually needed.
    """
    if not view:
        return payload
    link = assess(taxonomy, result, sparql, view, base, date_range)
    payload["view_url"] = link.url
    payload["view_unavailable"] = link.reason
    payload["view_count"] = link.count
    if link.url:
        payload["view_hint"] = (
            "Open this URL in a browser. With no browser available, report the URL "
            "as-is — it is reachable for as long as the ster server stays up."
        )
    return payload
