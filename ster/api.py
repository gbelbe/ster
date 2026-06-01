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
        """Schedule an 'updated' event to all connected listeners."""
        target = loop
        if target is None:
            try:
                target = asyncio.get_running_loop()
            except RuntimeError:
                return
        asyncio.run_coroutine_threadsafe(self._broadcast(), target)

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
    _st: dict[str, Any] = {"taxonomy": taxonomy, "file_path": file_path}
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

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def root(
        root_uri: str | None = Query(default=None, alias="root"),
    ) -> HTMLResponse:
        if html_fn is None:
            raise HTTPException(status_code=501, detail="No HTML renderer configured")
        return HTMLResponse(html_fn(root_uri))

    @app.get("/viz", response_class=HTMLResponse, include_in_schema=False)
    def viz(
        root_uri: str | None = Query(default=None, alias="root"),
    ) -> HTMLResponse:
        if html_fn is None:
            raise HTTPException(status_code=501, detail="No HTML renderer configured")
        return HTMLResponse(html_fn(root_uri))

    @app.get("/onto", response_class=Response, include_in_schema=False)
    def serve_ontology(request: Request) -> Response:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return _serve_pylode(_st["file_path"])
        return _serve_turtle(_st["taxonomy"])

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
        tax = _tax()
        result: list[IndividualOut] = []
        for u, ind in tax.owl_individuals.items():
            if type is not None and type not in ind.types:
                continue
            result.append(
                IndividualOut(
                    uri=u,
                    class_uri=ind.types[0] if ind.types else None,
                    labels=[LabelIn(lang=lb.lang, value=lb.value) for lb in ind.labels],
                    property_values=[
                        PropertyAssertionOut(property_uri=pv[0], target_uri=pv[1])
                        for pv in ind.property_values
                    ],
                )
            )
        return {"individuals": result}

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
        if body.class_uri not in tax.owl_classes:
            raise HTTPException(status_code=422, detail=f"Unknown class URI: {body.class_uri}")
        hint = body.local_name or (_slugify(body.labels[0].value) if body.labels else "individual")
        ns = _namespace(tax)
        new_uri = _unique_uri(tax, ns, hint)
        ind = OWLIndividual(
            uri=new_uri,
            labels=[Label(lang=lb.lang, value=lb.value, type=LabelType.PREF) for lb in body.labels],
            types=[body.class_uri],
            property_values=[(pv.property_uri, pv.target_uri) for pv in body.property_values],
            schema_urls=list(body.schema_urls),
            schema_images=list(body.schema_images),
        )
        tax.owl_individuals[new_uri] = ind
        assign_handles(tax)
        save_fn(tax)
        await broadcaster._broadcast()
        return IndividualOut(
            uri=new_uri,
            class_uri=body.class_uri,
            labels=list(body.labels),
            property_values=[
                PropertyAssertionOut(property_uri=pv.property_uri, target_uri=pv.target_uri)
                for pv in body.property_values
            ],
        )

    @app.get(
        "/api/graph",
        summary="Return the full VOWL graph payload",
        tags=["Visualisation"],
    )
    def get_graph(_: None = Depends(_check_auth)) -> dict[str, Any]:
        from .viz_vowl import build_vowl_graph

        return build_vowl_graph(_tax())  # type: ignore[return-value]

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

    return app


# ── Domain helpers ────────────────────────────────────────────────────────────


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
    try:
        from .html_export import _patch_missing_pyproject, detect_profile

        with _patch_missing_pyproject():
            from pylode import OntPub, VocPub  # type: ignore[import]
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="pyLODE is not installed. Run: pip install 'ster[html]'",
        )

    import logging

    _root_level = logging.root.level
    logging.root.setLevel(logging.WARNING)
    try:
        profile = detect_profile(file_path)
        if profile in ("ontpub", "both"):
            vp: Any = OntPub(ontology=str(file_path.resolve()))
        else:
            vp = VocPub(ontology=str(file_path.resolve()))
        html: str = vp.make_html()
    finally:
        logging.root.setLevel(_root_level)

    return HTMLResponse(html)
