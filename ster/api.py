"""FastAPI application for the ster ontology REST API.

Provides schema introspection, individual creation, VOWL graph retrieval,
and a Server-Sent Events stream for live graph refresh.
"""

from __future__ import annotations

import asyncio
import html
import re
import unicodedata
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import rdflib
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .handles import assign_handles
from .model import Label, LabelType, OWLIndividual, Taxonomy

# ── Pydantic I/O models ───────────────────────────────────────────────────────


class LayoutIn(BaseModel):
    """Node positions from the graph page: URI → [x, y]."""

    positions: dict[str, tuple[float, float]]


class LabelIn(BaseModel):
    lang: str
    value: str


class CommentIn(BaseModel):
    lang: str
    value: str


class PropertyAssertionIn(BaseModel):
    property_uri: str
    target_uri: str


class IndividualIn(BaseModel):
    class_uri: str
    local_name: str | None = None
    labels: list[LabelIn] = []
    comments: list[CommentIn] = []
    property_values: list[PropertyAssertionIn] = []
    schema_urls: list[str] = []
    schema_images: list[str] = []


class QueryIn(BaseModel):
    """A read-only SPARQL query. SELECT and ASK only; see is_read_only_sparql."""

    query: str
    # Optional "map", "graph" or "timeline": adds a link opening the result in that view, or
    # the reason one cannot be built. Offered here as well as on the MCP tool so
    # neither transport has a capability the other lacks.
    view: str | None = None
    # Timeline-only: keep only moments on/after *after* and on/before *before*.
    # A query still decides which entities are considered; these decide which of
    # their moments are — see time_shapes.timeline_items for why that split exists.
    after: str | None = None
    before: str | None = None


class _VersionedIn(BaseModel):
    """Optimistic concurrency, for any front-end that talks to this API.

    ``TaxonomyService.execute`` has always accepted a *base_version* and
    returned ``rejected`` when it did not match; nothing sent one, so the check
    never ran and the last writer silently won. That was survivable for the TUI
    — one user, one process — but this API is multi-client by construction: two
    browser tabs, or a browser alongside a TUI, are the ordinary case.

    Optional on purpose. Omitted means "no check", which is exactly the previous
    behaviour, so existing callers keep working. A client that sends the version
    it last saw gets a 409 instead of overwriting an edit it never saw. Read the
    starting value from ``GET /api/version``; every mutation response carries the
    new one, so a client only fetches it once.
    """

    base_version: int | None = None


class EntityFieldIn(_VersionedIn):
    """Body for the label/description editing endpoints — one localized field
    on one entity (see docs/architecture/graph-editor.md, Phase 3)."""

    uri: str
    lang: str
    value: str


class IndividualRelationIn(_VersionedIn):
    """Body for creating/replacing one object-property relation between two
    individuals (see docs/architecture/graph-editor.md, Phase 4).

    *old_target_uri*, when set, replaces that existing value instead of
    adding a second one for the same property — editing a relation rather
    than creating an extra one."""

    ind_uri: str
    prop_uri: str
    target_uri: str
    old_target_uri: str = ""


class IndividualRelationRemoveIn(_VersionedIn):
    ind_uri: str
    prop_uri: str
    target_uri: str


class ClassParentIn(_VersionedIn):
    """Add *parent_uri* as a superclass of *child_uri* (rdfs:subClassOf) — a
    polyhierarchy add, not a reparent: existing superclasses are kept."""

    child_uri: str
    parent_uri: str


class ClassParentRemoveIn(_VersionedIn):
    child_uri: str
    parent_uri: str


class PropertyAssertionOut(BaseModel):
    property_uri: str
    target_uri: str


class PropertySummary(BaseModel):
    uri: str
    label: str
    range_uri: str | None = None
    range_label: str | None = None


class ClassOut(BaseModel):
    uri: str
    labels: dict[str, str]
    comment: dict[str, str]
    sub_class_of: list[str]
    child_classes: list[str]  # noqa: V107  # serialised by pydantic, read by API clients
    applicable_properties: list[PropertySummary]  # noqa: V107  # serialised by pydantic, read by API clients


class LocateIn(BaseModel):
    """The row URIs a map wants placed, and the labels of rows that gave a name where an IRI belonged."""

    uris: list[str] = []
    labels: list[str] = []


class TimelineIn(BaseModel):
    """The row URIs a timeline wants dated, and the labels of rows that gave a name where an IRI belonged."""

    uris: list[str] = []
    labels: list[str] = []
    # Keep only moments on/after *after* and on/before *before* — see QueryIn.
    after: str | None = None
    before: str | None = None


class SchemaOut(BaseModel):
    classes: list[ClassOut]


class IndividualOut(BaseModel):
    uri: str
    class_uri: str | None = None
    labels: list[LabelIn]
    property_values: list[PropertyAssertionOut] = []


# ── SSE broadcaster ───────────────────────────────────────────────────────────


