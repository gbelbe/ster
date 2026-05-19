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

import functools
import http.server
import json
import re
import socket
import threading
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path

from .model import Taxonomy, is_builtin_uri
from .viz import (
    _detail_class,
    _detail_concept,
    _detail_individual,
    _detail_scheme,
    _label,
    _label_for,  # noqa: F401  (re-exported for potential callers)
    _local,
    _ontology_title,
    _taxonomy_meta,
)

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
                    "label": _label(label, 20),
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
    return {"nodes": nodes, "links": links, "layout": layout}


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
                    "label": _label(label, 20),
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


_out_path: Path | None = None
_file_path: Path | None = None

# One-per-process HTTP server that serves the ster cache directory.
_http_server: http.server.HTTPServer | None = None
_http_port: int | None = None


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


def _write_html(taxonomy: Taxonomy, file_path: Path | None, out_path: Path) -> None:
    title = _ontology_title(taxonomy, file_path)
    graph = build_vowl_graph(taxonomy)
    graph_json = json.dumps(graph, ensure_ascii=False)
    meta = _taxonomy_meta(taxonomy, file_path)
    meta_json = json.dumps(meta, ensure_ascii=False)
    html = (
        _HTML_TEMPLATE.replace("__TITLE__", title)
        .replace('"__GRAPH_DATA__"', graph_json)
        .replace('"__TAXO_META__"', meta_json)
        .replace("__D3_SCRIPT__", _d3_script_tag())
    )
    out_path.write_text(html, encoding="utf-8")


def open_in_browser(taxonomy: Taxonomy, file_path: Path | None = None) -> Path:
    """Write the VOWL HTML and open it via a local HTTP server (avoids file:// security blocks)."""
    global _out_path, _file_path
    _file_path = file_path
    _out_path = _graph_path(file_path)
    _write_html(taxonomy, file_path, _out_path)
    port = _ensure_server(_out_path.parent)
    webbrowser.open(f"http://127.0.0.1:{port}/{_out_path.name}")
    return _out_path


def push_update(taxonomy: Taxonomy) -> None:
    """Regenerate the VOWL HTML if it has been opened before."""
    if _out_path is not None:
        _write_html(taxonomy, _file_path, _out_path)


def open_focused_in_browser(
    taxonomy: Taxonomy, root_uri: str, file_path: Path | None = None
) -> Path:
    """Write a focused VOWL HTML centred on *root_uri* and open it in the browser."""
    root_cls = taxonomy.owl_classes.get(root_uri)
    root_label = root_cls.label("en") if root_cls else _local(root_uri)
    safe_label = re.sub(r"[^A-Za-z0-9_-]", "_", root_label)
    stem = (file_path.stem if file_path else "graph") + f"_focused_{safe_label}"
    cache = Path.home() / ".cache" / "ster"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{stem}_vowl.html"

    title = _ontology_title(taxonomy, file_path)
    graph = build_focused_vowl_graph(taxonomy, root_uri)
    graph_json = json.dumps(graph, ensure_ascii=False)
    meta = _taxonomy_meta(taxonomy, file_path)
    meta_json = json.dumps(meta, ensure_ascii=False)
    html = (
        _HTML_TEMPLATE.replace("__TITLE__", f"{title} — {root_label}")
        .replace('"__GRAPH_DATA__"', graph_json)
        .replace('"__TAXO_META__"', meta_json)
        .replace("__D3_SCRIPT__", _d3_script_tag())
    )
    out.write_text(html, encoding="utf-8")
    port = _ensure_server(out.parent)
    webbrowser.open(f"http://127.0.0.1:{port}/{out.name}")
    return out


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
  l._arc=(pairIdx[k]-(pairCount[k]-1)/2)*55;
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
}
function hierTargetY(d){
  const depth=owlHierDepth[d.id]!==undefined?owlHierDepth[d.id]:maxHierDepth+1;
  return 70+depth*Math.max((H-160)/(maxHierDepth+2),90);
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
  if(d.type==="individual") return 24;
  return 28;
}
// Slightly larger hitbox for force collision
function nodeRadiusColl(d){ return nodeRadius(d)+28; }

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
      n.x=(n._hierLaneX||W/2)+(Math.random()-0.5)*50;
      n.y=hierTargetY(n)+(Math.random()-0.5)*20;
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
const sim=d3.forceSimulation()
  .alphaDecay(0.016)
  .force("collide",d3.forceCollide(nodeRadiusColl).iterations(3));

