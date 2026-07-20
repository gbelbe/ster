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
import html as _html
import http.server
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
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


# ── class links subgraph ──────────────────────────────────────────────────────


def build_class_links_graph(
    taxonomy: Taxonomy, class_uri: str, subclass_only: bool = False
) -> dict:
    """Serialise the linked-classes neighbourhood of *class_uri* into a payload.

    Centred on one class, the subgraph contains:
      * the focus class;
      * its transitive ``subClassOf`` superclass trail (ancestor classes flagged
        ``superclass=1``, with ``subClassOf`` edges);
      * every class connected by an object property — both where the focus is the
        property's domain (``focus --prop--> range``) and where it is the range
        (``domain --prop--> focus``), as directed, property-labelled edges.

    Returns an empty payload when *class_uri* is not a known class.  Layout is
    always ``cose``.
    """
    if class_uri not in taxonomy.owl_classes:
        return {"nodes": [], "edges": [], "layout": "cose"}

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    seen_subclass_edges: set[tuple[str, str]] = set()
    _ec = 0

    def _eid() -> str:
        nonlocal _ec
        eid = f"e{_ec}"
        _ec += 1
        return eid

    def add_class(uri: str, superclass: int = 0) -> None:
        if uri in seen_nodes or is_builtin_uri(uri):
            return
        seen_nodes.add(uri)
        cls = taxonomy.owl_classes.get(uri)
        label = cls.label("en") if cls else _local(uri)
        detail = _detail_class(cls, taxonomy) if cls else {}
        nodes.append(
            {
                "id": uri,
                "label": label,
                "type": "class",
                "detail": detail,
                "rootClass": 0,
                "superclass": superclass,
            }
        )

    # ── object-property-linked classes (both directions) ──────────────────
    linked: set[str] = set()
    add_class(class_uri, superclass=0)
    # In subclass-only mode the T-Box object-property links between classes are
    # omitted (used when exploration started from an individual — the object
    # properties are already shown between the individuals at the A-Box level).
    props = [] if subclass_only else list(taxonomy.owl_properties.values())
    for prop in props:
        if prop.prop_type != "ObjectProperty":
            continue
        plabel = prop.label("en")
        for d in prop.domains:
            for r in prop.ranges:
                if is_builtin_uri(d) or is_builtin_uri(r):
                    continue
                if d == class_uri and r != class_uri:
                    add_class(r, superclass=0)
                    linked.add(r)
                    edges.append(
                        {
                            "id": _eid(),
                            "source": d,
                            "target": r,
                            "type": "objectProperty",
                            "label": plabel,
                        }
                    )
                elif r == class_uri and d != class_uri:
                    add_class(d, superclass=0)
                    linked.add(d)
                    edges.append(
                        {
                            "id": _eid(),
                            "source": d,
                            "target": r,
                            "type": "objectProperty",
                            "label": plabel,
                        }
                    )

    # ── superclass trail above the focus class and every linked class ─────
    non_superclass = {class_uri, *linked}
    stack = [class_uri, *linked]
    visited: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in visited or is_builtin_uri(cur):
            continue
        visited.add(cur)
        add_class(cur, superclass=0 if cur in non_superclass else 1)
        cls = taxonomy.owl_classes.get(cur)
        for parent in cls.sub_class_of if cls else []:
            if is_builtin_uri(parent):
                continue
            if (cur, parent) not in seen_subclass_edges:
                seen_subclass_edges.add((cur, parent))
                edges.append(
                    {
                        "id": _eid(),
                        "source": cur,
                        "target": parent,
                        "type": "subClassOf",
                        "label": "",
                    }
                )
            stack.append(parent)

    return {"nodes": nodes, "edges": edges, "layout": "cose"}


# ── individual relations subgraph ─────────────────────────────────────────────