class SSEBroadcaster:
    """Thread-safe SSE event broadcaster.

    ``notify()`` may be called from any thread; actual broadcasting runs in
    the asyncio event loop that owns this broadcaster.
    """

    def __init__(self) -> None:
        self._queues: list[asyncio.Queue[str]] = []

    def notify(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Schedule an 'updated' event to all connected listeners.

        A no-op when there is no loop to schedule on — including a *closed* one.
        The server runs on a daemon thread, so once it stops (shutdown, a bind
        failure, a crash) the cached loop is closed while callers still hold a
        reference; without this guard the next save would raise
        ``RuntimeError: Event loop is closed`` up through the TUI's save path.
        """
        target = loop
        if target is None:
            try:
                target = asyncio.get_running_loop()
            except RuntimeError:
                return
        if target.is_closed():
            return
        try:
            target.call_soon_threadsafe(self._broadcast)
        except RuntimeError:
            return  # loop closed between the check and the call

    def _broadcast(self) -> None:
        for q in self._queues:
            try:
                q.put_nowait("updated")
            except asyncio.QueueFull:
                pass

    async def subscribe(self) -> AsyncGenerator[str, None]:
        """Async generator that yields SSE-formatted lines."""
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=16)
        self._queues.append(q)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25)
                    yield f'data: {{"type": "{event}"}}\n\n'
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            try:
                self._queues.remove(q)
            except ValueError:
                pass


# ── App factory ───────────────────────────────────────────────────────────────


def _labelled_things_query(things: Any) -> str:
    """SELECT each of *things* with its label, or "" when there is none to ask about.

    Shared by the focused map and timeline queries: they differ only in which
    IRIs *focus* reaches, never in how those IRIs are asked for.
    """
    if not things:
        return ""
    values = " ".join(f"<{uri}>" for uri in things)
    return (
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n\n"
        "SELECT DISTINCT ?thing ?name\n"
        "WHERE {\n"
        f"  VALUES ?thing {{ {values} }}\n"
        "  OPTIONAL { ?thing rdfs:label ?name }\n"
        "}"
    )


# Starter query for GET /map when none is supplied: anything with WGS84
# coordinates, in any vocabulary.
# Used when the map is opened without a query of its own — the TUI's "open map"
# action does exactly that. Two things matter here and both are easy to undo by
# accident:
#
#   It selects the *entity*, never lat/long columns. geo_map_html places rows
#   straight from a lat/long column pair and never asks the server to resolve
#   them, so selecting those columns silently turns off the geometry ladder and
#   with it every level, parent and ancestor the drill-down needs.
#
#   Shapes are found by literal datatype rather than by predicate, as everywhere
#   else in ster: a registry of predicate names would never be finished, and the
#   previous default matched wgs:lat alone, so no polygon was ever on this map.
#
#   The limit is high on purpose. At 200 it was invisible on the 34-place demo
#   and quietly ruinous on a real file: an ontology of 1,267 places kept whichever
#   arbitrary 200 the graph yielded first, and the map read "France 2, Spain 164"
#   when the truth was France 588, Spain 266. A map that is confidently wrong is
#   worse than one that is slow, and the map draws a single level at a time
#   anyway, so a large result costs little to hold.
def _focused_map_query(taxonomy: Any, focus: str) -> str:
    """A map query over exactly what *focus* can put on a map, or "" for nothing.

    Built here rather than passed through the URL: a brand reaches every one of
    its stores, and 145 IRIs in a query string is a link nobody can send. The
    page carries it instead, where it also shows under "Show query" — so the
    reader can see what was asked and edit it, rather than facing a map that
    filtered itself for reasons it will not explain.
    """
    from .geo_shapes import located_from  # noqa: PLC0415

    graph = _graph_for_locate(taxonomy)
    reachable = located_from(graph, rdflib.URIRef(focus))
    return _labelled_things_query(reachable)


def _focused_timeline_query(taxonomy: Any, focus: str) -> str:
    """A timeline query over exactly what *focus* can put on an axis, or "".

    The mirror of :func:`_focused_map_query`, and built server-side for the same
    reason: a procedure reaches its events, its deadlines and its provenance, and
    those IRIs belong in the page rather than in a link nobody can send.
    """
    from .time_shapes import dated_from  # noqa: PLC0415

    graph = _graph_for_locate(taxonomy)
    reachable = dated_from(graph, rdflib.URIRef(focus))
    return _labelled_things_query(reachable)


# The shapes /timeline's after/before may take — a year, a year-month, a date,
# or a full date-time, matching exactly what time_shapes.TEMPORAL_DATATYPES
# recognises (xsd:gYear/gYearMonth/date/dateTime). Date-time suffixes are
# composed from flat parts rather than one expression with nested optionals.
_TIMELINE_DATE_TIME = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
_TIMELINE_TIME_SUFFIXES = ("", r":\d{2}", r"\.\d{1,6}", r":\d{2}\.\d{1,6}")
_TIMELINE_TIMEZONES = ("", "Z", r"[+-]\d{2}:\d{2}")
_TIMELINE_BOUND_SHAPES: Final = (
    re.compile(r"\d{4}"),
    re.compile(r"\d{4}-\d{2}"),
    re.compile(r"\d{4}-\d{2}-\d{2}"),
    *(
        re.compile(_TIMELINE_DATE_TIME + time_suffix + timezone)
        for time_suffix in _TIMELINE_TIME_SUFFIXES
        for timezone in _TIMELINE_TIMEZONES
    ),
)


def _validated_timeline_bound(value: str, field_name: str) -> str | None:
    """*value* if it has one of the shapes above, else a 400.

    The one thing this must never do is let *value* through unchanged when it
    doesn't: it reaches ``render_timeline_html``, which splices it into the
    timeline page's inline ``<script>`` tag — the sink CodeQL and SonarQube
    both flagged as a reflected XSS before this check existed. Restricting the
    accepted alphabet to digits, ``-``, ``:``, ``.``, ``T``, ``Z``, ``+`` makes
    ``</script>`` impossible to spell in a value that passes; that is a
    byproduct of validating *shape*, not a second escaping step — the escaping
    itself belongs to, and lives in, ``timeline_html._safe_json_for_script``,
    the actual sink, so this check is free to be about correctness rather than
    safety and still get safety for it.
    """
    if not value:
        return None
    if any(shape.fullmatch(value) for shape in _TIMELINE_BOUND_SHAPES):
        return value
    raise HTTPException(
        status_code=400,
        detail=f"Invalid {field_name}: expected ISO-like date/datetime.",
    )


_DEFAULT_MAP_QUERY = """\
PREFIX geo:  <http://www.opengis.net/ont/geosparql#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#>

SELECT DISTINCT ?thing ?name
WHERE {
  {
    ?thing ?geometryProperty ?geometry .
    FILTER (datatype(?geometry) IN (geo:wktLiteral, geo:geoJSONLiteral))
  }
  UNION
  { ?thing wgs:lat ?lat }
  OPTIONAL { ?thing rdfs:label ?name }
}
LIMIT 5000
"""


# Responses smaller than this are sent as they are: below roughly a packet the
# compressed form can be larger than the original, and the CPU buys nothing.
MIN_COMPRESS_BYTES = 1024


def create_app(
    taxonomy: Taxonomy,
    token: str,
    broadcaster: SSEBroadcaster,
    save_fn: Any,  # Callable[[Taxonomy], None] — Any avoids heavy typing import
    *,
    html_fn: Any = None,  # Callable[[], str] — returns rendered HTML for GET /
    file_path: Path | None = None,
    publish_dir: Path | None = None,
    context: list[Path] | None = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    All mutable state is held in ``_st`` — a dict closed over by every
    endpoint.  The file watcher in ``api_server`` updates ``_st["taxonomy"]``
    when the source file changes; the broadcasted SSE event triggers a reload
    in every connected graph client.
    """
    # html_fn lives in the mutable state rather than the closure so it can be
    # attached to an already-running server: the TUI starts the server for MCP
    # (no landing page), and opening the graph viewer later supplies the VOWL
    # renderer to that same server.
    _st: dict[str, Any] = {
        _LIT_TAXONOMY: taxonomy,
        _LIT_FILE_PATH: file_path,
        _LIT_CONTEXT: list(context or []),
        "html_fn": html_fn,
    }
    from .plugins.query_trace import follow_setting  # noqa: PLC0415

    follow_setting(file_path)
    _bearer = HTTPBearer(auto_error=False)

    def _tax() -> Taxonomy:
        return _st[_LIT_TAXONOMY]  # type: ignore[return-value]

    def _check_auth(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> None:
        if credentials is None or credentials.credentials != token:
            raise HTTPException(status_code=401, detail="Unauthorized")

    app = FastAPI(
        title="ster ontology API",
        description=(
            "Query OWL classes / properties and create individuals in a ster-managed ontology."
        ),
        version="1.0.0",
        license_info={"name": "MIT"},
    )

    # The map payload is one record per place and is overwhelmingly the same
    # strings repeated — ancestors, facet classes, an icon data URI, once per
    # store. On a file of a thousand shops that is 2.2 MB, and compressing it is
    # worth 94%. Restructuring the payload instead was measured and rejected: an
    # intern table saves a further 5 KB and costs a wire format on both sides.
    app.add_middleware(GZipMiddleware, minimum_size=MIN_COMPRESS_BYTES)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",  # NOSONAR - local-only address, not a network destination
            "http://127.0.0.1",  # NOSONAR - local-only address, not a network destination
        ],
        allow_origin_regex=r"chrome-extension://.*",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Expose mutable state so api_server can update the taxonomy reference
    app.state._ster = _st  # type: ignore[attr-defined]

    if publish_dir is not None and publish_dir.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount(
            f"/{publish_dir.name}",
            StaticFiles(directory=str(publish_dir), html=True),
            name="published",
        )

    # ── Endpoints ─────────────────────────────────────────────────────────────

    _register_pages(app, _st, token)
    _register_schema_routes(app, _st, _tax, _check_auth, save_fn, broadcaster)
    _register_graph_routes(app, _tax, _check_auth)
    _register_layout(app, _st, _tax, _check_auth)
    _register_mutation_routes(app, _st, _check_auth, broadcaster)
    _register_locate(app, _tax, _check_auth)
    _register_timeline(app, _tax, _check_auth)
    _register_events(app, token, broadcaster)
    _register_mcp(app, _st, _tax, _check_auth, token)
    _register_trace_answers(app, _check_auth)

    return app


# ── Route groups ──────────────────────────────────────────────────────────────
# create_app used to define every endpoint inline, which made it a 260-line
# function. Each group is now registered by its own function: the handlers are
# unchanged, but each concern can be read on its own and create_app is a short
# assembly step. They take the shared state explicitly rather than closing over
# it, so what each group touches is visible in its signature.


def _graph_html_response(
    _st: dict[str, Any], root_uri: str | None, full: bool = False, sparql: str = ""
) -> HTMLResponse:
    """Render a graph page while refusing requests before a renderer is attached."""
    # no-store: the page inlines its JS, so caching it served stale builds
    # until a manual hard-reload.
    render = _st.get("html_fn")
    if render is None:
        raise HTTPException(status_code=501, detail="No HTML renderer configured")
    return HTMLResponse(
        render(root_uri, full, sparql),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def _map_response(
    _st: dict[str, Any], token: str, sparql: str, show: str, focus: str, embed: bool
) -> HTMLResponse:
    from .geo_map_html import render_map_html  # noqa: PLC0415

    query = sparql or (_focused_map_query(_st[_LIT_TAXONOMY], focus) if focus else "")
    return HTMLResponse(
        render_map_html(query or _DEFAULT_MAP_QUERY, token, show_all=show == "all", embed=embed)
    )


@dataclass(frozen=True)
class _TimelinePage:
    """What a request for the timeline page asked: its query or focus, its date bounds, and whether to embed it."""

    sparql: str
    focus: str
    after: str
    before: str
    embed: bool


def _timeline_response(_st: dict[str, Any], token: str, ask: _TimelinePage) -> HTMLResponse:
    from .timeline_html import DEFAULT_TIMELINE_QUERY, render_timeline_html  # noqa: PLC0415

    query = ask.sparql or (
        _focused_timeline_query(_st[_LIT_TAXONOMY], ask.focus) if ask.focus else ""
    )
    # The validator restricts these to date characters. Escape them anyway
    # at this HTML boundary: it documents the sink contract to CodeQL and
    # keeps a future validator broadening from reopening reflected XSS.
    after_value = html.escape(_validated_timeline_bound(ask.after, "after") or "") or None
    before_value = html.escape(_validated_timeline_bound(ask.before, "before") or "") or None
    # No-cache, as /viz does: the page embeds its own app layer, so a cached
    # copy silently keeps serving yesterday's JavaScript after an edit — a
    # confusing failure the author hits before any user does.
    return HTMLResponse(
        render_timeline_html(
            query or DEFAULT_TIMELINE_QUERY, token, after_value, before_value, ask.embed
        ),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def _trace_timeline_response(
    _st: dict[str, Any], page: int, page_size: int, idle_seconds: int, after: str, before: str
) -> HTMLResponse:
    from .plugins.query_trace.sessions import agent_sessions_for_project  # noqa: PLC0415
    from .query_trace.timeline import render_timeline_html  # noqa: PLC0415

    # The bounds reach the page's inputs and its pager links, so they must be dates: the shape is
    # checked here (a 400 otherwise) and escaped again at the sink, as the /timeline route does.
    after_value = html.escape(_validated_timeline_bound(after, "after") or "")
    before_value = html.escape(_validated_timeline_bound(before, "before") or "")
    path = _st.get(_LIT_FILE_PATH)
    project = path.parent if path is not None else None
    sessions = agent_sessions_for_project(project, idle_seconds) if project else []
    filtered = [
        item
        for item in sessions
        if (not after_value or item.started >= after_value)
        and (not before_value or item.started <= before_value)
    ]
    return HTMLResponse(
        render_timeline_html(
            filtered,
            page=page,
            page_size=page_size,
            idle_seconds=idle_seconds,
            after=after_value,
            before=before_value,
        )
    )


def _register_pages(app: FastAPI, _st: dict[str, Any], token: str) -> None:
    """HTML landing pages and the raw-ontology endpoint (no auth: read-only views)."""

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def root(
        root_uri: str | None = Query(default=None, alias="root"),
        full: bool = False,
    ) -> HTMLResponse:
        return _graph_html_response(_st, root_uri, full)

    @app.get("/viz", response_class=HTMLResponse, include_in_schema=False)
    def viz(
        root_uri: str | None = Query(default=None, alias="root"),
        full: bool = False,
        sparql: str = Query(default="", alias="q"),
    ) -> HTMLResponse:
        """The graph page, optionally drawing a CONSTRUCT instead of the model.

        ``?q=`` mirrors ``/map?q=``: the query travels in the URL, the token does
        not — the page embeds it, so it stays out of browser history.
        """
        return _graph_html_response(_st, root_uri, full, sparql)

    @app.get("/map", response_class=HTMLResponse, include_in_schema=False)
    def map_page(
        sparql: str = Query(default="", alias="q"),
        show: str = Query(default="", alias="show"),
        focus: str = Query(default="", alias="focus"),
        embed: bool = Query(default=False, alias="embed"),
    ) -> HTMLResponse:
        """A live map of a SPARQL result — see :mod:`ster.geo_map_html`.

        Open like ``/viz``: the page itself needs no token, and embeds one so its
        own ``/mcp`` calls authenticate. Keeping the token out of the URL means it
        does not land in browser history.

        ``?embed=1`` hides the page's own header, query box and details panel, for showing
        the map inside another page; nothing else about it changes.
        """
        return _map_response(_st, token, sparql, show, focus, embed)

    @app.get("/timeline", response_class=HTMLResponse, include_in_schema=False)
    def timeline_page(
        sparql: str = Query(default="", alias="q"),
        focus: str = Query(default="", alias="focus"),
        after: str = Query(default="", alias="after"),
        before: str = Query(default="", alias="before"),
        embed: bool = Query(default=False, alias="embed"),
    ) -> HTMLResponse:
        """A live frieze of a SPARQL result — see :mod:`ster.timeline_html`.

        Opens like ``/map``: no token in the URL, one embedded in the page so its
        own calls to ``/api/sparql_query`` and ``/api/timeline`` authenticate.

        *after*/*before* prime the page's own date-range inputs, the same way *q*
        primes its query box — so a link built with them (``timeline_url``, or
        one a person edits by hand) reopens already bounded rather than needing
        the filter re-entered.

        ``?embed=1`` hides the page's own header and query box, for showing the frieze
        inside another page; nothing else about it changes.
        """
        return _timeline_response(_st, token, _TimelinePage(sparql, focus, after, before, embed))

    @app.get("/query-trace/timeline", response_class=HTMLResponse, include_in_schema=False)  # noqa: V103
    def query_trace_timeline(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=50),
        idle_seconds: int = Query(default=60, ge=1, le=3600),
        after: str = Query(default=""),
        before: str = Query(default=""),
    ) -> HTMLResponse:
        return _trace_timeline_response(_st, page, page_size, idle_seconds, after, before)

    @app.get("/onto", response_class=Response, include_in_schema=False)
    def serve_ontology(request: Request) -> Response:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return _serve_pylode(_st[_LIT_FILE_PATH])
        return _serve_turtle(_st[_LIT_TAXONOMY])


def _register_schema_routes(
    app: FastAPI,
    _st: dict[str, Any],
    _tax: Any,
    _check_auth: Any,
    save_fn: Any,
    broadcaster: SSEBroadcaster,
) -> None:
    """Class / individual introspection and individual creation."""

    @app.get(
        "/api/classes",
        response_model=SchemaOut,
        summary="List all classes or fetch one by URI",
        tags=["Schema"],
    )
    def get_classes(
        uri: str | None = Query(default=None, description="Filter to a single class URI"),
        _: None = Depends(_check_auth),
    ) -> SchemaOut:
        tax = _tax()
        if uri is not None:
            if uri not in tax.owl_classes:
                raise HTTPException(status_code=404, detail="Class not found")
            return SchemaOut(classes=[_class_out(tax, uri)])
        return SchemaOut(classes=[_class_out(tax, u) for u in tax.owl_classes])

    @app.get(
        "/api/individuals",
        summary="List individuals, optionally filtered by class",
        tags=["Individuals"],
    )
    def get_individuals(
        type: str | None = Query(default=None, description="Filter by rdf:type class URI"),
        _: None = Depends(_check_auth),
    ) -> dict[str, list[IndividualOut]]:
        return {"individuals": _individuals_out(_tax(), type)}

    @app.post(
        "/api/individuals",
        status_code=201,
        response_model=IndividualOut,
        summary="Create a new individual",
        tags=["Individuals"],
    )
    async def create_individual(
        body: IndividualIn,
        _: None = Depends(_check_auth),
    ) -> IndividualOut:
        tax = _tax()
        new_uri = _add_individual(tax, body)
        assign_handles(tax)
        save_fn(tax)
        broadcaster._broadcast()
        return _individual_out(new_uri, tax.owl_individuals[new_uri])


# A node type the graph page sends, and the fallback slug for an unnamed individual.
_INDIVIDUAL: Final = "individual"
_TAG_VIZ = "Visualisation"


def _register_graph_routes(app: FastAPI, _tax: Any, _check_auth: Any) -> None:
    """VOWL graph payloads and relation lookups."""

    @app.get(
        "/api/graph",
        summary="Return the default (root-level) VOWL graph payload",
        tags=[_TAG_VIZ],
    )
    def get_graph(
        full: bool = False,
        q: str = Query(default="", description="SPARQL CONSTRUCT to draw instead of the model"),
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .viz_vowl import (
            build_default_vowl_graph,
            build_vowl_graph,
            collapse_individuals,
            strip_detail,
        )

        # Detail is fetched per node from /api/node-detail; sending it here would
        # put the whole side-panel corpus on every live-refresh tick.
        # Individuals are collapsed for the same reason detail is stripped: on a
        # file of 1,027 shops they were 98.7% of the nodes and 98.5% of the
        # bytes, on every tick. A class carries its count; the page asks for one
        # class's individuals when it is opened.
        #
        # Default is root-level only (schemes, root classes, top concepts) —
        # the same reasoning generalised from individuals to classes/concepts:
        # a large ontology rendered whole is a wall of dots, not a graph. The
        # rest is revealed on click through /api/class-links and
        # /api/concept-relations, already used for that. ?full=true opts back
        # into the unscoped graph.
        # A query, when given, replaces the model walk entirely. The walk shows
        # what ster *understands*; a query shows what the graph *contains* —
        # including statements a context file makes, anything a reasoner added,
        # and relations no dataclass has a field for. Same payload either way,
        # so the page renders both without knowing which produced it.
        if q.strip():
            from .viz_vowl import graph_from_query  # noqa: PLC0415

            return graph_from_query(_tax(), q)  # type: ignore[return-value]
        from .api_server import load_graph_viz_config  # noqa: PLC0415

        limits = load_graph_viz_config()
        graph = (
            build_vowl_graph(_tax())
            if full
            else build_default_vowl_graph(_tax(), limits["classCollapse"])
        )
        return collapse_individuals(  # type: ignore[return-value]
            strip_detail(graph), limits["individualCollapse"]
        )

    @app.get(
        "/api/node-detail",
        summary="Return the side-panel detail for a single node",
        tags=[_TAG_VIZ],
    )
    def get_node_detail(
        uri: str = Query(description="URI of the entity to describe"),
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .viz_vowl import node_detail

        return node_detail(_tax(), uri)  # type: ignore[return-value]

    @app.get(
        "/api/class-individuals",
        summary="Return the individuals of one class, for expanding it in the graph",
        tags=[_TAG_VIZ],
    )
    def get_class_individuals(
        uri: str = Query(description="URI of the class to expand"),
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .api_server import load_graph_viz_config  # noqa: PLC0415
        from .viz_vowl import class_individuals

        return class_individuals(  # type: ignore[return-value]
            _tax(), uri, load_graph_viz_config()["classExpand"]
        )

    @app.get(
        "/api/individual-relations",
        summary="Return the object-property relations subgraph for an individual",
        tags=[_TAG_VIZ],
    )
    def get_individual_relations(
        uri: str = Query(description="URI of the individual to expand"),
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .viz_vowl import build_individual_relations_graph

        return build_individual_relations_graph(_tax(), uri)  # type: ignore[return-value]

    @app.get(
        "/api/concept-relations",
        summary="Return the broader/narrower subgraph for a SKOS concept",
        tags=[_TAG_VIZ],
    )
    def get_concept_relations(
        uri: str = Query(description="URI of the concept to explore"),
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .viz_vowl import build_concept_relations_graph

        return build_concept_relations_graph(_tax(), uri)  # type: ignore[return-value]

    @app.get(
        "/api/class-links",
        summary="Return the linked-classes subgraph for a class",
        tags=[_TAG_VIZ],
    )
    def get_class_links(
        uri: str = Query(description="URI of the class to explore"),
        subclass_only: bool = Query(
            False, description="Omit T-Box object-property links, keep only the subClassOf trail"
        ),
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .viz_vowl import build_class_links_graph

        return build_class_links_graph(_tax(), uri, subclass_only=subclass_only)  # type: ignore[return-value]

    @app.get(
        "/api/has-relations",
        summary="Whether exploring this node's relations would show anything",
        tags=[_TAG_VIZ],
    )
    def get_has_relations(
        uri: str = Query(description="URI of the node under the cursor"),
        kind: Literal["class", "individual", "concept", "topconcept"] = Query(
            alias="type", description="The node's type, as the graph page knows it"
        ),
        _: None = Depends(_check_auth),
    ) -> dict[str, bool]:
        """Asked on hover, so the page only offers "explore relations" when it
        would open something. Same builders as the explore endpoints above, so
        the button and the action cannot disagree."""
        from .viz_vowl import (  # noqa: PLC0415
            build_class_links_graph,
            build_concept_relations_graph,
            build_individual_relations_graph,
        )

        builders: dict[str, Callable[..., dict[str, Any]]] = {
            "class": build_class_links_graph,
            _INDIVIDUAL: build_individual_relations_graph,
            "concept": build_concept_relations_graph,
            "topconcept": build_concept_relations_graph,
        }
        graph = builders[kind](_tax(), uri)
        return {"relations": bool(graph.get("edges"))}

    @app.get(
        "/api/search",
        summary="Search the whole ontology, not just what is currently rendered",
        tags=[_TAG_VIZ],
    )
    def search_ontology(
        q: str = Query("", description="Search term (matched against label and URI)"),
        types: str = Query("", description="Comma-separated node types to restrict the search to"),
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .viz_vowl import build_search_results

        type_set = {t for t in types.split(",") if t} or None
        return build_search_results(_tax(), q, types=type_set)  # type: ignore[return-value]


_LIT_LANE_LABEL: Final = "label"
_LIT_LANE_COUNT: Final = "count"
_LIT_TAXONOMY: Final = "taxonomy"
_LIT_VERSION: Final = "version"
_LIT_FILE_PATH: Final = "file_path"
_LIT_CONTEXT: Final = "context"
_TAG_MUTATE = "Editing"


def _mutation_backend(_st: dict[str, Any]) -> tuple[Any, Any, Path] | None:
    """Lazily build (service, workspace, path) for the mutation endpoints below,
    cached on *_st* for the life of the app. ``None`` when there is no file
    backing this session (nothing a command could persist to — mirrors the TUI's
    own read-only fallback when it has no path, see ``_make_service``).

    Built from ``_st["taxonomy"]`` the first time a mutation is attempted, not
    eagerly at app start: most sessions (read-only graph viewing, MCP queries)
    never call this, so there is nothing to build for them.
    """
    path = _st.get(_LIT_FILE_PATH)
    if path is None:
        return None
    cached = _st.get("_mutation_backend")
    if cached is not None:
        return cached  # type: ignore[return-value]

    from . import graph_layout
    from .core.adapters import StorePersistence
    from .core.service import TaxonomyService
    from .core.validation import SkosValidatorAdapter
    from .workspace import TaxonomyWorkspace

    workspace = TaxonomyWorkspace.from_taxonomy(_st[_LIT_TAXONOMY], path)
    service = TaxonomyService(workspace, StorePersistence(), SkosValidatorAdapter())
    service.add_rename_listener(graph_layout.rename_nodes)  # positions follow renames
    backend = (service, workspace, path)
    _st["_mutation_backend"] = backend
    return backend


def _is_owl_entity(tax: Taxonomy, uri: str) -> bool:
    return uri in tax.owl_classes or uri in tax.owl_individuals or uri in tax.owl_properties


def _field_command(
    tax: Taxonomy, path: Path, body: EntityFieldIn, owl_cls: Any, skos_cls: Any, **skos_kwargs: Any
) -> Any:
    """Build the right command for *body.uri*'s entity kind — a concept goes
    through the SKOS command, an OWL class/individual/property through the OWL
    one; anything else is a 422 (the same shape ``OwlSetLabel``'s own silent
    no-op on an unknown URI would hide otherwise)."""
    if body.uri in tax.concepts:
        return skos_cls(path, body.uri, body.lang, body.value, **skos_kwargs)
    if _is_owl_entity(tax, body.uri):
        return owl_cls(path, body.uri, body.lang, body.value)
    raise HTTPException(status_code=422, detail=f"Unknown entity URI: {body.uri}")


def _require_editable(tax: Taxonomy, uri: str) -> None:
    """Refuse a write aimed at an entity that came from a read-only context file.

    ``store.is_editable`` is the single definition of what "editable" means, and
    this is the same call the rest of ster makes: an entity merged from a context
    file is visible so the graph reads correctly, and locked because the file it
    lives in is not the one this session writes.

    Enforced on the server, not merely in the page. The graph viewer already dims
    a ``readOnly`` node and hides its edit affordances, but a client is free not
    to — the guarantee has to hold for curl and for any other front-end, or it is
    a convention rather than a rule.
    """
    from .store import is_editable  # noqa: PLC0415

    if not is_editable(tax, uri):
        source = tax.context_source.get(uri)
        where = f" (it belongs to {Path(source).name})" if source else ""
        raise HTTPException(
            status_code=409,
            detail=f"{uri} is read-only context{where} — only the file this session opened is writable.",
        )


def _require_mutation_backend(_st: dict[str, Any]) -> tuple[Any, Any, Path]:
    backend = _mutation_backend(_st)
    if backend is None:
        raise HTTPException(
            status_code=503, detail="No ontology file path configured — editing is unavailable"
        )
    return backend


def _execute_mutation(
    _st: dict[str, Any],
    broadcaster: SSEBroadcaster,
    workspace: Any,
    path: Path,
    result: Any,
) -> dict[str, Any]:
    """Translate an already-executed ``CommandResult`` into an HTTP response (or
    the matching ``HTTPException``), and — on success — sync the live taxonomy
    reference and broadcast the change (same fan-out ``/api/individuals`` uses).

    A 409 here is a real stale-version rejection, not a lock timeout: the client
    sent a *base_version* that is no longer current, so someone else edited in
    between. Re-read the entity and retry — the response carries the version the
    client should now be on.

    Note the deliberate divergence from the TUI on persistence. The TUI executes
    with ``persist=False`` and writes on a background worker, because it keeps
    the file open and the user in the app. This API executes with the default
    ``persist=True``: an HTTP client that receives 200 is entitled to assume the
    change reached disk, and deferring the write would make that a lie the
    server could not honour if it died. Slower on a large file, and correct.
    """
    if result.status == "rejected":
        raise HTTPException(status_code=409, detail=result.error)
    if result.status == "failed":
        raise HTTPException(status_code=422, detail=result.error)
    _st[_LIT_TAXONOMY] = workspace.taxonomies[path]
    broadcaster._broadcast()
    return {
        "status": "ok",
        _LIT_VERSION: result.version,
        "affected_uris": list(result.affected_uris),
    }


def _run_field_edit(
    _st: dict[str, Any],
    broadcaster: SSEBroadcaster,
    body: EntityFieldIn,
    owl_cls: Any,
    skos_cls: Any,
    **skos_kwargs: Any,
) -> dict[str, Any]:
    """Shared body of every Phase 3 field-edit endpoint: resolve the mutation
    backend, dispatch to the right command, execute it, and translate the
    ``CommandResult`` into an HTTP response (or the matching HTTPException)."""
    service, workspace, path = _require_mutation_backend(_st)
    _require_editable(_st[_LIT_TAXONOMY], body.uri)
    command = _field_command(
        workspace.taxonomies[path], path, body, owl_cls, skos_cls, **skos_kwargs
    )
    return _execute_mutation(
        _st, broadcaster, workspace, path, service.execute(command, base_version=body.base_version)
    )


def _register_mutation_routes(
    app: FastAPI,
    _st: dict[str, Any],
    _check_auth: Any,
    broadcaster: SSEBroadcaster,
) -> None:
    """Editable side panel (Phase 3): label/description edits routed through
    ``TaxonomyService`` rather than the ad hoc mutate-then-save_fn pattern the
    schema routes above still use for individual creation — every command here
    gets the same OCC version check, validation gate, and atomic swap the TUI
    already relies on (see docs/architecture/graph-editor.md, Phase 3)."""

    # ── the semantic read views ──────────────────────────────────────────
    # Every MCP tool binds an endpoint, so a protocol is a way in and never the
    # only way to reach an answer. These three had none: their logic lived in
    # mcp_context and nothing but MCP could call it.
    #
    # They are not duplicates of /api/node-detail and /api/search. Those return
    # what a *panel* needs — images, scope notes, relations to draw. These
    # return what a *reader* needs — kind, parents, children, counts, the
    # vocabulary actually in use. Two projections of one model, for two
    # audiences, which is why both stay.

    @app.get(
        "/api/overview",
        summary="What this ontology is and how much of each thing it holds",
        tags=[_TAG_VIZ],
    )
    def get_overview_endpoint(
        lang: str = Query(default="en", description="Language for labels."),
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .mcp_context import overview  # noqa: PLC0415

        return overview(_st[_LIT_TAXONOMY], lang)

    @app.get(
        "/api/vocabulary",
        summary="The predicates, types and prefixes this ontology actually uses",
        tags=[_TAG_VIZ],
    )
    def get_vocabulary_endpoint(_: None = Depends(_check_auth)) -> dict[str, Any]:
        """What to read before composing a query — the terms really present,
        with counts, rather than the ones a vocabulary says ought to be."""
        from .mcp_context import vocabulary  # noqa: PLC0415

        return vocabulary(_st[_LIT_TAXONOMY])

    @app.post(
        "/api/sparql_query",
        summary="Run a read-only SPARQL query against the loaded ontology",
        tags=[_TAG_VIZ],
    )
    def run_query_endpoint(
        body: QueryIn,
        request: Request,
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        """The map's query path, and the place to put access control.

        Exists because /mcp was the only route that accepted SPARQL, so a page
        in the browser had to speak an agent protocol to its own backend to ask
        a question. MCP is a transport; the logic belongs here, and the tool now
        calls the same function this does.

        The Origin check is carried over from /mcp deliberately and is not
        boilerplate: this is the one endpoint that runs an arbitrary query
        against a server on the user's own machine, so a page they merely visit
        must not be able to script it (DNS rebinding). No other /api route needs
        it because no other one takes a query.
        """
        from .mcp_context import sparql_payload  # noqa: PLC0415
        from .mcp_server import origin_allowed  # noqa: PLC0415

        if not origin_allowed(request.headers.get("origin")):
            raise HTTPException(status_code=403, detail="Origin not allowed")
        return sparql_payload(
            _st[_LIT_TAXONOMY],
            body.query,
            body.view,
            str(request.base_url),
            after=body.after,
            before=body.before,
        )

    @app.get(
        "/api/version",
        summary="The current version of the loaded ontology, for optimistic concurrency",
        tags=[_TAG_MUTATE],
    )
    def get_version(_: None = Depends(_check_auth)) -> dict[str, Any]:
        """What a client sends back as *base_version* on its first edit.

        Zero when nothing has been edited in this session, and zero when there is
        no file backing it — a read-only session cannot go stale, so the caller
        needs no special case for it.
        """
        from ._version import __version__  # noqa: PLC0415

        # The ster build answering, alongside the ontology version. A page bakes
        # in the build that drew it, so comparing the two is how it notices the
        # server was replaced by a different one underneath it — which is the
        # whole of "I updated ster and the graph view is still old".
        backend = _mutation_backend(_st)
        if backend is None:
            return {_LIT_VERSION: 0, "editable": False, "ster": __version__}
        service, _workspace, path = backend
        return {_LIT_VERSION: service.version(path), "editable": True, "ster": __version__}

    @app.post(
        "/api/entity-label",
        summary="Set an entity's label (rdfs:label for OWL, skos:prefLabel for SKOS)",
        tags=[_TAG_MUTATE],
    )
    def set_entity_label(
        body: EntityFieldIn,
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .core.commands.owl import OwlSetLabel
        from .core.commands.skos import SkosSetLabel

        return _run_field_edit(_st, broadcaster, body, OwlSetLabel, SkosSetLabel, kind="pref")

    @app.post(
        "/api/entity-description",
        summary=("Set an entity's description (rdfs:comment for OWL, skos:definition for SKOS)"),
        tags=[_TAG_MUTATE],
    )
    def set_entity_description(
        body: EntityFieldIn,
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .core.commands.owl import OwlSetComment
        from .core.commands.skos import SkosSetDefinition

        return _run_field_edit(_st, broadcaster, body, OwlSetComment, SkosSetDefinition)

    # ── Phase 4: relations between existing nodes ───────────────────────────
    # Scoped to the two concrete cases already named in the plan (see
    # docs/architecture/graph-editor.md, Phase 4): an object-property value
    # between two individuals, and a subClassOf link between two classes.
    # Canvas drag-to-create (cytoscape-edgehandles / cytoscape-edge-editing) was
    # investigated and found to need an undeclared browser dependency each
    # (edgehandles expects a global `_` with lodash's memoize/throttle;
    # edge-editing expects konva.js) — shipping either unvendored would throw
    # on page load for no benefit, so relation editing here is panel-based
    # instead (reusing the Phase 3 editable-row pattern client-side), not
    # canvas-drag. See the doc's Phase 4 section for the full reasoning.

    @app.post(
        "/api/relation",
        summary="Create or replace an object-property relation between two individuals",
        tags=[_TAG_MUTATE],
    )
    def set_relation(
        body: IndividualRelationIn,
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .core.commands.owl import OwlSetIndividualValue

        service, workspace, path = _require_mutation_backend(_st)
        _require_editable(_st[_LIT_TAXONOMY], body.ind_uri)
        command = OwlSetIndividualValue(
            path, body.ind_uri, body.prop_uri, body.target_uri, body.old_target_uri
        )
        return _execute_mutation(
            _st,
            broadcaster,
            workspace,
            path,
            service.execute(command, base_version=body.base_version),
        )

    @app.post(
        "/api/relation/remove",
        summary="Remove an object-property relation between two individuals",
        tags=[_TAG_MUTATE],
    )
    def remove_relation(
        body: IndividualRelationRemoveIn,
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .core.commands.owl import OwlRemoveIndividualValue

        service, workspace, path = _require_mutation_backend(_st)
        _require_editable(_st[_LIT_TAXONOMY], body.ind_uri)
        command = OwlRemoveIndividualValue(path, body.ind_uri, body.prop_uri, body.target_uri)
        return _execute_mutation(
            _st,
            broadcaster,
            workspace,
            path,
            service.execute(command, base_version=body.base_version),
        )

    @app.post(
        "/api/class-parent",
        summary="Add a superclass link (rdfs:subClassOf) between two classes",
        tags=[_TAG_MUTATE],
    )
    def add_class_parent(
        body: ClassParentIn,
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .core.commands.owl import OwlMoveClass

        service, workspace, path = _require_mutation_backend(_st)
        _require_editable(_st[_LIT_TAXONOMY], body.child_uri)
        # replace=False: add a superclass alongside any existing ones
        # (polyhierarchy) — a link the user drew, not a reparent that would
        # silently drop the class's other superclasses.
        command = OwlMoveClass(path, body.child_uri, body.parent_uri, replace=False)
        return _execute_mutation(
            _st,
            broadcaster,
            workspace,
            path,
            service.execute(command, base_version=body.base_version),
        )

    @app.post(
        "/api/class-parent/remove",
        summary="Remove a superclass link (rdfs:subClassOf) between two classes",
        tags=[_TAG_MUTATE],
    )
    def remove_class_parent(
        body: ClassParentRemoveIn,
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .core.commands.owl import OwlRemoveSuperclass

        service, workspace, path = _require_mutation_backend(_st)
        _require_editable(_st[_LIT_TAXONOMY], body.child_uri)
        command = OwlRemoveSuperclass(path, body.child_uri, body.parent_uri)
        return _execute_mutation(
            _st,
            broadcaster,
            workspace,
            path,
            service.execute(command, base_version=body.base_version),
        )


def _places_wanted(graph: rdflib.Graph, uris: list[str]) -> list[tuple[str, bool]]:
    """The requested URIs, plus every place containing one, flagged as context.

    The result decides the hierarchy. Rows come back as results; the places
    containing them come back as context, so a query for stores groups under
    exactly the cities and countries that hold one — and a city with no store
    never appears. A query for cities gets every city for the same reason.
    """
    from .geo_shapes import place_ancestors  # noqa: PLC0415

    wanted: list[tuple[str, bool]] = [(uri, True) for uri in uris]
    seen = set(uris)
    for uri in uris:
        for ancestor in place_ancestors(graph, rdflib.URIRef(uri)):
            if ancestor not in seen:
                seen.add(ancestor)
                wanted.append((ancestor, False))
    return wanted


def _place_record(graph: rdflib.Graph, uri: str, is_result: bool) -> dict[str, Any] | None:
    """One place as the map wants it, positioned or not.

    A place with no geometry is kept rather than dropped. An ontology may hold
    entities it deliberately will not plot — a store outside the mapped area, a
    grouping tier with no shape of its own — and dropping them took them out of
    the *totals* as well as the map, so a country's count silently excluded the
    ones it could not draw. That makes the figure wrong rather than partial.

    None is returned only for a URI that is not in the graph at all.
    """
    from .geo_results import label_of  # noqa: PLC0415
    from .geo_shapes import (  # noqa: PLC0415
        badges_of,
        facets_of,
        geometry_of,
        image_of,
        numeric_literals,
        place_ancestors,
        place_level,
        place_parent,
        place_type,
    )

    node = rdflib.URIRef(uri)
    if (node, None, None) not in graph:
        return None
    geometry = geometry_of(graph, node)
    latitude, longitude = geometry.centroid if geometry else (None, None)
    return {
        "uri": uri,
        # False when the place is real but has nowhere to be drawn. The client
        # counts it and skips it when plotting.
        "mapped": geometry is not None,
        "label": label_of(graph, node),
        "lat": latitude,
        "long": longitude,
        # A bare point is already carried by lat/long.
        "shape": None if (geometry is None or geometry.kind == "Point") else geometry.geojson,
        # Depth in the class hierarchy, and the containing place: together these
        # let the map draw one level at a time and descend, without knowing what
        # the levels are called.
        "level": place_level(graph, node),
        "parent": place_parent(graph, node),
        "kind": place_type(graph, node),
        "ancestors": place_ancestors(graph, node),
        # False for a place pulled in only to group the results.
        "result": is_result,
        # Numeric properties, so the panel can total a branch.
        "figures": numeric_literals(graph, node),
        # What this place *is*, as opposed to where: the filter menu reads these,
        # and which exist is a property of the ontology rather than of ster.
        "facets": facets_of(graph, node),
        # Who operates here: entities pointing at this place that carry a logo.
        # Drawn on the shape, so only a place with geometry can use them.
        "badges": badges_of(graph, uri) if geometry is not None else [],
        # A picture of this place itself. When the ontology gives one, the map
        # draws it instead of a dot — what a thing looks like is the ontology's
        # to say, not ster's.
        "icon": image_of(graph, node),
    }


_LAYOUT_ROUTE: Final = "/api/layout"


def _register_layout(app: FastAPI, _st: dict[str, Any], _tax: Any, _check_auth: Any) -> None:
    """The graph page reads and saves node positions (see ster.graph_layout).

    Kept in the project rather than the browser: browser storage is per port,
    and ster serves the graph on a new port each launch.
    """

    def _layout_source() -> Path | None:
        return _st[_LIT_FILE_PATH]  # type: ignore[no-any-return]

    @app.get(
        _LAYOUT_ROUTE,
        summary="Where the graph's nodes were left, as remembered in the project",
        tags=[_TAG_VIZ],
    )
    def get_layout(_: None = Depends(_check_auth)) -> dict[str, dict[str, list[int]]]:
        from . import graph_layout  # noqa: PLC0415

        source = _layout_source()
        if source is None:
            return {"positions": {}}
        stored = graph_layout.load_positions(source, graph_layout.ONTOLOGY_VIEW, _tax())
        return {"positions": {uri: [x, y] for uri, (x, y) in stored.items()}}

    @app.put(
        _LAYOUT_ROUTE,
        summary="Remember node positions; merged with what is stored",
        tags=[_TAG_VIZ],
    )
    def put_layout(body: LayoutIn, _: None = Depends(_check_auth)) -> dict[str, int]:
        from . import graph_layout  # noqa: PLC0415

        source = _layout_source()
        if source is None:
            raise HTTPException(status_code=409, detail="No file to remember a layout for")
        graph_layout.save_positions(source, graph_layout.ONTOLOGY_VIEW, body.positions, _tax())
        return {"saved": len(body.positions)}

    @app.delete(
        _LAYOUT_ROUTE,
        summary="Forget the remembered positions (Reset layout)",
        tags=[_TAG_VIZ],
    )
    def delete_layout(_: None = Depends(_check_auth)) -> dict[str, bool]:
        from . import graph_layout  # noqa: PLC0415

        source = _layout_source()
        if source is not None:
            graph_layout.forget_positions(source, graph_layout.ONTOLOGY_VIEW)
        return {"cleared": True}


def _register_locate(app: FastAPI, _tax: Any, _check_auth: Any) -> None:
    """Place result rows on the earth — the map's half of geo_shapes."""

    @app.post(
        "/api/locate",
        summary="Resolve entity URIs to points and geometries",
        tags=[_TAG_VIZ],
    )
    def locate_uris(body: LocateIn, _: None = Depends(_check_auth)) -> dict[str, Any]:
        """Points and shapes for *uris*, skipping any that carry no geography.

        Resolved here rather than in the page's JavaScript so there is one
        implementation of the geometry ladder and of WKT parsing. The map used to
        query for wgs:lat/long itself, which reported every polygon as unmappable.
        """
        from .geo_shapes import facet_catalogue, map_layers  # noqa: PLC0415
        from .named_rows import placed_named  # noqa: PLC0415

        graph = _graph_for_locate(_tax())
        records = (
            _place_record(graph, uri, is_result)
            for uri, is_result in _places_wanted(graph, body.uris)
        )
        # Layers and the facet catalogue travel with the places, so neither the
        # layer menu nor the filter menu needs a second request.
        placed = [record for record in records if record is not None]
        return {
            "places": placed,
            "layers": map_layers(graph),
            "facets": facet_catalogue(graph, [p["uri"] for p in placed]),
            # Entities that rows name by label alone and that could be drawn: the page offers a map for them.
            "named": placed_named(graph, body.labels),
        }


def _lanes_of(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The lanes the items occupy, with their counts, for the filter row.

    Computed from the items rather than from the ontology's class list: a lane
    nothing falls into is a checkbox that does nothing, and the reader has no
    way of telling it from one whose items are hidden.
    """
    counts: dict[str, dict[str, Any]] = {}
    for item in items:
        lane = counts.setdefault(
            str(item["group"]),
            {"uri": item["group"], _LIT_LANE_LABEL: item["groupLabel"], _LIT_LANE_COUNT: 0},
        )
        lane[_LIT_LANE_COUNT] = int(lane[_LIT_LANE_COUNT]) + 1
    return sorted(counts.values(), key=lambda lane: str(lane[_LIT_LANE_LABEL]))


def _register_timeline(app: FastAPI, _tax: Any, _check_auth: Any) -> None:
    """Moments for a set of URIs — the timeline's counterpart to /api/locate."""

    @app.post(
        "/api/timeline",
        summary="Resolve entity URIs to instants and intervals",
        tags=[_TAG_VIZ],
    )
    def timeline_uris(body: TimelineIn, _: None = Depends(_check_auth)) -> dict[str, Any]:
        """Instants and spans for *uris*, skipping any that carry no time.

        Resolved here rather than in the page's JavaScript so there is one
        implementation of the datatype rule and of the declared interval pairs —
        the same reason /api/locate parses WKT on the server.
        """
        from .named_rows import dated_named  # noqa: PLC0415
        from .time_shapes import span_of, timeline_items  # noqa: PLC0415

        graph = _graph_for_locate(_tax())
        items = timeline_items(graph, body.uris, body.after, body.before)
        return {
            "items": items,
            "lanes": _lanes_of(items),
            "span": span_of(items),
            # Entities that rows name by label alone and that carry a date: the page offers a timeline for them.
            "named": dated_named(graph, body.labels, body.after, body.before),
        }


def _register_trace_answers(app: FastAPI, _check_auth: Any) -> None:
    """Where an agent runner reports the answer and the resume id the traces cannot see.

    Both need tracing on: the answers live in the trace folder and join its runs.
    """

    def _directory() -> Path:
        from .query_trace import get_recorder  # noqa: PLC0415

        directory = getattr(get_recorder(), "directory", None)
        if directory is None:
            raise HTTPException(status_code=409, detail="Query tracing is off.")
        return Path(directory)

    @app.post(  # noqa: V103
        "/api/query_trace/answers/{answer_id}",
        summary="Record the answer an agent gave, with the session it can be resumed with",
        tags=[_TAG_VIZ],
        status_code=201,
    )
    def put_trace_answer(
        answer_id: str, body: dict[str, Any], _: None = Depends(_check_auth)
    ) -> dict[str, str]:
        from .query_trace.answers import record_answer  # noqa: PLC0415

        directory = _directory()
        try:
            record_answer(directory, answer_id, body)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"id": answer_id}

    @app.get(  # noqa: V103
        "/api/query_trace/answers",
        summary="The recorded agent answers, oldest first",
        tags=[_TAG_VIZ],
    )
    def list_trace_answers(_: None = Depends(_check_auth)) -> list[dict[str, Any]]:
        from .query_trace.answers import read_answers  # noqa: PLC0415

        return read_answers(_directory())


def _register_events(app: FastAPI, token: str, broadcaster: SSEBroadcaster) -> None:
    """The SSE stream that drives live graph refresh."""

    @app.get(
        "/api/events",
        summary="SSE stream — fires 'updated' whenever the ontology changes",
        tags=[_TAG_VIZ],
    )
    async def sse_events(
        token_param: str = Query(..., alias="token"),
    ) -> StreamingResponse:
        if token_param != token:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return StreamingResponse(broadcaster.subscribe(), media_type="text/event-stream")


def _caller_is_local(request: Request) -> bool:
    """True when the request came from this machine (any loopback address).

    Decides whether ``open_view`` may open a browser: a window opened for a
    caller elsewhere on the network would appear on a screen nobody asking sees.
    """
    import ipaddress  # noqa: PLC0415

    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _in_process_api(app: FastAPI, token: str, base_url: str) -> Callable[..., Any]:
    """A ``POST`` to this server's own HTTP API, for MCP tools that must use it.

    Goes through the whole ASGI stack — middleware, authentication with the
    server's own token, validation, the route — without a network hop. Called
    from the worker thread ``/mcp`` runs on, it hands the request back to the
    event loop, which is free to serve it because ``/mcp`` is not holding it.
    """
    import anyio.from_thread  # noqa: PLC0415
    import httpx  # noqa: PLC0415

    async def _post(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            response = await client.post(
                path, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text}
        return response.status_code, body if isinstance(body, dict) else {"detail": body}

    def post(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return anyio.from_thread.run(_post, path, payload)

    return post


def _register_mcp(
    app: FastAPI, _st: dict[str, Any], _tax: Any, _check_auth: Any, token: str
) -> None:
    """The read-only MCP endpoint (see :mod:`ster.mcp_server`)."""

    @app.post(
        "/mcp",
        summary="MCP (Model Context Protocol) endpoint — read-only ontology context",
        tags=["MCP"],
    )
    async def mcp_endpoint(request: Request, _: None = Depends(_check_auth)) -> Response:
        """JSON-RPC 2.0 over HTTP, so any MCP-capable agent CLI can query the graph.

        The protocol logic lives in :mod:`ster.mcp_server`; this route only does
        auth, JSON decoding and the notification/response distinction.
        """
        from .mcp_server import (  # noqa: PLC0415
            PARSE_ERROR,
            CallContext,
            handle_message,
            origin_allowed,
        )

        # MCP spec: servers MUST validate Origin, or a page the user visits could
        # script requests against their local ster server (DNS rebinding).
        if not origin_allowed(request.headers.get("origin")):
            raise HTTPException(status_code=403, detail="Origin not allowed")

        try:
            message = await request.json()
        # A malformed body is a JSON-RPC protocol error, not a server fault: answer
        # with -32700 rather than letting it become a 500.
        except Exception:  # noqa: BLE001
            return _json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": PARSE_ERROR, "message": "Parse error."},
                }
            )
        from fastapi.concurrency import run_in_threadpool  # noqa: PLC0415

        from . import mcp_views  # noqa: PLC0415

        base_url = str(request.base_url)
        # On a worker thread, not the event loop: open_view calls back into this
        # server's own API, which the loop must be free to answer. The other
        # tools gain too — a slow query no longer stalls every other request.
        reply = await run_in_threadpool(
            handle_message,
            message,
            _tax(),
            call=CallContext(
                base_url=base_url,
                api_post=_in_process_api(app, token, base_url),
                open_browser=mcp_views.open_in_browser if _caller_is_local(request) else None,
                user_agent=request.headers.get("user-agent"),
            ),
        )
        if reply is None:  # a notification takes no response body
            return Response(status_code=202)
        return _json_response(reply)


def _json_response(payload: dict) -> Response:
    """A JSON body without FastAPI's response-model machinery (payloads are dynamic)."""
    import json as _json

    return Response(content=_json.dumps(payload), media_type="application/json")


# ── Domain helpers ────────────────────────────────────────────────────────────


def _individual_out(uri: str, ind: OWLIndividual) -> IndividualOut:
    """The wire shape of one individual."""
    return IndividualOut(
        uri=uri,
        class_uri=ind.types[0] if ind.types else None,
        labels=[LabelIn(lang=lb.lang, value=lb.value) for lb in ind.labels],
        property_values=[
            PropertyAssertionOut(property_uri=pv[0], target_uri=pv[1]) for pv in ind.property_values
        ],
    )


def _individuals_out(tax: Taxonomy, type_uri: str | None) -> list[IndividualOut]:
    """Every individual, or only those carrying *type_uri* as an rdf:type."""
    return [
        _individual_out(uri, ind)
        for uri, ind in tax.owl_individuals.items()
        if type_uri is None or type_uri in ind.types
    ]


def _add_individual(tax: Taxonomy, body: IndividualIn) -> str:
    """Create the individual described by *body* and return its new URI."""
    if body.class_uri not in tax.owl_classes:
        raise HTTPException(status_code=422, detail=f"Unknown class URI: {body.class_uri}")
    hint = body.local_name or (_slugify(body.labels[0].value) if body.labels else _INDIVIDUAL)
    new_uri = _unique_uri(tax, _namespace(tax), hint)
    tax.owl_individuals[new_uri] = OWLIndividual(
        uri=new_uri,
        labels=[Label(lang=lb.lang, value=lb.value, type=LabelType.PREF) for lb in body.labels],
        types=[body.class_uri],
        property_values=[(pv.property_uri, pv.target_uri) for pv in body.property_values],
        schema_urls=list(body.schema_urls),
        schema_images=list(body.schema_images),
    )
    return new_uri


def _class_out(tax: Taxonomy, uri: str) -> ClassOut:
    cls = tax.owl_classes[uri]
    children = [u for u, c in tax.owl_classes.items() if uri in c.sub_class_of]
    props: list[PropertySummary] = []
    for prop in tax.owl_properties.values():
        if prop.prop_type != "ObjectProperty":
            continue
        if not prop.domains or any(d == uri or _is_ancestor(tax, uri, d) for d in prop.domains):
            range_uri = prop.ranges[0] if prop.ranges else None
            range_label: str | None = None
            if range_uri and range_uri in tax.owl_classes:
                range_label = tax.owl_classes[range_uri].label()
            props.append(
                PropertySummary(
                    uri=prop.uri,
                    label=prop.label(),
                    range_uri=range_uri,
                    range_label=range_label,
                )
            )
    return ClassOut(
        uri=uri,
        labels={lb.lang: lb.value for lb in cls.labels},
        comment={d.lang: d.value for d in cls.comments},
        sub_class_of=list(cls.sub_class_of),
        child_classes=children,
        applicable_properties=props,
    )


def _is_ancestor(tax: Taxonomy, child_uri: str, candidate_ancestor: str) -> bool:
    """Return True if candidate_ancestor is an ancestor of child_uri."""
    visited: set[str] = set()
    queue: list[str] = list(
        tax.owl_classes[child_uri].sub_class_of if child_uri in tax.owl_classes else []
    )
    while queue:
        current = queue.pop()
        if current == candidate_ancestor:
            return True
        if current not in visited:
            visited.add(current)
            cls = tax.owl_classes.get(current)
            if cls:
                queue.extend(cls.sub_class_of)
    return False


def _namespace(tax: Taxonomy) -> str:
    """Derive the best namespace to use for newly created individuals."""
    if "" in tax.namespace_bindings:
        return tax.namespace_bindings[""]
    if tax.ontology_uri:
        return tax.ontology_uri.rstrip("/#") + "#"
    for u in tax.owl_classes:
        for sep in ("#", "/"):
            if sep in u:
                return u.rsplit(sep, 1)[0] + sep
    return "https://example.org/onto#"


def _slugify(text: str) -> str:
    """Convert free text to a URI-safe local name."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_")
    return slug or _INDIVIDUAL


def _unique_uri(tax: Taxonomy, namespace: str, local: str) -> str:
    """Return namespace+local, appending _N to avoid collisions."""
    candidate = namespace + local
    if candidate not in tax.owl_individuals:
        return candidate
    i = 1
    while f"{namespace}{local}_{i}" in tax.owl_individuals:
        i += 1
    return f"{namespace}{local}_{i}"


def _derive_slug(file_path: Path | None) -> str:
    """Return a URL-safe slug derived from the ontology file stem."""
    if file_path is None:
        return "onto"
    slug = re.sub(r"[^a-z0-9]+", "-", file_path.stem.lower()).strip("-")
    return slug or "onto"


def _graph_for_locate(taxonomy: Taxonomy) -> Any:
    """The whole session as one graph, for geometry lookups.

    This used to re-parse the source files, because a rebuilt model dropped
    wgs:lat/long and every GeoSPARQL triple and a map fed from it found nothing
    to place. Residue and literal_values fixed that: the model now carries the
    arbitrary predicates it once lost, and ``full_graph_rdflib`` reproduces 22,543 of
    the retail ontology's 22,546 triples — the three it does not are a second
    file's ``owl:Ontology`` header, which no map draws.

    Reading the model rather than the disk means the map shows the session the
    user is in, not the last thing written, and it sees the statements a context
    file makes about entities the editable file defines. Those are merged into
    the model and are not recoverable by parsing either file alone.
    """
    from .store import full_graph_rdflib  # noqa: PLC0415

    return full_graph_rdflib(taxonomy)


def _serve_turtle(taxonomy: Taxonomy) -> Response:
    from .store import taxonomy_to_graph

    g = taxonomy_to_graph(taxonomy)
    ttl: str = g.serialize(format="turtle")
    return Response(ttl, media_type="text/turtle; charset=utf-8")


def _serve_pylode(file_path: Path | None) -> Response:
    if file_path is None:
        raise HTTPException(status_code=503, detail="No ontology file path configured")

    from .html_export import render_html

    try:
        html = render_html(file_path)
    except RuntimeError:
        raise HTTPException(
            status_code=501,
            detail="pyLODE is not installed. Run: pip install 'ster[html]'",
        )

    return HTMLResponse(html)