if(hasClusters){
  sim.force("link",d3.forceLink().id(d=>d.id)
    .distance(d=>d.type==="inScheme"?H*0.12:d.type==="broader"?H*0.17:150).strength(0.12))
  .force("charge",d3.forceManyBody().strength(d=>d.type==="topconcept"?-800:d.type==="scheme"?-400:-200))
  .force("cx",d3.forceX(d=>d._laneX||W/2).strength(d=>d.type==="scheme"?0.04:0.35))
  .force("cy",d3.forceY(d=>tierY(d)).strength(d=>d.type==="scheme"?0.98:d.type==="topconcept"?0.85:0.70));
} else if(isHierarchical){
  sim.force("link",d3.forceLink().id(d=>d.id).distance(130).strength(0.10))
  .force("charge",d3.forceManyBody().strength(d=>isRoot(d)?-2000:-600))
  .force("cx",d3.forceX(d=>d._hierLaneX||W/2).strength(0.45))
  .force("cy",d3.forceY(d=>hierTargetY(d)).strength(0.75));
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
  const arc=d._arc||0;
  if(Math.abs(arc)<1) return `M${sx},${sy}L${tx},${ty}`;
  const mx=(sx+tx)/2-dy/dist*arc, my=(sy+ty)/2+dx/dist*arc;
  return `M${sx},${sy}Q${mx},${my} ${tx},${ty}`;
}
function propBoxPos(d){
  const s=d.source, t=d.target;
  if(!s||!t) return [0,0];
  const arc=d._arc||0;
  if(Math.abs(arc)<1) return [(s.x+t.x)/2,(s.y+t.y)/2];
  const dx=t.x-s.x, dy=t.y-s.y, dist=Math.sqrt(dx*dx+dy*dy)||1;
  const qx=(s.x+t.x)/2-dy/dist*arc, qy=(s.y+t.y)/2+dx/dist*arc;
  return [0.25*s.x+0.5*qx+0.25*t.x, 0.25*s.y+0.5*qy+0.25*t.y];
}

// ── Rendering layers ──────────────────────────────────────────────────────────
const linkG=root.append("g");
const propBoxG=root.append("g");
const nodeG=root.append("g");

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

// Nodes
let nodeSel=nodeG.selectAll("g")
  .data(nodes,d=>d.id)
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
        applyHighlight();
        if(newHl){ togglePanel(true); showDetail(d); } else showDefault();
      })
      .on("dblclick",(_,d)=>{ d.fx=null; d.fy=null; updatePinMarker(nodeSel); sim.alpha(0.3).restart(); })
      .on("mouseover",showTip).on("mousemove",moveTip).on("mouseout",hideTip);
    g.each(function(d){
      const s=d3.select(this);
      const r=nodeRadius(d);
      // Datatype nodes render as rectangles
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
      // Outer ring for root classes
      if(d.type==="class"&&isRoot(d)){
        s.append("circle").attr("r",r+9)
          .attr("fill","none").attr("stroke",stroke).attr("stroke-width",1.2).attr("opacity",.35);
      }
      s.append("circle").attr("r",r)
        .attr("fill",fill).attr("stroke",stroke)
        .attr("stroke-width",d.type==="class"&&isRoot(d)?2.5:1.5)
        .style("filter","drop-shadow(0 1px 3px rgba(0,0,0,.12))");
      s.append("text").text(d.label)
        .attr("font-size",d.type==="scheme"?12:d.type==="class"&&isRoot(d)?12:10)
        .attr("font-weight",d.type==="class"||d.type==="scheme"?"600":"400");
      s.append("circle").attr("class","pin-dot")
        .attr("cx",r-6).attr("cy",-r+6).attr("r",4)
        .attr("stroke","white").attr("stroke-width",1.5);
      // Individual count badge on class nodes
      if(d.type==="class"){
        const cnt=(classIndividualsMap[d.id]||[]).length;
        if(cnt>0){
          s.append("circle").attr("class","ind-badge")
            .attr("cx",0).attr("cy",r+8).attr("r",8)
            .attr("fill","#7fb8e0").attr("stroke","white").attr("stroke-width",1.5)
            .style("cursor","pointer")
            .on("mouseover",function(){
              d3.select(this).attr("r",10).attr("stroke-width",2.5);
            })
            .on("mouseout",function(){
              d3.select(this).attr("r",8).attr("stroke-width",1.5);
            })
            .on("click",function(e){
              e.stopPropagation();
              if(hiddenIndivClasses.has(d.id)) hiddenIndivClasses.delete(d.id);
              else hiddenIndivClasses.add(d.id);
              applyIndivVis();
            });
          s.append("text").attr("class","ind-badge-text")
            .attr("x",0).attr("y",r+8)
            .attr("text-anchor","middle").attr("dominant-baseline","central")
            .attr("font-size","8px").attr("fill","white")
            .attr("pointer-events","none")
            .text(cnt);
        }
      }
    });
    return g;
  });

sim.nodes(nodes);
sim.force("link").links(links);
sim.alpha(1).restart();

// ── Tick ──────────────────────────────────────────────────────────────────────
sim.on("tick",()=>{
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
    sim.force("cx",d3.forceX(d=>d._hierLaneX||W/2).strength(0.45));
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
    if(highlighted){ highlighted=null; applyHighlight(); showDefault(); }
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
</script>
</body>
</html>
"""