def build_individual_relations_graph(taxonomy: Taxonomy, ind_uri: str) -> dict:
    """Serialise the object-property neighbourhood of *ind_uri* into a payload.

    Centred on one individual, the subgraph contains:
      * the focus individual;
      * every individual linked to it by an object property in **either**
        direction (incoming ``S --prop--> focus`` and outgoing
        ``focus --prop--> T``), each as a directed, property-labelled edge;
      * the class(es) the focus belongs to (``instanceOf`` edges);
      * the class(es) of every related individual.

    Datatype / literal assertions are ignored. Returns an empty payload when
    *ind_uri* is not a known individual.  Layout is always ``cose``.
    """
    if ind_uri not in taxonomy.owl_individuals:
        return {"nodes": [], "edges": [], "layout": "cose"}

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    _ec = 0

    def _eid() -> str:
        nonlocal _ec
        eid = f"e{_ec}"
        _ec += 1
        return eid

    def add_node(
        uri: str, label: str, node_type: str, detail: dict | None = None, superclass: int = 0
    ) -> None:
        if uri not in seen_nodes:
            seen_nodes.add(uri)
            nodes.append(
                {
                    "id": uri,
                    "label": label,
                    "type": node_type,
                    "detail": detail or {},
                    "rootClass": 0,
                    "superclass": superclass,
                }
            )

    def add_individual(uri: str) -> None:
        ind = taxonomy.owl_individuals[uri]
        add_node(uri, ind.label("en"), "individual", _detail_individual(ind, taxonomy))

    def _prop_label(prop_uri: str) -> str:
        prop = taxonomy.owl_properties.get(prop_uri)
        return prop.label("en") if prop else _local(prop_uri)

    add_individual(ind_uri)

    related: set[str] = set()

    # Outgoing: focus --prop--> target (object-property values to individuals)
    for prop_uri, val_uri in taxonomy.owl_individuals[ind_uri].property_values:
        if val_uri in taxonomy.owl_individuals:
            add_individual(val_uri)
            related.add(val_uri)
            edges.append(
                {
                    "id": _eid(),
                    "source": ind_uri,
                    "target": val_uri,
                    "type": "objectProperty",
                    "label": _prop_label(prop_uri),
                }
            )

    # Incoming: source --prop--> focus
    for src_uri, src in taxonomy.owl_individuals.items():
        if src_uri == ind_uri:
            continue
        for prop_uri, val_uri in src.property_values:
            if val_uri == ind_uri:
                add_individual(src_uri)
                related.add(src_uri)
                edges.append(
                    {
                        "id": _eid(),
                        "source": src_uri,
                        "target": ind_uri,
                        "type": "objectProperty",
                        "label": _prop_label(prop_uri),
                    }
                )

    seen_subclass_edges: set[tuple[str, str]] = set()

    # A class is a superclass-trail node when it is reached only as an ancestor —
    # i.e. it is not the direct rdf:type of any individual shown here.
    direct_types: set[str] = {
        t
        for x_uri in {ind_uri, *related}
        for t in taxonomy.owl_individuals[x_uri].types
        if not is_builtin_uri(t)
    }

    def add_class_with_ancestors(cls_uri: str) -> None:
        """Add *cls_uri* and its transitive ``subClassOf`` ancestors as a trail.

        Each ancestor becomes a class node and each step a ``subClassOf`` edge
        (child → parent).  Builtin URIs are skipped, ancestor nodes and edges are
        de-duplicated, and subclass cycles terminate via the visited set.
        """
        stack = [cls_uri]
        visited: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in visited or is_builtin_uri(cur):
                continue
            visited.add(cur)
            cls = taxonomy.owl_classes.get(cur)
            label = cls.label("en") if cls else _local(cur)
            detail = _detail_class(cls, taxonomy) if cls else {}
            add_node(cur, label, "class", detail, superclass=0 if cur in direct_types else 1)
            for parent in cls.sub_class_of if cls else []:
                if is_builtin_uri(parent):
                    continue
                if (cur, parent) not in seen_subclass_edges:
                    seen_subclass_edges.add((cur, parent))
                    edges.append(
                        {
                            "id": _eid(),
                            "source": cur,
                            "target": parent,
                            "type": "subClassOf",
                            "label": "",
                        }
                    )
                stack.append(parent)

    # rdf:type (and the superclass trail above each class) for the focus and
    # every related individual
    for x_uri in {ind_uri, *related}:
        for type_uri in taxonomy.owl_individuals[x_uri].types:
            if is_builtin_uri(type_uri):
                continue
            add_class_with_ancestors(type_uri)
            edges.append(
                {
                    "id": _eid(),
                    "source": x_uri,
                    "target": type_uri,
                    "type": "instanceOf",
                    "label": "",
                }
            )

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
    meta = _taxonomy_meta(taxonomy, file_path)
    show_all_btn = (
        f'<span style="color:#cbd5e1"> │ </span>'
        f'<button class="ftbtn active" onclick="window.location.href=\'{full_graph_link}\'">'
        f"Show all nodes</button>"
        if full_graph_link
        else ""
    )
    html = (
        _HTML_TEMPLATE.replace("__TITLE__", _html.escape(title))
        .replace("__CY_SCRIPT__", _cytoscape_script_tag())
        .replace("__STER_DATA_SCRIPT__", _data_script(graph, meta, ""))
        .replace("__STER_APP_JS__", _app_js())
        .replace("__SHOW_ALL_BTN__", show_all_btn)
        .replace("__OFFLINE_BANNER__", _offline_banner(""))
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
    """Return an inline <script> tag with Cytoscape.js, downloading once to ~/.cache/ster.

    This is the *vendored library* layer, kept deliberately separate from ster's
    own graph code (:func:`_app_js`): swapping the library here — e.g. on a
    version bump — must never touch the application layer.
    """
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


@functools.lru_cache(maxsize=1)
def _app_js() -> str:
    """Return ster's graph *application* layer (interaction, styling, filtering,
    live update, detail panels) as JavaScript source.

    Lives in the versioned repo asset ``ster/assets/graph_app.js`` so it is fully
    decoupled from the vendored Cytoscape library: a library upgrade can never
    overwrite it. The code uses only the public ``cytoscape(...)`` factory and
    reads its per-render data from the injected ``window.__STER_GRAPH__`` global.
    """
    from importlib.resources import files  # noqa: PLC0415

    return (files("ster") / "assets" / "graph_app.js").read_text(encoding="utf-8")


def _data_script(graph: dict, meta: dict, api_token: str) -> str:
    """Return the per-render *data injection* layer.

    Keeps ontology data out of both the library and the app code: the app reads
    everything from ``window.__STER_GRAPH__``.
    """
    payload = {"data": graph, "meta": meta, "token": api_token}
    return "<script>window.__STER_GRAPH__=" + json.dumps(payload, ensure_ascii=False) + ";</script>"


def _offline_banner(api_token: str) -> str:
    """Return an in-page notice shown only when no live server backs the page.

    The explore / extend-relations hover actions are driven by the live API server
    (keyed off the page token). ``fastapi``/``uvicorn`` are core dependencies, so the
    only thing that stops the live server is the configured port already being in use —
    then the page is a static snapshot and those actions are unavailable. The banner
    says so, so the degraded mode is never silent. When a real token is present (live
    server) nothing is shown.
    """
    if api_token:
        return ""
    return (
        '<div id="offline-banner"><span>⚠ Live server not running — showing a '
        "static snapshot; explore / extend relations is unavailable. The configured "
        "port is in use by another process — close it (or change the port in Config) "
        "and reopen the graph.</span>"
        '<button id="offline-banner-close" title="Dismiss">×</button></div>'
    )


def is_live_server() -> bool:
    """True when the live FastAPI server backs the graph (vs a static snapshot)."""
    return _api_app is not None


def _server_host_port(host: str | None, port: int | None) -> tuple[str, int]:
    """Fill in *host*/*port* from the saved server config when not supplied."""
    if host is not None and port is not None:
        return host, port
    from .api_server import load_server_config  # noqa: PLC0415

    url, cfg_port = load_server_config()
    return host or url.split("://", 1)[-1], port or cfg_port


def _listening_pid(port: int) -> int | None:
    """The PID listening on *port* via ``lsof``, or None when the port is free, ``lsof``
    is unavailable, or nothing can be parsed (never raises — best-effort)."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    for token in result.stdout.split():
        try:
            return int(token)
        except ValueError:
            continue
    return None


def _process_name(pid: int) -> str:
    """A human description (the command line) of *pid* via ``ps``, else ``"PID <n>"``."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        name = result.stdout.strip()
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        name = ""
    return name or f"PID {pid}"


def port_holder(host: str | None = None, port: int | None = None) -> tuple[int, str] | None:
    """The ``(pid, command)`` of the process listening on the configured server port, or
    None when the port is free or the process cannot be identified. Used to warn — and
    offer to close — when the graph's live-server port is already taken."""
    host, port = _server_host_port(host, port)
    pid = _listening_pid(port)
    # A port held by *this* process (our own in-process server thread) is not something to
    # reclaim — returning it would make the caller SIGTERM our own PID, killing the TUI
    # (the terminal is left in mouse-tracking mode → escape codes garble the screen).
    if pid is None or pid == os.getpid():
        return None
    return (pid, _process_name(pid))


def _port_is_free(host: str, port: int) -> bool:
    """True when *host*:*port* can be bound (nothing is holding it)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def free_port(
    pid: int,
    host: str | None = None,
    port: int | None = None,
    *,
    timeout: float = 5.0,
    poll: float = 0.1,
) -> bool:
    """Gracefully terminate *pid* (``SIGTERM``) and wait until the server port is free.
    Returns True once the port can be bound, False on timeout (or if it never frees)."""
    host, port = _server_host_port(host, port)
    if pid == os.getpid():
        # Never signal ourselves — SIGTERM to our own PID would kill the running TUI.
        return _port_is_free(host, port)
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return _port_is_free(host, port)  # already gone / not ours → report the port state
    deadline = time.monotonic() + timeout
    while True:
        if _port_is_free(host, port):
            return True
        if time.monotonic() >= deadline:
            return _port_is_free(host, port)
        time.sleep(poll)


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


def _await_uvicorn_started(
    holder: dict[str, Any],
    *,
    timeout: float = 10.0,
    poll: float = 0.05,
    sleep: Any = None,
    monotonic: Any = None,
) -> bool:
    """Block until *our* uvicorn server reports it has bound and is serving.

    *holder* is the dict the server thread fills in: ``server`` (the
    ``uvicorn.Server`` once constructed), ``error`` (a startup exception, e.g. a
    bind failure), and ``done`` (set once ``serve()`` returns). Returns True only
    when ``server.started`` flips True — so a stale server squatting the
    configured port can never be mistaken for ours. Returns False on a startup
    error, when ``serve()`` finished without starting, or on timeout.
    """
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    deadline = monotonic() + timeout
    while True:
        server = holder.get("server")
        if server is not None and getattr(server, "started", False):
            return True
        if holder.get("error") is not None or holder.get("done"):
            return False
        if monotonic() >= deadline:
            return False
        sleep(poll)


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

    # Mount the project's publish tree (ontology/) so published stable/dev
    # artifacts are served at /ontology/... — created up-front so the mount
    # exists even before the first publish (StaticFiles serves live from disk).
    publish_dir = file_path.parent / "ontology" if file_path is not None else None
    if publish_dir is not None:
        publish_dir.mkdir(parents=True, exist_ok=True)

    app = create_app(
        taxonomy, token, broadcaster, save_fn, html_fn=html_fn, publish_dir=publish_dir
    )
    app.state._ster["broadcaster"] = broadcaster

    _api_app = app
    _api_broadcaster = broadcaster

    loop_captured: threading.Event = threading.Event()
    holder: dict[str, Any] = {}

    def _run() -> None:
        global _api_loop

        async def _serve() -> None:
            global _api_loop
            _api_loop = asyncio.get_running_loop()
            server = uvicorn.Server(
                uvicorn.Config(app, host=_server_host, port=_server_port, log_level="warning")
            )
            holder["server"] = server
            loop_captured.set()
            try:
                await server.serve()
            except BaseException as exc:  # noqa: BLE001  (bind failure must not crash the thread)
                holder["error"] = exc

        asyncio.run(_serve())
        holder["done"] = True

    threading.Thread(target=_run, daemon=True, name="ster-api-server").start()
    loop_captured.wait(timeout=10)
    # Report success only once *our* uvicorn has actually bound the socket. A
    # bare "is the port open?" probe accepts a stale static server squatting the
    # configured port — callers then open `/` against it and get a cache
    # directory listing instead of the graph.
    if _api_loop is None or not _await_uvicorn_started(holder):
        _api_app = _api_broadcaster = None
        _api_running = False
        return False
    _api_running = True
    return True


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler that suppresses access-log noise.

    It also refuses directory listings: the server backs specific ``*_vowl.html``
    files, so a request for a folder (most visibly ``/``) must 404 rather than
    expose an index of the whole ``~/.cache/ster`` directory.
    """

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def list_directory(self, path: str) -> None:  # type: ignore[override]
        self.send_error(404, "Not found")
        return None

    def end_headers(self) -> None:
        # The graph page inlines its JS, so a browser-cached page kept serving an
        # old build until a manual hard-reload. Forbid caching so a plain reload
        # (or reopening from ster) always gets the current page.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


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
    meta = _taxonomy_meta(taxonomy, file_path)
    return (
        _HTML_TEMPLATE.replace("__TITLE__", _html.escape(title))
        .replace("__CY_SCRIPT__", _cytoscape_script_tag())
        .replace("__STER_DATA_SCRIPT__", _data_script(graph, meta, api_token))
        .replace("__STER_APP_JS__", _app_js())
        .replace("__SHOW_ALL_BTN__", "")
        .replace("__OFFLINE_BANNER__", _offline_banner(api_token))
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


def ensure_published_server(taxonomy: Taxonomy, file_path: Path | None = None) -> str | None:
    """Ensure the live API server is running and return its base URL.

    Starts the FastAPI server (with the ``/ontology`` publish mount) if it is not
    already up, without opening the graph page. Returns the base URL, e.g.
    ``http://127.0.0.1:8765``, or ``None`` when the ``ster[api]`` extra is not
    installed (so callers can fall back to ``file://``).
    """
    if not _start_api_server(taxonomy, file_path):
        return None
    from .api_server import load_server_config  # noqa: PLC0415

    url, port = load_server_config()
    return f"{url}:{port}"


def open_in_browser(
    taxonomy: Taxonomy,
    file_path: Path | None = None,
    on_change_fn: Any = None,
) -> str:
    """Open the VOWL graph in the browser.

    Starts the live FastAPI server (SSE push refresh) — ``fastapi``/``uvicorn`` are core
    deps, so this works unless the configured port is busy, in which case it falls back
    to a static HTTP server.

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
#explore-btn{position:absolute;display:none;transform:translate(-50%,-100%);z-index:40;background:#2563eb;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:11px;font-weight:600;padding:4px 10px;box-shadow:0 2px 8px rgba(0,0,0,.25);white-space:nowrap}
#explore-btn:hover{background:#1d4ed8}
#hide-btn{position:absolute;display:none;transform:translate(-50%,0);z-index:40;background:#64748b;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:11px;font-weight:600;padding:4px 10px;box-shadow:0 2px 8px rgba(0,0,0,.25);white-space:nowrap}
#hide-btn:hover{background:#475569}
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
#offline-banner{position:fixed;top:48px;left:50%;transform:translateX(-50%);z-index:35;display:flex;align-items:center;gap:10px;background:#fef3c7;color:#92400e;border:1px solid #fcd34d;border-radius:8px;padding:6px 12px;font-size:12px;line-height:1.4;box-shadow:0 2px 8px rgba(0,0,0,.08);max-width:80vw}
#offline-banner code{background:#fde68a;padding:0 4px;border-radius:3px;font-size:11px}
#offline-banner-close{flex-shrink:0;background:none;border:none;color:#92400e;cursor:pointer;font-size:16px;line-height:1;padding:0 2px}
#offline-banner-close:hover{color:#451a03}
</style>
</head>
<body>
__OFFLINE_BANNER__
<div id="cy"></div>
<div id="detail-panel"></div>
<button id="panel-close" title="Close panel (Esc)">\xd7</button>
<div id="stats"></div>
<div id="hint">drag\xb7pan\xb7scroll→zoom \xb7 f: layout \xb7 click: details \xb7 esc: close<span style="color:#cbd5e1"> │ </span><button class="ftbtn active" id="ft-individuals">individuals</button><button class="ftbtn active" id="ft-first-order">1st order</button><button class="ftbtn active" id="ft-second-order">2nd order</button><button class="ftbtn active" id="ft-instanceOf">rdf:type</button><button class="ftbtn active" id="ft-superclasses">superclasses</button><button class="ftbtn active" id="ft-inScheme">inScheme</button><button class="ftbtn active" id="ft-datatypeProperty">datatype</button>__SHOW_ALL_BTN__</div>
<button id="explore-btn">&#8857; explore relations</button><button id="hide-btn">&#8854; hide node + parents</button>
<div id="zoom-ctrl"><button id="zoom-in" title="Zoom in (+)">+</button><button id="zoom-out" title="Zoom out (−)">&#8722;</button><button id="zoom-fit" title="Fit all (f)">Recenter</button></div>
<div id="tip"></div>
<div id="search-wrap"><svg width="14" height="14" viewBox="0 0 14 14" fill="none" style="flex-shrink:0;opacity:.5"><circle cx="5.5" cy="5.5" r="4" stroke="#475569" stroke-width="1.5"/><line x1="8.5" y1="8.5" x2="13" y2="13" stroke="#475569" stroke-width="1.5" stroke-linecap="round"/></svg><input id="search-box" type="search" placeholder="Search nodes…" autocomplete="off" spellcheck="false" autofocus><span id="search-count"></span><button id="search-clear" title="Clear (Esc)">\xd7</button></div>
__CY_SCRIPT__
__STER_DATA_SCRIPT__
<script>
__STER_APP_JS__
</script>
</body>
</html>
"""
