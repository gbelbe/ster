"""FastAPI application for the ster ontology REST API.

Provides schema introspection, individual creation, VOWL graph retrieval,
and a Server-Sent Events stream for live graph refresh.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .handles import assign_handles
from .model import Label, LabelType, OWLIndividual, Taxonomy

# ── Pydantic I/O models ───────────────────────────────────────────────────────


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
    child_classes: list[str]
    applicable_properties: list[PropertySummary]


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
            asyncio.run_coroutine_threadsafe(self._broadcast(), target)
        except RuntimeError:
            return  # loop closed between the check and the call

    async def _broadcast(self) -> None:
        for q in list(self._queues):
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


# Starter query for GET /map when none is supplied: anything with WGS84
# coordinates, in any vocabulary.
_DEFAULT_MAP_QUERY = """\
PREFIX wgs: <http://www.w3.org/2003/01/geo/wgs84_pos#>

SELECT ?thing ?lat ?long
WHERE { ?thing wgs:lat ?lat ; wgs:long ?long }
LIMIT 200
"""


def create_app(
    taxonomy: Taxonomy,
    token: str,
    broadcaster: SSEBroadcaster,
    save_fn: Any,  # Callable[[Taxonomy], None] — Any avoids heavy typing import
    *,
    html_fn: Any = None,  # Callable[[], str] — returns rendered HTML for GET /
    file_path: Path | None = None,
    publish_dir: Path | None = None,
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
    _st: dict[str, Any] = {"taxonomy": taxonomy, "file_path": file_path, "html_fn": html_fn}
    _bearer = HTTPBearer(auto_error=False)

    def _tax() -> Taxonomy:
        return _st["taxonomy"]  # type: ignore[return-value]

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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost", "http://127.0.0.1"],
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
    _register_events(app, token, broadcaster)
    _register_mcp(app, _st, _tax, _check_auth)

    return app


# ── Route groups ──────────────────────────────────────────────────────────────
# create_app used to define every endpoint inline, which made it a 260-line
# function. Each group is now registered by its own function: the handlers are
# unchanged, but each concern can be read on its own and create_app is a short
# assembly step. They take the shared state explicitly rather than closing over
# it, so what each group touches is visible in its signature.


def _register_pages(app: FastAPI, _st: dict[str, Any], token: str) -> None:
    """HTML landing pages and the raw-ontology endpoint (no auth: read-only views)."""

    def _graph_html_response(root_uri: str | None) -> HTMLResponse:
        # no-store: the page inlines its JS, so caching it served stale builds
        # until a manual hard-reload.
        render = _st.get("html_fn")
        if render is None:
            raise HTTPException(status_code=501, detail="No HTML renderer configured")
        return HTMLResponse(
            render(root_uri),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def root(
        root_uri: str | None = Query(default=None, alias="root"),
    ) -> HTMLResponse:
        return _graph_html_response(root_uri)

    @app.get("/viz", response_class=HTMLResponse, include_in_schema=False)
    def viz(
        root_uri: str | None = Query(default=None, alias="root"),
    ) -> HTMLResponse:
        return _graph_html_response(root_uri)

    @app.get("/map", response_class=HTMLResponse, include_in_schema=False)
    def map_page(sparql: str = Query(default="", alias="q")) -> HTMLResponse:
        """A live map of a SPARQL result — see :mod:`ster.geo_map_html`.

        Open like ``/viz``: the page itself needs no token, and embeds one so its
        own ``/mcp`` calls authenticate. Keeping the token out of the URL means it
        does not land in browser history.
        """
        from .geo_map_html import render_map_html  # noqa: PLC0415

        return HTMLResponse(render_map_html(sparql or _DEFAULT_MAP_QUERY, token))

    @app.get("/onto", response_class=Response, include_in_schema=False)
    def serve_ontology(request: Request) -> Response:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return _serve_pylode(_st["file_path"])
        return _serve_turtle(_st["taxonomy"])


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
        await broadcaster._broadcast()
        return _individual_out(new_uri, tax.owl_individuals[new_uri])


def _register_graph_routes(app: FastAPI, _tax: Any, _check_auth: Any) -> None:
    """VOWL graph payloads and relation lookups."""

    @app.get(
        "/api/graph",
        summary="Return the full VOWL graph payload",
        tags=["Visualisation"],
    )
    def get_graph(_: None = Depends(_check_auth)) -> dict[str, Any]:
        from .viz_vowl import build_vowl_graph, strip_detail

        # Detail is fetched per node from /api/node-detail; sending it here would
        # put the whole side-panel corpus on every live-refresh tick.
        return strip_detail(build_vowl_graph(_tax()))  # type: ignore[return-value]

    @app.get(
        "/api/node-detail",
        summary="Return the side-panel detail for a single node",
        tags=["Visualisation"],
    )
    def get_node_detail(
        uri: str = Query(description="URI of the entity to describe"),
        _: None = Depends(_check_auth),
    ) -> dict[str, Any]:
        from .viz_vowl import node_detail

        return node_detail(_tax(), uri)  # type: ignore[return-value]

    @app.get(
        "/api/individual-relations",
        summary="Return the object-property relations subgraph for an individual",
        tags=["Visualisation"],
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
        tags=["Visualisation"],
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
        tags=["Visualisation"],
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


def _register_events(app: FastAPI, token: str, broadcaster: SSEBroadcaster) -> None:
    """The SSE stream that drives live graph refresh."""

    @app.get(
        "/api/events",
        summary="SSE stream — fires 'updated' whenever the ontology changes",
        tags=["Visualisation"],
    )
    async def sse_events(
        token_param: str = Query(..., alias="token"),
    ) -> StreamingResponse:
        if token_param != token:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return StreamingResponse(broadcaster.subscribe(), media_type="text/event-stream")


def _register_mcp(app: FastAPI, _st: dict[str, Any], _tax: Any, _check_auth: Any) -> None:
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
        from .mcp_server import PARSE_ERROR, handle_message, origin_allowed  # noqa: PLC0415

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
        reply = handle_message(message, _tax(), _st.get("selection"))
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
    hint = body.local_name or (_slugify(body.labels[0].value) if body.labels else "individual")
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
    return slug or "individual"


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
