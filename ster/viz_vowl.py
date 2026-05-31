"""VOWL-style ontology visualisation — self-contained Cytoscape.js HTML file.

Implements Visual Notation for OWL Ontologies (VOWL) conventions rendered with
Cytoscape.js (https://js.cytoscape.org):
  - All classes rendered as circles; root classes carry a bold outer ring
  - Object-property edges carry an inline label box at the midpoint
  - subClassOf uses a hollow arrowhead (UML inheritance convention)
  - Individuals are pre-positioned tangentially around their class
  - OWL-only taxonomies use a pre-computed radial/concentric layout (no simulation)
  - Mixed SKOS/OWL taxonomies fall back to the Cytoscape CoSE force layout

To upgrade Cytoscape.js: bump ``_CY_VERSION`` below, then delete
``~/.cache/ster/cytoscape.min.js`` so it is re-downloaded on next launch.
The stylesheet API has been stable across all Cytoscape 3.x releases.

Public API
----------
open_in_browser()       Open the full graph in the browser (live-refresh via SSE
                        when the ster[api] extra is installed, static file otherwise).
open_focused_in_browser()  Open a subgraph centred on a single OWL class.
push_update()           Push a refreshed taxonomy to all connected viewers.
render_vowl_html()      Return the rendered HTML string (used by the FastAPI server).
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import json
import re
import socket
import threading
import urllib.parse
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path
from typing import Any

from .model import Taxonomy, is_builtin_uri
from .viz import (
    _detail_class,
    _detail_concept,
    _detail_individual,
    _detail_scheme,
    _label_for,  # noqa: F401  (re-exported for potential callers)
    _local,
    _ontology_title,
    _taxonomy_meta,
)

# ── Data builder ──────────────────────────────────────────────────────────────


def build_vowl_graph(taxonomy: Taxonomy) -> dict:
    """Serialise *taxonomy* into a Cytoscape.js-compatible {nodes, edges, layout} payload."""
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    _ec = 0

    def _eid() -> str:
        nonlocal _ec
        eid = f"e{_ec}"
        _ec += 1
        return eid

    def add_node(uri: str, label: str, node_type: str, detail: dict | None = None) -> None:
        if uri not in seen_nodes:
            seen_nodes.add(uri)
            nodes.append(
                {
                    "id": uri,
                    "label": label,
                    "type": node_type,
                    "detail": detail or {},
                    "rootClass": 0,
                }
            )

    # OWL classes
    for uri, cls in taxonomy.owl_classes.items():
        add_node(uri, cls.label("en"), "class", _detail_class(cls, taxonomy))

    # OWL individuals
    for uri, ind in taxonomy.owl_individuals.items():
        add_node(uri, ind.label("en"), "individual", _detail_individual(ind, taxonomy))

    # subClassOf
    for uri, cls in taxonomy.owl_classes.items():
        for parent in cls.sub_class_of:
            if not is_builtin_uri(parent) and parent in seen_nodes:
                edges.append(
                    {
                        "id": _eid(),
                        "source": uri,
                        "target": parent,
                        "type": "subClassOf",
                        "label": "",
                    }
                )

    # ObjectProperty T-Box edges
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != "ObjectProperty":
            continue
        plabel = prop.label("en")
        for domain_uri in prop.domains:
            for range_uri in prop.ranges:
                if domain_uri in seen_nodes and range_uri in seen_nodes:
                    e: dict = {
                        "id": _eid(),
                        "source": domain_uri,
                        "target": range_uri,
                        "type": "objectProperty",
                        "label": plabel,
                    }
                    if prop.is_functional:
                        e["cardinality"] = "0..1"
                    edges.append(e)

    # DatatypeProperty T-Box edges
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != "DatatypeProperty":
            continue
        plabel = prop.label("en")
        for domain_uri in prop.domains:
            if domain_uri not in seen_nodes:
                continue
            for range_uri in prop.ranges:
                if range_uri in seen_nodes:
                    continue
                add_node(range_uri, _local(range_uri), "datatype")
                edges.append(
                    {
                        "id": _eid(),
                        "source": domain_uri,
                        "target": range_uri,
                        "type": "datatypeProperty",
                        "label": plabel,
                    }
                )

    # rdf:type (individual → class)
    for uri, ind in taxonomy.owl_individuals.items():
        for type_uri in ind.types:
            if is_builtin_uri(type_uri):
                continue
            if type_uri not in seen_nodes:
                add_node(type_uri, _local(type_uri), "class", {})
            edges.append(
                {"id": _eid(), "source": uri, "target": type_uri, "type": "instanceOf", "label": ""}
            )

    # SKOS ConceptSchemes
    for uri, scheme in taxonomy.schemes.items():
        add_node(uri, scheme.title("en"), "scheme", _detail_scheme(scheme, taxonomy))

    # SKOS Concepts
    top_concept_uris: set[str] = {u for u, c in taxonomy.concepts.items() if c.top_concept_of}
    for uri, concept in taxonomy.concepts.items():
        ntype = "topconcept" if uri in top_concept_uris else "concept"
        add_node(uri, concept.pref_label("en"), ntype, _detail_concept(concept, taxonomy))

    # SKOS broader / inScheme
    for uri, concept in taxonomy.concepts.items():
        for broader_uri in concept.broader:
            if broader_uri in seen_nodes and uri in seen_nodes:
                edges.append(
                    {
                        "id": _eid(),
                        "source": uri,
                        "target": broader_uri,
                        "type": "broader",
                        "label": "",
                    }
                )
        if concept.top_concept_of and concept.top_concept_of in seen_nodes:
            edges.append(
                {
                    "id": _eid(),
                    "source": uri,
                    "target": concept.top_concept_of,
                    "type": "inScheme",
                    "label": "",
                }
            )

    layout = "cose"

    non_root = {
        cls_uri
        for cls_uri, cls in taxonomy.owl_classes.items()
        for p in cls.sub_class_of
        if not is_builtin_uri(p) and p in taxonomy.owl_classes
    }
    for n in nodes:
        if n["type"] == "class":
            n["rootClass"] = 0 if n["id"] in non_root else 1

    return {"nodes": nodes, "edges": edges, "layout": layout}


def build_focused_vowl_graph(taxonomy: Taxonomy, root_uri: str) -> dict:
    """Serialise a focused subgraph rooted at *root_uri* into Cytoscape payload.

    Collects the root class, all transitive subclasses, and individuals of those
    classes.  Property edges between included nodes are also included.
    """
    if root_uri not in taxonomy.owl_classes:
        return {"nodes": [], "edges": [], "layout": "preset"}

    children_of: dict[str, list[str]] = {u: [] for u in taxonomy.owl_classes}
    for uri, cls in taxonomy.owl_classes.items():
        for parent in cls.sub_class_of:
            if parent in children_of:
                children_of[parent].append(uri)

    included_classes: set[str] = set()
    queue: deque[str] = deque([root_uri])
    while queue:
        uri = queue.popleft()
        if uri in included_classes:
            continue
        included_classes.add(uri)
        queue.extend(children_of.get(uri, []))

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    _ec = 0

    def _eid() -> str:
        nonlocal _ec
        eid = f"e{_ec}"
        _ec += 1
        return eid

    def add_node(uri: str, label: str, node_type: str, detail: dict | None = None) -> None:
        if uri not in seen_nodes:
            seen_nodes.add(uri)
            nodes.append(
                {
                    "id": uri,
                    "label": label,
                    "type": node_type,
                    "detail": detail or {},
                    "rootClass": 0,
                }
            )

    for cls_uri in included_classes:
        cls = taxonomy.owl_classes[cls_uri]
        add_node(cls_uri, cls.label("en"), "class", _detail_class(cls, taxonomy))

    for cls_uri in included_classes:
        cls = taxonomy.owl_classes[cls_uri]
        for parent_uri in cls.sub_class_of:
            if parent_uri in included_classes:
                edges.append(
                    {
                        "id": _eid(),
                        "source": cls_uri,
                        "target": parent_uri,
                        "type": "subClassOf",
                        "label": "",
                    }
                )

    for prop in taxonomy.owl_properties.values():
        if prop.prop_type == "ObjectProperty":
            plabel = prop.label("en")
            for domain_uri in prop.domains:
                if domain_uri not in included_classes:
                    continue
                for range_uri in prop.ranges:
                    if range_uri not in seen_nodes:
                        continue
                    ef: dict = {
                        "id": _eid(),
                        "source": domain_uri,
                        "target": range_uri,
                        "type": "objectProperty",
                        "label": plabel,
                    }
                    if prop.is_functional:
                        ef["cardinality"] = "0..1"
                    edges.append(ef)
        elif prop.prop_type == "DatatypeProperty":
            plabel = prop.label("en")
            for domain_uri in prop.domains:
                if domain_uri not in included_classes:
                    continue
                for range_uri in prop.ranges:
                    if range_uri in seen_nodes:
                        continue
                    add_node(range_uri, _local(range_uri), "datatype")
                    edges.append(
                        {
                            "id": _eid(),
                            "source": domain_uri,
                            "target": range_uri,
                            "type": "datatypeProperty",
                            "label": plabel,
                        }
                    )

    for ind_uri, ind in taxonomy.owl_individuals.items():
        for type_uri in ind.types:
            if type_uri in included_classes:
                add_node(ind_uri, ind.label("en"), "individual", _detail_individual(ind, taxonomy))
                edges.append(
                    {
                        "id": _eid(),
                        "source": ind_uri,
                        "target": type_uri,
                        "type": "instanceOf",
                        "label": "",
                    }
                )
                break

    # Mark root classes within the focused set
    non_root_f = {
        u
        for u in included_classes
        if any(
            p in included_classes
            for p in taxonomy.owl_classes[u].sub_class_of
            if not is_builtin_uri(p)
        )
    }
    for n in nodes:
        if n["type"] == "class":
            n["rootClass"] = 0 if n["id"] in non_root_f else 1

    return {"nodes": nodes, "edges": edges, "layout": "cose"}


# ── SPARQL result subgraph ────────────────────────────────────────────────────


def build_query_result_graph(taxonomy: Taxonomy, uris: set[str]) -> dict:
    """Build a graph containing only the taxonomy nodes in *uris*.

    Edges are included only when both endpoints appear in *uris*.
    Always returns force layout.
    """
    nodes: list[dict] = []
    seen: set[str] = set()
    _ec = 0

    def _eid() -> str:
        nonlocal _ec
        eid = f"e{_ec}"
        _ec += 1
        return eid

    def _add(uri: str, label: str, node_type: str, detail: dict | None = None) -> None:
        if uri in uris and uri not in seen:
            seen.add(uri)
            nodes.append(
                {
                    "id": uri,
                    "label": label,
                    "type": node_type,
                    "detail": detail or {},
                    "rootClass": 0,
                }
            )

    for uri, cls in taxonomy.owl_classes.items():
        _add(uri, cls.label("en"), "class", _detail_class(cls, taxonomy))
    for uri, ind in taxonomy.owl_individuals.items():
        _add(uri, ind.label("en"), "individual", _detail_individual(ind, taxonomy))
    for uri, scheme in taxonomy.schemes.items():
        _add(uri, scheme.title("en"), "scheme", _detail_scheme(scheme, taxonomy))
    top_concept_uris = {u for u, c in taxonomy.concepts.items() if c.top_concept_of}
    for uri, concept in taxonomy.concepts.items():
        _add(
            uri,
            concept.pref_label("en"),
            "topconcept" if uri in top_concept_uris else "concept",
            _detail_concept(concept, taxonomy),
        )

    edges: list[dict] = []
    for uri, cls in taxonomy.owl_classes.items():
        if uri not in seen:
            continue
        for parent in cls.sub_class_of:
            if not is_builtin_uri(parent) and parent in seen:
                edges.append(
                    {
                        "id": _eid(),
                        "source": uri,
                        "target": parent,
                        "type": "subClassOf",
                        "label": "",
                    }
                )
    for uri, ind in taxonomy.owl_individuals.items():
        if uri not in seen:
            continue
        for type_uri in ind.types:
            if not is_builtin_uri(type_uri) and type_uri in seen:
                edges.append(
                    {
                        "id": _eid(),
                        "source": uri,
                        "target": type_uri,
                        "type": "instanceOf",
                        "label": "",
                    }
                )
    for uri, concept in taxonomy.concepts.items():
        if uri not in seen:
            continue
        for broader_uri in concept.broader:
            if broader_uri in seen:
                edges.append(
                    {
                        "id": _eid(),
                        "source": uri,
                        "target": broader_uri,
                        "type": "broader",
                        "label": "",
                    }
                )
        if concept.top_concept_of and concept.top_concept_of in seen:
            edges.append(
                {
                    "id": _eid(),
                    "source": uri,
                    "target": concept.top_concept_of,
                    "type": "inScheme",
                    "label": "",
                }
            )

    return {"nodes": nodes, "edges": edges, "layout": "cose"}


def _build_query_result_html(
    taxonomy: Taxonomy,
    uris: set[str],
    file_path: Path | None = None,
    full_graph_link: str = "",
) -> tuple[dict, str]:
    """Return (graph_dict, html_str) for a query result viz, or raise ValueError."""
    graph = build_query_result_graph(taxonomy, uris)
    if not graph["nodes"]:
        raise ValueError("No taxonomy nodes matched the query result URIs.")
    title = _ontology_title(taxonomy, file_path) + " — Query results"
    graph_json = json.dumps(graph, ensure_ascii=False)
    meta_json = json.dumps(_taxonomy_meta(taxonomy, file_path), ensure_ascii=False)
    show_all_btn = (
        f'<span style="color:#cbd5e1"> │ </span>'
        f'<button class="ftbtn active" onclick="window.location.href=\'{full_graph_link}\'">'
        f"Show all nodes</button>"
        if full_graph_link
        else ""
    )
    html = (
        _HTML_TEMPLATE.replace("__TITLE__", title)
        .replace('"__GRAPH_DATA__"', graph_json)
        .replace('"__TAXO_META__"', meta_json)
        .replace("__CY_SCRIPT__", _cytoscape_script_tag())
        .replace("__API_TOKEN__", "")
        .replace("__SHOW_ALL_BTN__", show_all_btn)
    )
    return graph, html


def open_query_result_in_browser(
    taxonomy: Taxonomy,
    uris: set[str],
    file_path: Path | None = None,
) -> tuple[str, Path]:
    """Open a VOWL graph of the SPARQL query result nodes in the browser.

    Only taxonomy nodes whose URI appears in *uris* are rendered.
    Raises ``ValueError`` when none of the URIs match any node.
    Returns ``(url, out_path)`` so callers can track the file for later refresh.
    """
    cache = Path.home() / ".cache" / "ster"
    cache.mkdir(parents=True, exist_ok=True)
    # Write the full ontology graph so the "Show all nodes" button has a target.
    full_path = _graph_path(file_path)
    _write_html(taxonomy, file_path, full_path)
    port = _ensure_server(cache)
    full_graph_link = f"/{full_path.name}"
    _graph, html = _build_query_result_html(taxonomy, uris, file_path, full_graph_link)
    stem = (file_path.stem if file_path else "query") + "_sparql_result"
    out = cache / f"{stem}_vowl.html"
    out.write_text(html, encoding="utf-8")
    url = f"http://127.0.0.1:{port}/{out.name}"
    webbrowser.open(url)
    return url, out


def refresh_query_result_in_browser(
    taxonomy: Taxonomy,
    uris: set[str],
    out: Path,
) -> None:
    """Rewrite an existing query-result viz file and bring the browser tab to front.

    Raises ``ValueError`` when none of the URIs match any taxonomy node.
    The *out* path must be the file previously returned by
    ``open_query_result_in_browser``.
    """
    stem_guess = out.name.replace("_sparql_result_vowl.html", "_vowl.html")
    full_candidate = out.parent / stem_guess
    full_graph_link = f"/{full_candidate.name}" if full_candidate.exists() else ""
    _graph, html = _build_query_result_html(taxonomy, uris, full_graph_link=full_graph_link)
    out.write_text(html, encoding="utf-8")
    port = _ensure_server(out.parent)
    url = f"http://127.0.0.1:{port}/{out.name}"
    webbrowser.open(url)


# ── JS dependency ─────────────────────────────────────────────────────────────
# To upgrade: bump _CY_VERSION, then delete ~/.cache/ster/cytoscape.min.js.

_CY_VERSION = "3.29.2"
_CY_CDN = f"https://cdnjs.cloudflare.com/ajax/libs/cytoscape/{_CY_VERSION}/cytoscape.min.js"
_CY_CACHE_FILE = "cytoscape.min.js"  # stored under ~/.cache/ster/


def _cytoscape_script_tag() -> str:
    """Return an inline <script> tag with Cytoscape.js, downloading once to ~/.cache/ster."""
    cache_dir = Path.home() / ".cache" / "ster"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cy_path = cache_dir / _CY_CACHE_FILE
    if not cy_path.exists():
        try:
            with urllib.request.urlopen(_CY_CDN, timeout=15) as resp:  # type: ignore[attr-defined]
                cy_path.write_bytes(resp.read())
        except Exception:
            return f'<script src="{_CY_CDN}"></script>'
    return f"<script>{cy_path.read_text()}</script>"


API_PORT: int = 8765

_out_path: Path | None = None
_file_path: Path | None = None

# One-per-process HTTP server that serves the ster cache directory.
_http_server: http.server.HTTPServer | None = None
_http_port: int | None = None

# FastAPI/SSE-based server — set when ster[api] is available.
_api_app: Any = None
_api_broadcaster: Any = None
_api_loop: Any = None
_api_running: bool = False


def _start_api_server(
    taxonomy: Taxonomy,
    file_path: Path | None,
    on_change_fn: Any = None,
) -> bool:
    """Start the FastAPI server in a daemon thread; return True on success."""
    global _api_app, _api_broadcaster, _api_loop, _api_running
    if _api_app is not None:
        _api_app.state._ster["taxonomy"] = taxonomy
        return True
    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:
        return False
    try:
        from .api import SSEBroadcaster, create_app  # noqa: PLC0415
    except ImportError:
        return False
    try:
        from .api_server import _load_or_create_token  # noqa: PLC0415
    except ImportError:
        return False

    from .api_server import load_server_config  # noqa: PLC0415

    _server_url, _server_port = load_server_config()
    _server_host = _server_url.split("://", 1)[-1]  # strip scheme for bind address

    token = _load_or_create_token()
    broadcaster = SSEBroadcaster()

    def html_fn(root_uri: str | None = None) -> str:
        tax = app.state._ster["taxonomy"]
        return render_vowl_html(tax, file_path, api_token=token, root_uri=root_uri)

    def save_fn(tax: Taxonomy) -> None:
        if file_path is not None:
            from .store import save  # noqa: PLC0415

            save(tax, file_path)
        if on_change_fn is not None:
            on_change_fn()

    app = create_app(taxonomy, token, broadcaster, save_fn, html_fn=html_fn)
    app.state._ster["broadcaster"] = broadcaster

    _api_app = app
    _api_broadcaster = broadcaster

    loop_captured: threading.Event = threading.Event()

    def _run() -> None:
        global _api_loop

        async def _serve() -> None:
            global _api_loop
            _api_loop = asyncio.get_running_loop()
            loop_captured.set()
            cfg = uvicorn.Config(app, host=_server_host, port=_server_port, log_level="warning")
            await uvicorn.Server(cfg).serve()

        asyncio.run(_serve())

    threading.Thread(target=_run, daemon=True, name="ster-api-server").start()
    loop_captured.wait(timeout=10)
    if _api_loop is None:
        _api_app = _api_broadcaster = None
        _api_running = False
        return False

    import time as _time  # noqa: PLC0415

    for _ in range(100):  # up to 10 s — uvicorn binds socket after loop starts
        try:
            with socket.socket() as _s:
                if _s.connect_ex((_server_host, _server_port)) == 0:
                    break
        except OSError:
            pass
        _time.sleep(0.1)
    return True


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler that suppresses access-log noise."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def _ensure_server(directory: Path) -> int:
    """Start the local HTTP server on first call; return its port on all calls.

    Uses the port from the ster server config so the browser origin is stable
    across restarts and localStorage graph state is preserved.
    """
    global _http_server, _http_port
    if _http_server is not None:
        return _http_port  # type: ignore[return-value]
    from .api_server import load_server_config  # noqa: PLC0415

    _cfg_url, preferred = load_server_config()
    handler = functools.partial(_QuietHandler, directory=str(directory))
    for port in [preferred + i for i in range(20)]:
        try:
            server = http.server.HTTPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            continue
    else:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = http.server.HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _http_server = server
    _http_port = port
    return port


def _graph_path(file_path: Path | None) -> Path:
    cache = Path.home() / ".cache" / "ster"
    cache.mkdir(parents=True, exist_ok=True)
    stem = file_path.stem if file_path else "graph"
    return cache / f"{stem}_vowl.html"


def render_vowl_html(
    taxonomy: Taxonomy,
    file_path: Path | None,
    api_token: str = "",
    root_uri: str | None = None,
) -> str:
    """Return the rendered VOWL HTML string.

    When *api_token* is non-empty the page connects to the SSE stream so the
    Graph view refreshes automatically whenever the ontology file changes.
    When *root_uri* is given a focused subgraph centred on that class is rendered.
    """
    title = _ontology_title(taxonomy, file_path)
    if root_uri:
        root_cls = taxonomy.owl_classes.get(root_uri)
        root_label = root_cls.label("en") if root_cls else _local(root_uri)
        title = f"{title} — {root_label}"
        graph = build_focused_vowl_graph(taxonomy, root_uri)
    else:
        graph = build_vowl_graph(taxonomy)
    graph_json = json.dumps(graph, ensure_ascii=False)
    meta = _taxonomy_meta(taxonomy, file_path)
    meta_json = json.dumps(meta, ensure_ascii=False)
    return (
        _HTML_TEMPLATE.replace("__TITLE__", title)
        .replace('"__GRAPH_DATA__"', graph_json)
        .replace('"__TAXO_META__"', meta_json)
        .replace("__CY_SCRIPT__", _cytoscape_script_tag())
        .replace("__API_TOKEN__", api_token)
        .replace("__SHOW_ALL_BTN__", "")
    )


def _write_html(taxonomy: Taxonomy, file_path: Path | None, out_path: Path) -> None:
    out_path.write_text(render_vowl_html(taxonomy, file_path), encoding="utf-8")


def _data_path(out_path: Path) -> Path:
    stem = out_path.stem.removesuffix("_vowl")
    return out_path.with_name(stem + "_data.json")


def _write_data_json(taxonomy: Taxonomy, out_path: Path) -> None:
    """Write companion JSON polled by the browser for static-mode live updates."""
    import time as _t  # noqa: PLC0415

    graph = build_vowl_graph(taxonomy)
    graph["_v"] = str(int(_t.time()))
    _data_path(out_path).write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")


def open_in_browser(
    taxonomy: Taxonomy,
    file_path: Path | None = None,
    on_change_fn: Any = None,
) -> str:
    """Open the VOWL graph in the browser.

    When ster[api] is installed, starts the live FastAPI server (SSE push refresh).
    Falls back to a static HTTP server otherwise.

    *on_change_fn* (optional) is called after any API mutation (e.g. individual
    creation) so the caller can rebuild its display tree.
    """
    if _start_api_server(taxonomy, file_path, on_change_fn):
        from .api_server import load_server_config  # noqa: PLC0415

        _url, _port = load_server_config()
        url = f"{_url}:{_port}/"
        webbrowser.open(url)
        return url
    # Fallback: static file server
    global _out_path, _file_path
    _file_path = file_path
    _out_path = _graph_path(file_path)
    _write_html(taxonomy, file_path, _out_path)
    _write_data_json(taxonomy, _out_path)
    port = _ensure_server(_out_path.parent)
    url = f"http://127.0.0.1:{port}/{_out_path.name}"
    webbrowser.open(url)
    return url


def push_update(taxonomy: Taxonomy) -> None:
    """Push an updated taxonomy to all connected viewers."""
    if _api_app is not None:
        _api_app.state._ster["taxonomy"] = taxonomy
        _api_broadcaster.notify(_api_loop)
        return
    if _out_path is not None:
        _write_html(taxonomy, _file_path, _out_path)
        _write_data_json(taxonomy, _out_path)


def open_focused_in_browser(
    taxonomy: Taxonomy, root_uri: str, file_path: Path | None = None
) -> str:
    """Open a focused VOWL graph centred on *root_uri* in the browser."""
    if _api_app is not None:
        from .api_server import load_server_config  # noqa: PLC0415

        _url, _port = load_server_config()
        url = f"{_url}:{_port}/?root={urllib.parse.quote(root_uri, safe='')}"
        webbrowser.open(url)
        return url
    # Fallback: static focused file
    root_cls = taxonomy.owl_classes.get(root_uri)
    root_label = root_cls.label("en") if root_cls else _local(root_uri)
    safe_label = re.sub(r"[^A-Za-z0-9_-]", "_", root_label)
    stem = (file_path.stem if file_path else "graph") + f"_focused_{safe_label}"
    cache = Path.home() / ".cache" / "ster"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{stem}_vowl.html"
    out.write_text(render_vowl_html(taxonomy, file_path, root_uri=root_uri), encoding="utf-8")
    port = _ensure_server(out.parent)
    url = f"http://127.0.0.1:{port}/{out.name}"
    webbrowser.open(url)
    return url


# ── HTML template ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f1f5f9;color:#1e293b;font-family:system-ui,-apple-system,sans-serif;display:flex;overflow:hidden}
#cy{flex:1;height:100vh;background:#fff}
#detail-panel{width:25vw;min-width:200px;max-width:380px;height:100vh;overflow-y:auto;background:#f8fafc;border-left:1px solid #e2e8f0;flex-shrink:0}
#panel-close{position:fixed;top:8px;right:8px;background:#f8fafc;border:1px solid #e2e8f0;color:#64748b;cursor:pointer;font-size:16px;line-height:1;padding:3px 8px;border-radius:4px;z-index:20}
#panel-close:hover{background:#e2e8f0;color:#0f172a}
#stats{position:fixed;bottom:10px;left:50%;transform:translateX(-50%);font-size:11px;color:#64748b;background:#f8fafc;padding:4px 12px;border-radius:20px;border:1px solid #e2e8f0;pointer-events:none}
#hint{position:fixed;bottom:10px;left:12px;font-size:10px;color:#94a3b8;background:#f8fafc;padding:3px 8px;border-radius:10px;border:1px solid #e2e8f0}
#zoom-ctrl{position:fixed;bottom:10px;right:12px;display:flex;gap:4px;z-index:10}
#zoom-ctrl button{background:#f8fafc;border:1px solid #e2e8f0;color:#475569;cursor:pointer;font-size:14px;min-width:28px;height:28px;border-radius:4px;line-height:1;padding:0 6px}
#zoom-ctrl button:hover{background:#e2e8f0}
#tip{position:fixed;pointer-events:none;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:6px 10px;font-size:11px;color:#e2e8f0;max-width:280px;word-break:break-all;display:none;z-index:99}
.ftbtn{background:none;border:1px solid #cbd5e1;color:#94a3b8;border-radius:6px;cursor:pointer;font-size:10px;padding:1px 6px;text-decoration:line-through}
.ftbtn.active{color:#475569;border-color:#94a3b8;text-decoration:none}
.ftbtn:hover{background:#f1f5f9}
.dp{padding:14px}
.dp-h2{font-size:15px;font-weight:600;color:#0f172a;margin-bottom:3px;line-height:1.3}
.dp-h3{font-size:13px;font-weight:600;color:#1e293b;margin-bottom:5px;line-height:1.3;word-break:break-word}
.dp-uri{font-size:10px;color:#94a3b8;word-break:break-all;margin-bottom:10px}
.dp-badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}
.dp-class{background:#dbeafe;color:#1d4ed8}.dp-individual{background:#fef3c7;color:#92400e}
.dp-concept{background:#dcfce7;color:#166534}.dp-topconcept{background:#cffafe;color:#0e7490}
.dp-scheme{background:#ede9fe;color:#6d28d9}
.dp-section{margin:8px 0}
.dp-row{display:flex;justify-content:space-between;align-items:center;padding:3px 0;border-bottom:1px solid #f1f5f9;font-size:11px;color:#334155}
.dp-row span:first-child{color:#64748b}
.dp-hr{border:none;border-top:1px solid #e2e8f0;margin:10px 0}
.dp-sub{font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px}
.dp-lbl{margin:2px 0;font-size:11px;line-height:1.3}
.dp-lang{color:#94a3b8;font-size:10px;margin-right:4px}
.dp-pref{font-weight:600;color:#1e293b}.dp-alt{color:#64748b;font-style:italic}
.dp-desc{color:#334155;font-size:11px;line-height:1.5;margin:8px 0}
.dp-rel{padding:3px 0;border-bottom:1px solid #f1f5f9;font-size:11px;display:flex;align-items:baseline;gap:6px}
.dp-rel-tag{color:#94a3b8;font-size:10px;min-width:72px;flex-shrink:0}
.dp-link{color:#3b82f6;cursor:pointer;background:none;border:none;font-size:11px;padding:0;text-align:left}
.dp-link:hover{text-decoration:underline}
.dp-back{background:none;border:none;color:#3b82f6;cursor:pointer;font-size:11px;padding:0 0 12px;display:block}
.dp-back:hover{text-decoration:underline}
.dp-indiv-btn{background:none;border:1px solid #cbd5e1;color:#475569;border-radius:6px;cursor:pointer;font-size:10px;padding:2px 8px;margin:5px 0 2px;display:block}
.dp-indiv-btn:hover{background:#f1f5f9}
.dp-hint{font-size:10px;color:#94a3b8;margin:4px 0 0;line-height:1.4}
.lr{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:11px;color:#334155}
#search-wrap{position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:30;display:flex;align-items:center;gap:6px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:4px 10px;box-shadow:0 2px 8px rgba(0,0,0,.08)}
#search-box{border:none;background:transparent;outline:none;font-size:13px;color:#1e293b;width:200px}
#search-box::placeholder{color:#94a3b8}
#search-count{font-size:11px;color:#64748b;white-space:nowrap;min-width:52px}
#search-clear{background:none;border:none;color:#94a3b8;cursor:pointer;font-size:16px;line-height:1;padding:0 2px;display:none}
#search-clear:hover{color:#475569}
</style>
</head>
<body>
<div id="cy"></div>
<div id="detail-panel"></div>
<button id="panel-close" title="Close panel (Esc)">\xd7</button>
<div id="stats"></div>
<div id="hint">drag\xb7pan\xb7scroll→zoom \xb7 f: layout \xb7 click: details \xb7 esc: close<span style="color:#cbd5e1"> │ </span><button class="ftbtn active" id="ft-individuals">individuals</button><button class="ftbtn active" id="ft-first-order">1st order</button><button class="ftbtn active" id="ft-second-order">2nd order</button><button class="ftbtn active" id="ft-instanceOf">rdf:type</button><button class="ftbtn active" id="ft-inScheme">inScheme</button><button class="ftbtn active" id="ft-datatypeProperty">datatype</button>__SHOW_ALL_BTN__</div>
<div id="zoom-ctrl"><button id="zoom-in" title="Zoom in (+)">+</button><button id="zoom-out" title="Zoom out (−)">&#8722;</button><button id="zoom-fit" title="Fit all (f)">Recenter</button></div>
<div id="tip"></div>
<div id="search-wrap"><svg width="14" height="14" viewBox="0 0 14 14" fill="none" style="flex-shrink:0;opacity:.5"><circle cx="5.5" cy="5.5" r="4" stroke="#475569" stroke-width="1.5"/><line x1="8.5" y1="8.5" x2="13" y2="13" stroke="#475569" stroke-width="1.5" stroke-linecap="round"/></svg><input id="search-box" type="search" placeholder="Search nodes…" autocomplete="off" spellcheck="false" autofocus><span id="search-count"></span><button id="search-clear" title="Clear (Esc)">\xd7</button></div>
__CY_SCRIPT__
<script>
(function(){
try{
const graphData="__GRAPH_DATA__";
const taxoMeta="__TAXO_META__";
const API_TOKEN="__API_TOKEN__";
const panelEl=document.getElementById('detail-panel');
let panelVisible=true;
let W=window.innerWidth-(panelVisible?panelEl.getBoundingClientRect().width:0);
const H=window.innerHeight;
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function buildElements(data){
  return[
    ...data.nodes.map(n=>({group:'nodes',data:{id:n.id,label:n.label,type:n.type,detail:n.detail||{},rootClass:n.rootClass||0}})),
    ...data.edges.map(e=>({group:'edges',data:{id:e.id,source:e.source,target:e.target,type:e.type,label:e.label||'',cardinality:e.cardinality||''}})),
  ];
}
const CY_STYLE=[
  {selector:'node',style:{'label':'data(label)','text-halign':'center','text-valign':'center','color':'white','font-family':'system-ui,sans-serif','text-wrap':'wrap','text-max-width':'80px','font-size':12}},
  {selector:'node[type="class"]',style:{'shape':'ellipse','width':84,'height':84,'background-color':'#3c6ebf','border-color':'#5a87cc','border-width':2,'font-weight':600}},
  {selector:'node[type="class"][rootClass=1]',style:{'width':104,'height':104,'border-color':'#6694d1','border-width':5,'font-size':13,'text-max-width':'92px'}},
  {selector:'node[type="individual"]',style:{'shape':'ellipse','width':68,'height':68,'background-color':'#7fb8e0','border-color':'#4a90c4','border-width':1.5,'color':'#0f172a'}},
  {selector:'node[type="scheme"]',style:{'shape':'ellipse','width':88,'height':88,'background-color':'#7c3aed','border-color':'#a78bfa','border-width':2,'font-weight':600}},
  {selector:'node[type="topconcept"]',style:{'shape':'ellipse','width':72,'height':72,'background-color':'#0e7490','border-color':'#22d3ee','border-width':2}},
  {selector:'node[type="concept"]',style:{'shape':'ellipse','width':56,'height':56,'background-color':'#166534','border-color':'#4ade80','border-width':1.5}},
  {selector:'node[type="datatype"]',style:{'shape':'round-rectangle','background-color':'#fef3c7','border-color':'#f59e0b','border-width':1.5,'color':'#92400e','font-size':10,'padding':'4px 8px','width':'label','height':22}},
  {selector:'node.searched',style:{'overlay-color':'#fbbf24','overlay-opacity':0.45,'overlay-padding':7}},
  {selector:'node.dimmed',style:{'opacity':0.08}},
  {selector:'node.hidden',style:{'display':'none'}},
  {selector:'edge',style:{'curve-style':'bezier','width':1.5,'target-arrow-shape':'triangle'}},
  {selector:'edge[type="subClassOf"]',style:{'line-color':'#94a3b8','target-arrow-color':'#94a3b8','target-arrow-fill':'hollow'}},
  {selector:'edge[type="objectProperty"]',style:{'line-color':'#818cf8','target-arrow-color':'#818cf8','label':'data(label)','font-size':10,'color':'#4f46e5','text-background-color':'white','text-background-opacity':1,'text-background-padding':'3px','text-border-width':1,'text-border-color':'#818cf8','text-border-opacity':1}},
  {selector:'edge[type="datatypeProperty"]',style:{'line-color':'#f59e0b','target-arrow-color':'#f59e0b','line-style':'dashed','line-dash-pattern':[4,3],'label':'data(label)','font-size':10,'color':'#92400e','text-background-color':'white','text-background-opacity':1,'text-background-padding':'3px','text-border-width':1,'text-border-color':'#f59e0b','text-border-opacity':1}},
  {selector:'edge[type="instanceOf"]',style:{'line-color':'#c4b5fd','target-arrow-color':'#c4b5fd','line-style':'dotted','opacity':0.5,'width':1}},
  {selector:'edge[type="broader"]',style:{'line-color':'#6b7280','target-arrow-color':'#6b7280','line-style':'dashed'}},
  {selector:'edge[type="inScheme"]',style:{'line-color':'#a78bfa','target-arrow-color':'#a78bfa','line-style':'dotted','opacity':0.6,'width':1}},
  {selector:'edge.dimmed',style:{'opacity':0.04}},
  {selector:'edge.hidden',style:{'display':'none'}},
];
function makeLayout(){
  return {name:'cose',animate:false,fit:true,padding:40,randomize:false,
    nodeRepulsion:4500,nodeOverlap:10,idealEdgeLength:100,edgeElasticity:100,
    gravity:60,numIter:1000,initialTemp:200,coolingFactor:0.95,minTemp:1.0};
}
// Create cy without running any layout — positions applied below
const cy=cytoscape({container:document.getElementById('cy'),elements:buildElements(graphData),style:CY_STYLE,layout:{name:'preset',animate:false},wheelSensitivity:0.3,minZoom:0.05,maxZoom:8,pixelRatio:window.devicePixelRatio||1});

// ── Graph state persistence (positions + viewport, survives browser/ster restart) ──
const _stateKey='ster_state_'+location.pathname;
function _saveState(){
  try{
    const pos=[];
    cy.nodes().forEach(n=>{const p=n.position();pos.push({id:n.id(),x:p.x,y:p.y});});
    localStorage.setItem(_stateKey,JSON.stringify({pos,zoom:cy.zoom(),pan:cy.pan()}));
  }catch(_){}
}
let _saveTimer;
function _debouncedSave(){clearTimeout(_saveTimer);_saveTimer=setTimeout(_saveState,400);}

// On load: restore saved state or run fresh layout
(function(){
  try{
    const s=JSON.parse(localStorage.getItem(_stateKey)||'null');
    if(s&&s.pos&&s.pos.length){
      const posMap={};
      s.pos.forEach(p=>{posMap[p.id]={x:p.x,y:p.y};});
      cy.nodes().forEach(n=>{
        if(posMap[n.id()]){n.position(posMap[n.id()]);}
        else{
          // New node not in saved state — place near its neighbours
          const nbrs=n.neighborhood('node').filter(nb=>!!posMap[nb.id()]);
          if(nbrs.length){
            let x=0,y=0;
            nbrs.forEach(nb=>{x+=nb.position().x;y+=nb.position().y;});
            n.position({x:x/nbrs.length+(Math.random()-.5)*80,y:y/nbrs.length+(Math.random()-.5)*80});
          }else{n.position({x:500+(Math.random()-.5)*300,y:400+(Math.random()-.5)*300});}
        }
      });
      cy.viewport({zoom:s.zoom||1,pan:s.pan||{x:0,y:0}});
      return;
    }
  }catch(_){}
  // No saved state — compute layout once and save it
  cy.layout(makeLayout()).run();
  _saveState();
})();

cy.on('viewport',_debouncedSave);
cy.on('dragfree','node',_debouncedSave);

// ── Smart graph update (live refresh — preserves positions and viewport) ──────
function applyGraphUpdate(d){
  const z=cy.zoom(),p=cy.pan();
  const prevPos={};
  cy.nodes().forEach(n=>{prevPos[n.id()]={...n.position()};});
  cy.elements().remove();
  cy.add(buildElements(d));
  cy.nodes().forEach(n=>{
    if(prevPos[n.id()]){n.position(prevPos[n.id()]);}
    else{
      const nbrs=n.neighborhood('node').filter(nb=>!!prevPos[nb.id()]);
      if(nbrs.length){
        let x=0,y=0;
        nbrs.forEach(nb=>{x+=nb.position().x;y+=nb.position().y;});
        n.position({x:x/nbrs.length+(Math.random()-.5)*80,y:y/nbrs.length+(Math.random()-.5)*80});
      }
    }
  });
  cy.viewport({zoom:z,pan:p});
  Object.assign(graphData,d);
  applyIndivVis();
  hiddenEdgeTypes.forEach(t=>cy.edges('[type="'+t+'"]').addClass('hidden'));
  _saveState();
}

function zoomBy(f){const c=cy.container();cy.zoom({level:cy.zoom()*f,renderedPosition:{x:c.clientWidth/2,y:c.clientHeight/2}});}

// ── Tooltip ───────────────────────────────────────────────────────────────────
const tipEl=document.getElementById('tip');
const KM={class:'Class',individual:'Individual',concept:'Concept',topconcept:'Top Concept',scheme:'Scheme'};
cy.on('mouseover','node',e=>{const d=e.target.data();tipEl.innerHTML=`<b>${KM[d.type]||d.type}</b><br>${esc(d.label)}<br><span style="color:#64748b;font-size:10px">${esc(d.id)}</span>`;tipEl.style.display='block';});
cy.on('mousemove','node',e=>{tipEl.style.left=(e.originalEvent.clientX+14)+'px';tipEl.style.top=(e.originalEvent.clientY+10)+'px';});
cy.on('mouseout','node',()=>{tipEl.style.display='none';});

// ── Individuals toggle ────────────────────────────────────────────────────────
const classIndMap={};
cy.edges('[type="instanceOf"]').forEach(e=>{const c=e.data('target');(classIndMap[c]=classIndMap[c]||[]).push(e.data('source'));});
const hiddenIndivClasses=new Set();
function applyIndivVis(){
  cy.nodes('[type="individual"]').forEach(n=>{
    const e=cy.edges('[source="'+n.id()+'"][type="instanceOf"]').first();
    if(hiddenIndivClasses.has(e.data('target'))){n.addClass('hidden');}else{n.removeClass('hidden');}
  });
  cy.edges('[type="instanceOf"]').forEach(e=>{if(hiddenIndivClasses.has(e.data('target'))){e.addClass('hidden');}else{e.removeClass('hidden');}});
}
function toggleAllIndividuals(){
  const ks=Object.keys(classIndMap);
  if(!ks.length)return;
  const allHid=ks.every(c=>hiddenIndivClasses.has(c));
  if(allHid)ks.forEach(c=>hiddenIndivClasses.delete(c));else ks.forEach(c=>hiddenIndivClasses.add(c));
  applyIndivVis();
  const nowHid=ks.every(c=>hiddenIndivClasses.has(c));
  const ftBtn=document.getElementById('ft-individuals');
  if(ftBtn){if(nowHid)ftBtn.classList.remove('active');else ftBtn.classList.add('active');}
  const btn=document.getElementById('btn-toggle-indivs');
  if(btn)btn.textContent=nowHid?'Show all individuals':'Hide all individuals';
}
// Hide the individuals button when no individuals exist
if(!Object.keys(classIndMap).length){const b=document.getElementById('ft-individuals');if(b)b.style.display='none';}

// ── Class-order toggles ───────────────────────────────────────────────────────
const firstOrderIds=new Set(cy.nodes('[type="class"][rootClass=1]').map(n=>n.id()));
const secondOrderIds=new Set();
cy.edges('[type="subClassOf"]').forEach(e=>{
  if(firstOrderIds.has(e.data('target')))secondOrderIds.add(e.data('source'));
});

let firstOrderHidden=false;
let secondOrderHidden=false;

function _applyClassOrderVis(ids,hidden){
  ids.forEach(id=>{
    const n=cy.$('#'+CSS.escape(id));
    if(hidden){
      n.addClass('hidden');
      cy.edges('[source="'+id+'"]').addClass('hidden');
      cy.edges('[target="'+id+'"]').addClass('hidden');
    }else{
      n.removeClass('hidden');
      cy.edges('[source="'+id+'"]').forEach(e=>{
        if(!cy.$('#'+CSS.escape(e.data('target'))).hasClass('hidden'))e.removeClass('hidden');
      });
      cy.edges('[target="'+id+'"]').forEach(e=>{
        if(!cy.$('#'+CSS.escape(e.data('source'))).hasClass('hidden'))e.removeClass('hidden');
      });
    }
  });
}
function toggleFirstOrderClasses(){
  firstOrderHidden=!firstOrderHidden;
  _applyClassOrderVis(firstOrderIds,firstOrderHidden);
  const btn=document.getElementById('ft-first-order');
  if(btn){if(firstOrderHidden)btn.classList.remove('active');else btn.classList.add('active');}
}
function toggleSecondOrderClasses(){
  secondOrderHidden=!secondOrderHidden;
  _applyClassOrderVis(secondOrderIds,secondOrderHidden);
  const btn=document.getElementById('ft-second-order');
  if(btn){if(secondOrderHidden)btn.classList.remove('active');else btn.classList.add('active');}
}
if(!firstOrderIds.size){const b=document.getElementById('ft-first-order');if(b)b.style.display='none';}
if(!secondOrderIds.size){const b=document.getElementById('ft-second-order');if(b)b.style.display='none';}

// ── Edge type toggle ──────────────────────────────────────────────────────────
const hiddenEdgeTypes=new Set();
function toggleEdgeType(t){
  const btn=document.getElementById('ft-'+t);
  if(hiddenEdgeTypes.has(t)){hiddenEdgeTypes.delete(t);btn&&btn.classList.add('active');}
  else{hiddenEdgeTypes.add(t);btn&&btn.classList.remove('active');}
  cy.edges('[type="'+t+'"]').forEach(e=>{if(hiddenEdgeTypes.has(t))e.addClass('hidden');else e.removeClass('hidden');});
}

// ── Highlight ─────────────────────────────────────────────────────────────────
let highlighted=null;
function applyHighlight(){
  if(!highlighted){cy.elements().removeClass('dimmed');return;}
  const n=cy.$('#'+CSS.escape(highlighted));
  cy.elements().addClass('dimmed');
  n.neighborhood().add(n).removeClass('dimmed');
}

// ── Search ────────────────────────────────────────────────────────────────────
function searchNodes(term){
  const t=term.trim().toLowerCase();
  const countEl=document.getElementById('search-count');
  const clearBtn=document.getElementById('search-clear');
  if(!t){clearSearch();return;}
  clearBtn.style.display='';
  highlighted=null;
  const matched=cy.nodes().filter(n=>n.data('label').toLowerCase().includes(t)||n.data('id').toLowerCase().includes(t));
  cy.nodes().forEach(n=>{
    if(matched.has(n)){n.removeClass('dimmed').addClass('searched');}
    else{n.addClass('dimmed').removeClass('searched');}
  });
  cy.edges().forEach(e=>{
    const s=cy.$('#'+CSS.escape(e.data('source')));
    const tg=cy.$('#'+CSS.escape(e.data('target')));
    if(!s.hasClass('dimmed')&&!tg.hasClass('dimmed')){e.removeClass('dimmed');}else{e.addClass('dimmed');}
  });
  countEl.textContent=matched.length+' match'+(matched.length!==1?'es':'');
  if(matched.length){
    const ext=cy.extent();
    const anyVisible=matched.toArray().some(n=>{const p=n.position();return p.x>=ext.x1&&p.x<=ext.x2&&p.y>=ext.y1&&p.y<=ext.y2;});
    if(!anyVisible){cy.animate({center:{eles:matched.first()}},{duration:350});}
  }
}
function clearSearch(){
  const box=document.getElementById('search-box');
  if(box)box.value='';
  const countEl=document.getElementById('search-count');
  if(countEl)countEl.textContent='';
  const clearBtn=document.getElementById('search-clear');
  if(clearBtn)clearBtn.style.display='none';
  cy.nodes().removeClass('dimmed searched');
  cy.edges().removeClass('dimmed');
}
document.getElementById('search-box').addEventListener('input',e=>searchNodes(e.target.value));
document.getElementById('search-clear').addEventListener('click',clearSearch);
window.addEventListener('load',()=>document.getElementById('search-box').focus());

// ── Click ─────────────────────────────────────────────────────────────────────
cy.on('tap','node',function(e){
  const d=e.target.data();
  clearSearch();
  if(highlighted===d.id){highlighted=null;applyHighlight();showDefault();return;}
  highlighted=d.id;applyHighlight();togglePanel(true);showDetail(d);
});
cy.on('tap',function(e){if(e.target===cy){highlighted=null;applyHighlight();showDefault();}});

// ── Panel ─────────────────────────────────────────────────────────────────────
function togglePanel(show){
  const was=panelVisible;
  panelVisible=show!==undefined?show:!panelVisible;
  if(panelVisible===was)return;
  panelEl.style.display=panelVisible?'':'none';
  document.getElementById('panel-close').style.display=panelVisible?'':'none';
  W=window.innerWidth-(panelVisible?panelEl.getBoundingClientRect().width:0);
  document.getElementById('stats').style.left=(W/2)+'px';
  cy.resize();
}
document.getElementById('panel-close').addEventListener('click',()=>togglePanel());
document.getElementById('zoom-in').addEventListener('click',()=>zoomBy(1.3));
document.getElementById('zoom-fit').addEventListener('click',()=>{try{localStorage.removeItem(_stateKey);}catch(_){}cy.layout(makeLayout()).run();_saveState();});
document.getElementById('zoom-out').addEventListener('click',()=>zoomBy(0.77));
document.getElementById('ft-individuals').addEventListener('click',toggleAllIndividuals);
document.getElementById('ft-first-order').addEventListener('click',toggleFirstOrderClasses);
document.getElementById('ft-second-order').addEventListener('click',toggleSecondOrderClasses);
[['instanceOf','ft-instanceOf'],['inScheme','ft-inScheme'],['datatypeProperty','ft-datatypeProperty']].forEach(([t,id])=>{
  const btn=document.getElementById(id);
  if(!btn)return;
  if(cy.edges('[type="'+t+'"]').length===0){btn.style.display='none';return;}
  btn.addEventListener('click',()=>toggleEdgeType(t));
});
// Expose wrappers for dynamically-created panel buttons (which run in global scope)
window._sterNav=navigateTo;
window._sterBack=function(){highlighted=null;applyHighlight();showDefault();};
window._sterToggleIndiv=toggleAllIndividuals;

// ── Keyboard ──────────────────────────────────────────────────────────────────
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){const sb=document.getElementById('search-box');if(sb&&sb.value){clearSearch();return;}if(highlighted){highlighted=null;applyHighlight();showDefault();}else togglePanel();}
  if(e.key==='f'){try{localStorage.removeItem(_stateKey);}catch(_){}cy.layout(makeLayout()).run();_saveState();}
  if(e.key==='+'){zoomBy(1.3);}
  if(e.key==='-'){zoomBy(0.77);}
});

// ── Stats ─────────────────────────────────────────────────────────────────────
(function(){
  const c=taxoMeta.counts,p=[];
  if(c.classes)p.push(c.classes+' class'+(c.classes!==1?'es':''));
  if(c.individuals)p.push(c.individuals+' individual'+(c.individuals!==1?'s':''));
  if(c.properties)p.push(c.properties+' propert'+(c.properties!==1?'ies':'y'));
  if(c.schemes)p.push(c.schemes+' scheme'+(c.schemes!==1?'s':''));
  if(c.top_concepts)p.push(c.top_concepts+' top concept'+(c.top_concepts!==1?'s':''));
  if(c.concepts)p.push(c.concepts+' concept'+(c.concepts!==1?'s':''));
  document.getElementById('stats').textContent=p.join(' \xb7 ');
  document.getElementById('stats').style.left=(W/2)+'px';
})();

// ── Detail panel ──────────────────────────────────────────────────────────────
function nodeSvg(t){
  const S={'class-root':'<svg width="34" height="16"><circle cx="17" cy="8" r="8" fill="none" stroke="#6694d1" stroke-width="1" opacity=".4"/><circle cx="17" cy="8" r="7" fill="#3c6ebf" stroke="#6694d1" stroke-width="2"/></svg>','class-sub':'<svg width="34" height="16"><circle cx="17" cy="8" r="6" fill="#3c6ebf" stroke="#5a87cc" stroke-width="1.5"/></svg>','individual':'<svg width="34" height="16"><circle cx="17" cy="8" r="7" fill="#7fb8e0" stroke="#4a90c4" stroke-width="1.5"/></svg>','topconcept':'<svg width="34" height="16"><circle cx="17" cy="8" r="7" fill="#0e7490" stroke="#22d3ee" stroke-width="2"/></svg>','concept':'<svg width="34" height="16"><circle cx="17" cy="8" r="6" fill="#166534" stroke="#4ade80" stroke-width="1.5"/></svg>','scheme':'<svg width="34" height="16"><circle cx="17" cy="8" r="8" fill="#7c3aed" stroke="#a78bfa" stroke-width="2"/></svg>'};
  return S[t]||'';
}
function edgeLine(t){
  const S={'subClassOf':'border-top:2px solid #94a3b8','objectProperty':'border-top:2px solid #818cf8','datatypeProperty':'border-top:1.5px dashed #f59e0b','instanceOf':'border-top:1px dotted #c4b5fd;opacity:.5','broader':'border-top:2px dashed #6b7280','inScheme':'border-top:1px dotted #a78bfa'};
  return `<div style="width:28px;height:0;flex-shrink:0;${S[t]||''}"></div>`;
}
function showDefault(){
  highlighted=null;
  const cc=cy.nodes('[type="class"]').length,ic=cy.nodes('[type="individual"]').length,pc=cy.edges('[type="objectProperty"],[type="datatypeProperty"]').length,sc=cy.nodes('[type="scheme"]').length,tc=cy.nodes('[type="topconcept"]').length,cc2=cy.nodes('[type="concept"]').length;
  let rows='';
  if(cc)rows+='<div class="dp-row"><span>Classes</span><span>'+cc+'</span></div>';
  if(ic)rows+='<div class="dp-row"><span>Individuals</span><span>'+ic+'</span></div>';
  if(pc)rows+='<div class="dp-row"><span>Properties</span><span>'+pc+'</span></div>';
  if(sc)rows+='<div class="dp-row"><span>Schemes</span><span>'+sc+'</span></div>';
  if(tc)rows+='<div class="dp-row"><span>Top Concepts</span><span>'+tc+'</span></div>';
  if(cc2)rows+='<div class="dp-row"><span>Concepts</span><span>'+cc2+'</span></div>';
  const hasRoot=cy.nodes('[type="class"][rootClass=1]').length>0,hasSub=cy.nodes('[type="class"][rootClass=0]').length>0;
  const ntypes=new Set(cy.nodes().map(n=>n.data('type')));
  const etypes=new Set(cy.edges().map(e=>e.data('type')));
  let indToggle='';
  if(Object.keys(classIndMap).length>0){
    const allHid=Object.keys(classIndMap).every(c=>hiddenIndivClasses.has(c));
    indToggle='<button id="btn-toggle-indivs" class="dp-indiv-btn" onclick="window._sterToggleIndiv()">'+(allHid?'Show all individuals':'Hide all individuals')+'</button><div class="dp-hint">Click a class to view details and highlight connections.</div>';
  }
  let leg='<hr class="dp-hr"><div class="dp-sub">Legend</div>';
  [['class-root','Root Class',hasRoot],['class-sub','Class',hasSub],['individual','Individual',ntypes.has('individual')],['topconcept','Top Concept',ntypes.has('topconcept')],['concept','Concept',ntypes.has('concept')],['scheme','Scheme',ntypes.has('scheme')]].forEach(([t,lbl,show])=>{if(!show)return;leg+='<div class="lr">'+nodeSvg(t)+lbl+'</div>';if(t==='individual')leg+=indToggle;});
  leg+='<hr class="dp-hr"><div class="dp-sub">Relations</div>';
  [['subClassOf','subClassOf'],['objectProperty','objectProperty'],['datatypeProperty','datatypeProperty'],['instanceOf','rdf:type'],['broader','broader'],['inScheme','inScheme']].filter(([t])=>etypes.has(t)).forEach(([t,lbl])=>{leg+='<div class="lr">'+edgeLine(t)+lbl+'</div>';});
  panelEl.innerHTML='<div class="dp"><div class="dp-h2">'+esc(taxoMeta.title)+'</div>'+(taxoMeta.ontology_uri?'<div class="dp-uri">'+esc(taxoMeta.ontology_uri)+'</div>':'')+'<div class="dp-sub" style="margin-top:6px">Overview</div><div class="dp-section">'+rows+'</div>'+leg+'</div>';
}
showDefault();
function showDetail(d){
  const det=d.detail||{};let h='<div class="dp">';
  h+='<button class="dp-back" onclick="window._sterBack()">← Overview</button>';
  h+='<span class="dp-badge dp-'+d.type+'">'+(KM[d.type]||d.type)+'</span>';
  h+='<div class="dp-h3">'+esc(d.label)+'</div><div class="dp-uri">'+esc(d.id)+'</div>';
  const lbls=det.labels||[],showLbls=[...lbls.filter(l=>l.kind==='pref').slice(1),...lbls.filter(l=>l.kind==='alt'),...lbls.filter(l=>l.kind==='label')];
  if(showLbls.length){h+='<hr class="dp-hr"><div class="dp-sub">Labels</div>';showLbls.forEach(l=>{h+='<div class="dp-lbl">';if(l.lang)h+='<span class="dp-lang">['+esc(l.lang)+']</span>';h+='<span class="'+(l.kind==='alt'?'dp-alt':'dp-pref')+'">'+esc(l.value)+'</span></div>';});}
  const coms=det.comments||[];if(coms.length){h+='<hr class="dp-hr"><div class="dp-sub">Comments</div>';coms.forEach(c=>{h+='<div class="dp-desc">'+esc(c.value)+'</div>';});}
  if(det.description)h+='<hr class="dp-hr"><div class="dp-desc">'+esc(det.description)+'</div>';
  const rels=det.relations||[];if(rels.length){h+='<hr class="dp-hr"><div class="dp-sub">Relations</div>';rels.forEach(r=>{const lbl=r.label||r.uri,inG=cy.$('#'+CSS.escape(r.uri)).length>0;h+='<div class="dp-rel"><span class="dp-rel-tag">'+esc(r.rel)+'</span>';h+=inG?'<button class="dp-link" onclick="window._sterNav('+JSON.stringify(r.uri)+')">'+esc(lbl)+'</button>':'<span>'+esc(lbl)+'</span>';h+='</div>';});}
  h+='</div>';panelEl.innerHTML=h;
}
function navigateTo(uri){
  const n=cy.$('#'+CSS.escape(uri));if(!n.length)return;
  highlighted=uri;applyHighlight();togglePanel(true);showDetail(n.data());
  cy.animate({center:{eles:n},zoom:Math.max(cy.zoom(),1)},{duration:400});
}

// ── Live refresh ──────────────────────────────────────────────────────────────
if(API_TOKEN){
  // SSE mode (ster[api] installed)
  const src=new EventSource('/api/events?token='+encodeURIComponent(API_TOKEN));
  src.onmessage=async function(){
    try{
      const resp=await fetch('/api/graph',{headers:{'Authorization':'Bearer '+API_TOKEN}});
      const data=await resp.json();
      applyGraphUpdate(data);
    }catch(err){console.error('Graph refresh failed:',err);}
  };
}else{
  // Static-file mode: poll companion _data.json every 2.5 s
  const dataUrl=window.location.origin+window.location.pathname.replace(/_vowl\\.html$/,'_data.json');
  let _ver='';
  setInterval(async()=>{
    try{
      const r=await fetch(dataUrl+'?_='+Date.now(),{cache:'no-store'});
      if(!r.ok)return;
      const d=await r.json();
      const v=d._v||'';
      if(!_ver){_ver=v;return;}
      if(v===_ver)return;
      _ver=v;
      applyGraphUpdate(d);
    }catch(_){}
  },2500);
}
}catch(err){
  const el=document.createElement('div');
  el.style.cssText='position:fixed;inset:0;background:rgba(220,38,38,.95);color:white;padding:24px;font-family:monospace;font-size:13px;z-index:200;white-space:pre-wrap;overflow:auto';
  el.textContent='Graph error — see browser console (F12):\\n\\n'+(err.stack||err);
  document.body.appendChild(el);
}
})();
</script>
</body>
</html>
"""
