"""VOWL-style ontology visualisation — self-contained D3 HTML file.

Implements the Visual Notation for OWL Ontologies (VOWL) conventions:
  - All classes rendered as circles (not rectangles)
  - Object-property edges carry a floating label box at the midpoint
  - subClassOf uses an open/hollow arrowhead (UML inheritance convention)
  - Light background theme for maximum readability
  - Hierarchical layout auto-selected for OWL-only taxonomies

Call open_in_browser() to write the HTML and open it in the default browser.
push_update() regenerates the file after any taxonomy mutation.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import json
import math
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

# ── Layout helpers ────────────────────────────────────────────────────────────

_ROOT_CLASS_R = 50  # px radius for root OWL classes in the VOWL renderer
_SUB_CLASS_R = 40  # px radius for non-root OWL classes
_INDIVIDUAL_R = 34  # px radius for individual nodes (must match JS nodeRadius default)
_ORBIT_GAP = 8  # px gap between class circle edge and first orbit ring
_RING_GAP = 6  # px gap between successive orbit rings


def _root_class_order(taxonomy: Taxonomy) -> list[str]:
    """Return root-class URIs sorted to minimise objectProperty edge crossings.

    Uses the barycenter heuristic (3 passes).  A root class is any OWL class
    that has no non-builtin parent inside *taxonomy*.
    """
    parent_of: dict[str, str] = {}
    for cls_uri, cls in taxonomy.owl_classes.items():
        for p in cls.sub_class_of:
            if not is_builtin_uri(p) and p in taxonomy.owl_classes:
                parent_of[cls_uri] = p
                break

    roots = [u for u in taxonomy.owl_classes if u not in parent_of]
    if len(roots) <= 1:
        return roots

    def get_root(cls_uri: str, depth: int = 0) -> str | None:
        if depth > 40:
            return None
        if cls_uri not in parent_of:
            return cls_uri if cls_uri in taxonomy.owl_classes else None
        return get_root(parent_of[cls_uri], depth + 1)

    # Inter-root adjacency from objectProperty edges
    adj: dict[str, list[str]] = {r: [] for r in roots}
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != "ObjectProperty":
            continue
        for domain_uri in prop.domains:
            for range_uri in prop.ranges:
                src_root = get_root(domain_uri)
                tgt_root = get_root(range_uri)
                if src_root and tgt_root and src_root != tgt_root:
                    if src_root in adj:
                        adj[src_root].append(tgt_root)
                    if tgt_root in adj:
                        adj[tgt_root].append(src_root)

    order: dict[str, float] = {r: float(i) for i, r in enumerate(roots)}
    for _ in range(3):
        new_order: dict[str, float] = {}
        for r in roots:
            peers = adj[r]
            new_order[r] = (
                sum(order[p] for p in peers if p in order) / len(peers) if peers else order[r]
            )
        sorted_roots = sorted(roots, key=lambda r: new_order[r])
        order = {r: float(i) for i, r in enumerate(sorted_roots)}

    return sorted(roots, key=lambda r: order[r])


def _individual_orbit_data(taxonomy: Taxonomy, root_order: list[str]) -> dict[str, dict]:
    """Compute per-individual orbital placement data.

    Returns a mapping ``{individual_uri: {angle, orbit_r, class_uri}}``.
    The angle (radians) points into the largest angular gap around the class —
    away from its subClassOf parent, children, and objectProperty peers.
    """
    # individual → first non-builtin type
    ind_class: dict[str, str] = {}
    for ind_uri, ind in taxonomy.owl_individuals.items():
        for type_uri in ind.types:
            if not is_builtin_uri(type_uri):
                ind_class[ind_uri] = type_uri
                break

    if not ind_class:
        return {}

    # Class hierarchy maps
    parent_of: dict[str, str] = {}
    children_of: dict[str, list[str]] = {}
    for cls_uri, cls in taxonomy.owl_classes.items():
        for p in cls.sub_class_of:
            if not is_builtin_uri(p) and p in taxonomy.owl_classes:
                parent_of[cls_uri] = p
                children_of.setdefault(p, []).append(cls_uri)
                break

    root_index: dict[str, int] = {r: i for i, r in enumerate(root_order)}

    def get_root(cls_uri: str, depth: int = 0) -> str | None:
        if depth > 40:
            return None
        if cls_uri not in parent_of:
            return cls_uri if cls_uri in taxonomy.owl_classes else None
        return get_root(parent_of[cls_uri], depth + 1)

    # objectProperty adjacency per class
    obj_peers: dict[str, list[str]] = {}
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != "ObjectProperty":
            continue
        for domain_uri in prop.domains:
            for range_uri in prop.ranges:
                if domain_uri != range_uri:
                    obj_peers.setdefault(domain_uri, []).append(range_uri)
                    obj_peers.setdefault(range_uri, []).append(domain_uri)

    # Group individuals by class (preserving insertion order for determinism)
    class_individuals: dict[str, list[str]] = {}
    for ind_uri, cls_uri in ind_class.items():
        class_individuals.setdefault(cls_uri, []).append(ind_uri)

    result: dict[str, dict] = {}

    for cls_uri, ind_uris in class_individuals.items():
        is_root_cls = cls_uri not in parent_of
        cls_r = _ROOT_CLASS_R if is_root_cls else _SUB_CLASS_R
        orbit_r = cls_r + _INDIVIDUAL_R + _ORBIT_GAP

        # Collect "busy" directions (radians, screen coords: Y grows downward)
        busy: list[float] = []
        if cls_uri in parent_of:
            busy.append(-math.pi / 2)  # parent is above
        if cls_uri in children_of:
            busy.append(math.pi / 2)  # children are below

        my_root = get_root(cls_uri)
        my_idx = root_index.get(my_root, -1) if my_root else -1
        for peer_uri in obj_peers.get(cls_uri, []):
            peer_root = get_root(peer_uri)
            peer_idx = root_index.get(peer_root, -1) if peer_root else -1
            if peer_idx < 0 or my_idx < 0 or peer_idx == my_idx:
                continue
            busy.append(0.0 if peer_idx > my_idx else math.pi)

        # Find the largest angular gap and its angular size
        free_center = math.pi / 2  # default: downward
        max_free_angle = 2 * math.pi  # default: full circle
        if busy:
            norm = sorted((a % (2 * math.pi) + 2 * math.pi) % (2 * math.pi) for a in busy)
            max_gap = 0.0
            for i, a in enumerate(norm):
                gap = (norm[0] + 2 * math.pi - a) if i == len(norm) - 1 else (norm[i + 1] - a)
                if gap > max_gap:
                    max_gap = gap
                    free_center = a + gap / 2
            max_free_angle = max_gap

        # Place individuals into concentric rings.  Each ring packs individuals
        # at the minimum angular step that prevents overlap (touching is fine).
        # Overflow individuals move to the next ring at a larger radius.
        available_arc = max_free_angle * 0.92  # leave a small margin at the edges
        remaining = list(ind_uris)
        ring = 0
        while remaining and ring < 8:
            ring_r = orbit_r + ring * (2 * _INDIVIDUAL_R + _RING_GAP)
            # Minimum angular gap between adjacent individual centres on this ring
            min_step = 2 * math.asin(min(_INDIVIDUAL_R / ring_r, 1.0))
            # How many individuals fit without overlapping inside available_arc
            capacity = 1 + int(available_arc / min_step) if available_arc > 0 else 1
            batch = remaining[:capacity]
            remaining = remaining[capacity:]
            n_batch = len(batch)
            # Arc spread: use exactly the minimum touching distance so individuals
            # are as compact as possible while never stacking
            spread = 0.0 if n_batch == 1 else (n_batch - 1) * min_step
            for i, ind_uri in enumerate(batch):
                offset = 0.0 if n_batch == 1 else spread * (i / (n_batch - 1) - 0.5)
                result[ind_uri] = {
                    "angle": free_center + offset,
                    "orbit_r": ring_r,
                    "class_uri": cls_uri,
                }
            ring += 1

    return result


# ── Data builder ──────────────────────────────────────────────────────────────


def build_vowl_graph(taxonomy: Taxonomy) -> dict:
    """Serialise *taxonomy* into a VOWL-style ``{nodes, links, layout}`` payload."""
    nodes: list[dict] = []
    links: list[dict] = []
    seen_nodes: set[str] = set()

    def add_node(uri: str, label: str, node_type: str, detail: dict | None = None) -> None:
        if uri not in seen_nodes:
            seen_nodes.add(uri)
            nodes.append(
                {
                    "id": uri,
                    "label": label,
                    "fullLabel": label,
                    "type": node_type,
                    "detail": detail or {},
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
                links.append({"source": uri, "target": parent, "type": "subClassOf", "label": ""})

    # Object-property T-Box edges (domain class → range class)
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != "ObjectProperty":
            continue
        plabel = prop.label("en")
        for domain_uri in prop.domains:
            for range_uri in prop.ranges:
                if domain_uri in seen_nodes and range_uri in seen_nodes:
                    edge: dict = {
                        "source": domain_uri,
                        "target": range_uri,
                        "type": "objectProperty",
                        "label": plabel,
                    }
                    if prop.is_functional:
                        edge["cardinality"] = "0..1"
                    links.append(edge)

    # DatatypeProperty T-Box edges (domain class → datatype node)
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != "DatatypeProperty":
            continue
        plabel = prop.label("en")
        for domain_uri in prop.domains:
            if domain_uri not in seen_nodes:
                continue
            for range_uri in prop.ranges:
                if range_uri in seen_nodes:
                    continue  # range is already a class node — skip
                add_node(range_uri, _local(range_uri), "datatype")
                links.append(
                    {
                        "source": domain_uri,
                        "target": range_uri,
                        "type": "datatypeProperty",
                        "label": plabel,
                    }
                )

    # rdf:type  (individual → class)
    for uri, ind in taxonomy.owl_individuals.items():
        for type_uri in ind.types:
            if is_builtin_uri(type_uri):
                continue
            if type_uri not in seen_nodes:
                add_node(type_uri, _local(type_uri), "class", {})
            links.append({"source": uri, "target": type_uri, "type": "instanceOf", "label": ""})

    # SKOS ConceptSchemes
    for uri, scheme in taxonomy.schemes.items():
        add_node(uri, scheme.title("en"), "scheme", _detail_scheme(scheme, taxonomy))

    # SKOS Concepts
    top_concept_uris: set[str] = {u for u, c in taxonomy.concepts.items() if c.top_concept_of}
    for uri, concept in taxonomy.concepts.items():
        ntype = "topconcept" if uri in top_concept_uris else "concept"
        add_node(uri, concept.pref_label("en"), ntype, _detail_concept(concept, taxonomy))

    # SKOS broader
    for uri, concept in taxonomy.concepts.items():
        for broader_uri in concept.broader:
            if broader_uri in seen_nodes and uri in seen_nodes:
                links.append({"source": uri, "target": broader_uri, "type": "broader", "label": ""})

    # SKOS inScheme
    for uri, concept in taxonomy.concepts.items():
        if concept.top_concept_of and concept.top_concept_of in seen_nodes:
            links.append(
                {"source": uri, "target": concept.top_concept_of, "type": "inScheme", "label": ""}
            )

    has_skos = bool(taxonomy.schemes) or bool(taxonomy.concepts)
    layout = "hierarchical" if (bool(taxonomy.owl_classes) and not has_skos) else "force"

    result: dict = {"nodes": nodes, "links": links, "layout": layout}

    if layout == "hierarchical":
        root_order = _root_class_order(taxonomy)
        orbit_map = _individual_orbit_data(taxonomy, root_order)
        result["rootClassOrder"] = root_order

        # Embed orbit data into individual nodes
        node_by_id = {n["id"]: n for n in nodes}
        for ind_uri, od in orbit_map.items():
            node = node_by_id.get(ind_uri)
            if node:
                node["orbitAngle"] = od["angle"]
                node["orbitR"] = od["orbit_r"]
                node["orbitClassUri"] = od["class_uri"]

        # Add groupRadius to class nodes so the JS collision force reserves
        # enough space for each class together with its orbiting individuals.
        non_root = {
            cls_uri
            for cls_uri, cls in taxonomy.owl_classes.items()
            for p in cls.sub_class_of
            if not is_builtin_uri(p) and p in taxonomy.owl_classes
        }
        class_orbit_r: dict[str, int] = {}
        for od in orbit_map.values():
            cu = od["class_uri"]
            class_orbit_r[cu] = max(class_orbit_r.get(cu, 0), od["orbit_r"])

        for node in nodes:
            if node["type"] != "class":
                continue
            cls_r = _SUB_CLASS_R if node["id"] in non_root else _ROOT_CLASS_R
            orb_r = class_orbit_r.get(node["id"], 0)
            node["groupRadius"] = (orb_r + _INDIVIDUAL_R) if orb_r else (cls_r + 28)

    return result


def build_focused_vowl_graph(taxonomy: Taxonomy, root_uri: str) -> dict:
    """Serialise a focused subgraph rooted at *root_uri* into VOWL payload.

    Collects the root class, all transitive subclasses (downward), and the
    individuals that belong to any of those classes.  Object/datatype property
    edges between included nodes are also included.
    """
    if root_uri not in taxonomy.owl_classes:
        return {"nodes": [], "links": [], "layout": "hierarchical"}

    # BFS downward through subClassOf (children point UP, so invert the index)
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
    links: list[dict] = []
    seen_nodes: set[str] = set()

    def add_node(uri: str, label: str, node_type: str, detail: dict | None = None) -> None:
        if uri not in seen_nodes:
            seen_nodes.add(uri)
            nodes.append(
                {
                    "id": uri,
                    "label": label,
                    "fullLabel": label,
                    "type": node_type,
                    "detail": detail or {},
                }
            )

    # Class nodes
    for cls_uri in included_classes:
        cls = taxonomy.owl_classes[cls_uri]
        add_node(cls_uri, cls.label("en"), "class", _detail_class(cls, taxonomy))

    # subClassOf links (only within the included set)
    for cls_uri in included_classes:
        cls = taxonomy.owl_classes[cls_uri]
        for parent_uri in cls.sub_class_of:
            if parent_uri in included_classes:
                links.append(
                    {"source": cls_uri, "target": parent_uri, "type": "subClassOf", "label": ""}
                )

    # Object-property edges between included classes
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != "ObjectProperty":
            continue
        plabel = prop.label("en")
        for domain_uri in prop.domains:
            if domain_uri not in included_classes:
                continue
            for range_uri in prop.ranges:
                if range_uri not in seen_nodes:
                    continue
                edge: dict = {
                    "source": domain_uri,
                    "target": range_uri,
                    "type": "objectProperty",
                    "label": plabel,
                }
                if prop.is_functional:
                    edge["cardinality"] = "0..1"
                links.append(edge)

    # DatatypeProperty edges (domain must be in included classes)
    for prop in taxonomy.owl_properties.values():
        if prop.prop_type != "DatatypeProperty":
            continue
        plabel = prop.label("en")
        for domain_uri in prop.domains:
            if domain_uri not in included_classes:
                continue
            for range_uri in prop.ranges:
                if range_uri in seen_nodes:
                    continue
                add_node(range_uri, _local(range_uri), "datatype")
                links.append(
                    {
                        "source": domain_uri,
                        "target": range_uri,
                        "type": "datatypeProperty",
                        "label": plabel,
                    }
                )

    # Individuals of included classes
    for ind_uri, ind in taxonomy.owl_individuals.items():
        for type_uri in ind.types:
            if type_uri in included_classes:
                add_node(ind_uri, ind.label("en"), "individual", _detail_individual(ind, taxonomy))
                links.append(
                    {"source": ind_uri, "target": type_uri, "type": "instanceOf", "label": ""}
                )
                break

    return {"nodes": nodes, "links": links, "layout": "hierarchical"}


# ── SPARQL result subgraph ────────────────────────────────────────────────────


def build_query_result_graph(taxonomy: Taxonomy, uris: set[str]) -> dict:
    """Build a VOWL graph containing only the taxonomy nodes in *uris*.

    Links are included only when both their source and target appear in *uris*.
    Always returns force layout — arbitrary query result subsets have no
    meaningful hierarchy.
    """
    nodes: list[dict] = []
    seen: set[str] = set()

    def _add(uri: str, label: str, node_type: str, detail: dict | None = None) -> None:
        if uri in uris and uri not in seen:
            seen.add(uri)
            nodes.append(
                {
                    "id": uri,
                    "label": label,
                    "fullLabel": label,
                    "type": node_type,
                    "detail": detail or {},
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

    links: list[dict] = []

    for uri, cls in taxonomy.owl_classes.items():
        if uri not in seen:
            continue
        for parent in cls.sub_class_of:
            if not is_builtin_uri(parent) and parent in seen:
                links.append({"source": uri, "target": parent, "type": "subClassOf", "label": ""})

    for uri, ind in taxonomy.owl_individuals.items():
        if uri not in seen:
            continue
        for type_uri in ind.types:
            if not is_builtin_uri(type_uri) and type_uri in seen:
                links.append({"source": uri, "target": type_uri, "type": "instanceOf", "label": ""})

    for uri, concept in taxonomy.concepts.items():
        if uri not in seen:
            continue
        for broader_uri in concept.broader:
            if broader_uri in seen:
                links.append({"source": uri, "target": broader_uri, "type": "broader", "label": ""})
        if concept.top_concept_of and concept.top_concept_of in seen:
            links.append(
                {"source": uri, "target": concept.top_concept_of, "type": "inScheme", "label": ""}
            )

    return {"nodes": nodes, "links": links, "layout": "force"}


def _build_query_result_html(
    taxonomy: Taxonomy,
    uris: set[str],
    file_path: Path | None = None,
) -> tuple[dict, str]:
    """Return (graph_dict, html_str) for a query result viz, or raise ValueError."""
    graph = build_query_result_graph(taxonomy, uris)
    if not graph["nodes"]:
        raise ValueError("No taxonomy nodes matched the query result URIs.")
    title = _ontology_title(taxonomy, file_path) + " — Query results"
    graph_json = json.dumps(graph, ensure_ascii=False)
    meta_json = json.dumps(_taxonomy_meta(taxonomy, file_path), ensure_ascii=False)
    html = (
        _HTML_TEMPLATE.replace("__TITLE__", title)
        .replace('"__GRAPH_DATA__"', graph_json)
        .replace('"__TAXO_META__"', meta_json)
        .replace("__D3_SCRIPT__", _d3_script_tag())
        .replace("__API_TOKEN__", "")
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
    _graph, html = _build_query_result_html(taxonomy, uris, file_path)
    cache = Path.home() / ".cache" / "ster"
    cache.mkdir(parents=True, exist_ok=True)
    stem = (file_path.stem if file_path else "query") + "_sparql_result"
    out = cache / f"{stem}_vowl.html"
    out.write_text(html, encoding="utf-8")
    port = _ensure_server(out.parent)
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
    _graph, html = _build_query_result_html(taxonomy, uris)
    out.write_text(html, encoding="utf-8")
    port = _ensure_server(out.parent)
    url = f"http://127.0.0.1:{port}/{out.name}"
    webbrowser.open(url)


# ── File output ───────────────────────────────────────────────────────────────

_D3_CDN = "https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"


def _d3_script_tag() -> str:
    """Return an inline <script> tag with D3 v7, downloading once to ~/.cache/ster."""
    cache_dir = Path.home() / ".cache" / "ster"
    cache_dir.mkdir(parents=True, exist_ok=True)
    d3_path = cache_dir / "d3.v7.min.js"
    if not d3_path.exists():
        try:
            with urllib.request.urlopen(_D3_CDN, timeout=15) as resp:  # type: ignore[attr-defined]
                d3_path.write_bytes(resp.read())
        except Exception:
            return f'<script src="{_D3_CDN}"></script>'
    return f"<script>{d3_path.read_text()}</script>"


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
    """Start the local HTTP server on first call; return its port on all calls."""
    global _http_server, _http_port
    if _http_server is not None:
        return _http_port  # type: ignore[return-value]
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
    handler = functools.partial(_QuietHandler, directory=str(directory))
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
    WebVOWL view refreshes automatically whenever the ontology file changes.
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
        .replace("__D3_SCRIPT__", _d3_script_tag())
        .replace("__API_TOKEN__", api_token)
    )


def _write_html(taxonomy: Taxonomy, file_path: Path | None, out_path: Path) -> None:
    out_path.write_text(render_vowl_html(taxonomy, file_path), encoding="utf-8")


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
<title>VOWL — __TITLE__</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f1f5f9;color:#1e293b;font-family:system-ui,-apple-system,sans-serif;display:flex;overflow:hidden}
#canvas{flex:1;height:100vh;display:block;background:#fff}
#detail-panel{width:25vw;min-width:200px;max-width:380px;height:100vh;overflow-y:auto;
              background:#f8fafc;border-left:1px solid #e2e8f0;flex-shrink:0}
#panel-close{position:fixed;top:8px;right:8px;background:#f8fafc;border:1px solid #e2e8f0;
             color:#64748b;cursor:pointer;font-size:16px;line-height:1;padding:3px 8px;
             border-radius:4px;z-index:20}
#panel-close:hover{background:#e2e8f0;color:#0f172a}
.node circle{cursor:grab}
.node text{pointer-events:none;font-family:system-ui,sans-serif;fill:white;
           text-anchor:middle;dominant-baseline:central}
.node-individual text{fill:#000}
.node-pinned .pin-dot{display:block}
.pin-dot{display:none;pointer-events:none;fill:#f59e0b}
.link{fill:none}
.link-subClassOf{stroke:#94a3b8;stroke-width:1.5}
.link-objectProperty{stroke:#818cf8;stroke-width:1.5}
.link-datatypeProperty{stroke:#f59e0b;stroke-width:1.5;stroke-dasharray:4 3}
.link-instanceOf{stroke:#c4b5fd;stroke-width:1;stroke-dasharray:3 4;stroke-opacity:.5}
.link-broader{stroke:#6b7280;stroke-width:1.5;stroke-dasharray:5 3}
.link-related{stroke:#f97316;stroke-width:1.5}
.link-inScheme{stroke:#a78bfa;stroke-width:1;stroke-dasharray:3 2;stroke-opacity:.6}
.prop-box rect{fill:white;stroke:#818cf8;stroke-width:1}
.prop-box text{font-size:10px;fill:#4f46e5;text-anchor:middle;dominant-baseline:central;
               pointer-events:none;font-weight:500}
.prop-box-datatypeProperty rect{stroke:#f59e0b}
.prop-box-datatypeProperty text{fill:#92400e}
.dp-hint{font-size:10px;color:#94a3b8;margin:4px 0 0;line-height:1.4}
.dp-indiv-btn{background:none;border:1px solid #cbd5e1;color:#475569;border-radius:6px;
              cursor:pointer;font-size:10px;padding:2px 8px;margin:5px 0 2px;display:block}
.dp-indiv-btn:hover{background:#f1f5f9}
#stats{position:fixed;bottom:10px;left:50%;transform:translateX(-50%);
       font-size:11px;color:#64748b;background:#f8fafc;padding:4px 12px;
       border-radius:20px;border:1px solid #e2e8f0;pointer-events:none}
#hint{position:fixed;bottom:10px;left:12px;font-size:10px;color:#94a3b8;
      background:#f8fafc;padding:3px 8px;border-radius:10px;border:1px solid #e2e8f0}
.ftbtn{background:none;border:1px solid #cbd5e1;color:#94a3b8;border-radius:6px;
       cursor:pointer;font-size:10px;padding:1px 6px;text-decoration:line-through}
.ftbtn.active{color:#475569;border-color:#94a3b8;text-decoration:none}
.ftbtn:hover{background:#f1f5f9}
#tip{position:fixed;pointer-events:none;background:#1e293b;border:1px solid #334155;
     border-radius:6px;padding:6px 10px;font-size:11px;color:#e2e8f0;
     max-width:280px;word-break:break-all;display:none;z-index:99}
.dp{padding:14px}
.dp-h2{font-size:15px;font-weight:600;color:#0f172a;margin-bottom:3px;line-height:1.3}
.dp-h3{font-size:13px;font-weight:600;color:#1e293b;margin-bottom:5px;line-height:1.3;word-break:break-word}
.dp-uri{font-size:10px;color:#94a3b8;word-break:break-all;margin-bottom:10px}
.dp-badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;
          font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}
.dp-class{background:#dbeafe;color:#1d4ed8}
.dp-individual{background:#fef3c7;color:#92400e}
.dp-concept{background:#dcfce7;color:#166534}
.dp-topconcept{background:#cffafe;color:#0e7490}
.dp-scheme{background:#ede9fe;color:#6d28d9}
.dp-section{margin:8px 0}
.dp-row{display:flex;justify-content:space-between;align-items:center;
        padding:3px 0;border-bottom:1px solid #f1f5f9;font-size:11px;color:#334155}
.dp-row span:first-child{color:#64748b}
.dp-hr{border:none;border-top:1px solid #e2e8f0;margin:10px 0}
.dp-sub{font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px}
.dp-lbl{margin:2px 0;font-size:11px;line-height:1.3}
.dp-lang{color:#94a3b8;font-size:10px;margin-right:4px}
.dp-pref{font-weight:600;color:#1e293b}
.dp-alt{color:#64748b;font-style:italic}
.dp-desc{color:#334155;font-size:11px;line-height:1.5;margin:8px 0}
.dp-rel{padding:3px 0;border-bottom:1px solid #f1f5f9;font-size:11px;
        display:flex;align-items:baseline;gap:6px}
.dp-rel-tag{color:#94a3b8;font-size:10px;min-width:72px;flex-shrink:0}
.dp-link{color:#3b82f6;cursor:pointer;background:none;border:none;
         font-size:11px;padding:0;text-align:left}
.dp-link:hover{text-decoration:underline}
.dp-back{background:none;border:none;color:#3b82f6;cursor:pointer;
         font-size:11px;padding:0 0 12px;display:block}
.dp-back:hover{text-decoration:underline}
.lr{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:11px;color:#334155}
.lsvg{flex-shrink:0}
.lline{width:28px;height:0;flex-shrink:0}
</style>
</head>
<body>
<svg id="canvas"></svg>
<div id="detail-panel"></div>
<button id="panel-close" title="Close panel (Esc)">×</button>
<div id="stats"></div>
<div id="hint">drag: move · dbl-click: unpin · click: details · f: re-layout · esc: close<span style="color:#cbd5e1"> │ </span><button class="ftbtn active" id="ft-instanceOf" onclick="toggleLink('instanceOf')">rdf:type</button><button class="ftbtn active" id="ft-inScheme" onclick="toggleLink('inScheme')">inScheme</button><button class="ftbtn active" id="ft-datatypeProperty" onclick="toggleLink('datatypeProperty')">datatype</button></div>
<div id="tip"></div>
<div id="err" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(220,38,38,.95);color:#fff;padding:24px;font-family:monospace;font-size:13px;z-index:200;white-space:pre-wrap;overflow:auto"></div>
__D3_SCRIPT__
<script>
function _showVowlErr(msg){var el=document.getElementById('err');if(el){el.textContent='VOWL error — open browser DevTools (F12\\u2192Console) for details:\\n\\n'+msg;el.style.display='block';}}
window.onerror=function(msg,src,line,col,err){_showVowlErr((err&&err.stack)||msg);return true;};
(function(){
try{
if(typeof d3==='undefined'){ _showVowlErr('D3 library failed to load.'); return; }
const graphData = "__GRAPH_DATA__";
const taxoMeta  = "__TAXO_META__";

const panelEl = document.getElementById('detail-panel');
let panelVisible = true;
let W = window.innerWidth - panelEl.offsetWidth;
const H = window.innerHeight;
document.getElementById('stats').style.left = (W/2)+'px';
const svg = d3.select("#canvas");
const defs = svg.append("defs");

// ── Arrow markers ────────────────────────────────────────────────────────────

// subClassOf: hollow triangle (VOWL / UML inheritance)
defs.append("marker").attr("id","arr-subClassOf")
  .attr("viewBox","0 -5 10 10").attr("refX",10).attr("refY",0)
  .attr("markerWidth",8).attr("markerHeight",8).attr("orient","auto")
  .append("path").attr("d","M0,-5L10,0L0,5Z")
  .attr("fill","white").attr("stroke","#94a3b8").attr("stroke-width",1.5);

// objectProperty: solid indigo
defs.append("marker").attr("id","arr-objectProperty")
  .attr("viewBox","0 -4 8 8").attr("refX",8).attr("refY",0)
  .attr("markerWidth",6).attr("markerHeight",6).attr("orient","auto")
  .append("path").attr("d","M0,-4L8,0L0,4Z").attr("fill","#818cf8");

// instanceOf
defs.append("marker").attr("id","arr-instanceOf")
  .attr("viewBox","0 -3 6 6").attr("refX",6).attr("refY",0)
  .attr("markerWidth",4).attr("markerHeight",4).attr("orient","auto")
  .append("path").attr("d","M0,-3L6,0L0,3Z").attr("fill","#c4b5fd").attr("opacity",.5);

// broader
defs.append("marker").attr("id","arr-broader")
  .attr("viewBox","0 -4 8 8").attr("refX",8).attr("refY",0)
  .attr("markerWidth",6).attr("markerHeight",6).attr("orient","auto")
  .append("path").attr("d","M0,-4L8,0L0,4Z").attr("fill","#6b7280");

// inScheme
defs.append("marker").attr("id","arr-inScheme")
  .attr("viewBox","0 -4 8 8").attr("refX",8).attr("refY",0)
  .attr("markerWidth",6).attr("markerHeight",6).attr("orient","auto")
  .append("path").attr("d","M0,-4L8,0L0,4Z").attr("fill","#a78bfa");

// datatypeProperty
defs.append("marker").attr("id","arr-datatypeProperty")
  .attr("viewBox","0 -3 6 6").attr("refX",6).attr("refY",0)
  .attr("markerWidth",4).attr("markerHeight",4).attr("orient","auto")
  .append("path").attr("d","M0,-3L6,0L0,3Z").attr("fill","#f59e0b");

const root = svg.append("g");
const zoomBehavior = d3.zoom().scaleExtent([0.05,8])
  .on("zoom",e=>root.attr("transform",e.transform));
svg.call(zoomBehavior);

const nodes = graphData.nodes;
const links = graphData.links;
const nodeById = Object.fromEntries(nodes.map(n=>[n.id,n]));

// ── Individual visibility state ───────────────────────────────────────────────
const classIndividualsMap={};
links.forEach(l=>{
  if(l.type!=="instanceOf") return;
  const cUri=l.target, iUri=l.source;
  (classIndividualsMap[cUri]=classIndividualsMap[cUri]||[]).push(iUri);
});
const hiddenIndivClasses=new Set();
const hiddenIndivUris=new Set();

// ── Pair-arc computation (curves for parallel edges) ─────────────────────────
const pairCount={}, pairIdx={};
links.forEach(l=>{
  const k=[l.source,l.target].sort().join("\x00");
  pairCount[k]=(pairCount[k]||0)+1;
});
links.forEach(l=>{
  const k=[l.source,l.target].sort().join("\x00");
  pairIdx[k]=(pairIdx[k]||0);
  l._arc=(pairIdx[k]-(pairCount[k]-1)/2)*(l.type==="objectProperty"?90:55);
  pairIdx[k]++;
});

// ── Class hierarchy maps ──────────────────────────────────────────────────────
const subClassOfParentMap={};
const subClassOfChildMap={};
nodes.forEach(n=>{ subClassOfChildMap[n.id]=[]; });
links.forEach(l=>{
  if(l.type!=="subClassOf") return;
  if(!subClassOfParentMap[l.source]) subClassOfParentMap[l.source]=l.target;
  (subClassOfChildMap[l.target]=subClassOfChildMap[l.target]||[]).push(l.source);
});

const broaderMap={};
const childrenMap={};
nodes.forEach(n=>{ childrenMap[n.id]=[]; });
links.forEach(l=>{
  if(l.type!=="broader") return;
  broaderMap[l.source]=l.target;
  (childrenMap[l.target]=childrenMap[l.target]||[]).push(l.source);
});

// ── Layout flags ──────────────────────────────────────────────────────────────
const topConcepts=nodes.filter(n=>n.type==="topconcept");
const schemeNodes=nodes.filter(n=>n.type==="scheme");
const hasClusters=topConcepts.length>0;
const isHierarchical=!hasClusters&&graphData.layout==="hierarchical";

const rootClasses=!hasClusters
  ?nodes.filter(n=>n.type==="class"&&!subClassOfParentMap[n.id])
  :[];

// ── Hierarchical depth + lane assignment (OWL-only mode) ────────────────────
const owlHierDepth={};
let maxHierDepth=0;
if(isHierarchical&&rootClasses.length>0){
  rootClasses.forEach(rc=>{ owlHierDepth[rc.id]=0; });
  let bfsQ=rootClasses.map(rc=>rc.id);
  while(bfsQ.length){
    const next=[];
    bfsQ.forEach(id=>{
      (subClassOfChildMap[id]||[]).forEach(cid=>{
        if(owlHierDepth[cid]===undefined){
          owlHierDepth[cid]=owlHierDepth[id]+1;
          if(owlHierDepth[cid]>maxHierDepth) maxHierDepth=owlHierDepth[cid];
          next.push(cid);
        }
      });
    });
    bfsQ=next;
  }
  // ── Step 1: order root classes using Python-computed rootClassOrder ──
  if(graphData.rootClassOrder&&rootClasses.length>1){
    const rcIdx={};
    graphData.rootClassOrder.forEach((u,i)=>{ rcIdx[u]=i; });
    rootClasses.sort((a,b)=>(rcIdx[a.id]??rootClasses.length)-(rcIdx[b.id]??rootClasses.length));
  }
  // ── Step 2: assign lanes (uses the now-ordered rootClasses) ──────────────────
  const hierLaneW=W/Math.max(rootClasses.length,1);
  rootClasses.forEach((rc,i)=>{ rc._hierLaneX=hierLaneW*(i+0.5); });
  nodes.forEach(n=>{
    let cur=n.id, rootId=null;
    for(let d=0;d<40&&cur;d++){
      if(owlHierDepth[cur]===0){ rootId=cur; break; }
      cur=subClassOfParentMap[cur];
    }
    const rcNode=rootId?nodeById[rootId]:null;
    n._hierLaneX=rcNode?rcNode._hierLaneX:W/2;
  });
  // ── Step 3: spread siblings within each subtree + align individual lanes ──
  spreadSubtrees();
}
function hierTargetY(d){
  if(d.orbitClassUri){
    const dep=owlHierDepth[d.orbitClassUri];
    if(dep!==undefined) return 70+dep*Math.max((H-160)/(maxHierDepth+2),90);
  }
  const depth=owlHierDepth[d.id]!==undefined?owlHierDepth[d.id]:maxHierDepth+1;
  return 70+depth*Math.max((H-160)/(maxHierDepth+2),90);
}
// Spread sibling class nodes within each subtree lane to minimise subClassOf crossings.
// Sorts each depth level by the parent's X position and evenly spaces siblings
// within the lane width, so parent→child edges never interleave.
function spreadSubtrees(){
  const laneW=W/Math.max(rootClasses.length,1);
  rootClasses.forEach(rc=>{
    const subX={};
    subX[rc.id]=rc._hierLaneX;
    // BFS within this subtree, collecting nodes by depth
    const byDepth=[[rc.id]];
    const seen=new Set([rc.id]);
    let front=[rc.id];
    while(front.length){
      const next=[];
      front.forEach(id=>(subClassOfChildMap[id]||[]).forEach(cId=>{
        if(!seen.has(cId)&&nodeById[cId]&&nodeById[cId].type==="class"){
          seen.add(cId);next.push(cId);
        }
      }));
      if(next.length) byDepth.push(next);
      front=next;
    }
    byDepth.forEach((depthNodes,d)=>{
      if(d===0) return;
      const n=depthNodes.length;
      // Sort by parent X to preserve parent ordering → no crossing between subtrees
      depthNodes.sort((a,b)=>(subX[subClassOfParentMap[a]]??rc._hierLaneX)-(subX[subClassOfParentMap[b]]??rc._hierLaneX));
      const spread=Math.min(laneW*0.88,(n-1)*110);
      depthNodes.forEach((id,i)=>{
        subX[id]=n===1?rc._hierLaneX:rc._hierLaneX+(i-(n-1)/2)*(spread/Math.max(n-1,1));
      });
    });
    seen.forEach(id=>{ const nd=nodeById[id]; if(nd) nd._hierLaneX=subX[id]; });
  });
  // Re-align each individual to its class's (possibly updated) lane X
  nodes.forEach(n=>{
    if(!n.orbitClassUri) return;
    const cls=nodeById[n.orbitClassUri]; if(cls) n._hierLaneX=cls._hierLaneX||W/2;
  });
}

// ── SKOS cluster lane assignment ─────────────────────────────────────────────
const clusterHue={};
topConcepts.forEach((tc,i)=>{
  clusterHue[tc.id]=Math.round((i/topConcepts.length)*360+200)%360;
});
function clusterOf(id,depth){
  if(depth>20) return null;
  const n=nodeById[id]; if(!n) return null;
  if(n.type==="topconcept") return id;
  const b=broaderMap[id];
  return b?clusterOf(b,depth+1):null;
}
nodes.forEach(n=>{ n._cluster=(n.type==="topconcept")?n.id:clusterOf(n.id,0); });
const laneWidth=hasClusters?W/(topConcepts.length+1):W;
if(hasClusters){
  topConcepts.forEach((tc,i)=>{ tc._laneX=laneWidth*(i+1); });
  nodes.forEach(n=>{
    if(n.type==="scheme"){ n._laneX=W/2; return; }
    if(n._cluster){ n._laneX=(nodeById[n._cluster]||{})._laneX||W/2; return; }
    n._laneX=W/2;
  });
}
function depthOf(id,visited){
  if(visited.has(id)) return 99;
  visited.add(id);
  const n=nodeById[id]; if(!n) return 1;
  if(n.type==="topconcept") return 0;
  const b=broaderMap[id]; if(!b) return 1;
  const bd=depthOf(b,visited);
  return bd<0?1:bd+1;
}
nodes.forEach(n=>{
  if(n.type==="scheme")          n._depth=-1;
  else if(n.type==="topconcept") n._depth=0;
  else                            n._depth=depthOf(n.id,new Set());
});
function tierY(n){
  if(n.type==="scheme")     return H*0.04;
  if(n.type==="topconcept") return H*0.14;
  const d=Math.min(n._depth||1,4);
  return H*(0.14+d*0.18);
}

// ── Node geometry ─────────────────────────────────────────────────────────────
function isRoot(d){ return d.type==="class"&&!subClassOfParentMap[d.id]; }
function nodeRadius(d){
  if(d.type==="datatype") return Math.max((d.label||"").length*3.5+12,20);
  if(d.type==="class") return isRoot(d)?50:40;
  if(d.type==="scheme") return 44;
  if(d.type==="topconcept") return 36;
  if(d.type==="individual") return d._expandR||34;
  return 28;
}
// Group footprint for collision: Python pre-computes groupRadius for class nodes
function nodeRadiusColl(d){ return d.groupRadius||nodeRadius(d)+28; }
// Render a node label inside a circle of radius r at font size fs.
// Words wrap greedily to fit the circle width. If all wrapped lines fit
// vertically the block is centred; if there are more lines than fit the text
// starts at the top of the circle and the last visible line ends with "…".
function renderLabel(textEl,label,r,fs){
  textEl.each(function(){ while(this.firstChild) this.removeChild(this.firstChild); });
  if(!label) return;
  const lh=fs*1.3;
  const pad=4;
  const charW=fs*0.62;
  // Maximum chars per line and maximum lines that fit inside the circle
  const maxCpl=Math.max(Math.floor((r*2-pad*2)*0.88/charW),4);
  const maxLines=Math.max(Math.floor((r*2-pad*2)/lh),1);
  const words=label.split(/\\s+/).filter(Boolean);
  // Pre-truncate each token so no single word ever exceeds one line, then wrap
  const allLines=[];
  let cur='';
  for(const w of words){
    const tok=w.length>maxCpl?w.slice(0,maxCpl-1)+'…':w;
    const test=cur?cur+' '+tok:tok;
    if(cur&&test.length>maxCpl){ allLines.push(cur); cur=tok; }
    else cur=test;
  }
  if(cur) allLines.push(cur);
  // Clip to maxLines; mark last visible line with "…" when content is cut off
  const overflow=allLines.length>maxLines;
  const visLines=overflow?allLines.slice(0,maxLines):[...allLines];
  if(overflow){
    let last=visLines[visLines.length-1];
    if(!last.endsWith('…'))
      last=last.length>=maxCpl?last.slice(0,maxCpl-1)+'…':last+'…';
    visLines[visLines.length-1]=last;
  }
  const n=visLines.length;
  if(n===0) return;
  if(n===1){ textEl.text(visLines[0]); return; }
  if(overflow){
    // Top-aligned: first line near the top of the circle
    const yTop=-(r-pad-lh/2);
    visLines.forEach((line,i)=>{
      textEl.append("tspan").attr("x",0).attr("y",yTop+i*lh)
        .attr("dominant-baseline","central").text(line);
    });
  } else {
    // All lines fit: centre the block vertically
    visLines.forEach((line,i)=>{
      textEl.append("tspan").attr("x",0).attr("y",(i-(n-1)/2)*lh)
        .attr("dominant-baseline","central").text(line);
    });
  }
}

// ── Node colours (VOWL palette) ───────────────────────────────────────────────
function nodeFill(d){
  if(d.type==="datatype") return "#fef3c7";
  if(d.type==="class") return "#3c6ebf";
  if(d.type==="individual") return "#7fb8e0";
  if(d.type==="scheme") return "#7c3aed";
  if(d.type==="topconcept"){
    const hue=d._cluster?clusterHue[d._cluster]:null;
    return hue!=null?`hsl(${hue},65%,28%)`:"#0e7490";
  }
  if(d.type==="concept"){
    const hue=d._cluster?clusterHue[d._cluster]:null;
    if(hue!=null){
      const dep=Math.max(0,d._depth||0);
      return `hsl(${hue},60%,${Math.max(16,30-dep*5)}%)`;
    }
    return "#166534";
  }
  return "#64748b";
}
function nodeStroke(d){
  if(d.type==="datatype") return "#f59e0b";
  if(d.type==="class") return isRoot(d)?"#6694d1":"#5a87cc";
  if(d.type==="individual") return "#4a90c4";
  if(d.type==="scheme") return "#a78bfa";
  if(d.type==="topconcept"){
    const hue=d._cluster?clusterHue[d._cluster]:null;
    return hue!=null?`hsl(${hue},80%,52%)`:"#22d3ee";
  }
  if(d.type==="concept"){
    const hue=d._cluster?clusterHue[d._cluster]:null;
    return hue!=null?`hsl(${hue},80%,52%)`:"#4ade80";
  }
  return "#94a3b8";
}

// ── Seed positions ────────────────────────────────────────────────────────────
function seedPositions(){
  nodes.forEach(n=>{ n.vx=0; n.vy=0; n.fx=null; n.fy=null; });
  if(hasClusters){
    schemeNodes.forEach(s=>{ s.x=W/2; s.y=H*0.04; });
    topConcepts.forEach(tc=>{ tc.x=tc._laneX; tc.y=H*0.14; tc.fx=tc._laneX; tc.fy=H*0.14; });
    nodes.forEach(n=>{
      if(n.type==="topconcept"||n.type==="scheme") return;
      n.x=(n._laneX||W/2)+(Math.random()-0.5)*laneWidth*0.5;
      n.y=tierY(n)+(Math.random()-0.5)*40;
    });
  } else if(isHierarchical){
    nodes.forEach(n=>{
      if(n.orbitClassUri){
        const cls=nodeById[n.orbitClassUri];
        const cx=cls?(cls._hierLaneX||W/2):W/2;
        n.x=cx+Math.cos(n.orbitAngle)*(n.orbitR||65);
        n.y=hierTargetY(n)+Math.sin(n.orbitAngle)*(n.orbitR||65);
      } else {
        n.x=(n._hierLaneX||W/2)+(Math.random()-0.5)*50;
        n.y=hierTargetY(n)+(Math.random()-0.5)*20;
      }
    });
  } else {
    nodes.forEach(n=>{
      n.x=W/2+(Math.random()-0.5)*Math.min(W,H)*0.6;
      n.y=H/2+(Math.random()-0.5)*Math.min(W,H)*0.6;
    });
  }
}
seedPositions();

// ── Force simulation ──────────────────────────────────────────────────────────
// Custom collision for hierarchical OWL layout: skips class ↔ own-individual and
// same-class individual pairs so the orbit force can hold individuals close to
// their class without being overridden by the group's own collision radius.
function hierCollide(alpha){
  for(let i=0;i<nodes.length;i++){
    const ni=nodes[i];
    const ri=ni.orbitClassUri?nodeRadius(ni):(ni.groupRadius||nodeRadius(ni)+28);
    for(let j=i+1;j<nodes.length;j++){
      const nj=nodes[j];
      if(ni.type==="class"&&nj.orbitClassUri===ni.id) continue;
      if(nj.type==="class"&&ni.orbitClassUri===nj.id) continue;
      if(ni.orbitClassUri&&ni.orbitClassUri===nj.orbitClassUri) continue;
      const rj=nj.orbitClassUri?nodeRadius(nj):(nj.groupRadius||nodeRadius(nj)+28);
      const dx=nj.x-ni.x,dy=nj.y-ni.y,d2=dx*dx+dy*dy;
      const minD=ri+rj+2;
      if(d2>0&&d2<minD*minD){
        const dist=Math.sqrt(d2),k=(minD-dist)/dist*alpha*0.5;
        const fx=dx*k,fy=dy*k;
        if(!ni.fx){ni.vx-=fx;ni.vy-=fy;}
        if(!nj.fx){nj.vx+=fx;nj.vy+=fy;}
      }
    }
  }
}
const sim=d3.forceSimulation()
  .alphaDecay(0.016)
  .force("collide",isHierarchical?hierCollide:d3.forceCollide(nodeRadiusColl).iterations(3));

if(hasClusters){
  sim.force("link",d3.forceLink().id(d=>d.id)
    .distance(d=>d.type==="inScheme"?H*0.12:d.type==="broader"?H*0.17:150).strength(0.12))
  .force("charge",d3.forceManyBody().strength(d=>d.type==="topconcept"?-800:d.type==="scheme"?-400:-200))
  .force("cx",d3.forceX(d=>d._laneX||W/2).strength(d=>d.type==="scheme"?0.04:0.35))
  .force("cy",d3.forceY(d=>tierY(d)).strength(d=>d.type==="scheme"?0.98:d.type==="topconcept"?0.85:0.70));
} else if(isHierarchical){
  sim.force("link",d3.forceLink().id(d=>d.id).distance(130).strength(0.10))
  .force("charge",d3.forceManyBody().strength(d=>d.type==="individual"?-80:isRoot(d)?-2000:-600))
  // Classes: strong lane forces so subtrees don't drift and cross each other
  .force("cx",d3.forceX(d=>d._hierLaneX||W/2).strength(d=>d.orbitClassUri?0:0.65))
  .force("cy",d3.forceY(d=>hierTargetY(d)).strength(d=>d.orbitClassUri?0:0.75))
  // Individuals: pulled toward their Python-computed orbital position around their class
  .force("orbit",function(alpha){
    nodes.forEach(n=>{
      if(!n.orbitClassUri) return;
      const cls=nodeById[n.orbitClassUri];
      if(!cls||cls.x==null||cls.y==null) return;
      const angle=n._expandAngle!=null?n._expandAngle:n.orbitAngle;
      const orbitR=n._expandOrbitR!=null?n._expandOrbitR:(n.orbitR||65);
      const tx=cls.x+Math.cos(angle)*orbitR;
      const ty=cls.y+Math.sin(angle)*orbitR;
      n.vx+=(tx-n.x)*0.9*alpha;
      n.vy+=(ty-n.y)*0.9*alpha;
    });
  });
} else {
  sim.force("link",d3.forceLink().id(d=>d.id).distance(180).strength(0.2))
  .force("charge",d3.forceManyBody().strength(-800))
  .force("cx",d3.forceX(W/2).strength(0.04))
  .force("cy",d3.forceY(H/2).strength(0.04));
}

// ── Edge path ─────────────────────────────────────────────────────────────────
function edgePath(d){
  const s=d.source, t=d.target;
  if(!s||!t) return "";
  const dx=t.x-s.x, dy=t.y-s.y;
  const dist=Math.sqrt(dx*dx+dy*dy)||1;
  const sr=nodeRadius(s)+2, tr=nodeRadius(t)+2;
  if(dist<sr+tr) return "";
  const sx=s.x+dx/dist*sr, sy=s.y+dy/dist*sr;
  const tx=t.x-dx/dist*tr, ty=t.y-dy/dist*tr;
  const arc=(d._arc||0)+(d._arcDyn||0);
  if(Math.abs(arc)<1) return `M${sx},${sy}L${tx},${ty}`;
  const mx=(sx+tx)/2-dy/dist*arc, my=(sy+ty)/2+dx/dist*arc;
  return `M${sx},${sy}Q${mx},${my} ${tx},${ty}`;
}
function propBoxPos(d){
  const s=d.source, t=d.target;
  if(!s||!t) return [0,0];
  const arc=(d._arc||0)+(d._arcDyn||0);
  if(Math.abs(arc)<1) return [(s.x+t.x)/2,(s.y+t.y)/2];
  const dx=t.x-s.x, dy=t.y-s.y, dist=Math.sqrt(dx*dx+dy*dy)||1;
  const qx=(s.x+t.x)/2-dy/dist*arc, qy=(s.y+t.y)/2+dx/dist*arc;
  return [0.25*s.x+0.5*qx+0.25*t.x, 0.25*s.y+0.5*qy+0.25*t.y];
}

// ── Rendering layers: indivG < linkG < propBoxG < classNodeG ─────────────────
const indivG=root.append("g");
const linkG=root.append("g");
const propBoxG=root.append("g");
const classNodeG=root.append("g");

const hiddenLinkTypes=new Set();
function applyLinkVis(){
  linkSel.style("display",d=>{
    if(hiddenLinkTypes.has(d.type)) return "none";
    if(d.type==="instanceOf"){
      const iUri=typeof d.source==="object"?d.source.id:d.source;
      if(hiddenIndivUris.has(iUri)) return "none";
    }
    return null;
  });
  propBoxSel.style("display",d=>hiddenLinkTypes.has(d.type)?"none":null);
}
function toggleLink(type){
  const btn=document.getElementById("ft-"+type);
  if(hiddenLinkTypes.has(type)){ hiddenLinkTypes.delete(type); btn.classList.add("active"); }
  else{ hiddenLinkTypes.add(type); btn.classList.remove("active"); }
  applyLinkVis();
}
function applyIndivVis(){
  hiddenIndivUris.clear();
  hiddenIndivClasses.forEach(cUri=>{
    (classIndividualsMap[cUri]||[]).forEach(iUri=>hiddenIndivUris.add(iUri));
  });
  nodeSel.style("display",d=>
    d.type==="individual"&&hiddenIndivUris.has(d.id)?"none":null);
  applyLinkVis();
  nodeSel.filter(d=>d.type==="class").each(function(d){
    const hidden=hiddenIndivClasses.has(d.id);
    d3.select(this).select(".ind-badge").attr("fill",hidden?"#94a3b8":"#7fb8e0");
  });
}
function toggleAllIndividuals(){
  const cKeys=Object.keys(classIndividualsMap);
  const allHidden=cKeys.length>0&&cKeys.every(c=>hiddenIndivClasses.has(c));
  if(allHidden) cKeys.forEach(c=>hiddenIndivClasses.delete(c));
  else cKeys.forEach(c=>hiddenIndivClasses.add(c));
  applyIndivVis();
  const btn=document.getElementById("btn-toggle-indivs");
  if(btn){
    const nowAllHidden=cKeys.every(c=>hiddenIndivClasses.has(c));
    btn.textContent=nowAllHidden?"Show all individuals":"Hide all individuals";
  }
}

// Links
let linkSel=linkG.selectAll("path")
  .data(links,d=>`${d.source}|${d.target}|${d.type}`)
  .join("path")
  .attr("class",d=>`link link-${d.type}`)
  .attr("marker-end",d=>`url(#arr-${d.type})`);

// Property label boxes (objectProperty + datatypeProperty edges with labels)
const propLinks=links.filter(l=>(l.type==="objectProperty"||l.type==="datatypeProperty")&&l.label);
let propBoxSel=propBoxG.selectAll("g")
  .data(propLinks,d=>`${d.source}|${d.target}|${d.label}`)
  .join("g").attr("class",d=>`prop-box prop-box-${d.type}`);
propBoxSel.each(function(d){
  const g=d3.select(this);
  const card=d.cardinality||"";
  const h=card?26:18;
  const w=Math.max(Math.max(d.label.length*6.5,card.length*6)+16,44);
  g.append("rect").attr("x",-w/2).attr("y",-h/2).attr("width",w).attr("height",h).attr("rx",4);
  g.append("text").text(d.label).attr("y",card?-4:0);
  if(card) g.append("text").text(card).attr("y",8)
    .attr("font-size","9px").attr("fill","#7c3aed");
});

applyLinkVis();

// Expand/revert state — assigned after node selections are created below
let indivNodeSel,classNodeSel,nodeSel;
let expandedClass=null;

// Saved zoom transform captured when an expand is first opened; null when idle.
let _preExpandTransform=null;

// Internal cleanup: remove expand data and reset DOM without touching zoom.
function _clearExpand(){
  if(!expandedClass) return;
  const prev=expandedClass; expandedClass=null;
  (classIndividualsMap[prev]||[]).forEach(iUri=>{
    const nd=nodeById[iUri]; if(!nd) return;
    delete nd._expandR; delete nd._expandAngle; delete nd._expandOrbitR;
  });
  indivNodeSel.filter(d=>d.orbitClassUri===prev).each(function(d){
    const s=d3.select(this),r=34;
    s.select("circle:not(.pin-dot)").attr("r",r);
    renderLabel(s.select("text"),d.label,r,10);
  });
  sim.alpha(0.3).restart();
}

function applyExpand(classId){
  // Silently collapse any previous expand (no zoom restore when switching classes)
  _clearExpand();
  expandedClass=classId;
  const cls=nodeById[classId];
  const clsR=cls?nodeRadius(cls):40;
  const indR=34;
  const firstRingR=clsR+indR+12;
  const ringGap=6;
  const indivs=classIndividualsMap[classId]||[];
  let remaining=indivs.slice();
  let ring=0;
  let maxOrbitR=firstRingR;
  while(remaining.length>0&&ring<8){
    const ringR=firstRingR+ring*(2*indR+ringGap);
    maxOrbitR=ringR;
    const minStep=2*Math.asin(Math.min(indR/ringR,1));
    const capacity=Math.max(1,Math.floor(Math.PI*2*0.98/minStep));
    const batch=remaining.splice(0,capacity);
    const nb=batch.length;
    batch.forEach((iUri,i)=>{
      const nd=nodeById[iUri]; if(!nd) return;
      nd._expandR=indR;
      nd._expandAngle=-Math.PI/2+Math.PI*2*i/nb;
      nd._expandOrbitR=ringR;
    });
    ring++;
  }
  indivNodeSel.filter(d=>d.orbitClassUri===classId).each(function(d){
    const s=d3.select(this);
    s.select("circle:not(.pin-dot)").attr("r",indR);
    renderLabel(s.select("text"),d.label,indR,10);
  });
  sim.alpha(0.3).restart();
  // Save zoom state only on the first expand in a session
  if(!_preExpandTransform) _preExpandTransform=d3.zoomTransform(svg.node());
  // Collect all highlighted nodes: clicked class + directly connected + their individuals
  const conn=new Set([classId]);
  sim.force("link").links().forEach(l=>{
    const sid=l.source.id||l.source, tid=l.target.id||l.target;
    if(sid===classId) conn.add(tid);
    if(tid===classId) conn.add(sid);
  });
  conn.forEach(nid=>{ (classIndividualsMap[nid]||[]).forEach(iUri=>conn.add(iUri)); });
  // Bounding box of all highlighted nodes using their current positions + radii
  let bx0=Infinity,by0=Infinity,bx1=-Infinity,by1=-Infinity;
  conn.forEach(nid=>{
    const nd=nodeById[nid]; if(!nd||nd.x==null) return;
    const r=nodeRadius(nd);
    bx0=Math.min(bx0,nd.x-r); by0=Math.min(by0,nd.y-r);
    bx1=Math.max(bx1,nd.x+r); by1=Math.max(by1,nd.y+r);
  });
  // Also extend for the expanded-class orbit rings (individuals not yet settled)
  if(cls&&cls.x!=null){
    const er=maxOrbitR+indR+16;
    bx0=Math.min(bx0,cls.x-er); by0=Math.min(by0,cls.y-er);
    bx1=Math.max(bx1,cls.x+er); by1=Math.max(by1,cls.y+er);
  }
  if(isFinite(bx0)){
    const pad=60;
    const k=Math.min(W/(bx1-bx0+pad*2),H/(by1-by0+pad*2));
    const cx=(bx0+bx1)/2, cy=(by0+by1)/2;
    svg.transition().duration(600)
      .call(zoomBehavior.transform,d3.zoomIdentity.translate(W/2-k*cx,H/2-k*cy).scale(k));
  }
}

// Explicit close (Escape / re-click): collapse expand AND restore the saved zoom.
function revertExpand(){
  _clearExpand();
  if(_preExpandTransform){
    svg.transition().duration(400)
      .call(zoomBehavior.transform,_preExpandTransform);
    _preExpandTransform=null;
  }
}

function makeNodes(container,data){
  return container.selectAll("g")
    .data(data,d=>d.id)
    .join(enter=>{
      const g=enter.append("g")
        .attr("class",d=>`node node-${d.type}`)
        .call(d3.drag()
          .on("start",(e,d)=>{ if(!e.active) sim.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
          .on("drag",(e,d)=>{ d.fx=e.x; d.fy=e.y; })
          .on("end",(e,d)=>{ if(!e.active) sim.alphaTarget(0); updatePinMarker(nodeSel); }))
        .on("click",(_,d)=>{
          const newHl=highlighted===d.id?null:d.id;
          highlighted=newHl;
          if(d.type==="class"){ if(newHl) applyExpand(d.id); else revertExpand(); }
          applyHighlight();
          if(newHl){ togglePanel(true); showDetail(d); } else showDefault();
        })
        .on("dblclick",(_,d)=>{ d.fx=null; d.fy=null; updatePinMarker(nodeSel); sim.alpha(0.3).restart(); })
        .on("mouseover",showTip).on("mousemove",moveTip).on("mouseout",hideTip);
      g.each(function(d){
        const s=d3.select(this);
        const r=nodeRadius(d);
        if(d.type==="datatype"){
          const w=Math.max((d.label||"").length*7+16,50), h=22;
          s.append("rect").attr("x",-w/2).attr("y",-h/2).attr("width",w).attr("height",h).attr("rx",4)
            .attr("fill","#fef3c7").attr("stroke","#f59e0b").attr("stroke-width",1.5)
            .style("filter","drop-shadow(0 1px 2px rgba(0,0,0,.08))");
          s.append("text").text(d.label)
            .attr("font-size",10).attr("fill","#92400e").attr("font-weight","500")
            .attr("text-anchor","middle").attr("dominant-baseline","central");
          return;
        }
        const fill=nodeFill(d), stroke=nodeStroke(d);
        if(d.type==="class"&&isRoot(d)){
          s.append("circle").attr("r",r+9)
            .attr("fill","none").attr("stroke",stroke).attr("stroke-width",1.2).attr("opacity",.35);
        }
        s.append("circle").attr("r",r)
          .attr("fill",fill).attr("stroke",stroke)
          .attr("stroke-width",d.type==="class"&&isRoot(d)?2.5:1.5)
          .style("filter","drop-shadow(0 1px 3px rgba(0,0,0,.12))");
        const fs=d.type==="scheme"?12:d.type==="class"&&isRoot(d)?12:10;
        {const t=s.append("text")
          .attr("font-size",fs)
          .attr("font-weight",d.type==="class"||d.type==="scheme"?"600":"400");
        renderLabel(t,d.label,r,fs);}
        s.append("circle").attr("class","pin-dot")
          .attr("cx",r-6).attr("cy",-r+6).attr("r",4)
          .attr("stroke","white").attr("stroke-width",1.5);
        if(d.type==="class"){
          const cnt=(classIndividualsMap[d.id]||[]).length;
          if(cnt>0){
            s.append("circle").attr("class","ind-badge")
              .attr("cx",0).attr("cy",r+13).attr("r",13)
              .attr("fill","#7fb8e0").attr("stroke","white").attr("stroke-width",2)
              .style("cursor","pointer")
              .on("mouseover",function(){
                d3.select(this).attr("r",15).attr("stroke-width",2.5);
              })
              .on("mouseout",function(){
                d3.select(this).attr("r",13).attr("stroke-width",2);
              })
              .on("click",function(e){
                e.stopPropagation();
                if(hiddenIndivClasses.has(d.id)) hiddenIndivClasses.delete(d.id);
                else hiddenIndivClasses.add(d.id);
                applyIndivVis();
              });
            s.append("text").attr("class","ind-badge-text")
              .attr("x",0).attr("y",r+13)
              .attr("text-anchor","middle").attr("dominant-baseline","central")
              .attr("font-size","11px").attr("fill","white")
              .attr("pointer-events","none")
              .text(cnt);
          }
        }
      });
      return g;
    });
}

// Individual nodes rendered in indivG (below edges); all others in classNodeG (above edges)
indivNodeSel=makeNodes(indivG,nodes.filter(d=>d.type==="individual"));
classNodeSel=makeNodes(classNodeG,nodes.filter(d=>d.type!=="individual"));
// Combined selection for highlight, visibility, and tick transforms
nodeSel=d3.selectAll([...indivNodeSel.nodes(),...classNodeSel.nodes()]);

sim.nodes(nodes);
sim.force("link").links(links);
sim.alpha(1).restart();

// ── Tick ──────────────────────────────────────────────────────────────────────
sim.on("tick",()=>{
  // Dynamic arc adjustments for hierarchical OWL layout — recomputed each tick
  // from current node positions so they stay correct after dragging.
  if(isHierarchical){
    // Reset dynamic arcs for all routed edge types
    links.forEach(l=>{
      if(l.type==="objectProperty"||l.type==="subClassOf") l._arcDyn=0;
    });

    // ── 1. objectProperty edge-edge midpoint repulsion ────────────────────────
    const opLinks=links.filter(l=>l.type==="objectProperty");
    for(let i=0;i<opLinks.length;i++){
      const ei=opLinks[i]; if(!ei.source.x) continue;
      for(let j=i+1;j<opLinks.length;j++){
        const ej=opLinks[j]; if(!ej.source.x) continue;
        if(ei.source===ej.source&&ei.target===ej.target) continue;
        if(ei.source===ej.target&&ei.target===ej.source) continue;
        const mx1=(ei.source.x+ei.target.x)/2,my1=(ei.source.y+ei.target.y)/2;
        const mx2=(ej.source.x+ej.target.x)/2,my2=(ej.source.y+ej.target.y)/2;
        const d=Math.hypot(mx1-mx2,my1-my2);
        if(d<60){
          const push=Math.min((60-d)*0.6,24);
          const srcDiff=ei.source.x-ej.source.x;
          const sign=srcDiff!==0?(srcDiff>0?1:-1):(ei.target.x>=ej.target.x?1:-1);
          ei._arcDyn=Math.max(-80,Math.min(80,ei._arcDyn+sign*push));
          ej._arcDyn=Math.max(-80,Math.min(80,ej._arcDyn-sign*push));
        }
      }
    }

    // ── 2. Route objectProperty and subClassOf edges around blocking class nodes ─
    // Uses the signed perpendicular distance from the blocking node to the edge
    // line to determine which side to arc toward, avoiding the zero-vector problem
    // that occurs when a node sits exactly on the edge path.
    links.forEach(edge=>{
      if(edge.type!=="objectProperty"&&edge.type!=="subClassOf") return;
      if(!edge.source.x) return;
      const s=edge.source,t=edge.target;
      const edx=t.x-s.x,edy=t.y-s.y,len2=edx*edx+edy*edy;
      if(len2<1) return;
      const len=Math.sqrt(len2);
      nodes.forEach(n=>{
        if(n.type!=="class"||n===s||n===t) return;
        // Only consider nodes whose projection falls strictly between the endpoints
        const param=((n.x-s.x)*edx+(n.y-s.y)*edy)/len2;
        if(param<=0||param>=1) return;
        // Signed perpendicular distance: positive = node is to the right of s→t
        const cross=(edx*(n.y-s.y)-edy*(n.x-s.x))/len;
        const perpDist=Math.abs(cross);
        const r=nodeRadius(n)+16;
        if(perpDist<r){
          // Geometric minimum arc: the bezier at parameter `param` deviates from the
          // chord by 2·param·(1−param)·arc. Invert to get the arc that fully clears
          // the blocking node. Clamp the bezier factor to avoid huge values near the
          // endpoints, and cap the final arc to keep curves reasonable.
          // In SVG (Y down): cross<0 means node is above/left of the edge line →
          // arc downward (+) to route below; cross>0 → arc upward (−).
          const f=Math.max(2*param*(1-param),0.04);
          const needed=Math.min((r-perpDist)/f+10,200);
          const dir=cross<=0?1:-1;
          edge._arcDyn=Math.max(-200,Math.min(200,edge._arcDyn+dir*needed));
        }
      });
    });

    // ── 3. Avoid objectProperty ↔ subClassOf crossings ──────────────────────
    // Detect straight-line segment intersections between the two edge types and
    // arc each crossing pair apart in opposite perpendicular directions.
    const segCross=(ax,ay,bx,by,cx,cy,dx,dy)=>{
      const abx=bx-ax,aby=by-ay,cdx=dx-cx,cdy=dy-cy;
      const denom=abx*cdy-aby*cdx;
      if(Math.abs(denom)<1e-6) return false;
      const t=((cx-ax)*cdy-(cy-ay)*cdx)/denom;
      const u=((cx-ax)*aby-(cy-ay)*abx)/denom;
      return t>0&&t<1&&u>0&&u<1;
    };
    const scLinks=links.filter(l=>l.type==="subClassOf");
    opLinks.forEach(op=>{
      if(!op.source.x) return;
      scLinks.forEach(sc=>{
        if(!sc.source.x) return;
        // Adjacent edges share a node and cannot truly cross
        if(op.source===sc.source||op.source===sc.target||op.target===sc.source||op.target===sc.target) return;
        if(!segCross(op.source.x,op.source.y,op.target.x,op.target.y,
                     sc.source.x,sc.source.y,sc.target.x,sc.target.y)) return;
        // Determine which side sc's midpoint is relative to op's direction.
        // Positive cross ⟹ sc is to the right of op (in SVG/arc convention) ⟹ arc op left (−).
        const opMx=(op.source.x+op.target.x)/2, opMy=(op.source.y+op.target.y)/2;
        const scMx=(sc.source.x+sc.target.x)/2, scMy=(sc.source.y+sc.target.y)/2;
        const cross=(op.target.x-op.source.x)*(scMy-opMy)-(op.target.y-op.source.y)*(scMx-opMx);
        const opSign=cross>0?-1:1;
        const push=30;
        op._arcDyn=Math.max(-200,Math.min(200,op._arcDyn+opSign*push));
        sc._arcDyn=Math.max(-200,Math.min(200,sc._arcDyn-opSign*push));
      });
    });
  }
  linkSel.attr("d",edgePath);
  propBoxSel.attr("transform",d=>{
    const [px,py]=propBoxPos(d);
    return `translate(${px},${py})`;
  });
  nodeSel.attr("transform",d=>`translate(${d.x},${d.y})`);
});

// ── Stats bar ─────────────────────────────────────────────────────────────────
(function(){
  const c=taxoMeta.counts, p=[];
  if(c.classes)      p.push(c.classes+" class"+(c.classes!==1?"es":""));
  if(c.individuals)  p.push(c.individuals+" individual"+(c.individuals!==1?"s":""));
  if(c.properties)   p.push(c.properties+" propert"+(c.properties!==1?"ies":"y"));
  if(c.schemes)      p.push(c.schemes+" scheme"+(c.schemes!==1?"s":""));
  if(c.top_concepts) p.push(c.top_concepts+" top concept"+(c.top_concepts!==1?"s":""));
  if(c.concepts)     p.push(c.concepts+" concept"+(c.concepts!==1?"s":""));
  document.getElementById("stats").textContent=p.join(" · ");
})();

// ── Highlight ─────────────────────────────────────────────────────────────────
let highlighted=null;
function applyHighlight(){
  if(!highlighted){ nodeSel.style("opacity",1); linkSel.style("opacity",null); propBoxSel.style("opacity",null); return; }
  const conn=new Set([highlighted]);
  sim.force("link").links().forEach(l=>{
    const sid=l.source.id||l.source, tid=l.target.id||l.target;
    if(sid===highlighted) conn.add(tid);
    if(tid===highlighted) conn.add(sid);
  });
  nodeSel.style("opacity",d=>conn.has(d.id)?1:0.08);
  linkSel.style("opacity",d=>{
    const sid=d.source.id||d.source, tid=d.target.id||d.target;
    return (sid===highlighted||tid===highlighted)?1:0.04;
  });
  propBoxSel.style("opacity",d=>{
    const sid=d.source.id||d.source, tid=d.target.id||d.target;
    return (sid===highlighted||tid===highlighted)?1:0.04;
  });
}

// ── Tooltip ───────────────────────────────────────────────────────────────────
const tip=document.getElementById("tip");
const km={class:"Class",individual:"Individual",concept:"Concept",topconcept:"Top Concept",scheme:"Scheme"};
function showTip(e,d){
  tip.innerHTML=`<b>${km[d.type]||d.type}</b><br>${d.fullLabel}<br><span style="color:#64748b;font-size:10px">${d.id}</span>`;
  tip.style.display="block";
}
function moveTip(e){ tip.style.left=(e.clientX+14)+"px"; tip.style.top=(e.clientY+10)+"px"; }
function hideTip(){ tip.style.display="none"; }
function updatePinMarker(sel){ sel.classed("node-pinned",d=>d.fx!=null); }

// ── Panel ─────────────────────────────────────────────────────────────────────
function togglePanel(show){
  const was=panelVisible;
  panelVisible=show!==undefined?show:!panelVisible;
  if(panelVisible===was) return;
  panelEl.style.display=panelVisible?"":"none";
  document.getElementById("panel-close").style.display=panelVisible?"":"none";
  W=window.innerWidth-(panelVisible?panelEl.getBoundingClientRect().width:0);
  if(hasClusters){
    const lw=W/(topConcepts.length+1);
    topConcepts.forEach((tc,i)=>{ tc._laneX=lw*(i+1); });
    nodes.forEach(n=>{
      if(n.type==="scheme") n._laneX=W/2;
      else if(n._cluster) n._laneX=(nodeById[n._cluster]||{})._laneX||W/2;
      else n._laneX=W/2;
    });
    sim.force("cx",d3.forceX(d=>d._laneX||W/2).strength(d=>d.type==="scheme"?0.04:0.35));
  } else if(isHierarchical){
    const hierLaneW2=W/Math.max(rootClasses.length,1);
    rootClasses.forEach((rc,i)=>{ rc._hierLaneX=hierLaneW2*(i+0.5); });
    nodes.forEach(n=>{
      let cur=n.id, rcId=null;
      for(let d=0;d<40&&cur;d++){
        if(owlHierDepth[cur]===0){ rcId=cur; break; }
        cur=subClassOfParentMap[cur];
      }
      const rcNode=rcId?nodeById[rcId]:null;
      n._hierLaneX=rcNode?rcNode._hierLaneX:W/2;
    });
    spreadSubtrees();
    sim.force("cx",d3.forceX(d=>d._hierLaneX||W/2).strength(d=>d.orbitClassUri?0:0.65));
  } else {
    sim.force("cx",d3.forceX(W/2).strength(0.04));
  }
  document.getElementById("stats").style.left=(W/2)+"px";
  sim.alpha(0.4).restart();
}
document.getElementById("panel-close").addEventListener("click",()=>togglePanel());

// ── Keyboard ──────────────────────────────────────────────────────────────────
document.addEventListener("keydown",e=>{
  if(e.key==="Escape"){
    if(highlighted){ highlighted=null; revertExpand(); applyHighlight(); showDefault(); }
    else togglePanel();
  }
  if(e.key==="f"){
    nodes.forEach(n=>{ n.fx=null; n.fy=null; });
    seedPositions();
    updatePinMarker(nodeSel);
    sim.alpha(0.9).restart();
  }
});

// ── Detail panel ──────────────────────────────────────────────────────────────
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function showDefault(){
  highlighted=null;
  const classCount   =nodes.filter(n=>n.type==='class').length;
  const indivCount   =nodes.filter(n=>n.type==='individual').length;
  const propLinkCount=links.filter(l=>l.type==='objectProperty'||l.type==='datatypeProperty').length;
  const schemeCount  =nodes.filter(n=>n.type==='scheme').length;
  const topConCount  =nodes.filter(n=>n.type==='topconcept').length;
  const conceptCount =nodes.filter(n=>n.type==='concept').length;
  let rows='';
  if(classCount)    rows+='<div class="dp-row"><span>Classes</span><span>'+classCount+'</span></div>';
  if(indivCount)    rows+='<div class="dp-row"><span>Individuals</span><span>'+indivCount+'</span></div>';
  if(propLinkCount) rows+='<div class="dp-row"><span>Properties</span><span>'+propLinkCount+'</span></div>';
  if(schemeCount)   rows+='<div class="dp-row"><span>Schemes</span><span>'+schemeCount+'</span></div>';
  if(topConCount)   rows+='<div class="dp-row"><span>Top Concepts</span><span>'+topConCount+'</span></div>';
  if(conceptCount)  rows+='<div class="dp-row"><span>Concepts</span><span>'+conceptCount+'</span></div>';

  const nodeTypes=new Set(nodes.map(n=>n.type));
  const linkTypes=new Set(links.map(l=>l.type));
  const hasRoot=nodes.some(n=>n.type==="class"&&!subClassOfParentMap[n.id]);
  const hasSub=nodes.some(n=>n.type==="class"&&!!subClassOfParentMap[n.id]);

  const NT=[
    ['class-root','<svg width="34" height="16"><circle cx="17" cy="8" r="8" fill="none" stroke="#6694d1" stroke-width="1" opacity=".4"/><circle cx="17" cy="8" r="7" fill="#3c6ebf" stroke="#6694d1" stroke-width="2"/></svg>','Root Class'],
    ['class-sub', '<svg width="34" height="16"><circle cx="17" cy="8" r="6" fill="#3c6ebf" stroke="#5a87cc" stroke-width="1.5"/></svg>','Class'],
    ['individual','<svg width="34" height="16"><circle cx="17" cy="8" r="7" fill="#7fb8e0" stroke="#4a90c4" stroke-width="1.5"/></svg>','Individual'],
    ['topconcept','<svg width="34" height="16"><circle cx="17" cy="8" r="7" fill="#0e7490" stroke="#22d3ee" stroke-width="2"/></svg>','Top Concept'],
    ['concept',   '<svg width="34" height="16"><circle cx="17" cy="8" r="6" fill="#166534" stroke="#4ade80" stroke-width="1.5"/></svg>','Concept'],
    ['scheme',    '<svg width="34" height="16"><circle cx="17" cy="8" r="8" fill="#7c3aed" stroke="#a78bfa" stroke-width="2"/></svg>','Scheme'],
    ['datatype',  '<svg width="50" height="16"><rect x="1" y="2" width="48" height="12" rx="2" fill="#fef3c7" stroke="#f59e0b" stroke-width="1.5"/><text x="25" y="8" text-anchor="middle" dominant-baseline="central" font-size="8" fill="#92400e">literal</text></svg>','Datatype'],
  ];
  const LT=[
    ['subClassOf',       'border-top:2px solid #94a3b8','subClassOf (hollow ▷)'],
    ['objectProperty',   'border-top:2px solid #818cf8','objectProperty'],
    ['datatypeProperty', 'border-top:1.5px dashed #f59e0b','datatypeProperty'],
    ['instanceOf',       'border-top:1px dotted #c4b5fd;opacity:.5','rdf:type'],
    ['broader',          'border-top:2px dashed #6b7280','broader'],
    ['related',          'border-top:2px solid #f97316','related'],
    ['inScheme',         'border-top:1px dotted #a78bfa','inScheme'],
  ];
  let leg='<hr class="dp-hr"><div class="dp-sub">Legend</div>';
  NT.forEach(([t,svg,label])=>{
    let show=false;
    if(t==='class-root') show=hasRoot;
    else if(t==='class-sub') show=hasSub;
    else show=nodeTypes.has(t);
    if(!show) return;
    leg+='<div class="lr">'+svg+label+'</div>';
    if(t==='individual'&&Object.keys(classIndividualsMap).length>0){
      const allHid=Object.keys(classIndividualsMap).every(c=>hiddenIndivClasses.has(c));
      leg+='<button id="btn-toggle-indivs" class="dp-indiv-btn" onclick="toggleAllIndividuals()">'
        +(allHid?'Show all individuals':'Hide all individuals')+'</button>';
      leg+='<div class="dp-hint">Click the count badge on a class to show/hide its individuals.</div>';
    }
  });
  leg+='<hr class="dp-hr"><div class="dp-sub">Relations</div>';
  LT.filter(([t])=>linkTypes.has(t)).forEach(([,style,label])=>{
    leg+='<div class="lr"><div class="lline" style="'+style+'"></div>'+label+'</div>';
  });

  panelEl.innerHTML='<div class="dp">'
    +'<div class="dp-h2">'+esc(taxoMeta.title)+'</div>'
    +(taxoMeta.ontology_uri?'<div class="dp-uri">'+esc(taxoMeta.ontology_uri)+'</div>':'')
    +'<div class="dp-sub" style="margin-top:6px">Overview</div>'
    +'<div class="dp-section">'+rows+'</div>'
    +leg+'</div>';
}

function showDetail(d){
  const det=d.detail||{};
  let h='<div class="dp">';
  h+='<button class="dp-back" onclick="dpBack()">&#8592; Overview</button>';
  h+='<span class="dp-badge dp-'+d.type+'">'+(km[d.type]||d.type)+'</span>';
  h+='<div class="dp-h3">'+esc(d.fullLabel)+'</div>';
  h+='<div class="dp-uri">'+esc(d.id)+'</div>';

  const labels=det.labels||[];
  const prefs=labels.filter(l=>l.kind==='pref');
  const alts=labels.filter(l=>l.kind==='alt');
  const others=labels.filter(l=>l.kind==='label');
  const showLbls=[...prefs.slice(1),...alts,...others];
  if(showLbls.length){
    h+='<hr class="dp-hr"><div class="dp-sub">Labels</div>';
    showLbls.forEach(l=>{
      h+='<div class="dp-lbl">';
      if(l.lang) h+='<span class="dp-lang">['+esc(l.lang)+']</span>';
      h+='<span class="'+(l.kind==='alt'?'dp-alt':'dp-pref')+'">'+esc(l.value)+'</span></div>';
    });
  }

  const comments=det.comments||[];
  if(comments.length){
    h+='<hr class="dp-hr"><div class="dp-sub">Comments</div>';
    comments.forEach(c=>{ h+='<div class="dp-desc">'+esc(c.value)+'</div>'; });
  }

  if(det.description){
    h+='<hr class="dp-hr"><div class="dp-desc">'+esc(det.description)+'</div>';
  }

  const rels=det.relations||[];
  if(rels.length){
    h+='<hr class="dp-hr"><div class="dp-sub">Relations</div>';
    rels.forEach(r=>{
      const lbl=r.label||r.uri;
      const inGraph=!!nodeById[r.uri];
      h+='<div class="dp-rel"><span class="dp-rel-tag">'+esc(r.rel)+'</span>';
      if(inGraph){
        h+='<button class="dp-link" data-uri="'+esc(r.uri)+'" onclick="navigateTo(this.dataset.uri)">'+esc(lbl)+'</button>';
      } else {
        h+='<span>'+esc(lbl)+'</span>';
      }
      h+='</div>';
    });
  }
  h+='</div>';
  panelEl.innerHTML=h;
}

function dpBack(){ showDefault(); applyHighlight(); }

function navigateTo(uri){
  const n=nodeById[uri]; if(!n) return;
  highlighted=uri;
  applyHighlight();
  showDetail(n);
  // Fly to node
  const scale=1.4;
  const tx=W/2-n.x*scale, ty=H/2-n.y*scale;
  svg.transition().duration(500)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx,ty).scale(scale));
}

// Expose event handlers used by inline onclick attributes (IIFE scope → global)
window.toggleLink=toggleLink;
window.dpBack=dpBack;
window.navigateTo=navigateTo;
window.toggleAllIndividuals=toggleAllIndividuals;

showDefault();
}catch(e){_showVowlErr(e.stack||e.message||String(e));}
})();

// ── Live refresh via SSE (injected by `ster serve`) ───────────────────────────
(function(){
  const tok="__API_TOKEN__";
  if(!tok) return;
  const es=new EventSource("/api/events?token="+encodeURIComponent(tok));
  es.onmessage=function(){ location.reload(); };
  // No onerror override — let EventSource auto-reconnect on transient failures.
})();
</script>
</body>
</html>
"""
