"""Generate a self-contained D3 v7 ontology graph and open it in a browser.

The graph is written as a static HTML file.  Call push_update() after any
taxonomy mutation to regenerate it; the user refreshes the browser tab to see
the latest state.
"""

from __future__ import annotations

import json
import webbrowser
from pathlib import Path

from .model import Taxonomy, is_builtin_uri

# ── Data builder ──────────────────────────────────────────────────────────────


def _label(text: str, max_len: int = 18) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _ontology_title(taxonomy: Taxonomy, file_path: Path | None) -> str:
    if taxonomy.ontology_label:
        return taxonomy.ontology_label
    if taxonomy.ontology_uri:
        uri = taxonomy.ontology_uri.rstrip("/")
        for sep in ("#", "/"):
            if sep in uri:
                return uri.rsplit(sep, 1)[-1]
        return taxonomy.ontology_uri
    if file_path:
        return file_path.stem
    return "Ontology"


def build_graph(taxonomy: Taxonomy) -> dict:
    """Serialise taxonomy into a D3 {nodes, links} payload."""
    nodes: list[dict] = []
    links: list[dict] = []
    seen_nodes: set[str] = set()

    def add_node(uri: str, label: str, node_type: str, img: str = "") -> None:
        if uri not in seen_nodes:
            seen_nodes.add(uri)
            nodes.append(
                {
                    "id": uri,
                    "label": _label(label),
                    "fullLabel": label,
                    "type": node_type,
                    "img": img,
                }
            )

    # Classes
    for uri, cls in taxonomy.owl_classes.items():
        add_node(uri, cls.label("en"), "class", cls.schema_images[0] if cls.schema_images else "")

    # Individuals
    for uri, ind in taxonomy.owl_individuals.items():
        add_node(
            uri, ind.label("en"), "individual", ind.schema_images[0] if ind.schema_images else ""
        )

    # subClassOf
    for uri, cls in taxonomy.owl_classes.items():
        for parent in cls.sub_class_of:
            if not is_builtin_uri(parent) and parent in seen_nodes:
                links.append({"source": uri, "target": parent, "type": "subClassOf", "label": ""})

    # equivalentClass
    seen_equiv: set[frozenset] = set()
    for uri, cls in taxonomy.owl_classes.items():
        for eq in cls.equivalent_class:
            if not is_builtin_uri(eq) and eq in seen_nodes:
                key = frozenset((uri, eq))
                if key not in seen_equiv:
                    seen_equiv.add(key)
                    links.append(
                        {"source": uri, "target": eq, "type": "equivalentClass", "label": ""}
                    )

    # disjointWith
    seen_disj: set[frozenset] = set()
    for uri, cls in taxonomy.owl_classes.items():
        for dj in cls.disjoint_with:
            if not is_builtin_uri(dj) and dj in seen_nodes:
                key = frozenset((uri, dj))
                if key not in seen_disj:
                    seen_disj.add(key)
                    links.append({"source": uri, "target": dj, "type": "disjointWith", "label": ""})

    # rdf:type  (individual → class)
    for uri, ind in taxonomy.owl_individuals.items():
        for type_uri in ind.types:
            if not is_builtin_uri(type_uri) and type_uri in seen_nodes:
                links.append({"source": uri, "target": type_uri, "type": "instanceOf", "label": ""})

    # Object-property assertions  (individual → individual)
    for uri, ind in taxonomy.owl_individuals.items():
        for prop_uri, val_uri in ind.property_values:
            if val_uri in seen_nodes:
                prop = taxonomy.owl_properties.get(prop_uri)
                if prop:
                    plabel = _label(prop.label("en"), 14)
                else:
                    local = prop_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                    plabel = _label(local, 14)
                links.append(
                    {"source": uri, "target": val_uri, "type": "property", "label": plabel}
                )

    # SKOS ConceptSchemes
    for uri, scheme in taxonomy.schemes.items():
        add_node(uri, scheme.title("en"), "scheme")

    # SKOS Concepts — top concepts get their own type for distinct rendering
    top_concept_uris: set[str] = {uri for uri, c in taxonomy.concepts.items() if c.top_concept_of}
    for uri, concept in taxonomy.concepts.items():
        node_type = "topconcept" if uri in top_concept_uris else "concept"
        add_node(
            uri,
            concept.pref_label("en"),
            node_type,
            concept.schema_images[0] if concept.schema_images else "",
        )

    # SKOS broader/narrower (show broader only to avoid duplicate edges)
    for uri, concept in taxonomy.concepts.items():
        for broader_uri in concept.broader:
            if broader_uri in seen_nodes and uri in seen_nodes:
                links.append({"source": uri, "target": broader_uri, "type": "broader", "label": ""})

    # SKOS related
    seen_rel: set[frozenset] = set()
    for uri, concept in taxonomy.concepts.items():
        for rel_uri in concept.related:
            if rel_uri in seen_nodes and uri in seen_nodes:
                key = frozenset((uri, rel_uri))
                if key not in seen_rel:
                    seen_rel.add(key)
                    links.append({"source": uri, "target": rel_uri, "type": "related", "label": ""})

    # topConceptOf / inScheme
    for uri, concept in taxonomy.concepts.items():
        if concept.top_concept_of and concept.top_concept_of in seen_nodes:
            links.append(
                {"source": uri, "target": concept.top_concept_of, "type": "inScheme", "label": ""}
            )

    # ── Tier assignment for layout ─────────────────────────────────────────────
    # tier 0 = roots (schemes, root OWL classes)
    # tier 1 = top concepts, direct subclasses of root classes, root individuals
    # tier 2 = deeper concepts / subclasses / typed individuals
    child_classes: set[str] = {p for cls in taxonomy.owl_classes.values() for p in cls.sub_class_of}
    for node in nodes:
        t = node["type"]
        if t in ("scheme",):
            node["tier"] = 0
        elif t == "topconcept":
            node["tier"] = 1
        elif t == "concept":
            node["tier"] = 2
        elif t == "class":
            node["tier"] = 0 if node["id"] not in child_classes else 1
        else:  # individual
            node["tier"] = 2

    return {"nodes": nodes, "links": links}


# ── File output ───────────────────────────────────────────────────────────────

# Module-level state: where the graph was last written.
_out_path: Path | None = None
_file_path: Path | None = None


def _graph_path(file_path: Path | None) -> Path:
    cache = Path.home() / ".cache" / "ster"
    cache.mkdir(parents=True, exist_ok=True)
    stem = file_path.stem if file_path else "graph"
    return cache / f"{stem}_graph.html"


def _write_html(taxonomy: Taxonomy, file_path: Path | None, out_path: Path) -> None:
    title = _ontology_title(taxonomy, file_path)
    graph = build_graph(taxonomy)
    graph_json = json.dumps(graph, ensure_ascii=False)
    html = _HTML_TEMPLATE.replace("__TITLE__", title).replace('"__GRAPH_DATA__"', graph_json)
    out_path.write_text(html, encoding="utf-8")


def open_in_browser(taxonomy: Taxonomy, file_path: Path | None = None) -> Path:
    """Write the graph HTML and open it in the default browser."""
    global _out_path, _file_path
    _file_path = file_path
    _out_path = _graph_path(file_path)
    _write_html(taxonomy, file_path, _out_path)
    webbrowser.open(_out_path.as_uri())
    return _out_path


def push_update(taxonomy: Taxonomy) -> None:
    """Regenerate the graph HTML if it has been opened before."""
    if _out_path is not None:
        _write_html(taxonomy, _file_path, _out_path)


# ── HTML template ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font-family:system-ui,sans-serif;overflow:hidden}
#canvas{width:100vw;height:100vh;display:block}
/* fill/stroke set inline per node for cluster colours; only structural props here */
.node-class rect,.node-scheme rect{stroke-width:1.5px}
.node-individual ellipse,.node-concept ellipse{stroke-width:1.5px}
.node-topconcept ellipse{stroke-width:2.5px}
.node-class rect:hover,.node-individual ellipse:hover,
.node-concept ellipse:hover,.node-topconcept ellipse:hover,
.node-scheme rect:hover{filter:brightness(1.4);cursor:grab}
.node text{fill:#f0f6fc;font-size:11px;text-anchor:middle;dominant-baseline:central;
           pointer-events:none;font-family:system-ui,sans-serif}
.node-pinned circle.pin{display:block}
.pin{display:none;pointer-events:none}
.link{fill:none;stroke-opacity:.75}
.link-subClassOf{stroke:#475569;stroke-dasharray:7 3}
.link-equivalentClass{stroke:#0ea5e9;stroke-dasharray:4 2}
.link-disjointWith{stroke:#ef4444;stroke-dasharray:5 3}
.link-instanceOf{stroke:#8b5cf6;stroke-dasharray:3 3}
.link-property{stroke:#10b981}
.link-broader{stroke-dasharray:6 3}   /* stroke colour set inline per cluster */
.link-related{stroke:#f97316}
.link-inScheme{stroke:#a855f7;stroke-dasharray:3 2}
.link-label{font-size:9px;fill:#94a3b8;pointer-events:none;font-family:system-ui,sans-serif}
#legend{position:fixed;top:12px;right:12px;background:#161b22;
        border:1px solid #30363d;border-radius:8px;padding:10px 14px;min-width:170px;
        max-height:calc(100vh - 24px);overflow-y:auto}
#legend h3{font-size:12px;color:#8b949e;margin-bottom:8px;text-transform:uppercase;
           letter-spacing:.05em}
#legend h4{font-size:10px;color:#6b7280;margin:10px 0 5px;text-transform:uppercase;
           letter-spacing:.04em}
.lr{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:12px;color:#c9d1d9}
.lsvg{flex-shrink:0}
.lline{width:28px;height:0;flex-shrink:0}
#stats{position:fixed;bottom:10px;left:50%;transform:translateX(-50%);
       font-size:11px;color:#8b949e;background:#161b22;padding:4px 12px;
       border-radius:20px;border:1px solid #30363d}
#hint{position:fixed;bottom:10px;left:12px;font-size:10px;color:#4b5563;
      background:#161b22;padding:3px 8px;border-radius:10px;border:1px solid #30363d}
#tip{position:fixed;pointer-events:none;background:#161b22;border:1px solid #30363d;
     border-radius:6px;padding:6px 10px;font-size:11px;color:#c9d1d9;
     max-width:280px;word-break:break-all;display:none;z-index:99}
</style>
</head>
<body>
<svg id="canvas"></svg>

<div id="legend">
  <h3>Legend</h3>
  <div class="lr"><svg class="lsvg" width="34" height="16"><rect x="1" y="3" width="32" height="10" rx="2" fill="#1d4ed8" stroke="#60a5fa" stroke-width="1.5"/></svg>Class</div>
  <div class="lr"><svg class="lsvg" width="34" height="16"><rect x="1" y="4" width="32" height="8" rx="4" fill="#6b21a8" stroke="#c084fc" stroke-width="1.5"/></svg>Scheme</div>
  <div class="lr"><svg class="lsvg" width="34" height="16"><ellipse cx="17" cy="8" rx="15" ry="7.5" fill="none" stroke="#22d3ee" stroke-width="1" stroke-dasharray="3 2" opacity="0.6"/><ellipse cx="17" cy="8" rx="11" ry="5.5" fill="#0e7490" stroke="#22d3ee" stroke-width="2"/></svg>Top Concept</div>
  <div class="lr"><svg class="lsvg" width="34" height="16"><ellipse cx="17" cy="8" rx="13" ry="6.5" fill="#166534" stroke="#4ade80" stroke-width="1.5"/></svg>Concept</div>
  <div class="lr"><svg class="lsvg" width="34" height="16"><ellipse cx="17" cy="8" rx="11" ry="5.5" fill="#b45309" stroke="#fcd34d" stroke-width="1.5"/></svg>Individual</div>
  <div id="cluster-legend"></div>
  <h4>Relations</h4>
  <div class="lr"><div class="lline" style="border-top:2px dashed #475569"></div>subClassOf</div>
  <div class="lr"><div class="lline" style="border-top:2px dashed #0ea5e9"></div>equivalentClass</div>
  <div class="lr"><div class="lline" style="border-top:2px dashed #ef4444"></div>disjointWith</div>
  <div class="lr"><div class="lline" style="border-top:2px dotted #8b5cf6"></div>rdf:type</div>
  <div class="lr"><div class="lline" style="border-top:2px solid #10b981"></div>property</div>
  <div class="lr"><div class="lline" style="border-top:2px dashed #6b7280"></div>broader</div>
  <div class="lr"><div class="lline" style="border-top:2px solid #f97316"></div>related</div>
  <div class="lr"><div class="lline" style="border-top:2px dotted #a855f7"></div>inScheme</div>
</div>

<div id="stats"></div>
<div id="hint">drag top-concept → moves whole tree · dbl-click to unpin · click: highlight · f: re-layout · esc: clear</div>
<div id="tip"></div>

<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script>
(function(){
const graphData = "__GRAPH_DATA__";
const svg = d3.select("#canvas");
const W = window.innerWidth, H = window.innerHeight;

const defs = svg.append("defs");
// Base markers for non-cluster link types (broader gets per-cluster markers below)
[
  {id:"arr-subClassOf",     color:"#475569"},
  {id:"arr-equivalentClass",color:"#0ea5e9"},
  {id:"arr-disjointWith",   color:"#ef4444"},
  {id:"arr-instanceOf",     color:"#8b5cf6"},
  {id:"arr-property",       color:"#10b981"},
  {id:"arr-broader",        color:"#6b7280"},
  {id:"arr-related",        color:"#f97316"},
  {id:"arr-inScheme",       color:"#a855f7"},
].forEach(m=>{
  defs.append("marker")
    .attr("id",m.id).attr("viewBox","0 -4 8 8")
    .attr("refX",8).attr("refY",0)
    .attr("markerWidth",6).attr("markerHeight",6)
    .attr("orient","auto")
    .append("path").attr("d","M0,-4L8,0L0,4Z").attr("fill",m.color);
});

const root = svg.append("g");
svg.call(d3.zoom().scaleExtent([0.05,6])
  .on("zoom",e=>root.attr("transform",e.transform)));

const CLS_W=110, CLS_H=36, IND_RX=52, IND_RY=24, TC_RX=60, TC_RY=30;

function isRootClass(d){
  return d.type==="class"&&!hasClusters&&d._owlCluster===d.id;
}
function nodeRadius(d){
  if(isRootClass(d)) return Math.sqrt((CLS_W/2+7)**2+(CLS_H/2+7)**2);
  if(d.type==="class"||d.type==="scheme") return Math.sqrt((CLS_W/2)**2+(CLS_H/2)**2);
  if(d.type==="topconcept") return Math.max(TC_RX,TC_RY);
  return Math.max(IND_RX,IND_RY);
}

// ── Pre-computation (before D3 mutates link.source/target to node objects) ────
const nodes = graphData.nodes;
const links = graphData.links;
const nodeById = Object.fromEntries(nodes.map(n=>[n.id,n]));

// Arc offsets: parallel edges between the same pair fan out as curves.
const pairCount={}, pairIdx={};
links.forEach(l=>{
  const k=[l.source,l.target].sort().join("\x00");
  pairCount[k]=(pairCount[k]||0)+1;
});
links.forEach(l=>{
  const k=[l.source,l.target].sort().join("\x00");
  pairIdx[k]=(pairIdx[k]||0);
  l._arc=(pairIdx[k]-(pairCount[k]-1)/2)*40;
  pairIdx[k]++;
});

// Broader map (child→parent) and children map (parent→[children]).
const broaderMap={};
const childrenMap={};
nodes.forEach(n=>{ childrenMap[n.id]=[]; });
links.forEach(l=>{
  if(l.type!=="broader") return;
  broaderMap[l.source]=l.target;
  (childrenMap[l.target]=childrenMap[l.target]||[]).push(l.source);
});

// subClassOf maps (child→parent, parent→[children]) for OWL tree coloring.
const subClassOfParentMap={};
const subClassOfChildMap={};
nodes.forEach(n=>{ subClassOfChildMap[n.id]=[]; });
links.forEach(l=>{
  if(l.type!=="subClassOf") return;
  subClassOfParentMap[l.source]=l.target;
  (subClassOfChildMap[l.target]=subClassOfChildMap[l.target]||[]).push(l.source);
});

// Cluster: walk broader chain to find topconcept ancestor.
function clusterOf(id,depth){
  if(depth>20) return null;
  const n=nodeById[id]; if(!n) return null;
  if(n.type==="topconcept") return id;
  const b=broaderMap[id];
  return b?clusterOf(b,depth+1):null;
}
nodes.forEach(n=>{
  n._cluster=(n.type==="topconcept")?n.id:clusterOf(n.id,0);
});

// Depth: 0=topconcept, 1=direct child, 2=grandchild, …
function depthOf(id,visited){
  if(visited.has(id)) return 99;
  visited.add(id);
  const n=nodeById[id]; if(!n) return 1;
  if(n.type==="topconcept") return 0;
  if(n.type==="scheme") return -1;
  const b=broaderMap[id]; if(!b) return 1;
  const bd=depthOf(b,visited);
  return bd<0?1:bd+1;
}
nodes.forEach(n=>{
  if(n.type==="scheme")       n._depth=-1;
  else if(n.type==="topconcept") n._depth=0;
  else                           n._depth=depthOf(n.id,new Set());
});

// Tag each broader link with its source cluster (for per-cluster colouring).
links.forEach(l=>{
  if(l.type==="broader") l._cluster=(nodeById[l.source]||{})._cluster||null;
});

const topConcepts=nodes.filter(n=>n.type==="topconcept");
const schemeNodes=nodes.filter(n=>n.type==="scheme");
const hasClusters=topConcepts.length>0;

// ── OWL class-tree clusters ───────────────────────────────────────────────────
// Root classes (no superclass in the graph) each become a colour-coded tree.
// Root OWL class = no superclass in the visible graph (regardless of tier).
const rootClasses=!hasClusters
  ?nodes.filter(n=>n.type==="class"&&!subClassOfParentMap[n.id])
  :[];
const classTreeHue={};
rootClasses.forEach((rc,i)=>{
  classTreeHue[rc.id]=Math.round((i/Math.max(rootClasses.length,1))*360+200)%360;
});

function owlClusterOf(id,depth){
  if(depth>30) return null;
  if(classTreeHue[id]!==undefined) return id;  // reached a root class
  const p=subClassOfParentMap[id];
  return p?owlClusterOf(p,depth+1):null;
}
nodes.forEach(n=>{
  n._owlCluster=n.type==="class"?owlClusterOf(n.id,0):null;
});
// Propagate to individuals via instanceOf links.
links.forEach(l=>{
  if(l.type!=="instanceOf") return;
  const ind=nodeById[l.source], cls=nodeById[l.target];
  if(ind&&cls&&!ind._owlCluster) ind._owlCluster=cls._owlCluster;
});
// Tag each subClassOf link with its cluster.
links.forEach(l=>{
  if(l.type==="subClassOf") l._owlCluster=(nodeById[l.source]||{})._owlCluster||null;
});

// ── Cluster colour palette ────────────────────────────────────────────────────
// Each top concept gets a distinct hue; descendants inherit at reduced lightness.
const clusterHue={};
topConcepts.forEach((tc,i)=>{
  clusterHue[tc.id]=Math.round((i/topConcepts.length)*360+200)%360;
});

function nodeFill(d){
  if(d.type==="scheme") return "#6b21a8";
  if(d.type==="class"){
    const hue=d._owlCluster!=null?classTreeHue[d._owlCluster]:null;
    return hue!=null?`hsl(${hue},65%,22%)`:"#1d4ed8";
  }
  if(d.type==="individual"){
    const hue=d._owlCluster!=null?classTreeHue[d._owlCluster]:null;
    return hue!=null?`hsl(${hue},55%,18%)`:"#b45309";
  }
  // SKOS (concept, topconcept)
  const hue=d._cluster?clusterHue[d._cluster]:null;
  if(hue==null) return d.type==="topconcept"?"#0e7490":"#166534";
  const dep=Math.max(0,d._depth||0);
  return `hsl(${hue},65%,${Math.max(14,28-dep*5)}%)`;
}
function nodeStroke(d){
  if(d.type==="scheme") return "#c084fc";
  if(d.type==="class"){
    const hue=d._owlCluster!=null?classTreeHue[d._owlCluster]:null;
    return hue!=null?`hsl(${hue},90%,58%)`:"#60a5fa";
  }
  if(d.type==="individual"){
    const hue=d._owlCluster!=null?classTreeHue[d._owlCluster]:null;
    return hue!=null?`hsl(${hue},80%,52%)`:"#fcd34d";
  }
  // SKOS
  const hue=d._cluster?clusterHue[d._cluster]:null;
  if(hue==null) return d.type==="topconcept"?"#22d3ee":"#4ade80";
  const dep=Math.max(0,d._depth||0);
  return `hsl(${hue},90%,${Math.max(42,62-dep*8)}%)`;
}
function broaderStroke(cluster){
  const hue=clusterHue[cluster];
  return hue!=null?`hsl(${hue},55%,40%)`:"#4b5563";
}
function subClassOfStroke(owlCluster){
  const hue=classTreeHue[owlCluster];
  return hue!=null?`hsl(${hue},55%,40%)`:"#475569";
}

// Per-cluster arrowhead markers — broader (SKOS) and subClassOf (OWL).
const clusterMarkerId={};
topConcepts.forEach(tc=>{
  const hue=clusterHue[tc.id];
  const color=`hsl(${hue},80%,52%)`;
  const mid=`arr-b-${tc.id.replace(/[^a-zA-Z0-9]/g,"_")}`;
  clusterMarkerId[tc.id]=mid;
  defs.append("marker")
    .attr("id",mid).attr("viewBox","0 -4 8 8")
    .attr("refX",8).attr("refY",0)
    .attr("markerWidth",6).attr("markerHeight",6)
    .attr("orient","auto")
    .append("path").attr("d","M0,-4L8,0L0,4Z").attr("fill",color);
});
const owlClassMarkerId={};
rootClasses.forEach(rc=>{
  const hue=classTreeHue[rc.id];
  const color=`hsl(${hue},80%,52%)`;
  const mid=`arr-sc-${rc.id.replace(/[^a-zA-Z0-9]/g,"_")}`;
  owlClassMarkerId[rc.id]=mid;
  defs.append("marker")
    .attr("id",mid).attr("viewBox","0 -4 8 8")
    .attr("refX",8).attr("refY",0)
    .attr("markerWidth",6).attr("markerHeight",6)
    .attr("orient","auto")
    .append("path").attr("d","M0,-4L8,0L0,4Z").attr("fill",color);
});

// ── Subtree helpers ───────────────────────────────────────────────────────────
function getSubtree(rootId){
  const result=[],queue=[rootId],seen=new Set();
  while(queue.length){
    const id=queue.shift();
    if(seen.has(id)) continue;
    seen.add(id);
    const n=nodeById[id]; if(n) result.push(n);
    (childrenMap[id]||[]).forEach(c=>queue.push(c));
  }
  return result;
}

// ── SKOS lane assignment ──────────────────────────────────────────────────────
// Each top concept owns an equal-width horizontal strip; _laneX is its centre.
const laneWidth=hasClusters?W/(topConcepts.length+1):W;
if(hasClusters){
  topConcepts.forEach((tc,i)=>{ tc._laneX=laneWidth*(i+1); });
  nodes.forEach(n=>{
    if(n.type==="scheme"){ n._laneX=W/2; return; }
    if(n._cluster){ n._laneX=(nodeById[n._cluster]||{})._laneX||W/2; return; }
    n._laneX=W/2;
  });
}

// ── OWL cluster layout ────────────────────────────────────────────────────────
// Root classes placed on a circle; subclasses orbit their root as a free network.
const owlCircleR=!hasClusters&&rootClasses.length>0
  ?Math.min(W,H)*(0.28+0.05*Math.min(rootClasses.length,8)):0;
if(!hasClusters){
  rootClasses.forEach((rc,i)=>{
    const a=2*Math.PI*i/Math.max(rootClasses.length,1)-Math.PI/2;
    rc._cx=W/2+(rootClasses.length>1?owlCircleR*Math.cos(a):0);
    rc._cy=H/2+(rootClasses.length>1?owlCircleR*Math.sin(a):0);
  });
}

// Custom force: pull OWL subclasses toward their root-class centre.
function owlClusterForce(alpha){
  nodes.forEach(n=>{
    if(!n._owlCluster||n._owlCluster===n.id) return;
    const root=nodeById[n._owlCluster]; if(!root) return;
    n.vx+=(root.x-n.x)*0.12*alpha;
    n.vy+=(root.y-n.y)*0.12*alpha;
  });
}

// ── Tier Y positions (SKOS only) ──────────────────────────────────────────────
function tierY(n){
  if(n.type==="scheme")     return H*0.04;
  if(n.type==="topconcept") return H*0.14;
  const d=Math.min(n._depth||1,4);
  return H*(0.14+d*0.18);  // depth1=32% depth2=50% depth3=68% depth4=86%
}
function tierYStr(n){
  if(n.type==="scheme")     return 0.98;
  if(n.type==="topconcept") return 0.85;
  return 0.70;
}

// ── Seed positions ────────────────────────────────────────────────────────────
function seedPositions(){
  nodes.forEach(n=>{ n.vx=0; n.vy=0; n.fx=null; n.fy=null; });
  if(hasClusters){
    // SKOS: scheme at top, top concepts in horizontal lanes.
    schemeNodes.forEach(s=>{ s.x=W/2; s.y=H*0.04; });
    topConcepts.forEach(tc=>{
      tc.x=tc._laneX; tc.y=H*0.14;
      tc.fx=tc._laneX; tc.fy=H*0.14;
    });
    nodes.forEach(n=>{
      if(n.type==="topconcept"||n.type==="scheme") return;
      n.x=(n._laneX||W/2)+(Math.random()-0.5)*laneWidth*0.5;
      n.y=tierY(n)+(Math.random()-0.5)*40;
    });
  } else {
    // OWL: root classes pinned on a circle; subclasses seeded around their root.
    rootClasses.forEach(rc=>{
      rc.x=rc._cx; rc.y=rc._cy;
      rc.fx=rc._cx; rc.fy=rc._cy;
    });
    nodes.forEach(n=>{
      if(n.type==="class"&&n._owlCluster===n.id) return;  // root, already placed
      if(n._owlCluster){
        const root=nodeById[n._owlCluster];
        if(root){
          const a=Math.random()*2*Math.PI, r=60+Math.random()*90;
          n.x=root.x+r*Math.cos(a); n.y=root.y+r*Math.sin(a);
          return;
        }
      }
      n.x=W/2+(Math.random()-0.5)*200; n.y=H/2+(Math.random()-0.5)*200;
    });
  }
}
seedPositions();

// ── Edge path ─────────────────────────────────────────────────────────────────
function edgePath(d){
  const dx=d.target.x-d.source.x, dy=d.target.y-d.source.y;
  const dist=Math.sqrt(dx*dx+dy*dy)||1;
  const sr=nodeRadius(d.source)+2, tr=nodeRadius(d.target)+2;
  if(dist<sr+tr) return "";
  const sx=d.source.x+dx/dist*sr, sy=d.source.y+dy/dist*sr;
  const tx=d.target.x-dx/dist*tr, ty=d.target.y-dy/dist*tr;
  const arc=d._arc||0;
  if(Math.abs(arc)<1) return `M${sx},${sy}L${tx},${ty}`;
  const mx=(sx+tx)/2-dy/dist*arc, my=(sy+ty)/2+dx/dist*arc;
  return `M${sx},${sy}Q${mx},${my} ${tx},${ty}`;
}

// ── Simulation ────────────────────────────────────────────────────────────────
const sim=d3.forceSimulation()
  .force("collide",d3.forceCollide(d=>nodeRadius(d)+18));

if(hasClusters){
  // SKOS: lane + tier forces
  sim.force("link",d3.forceLink().id(d=>d.id)
    .distance(d=>d.type==="inScheme"?H*0.12:d.type==="broader"?H*0.17:150)
    .strength(0.12))
  .force("charge",d3.forceManyBody().strength(d=>
    d.type==="topconcept"?-800:d.type==="scheme"?-400:-180))
  .force("cx",d3.forceX(d=>d._laneX).strength(d=>d.type==="scheme"?0.04:0.35))
  .force("cy",d3.forceY(d=>tierY(d)).strength(d=>tierYStr(d)));
} else {
  // OWL: network clusters — root classes repel hard, subclasses pulled to their root.
  sim.force("link",d3.forceLink().id(d=>d.id)
    .distance(120).strength(0.3))
  .force("charge",d3.forceManyBody().strength(d=>
    isRootClass(d)?-4000:-320))
  .force("cx",d3.forceX(W/2).strength(0.01))
  .force("cy",d3.forceY(H/2).strength(0.01))
  .force("owlCluster",owlClusterForce);
}

// ── Rendering ─────────────────────────────────────────────────────────────────
const linkG=root.append("g");
const nodeG=root.append("g");

let linkSel=linkG.selectAll("path");
let linkLabelSel=linkG.selectAll("text");
let nodeSel=nodeG.selectAll("g");
let highlighted=null;

function applyHighlight(){
  if(!highlighted){ nodeSel.style("opacity",1); linkSel.style("opacity",.75); return; }
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
}

function updateStats(ns,ls){
  const nC=ns.filter(d=>d.type==="class").length;
  const nI=ns.filter(d=>d.type==="individual").length;
  const nT=ns.filter(d=>d.type==="topconcept").length;
  const nK=ns.filter(d=>d.type==="concept").length;
  const nS=ns.filter(d=>d.type==="scheme").length;
  const p=[];
  if(nC) p.push(nC+" class"+(nC!==1?"es":""));
  if(nI) p.push(nI+" individual"+(nI!==1?"s":""));
  if(nT) p.push(nT+" top concept"+(nT!==1?"s":""));
  if(nK) p.push(nK+" concept"+(nK!==1?"s":""));
  if(nS) p.push(nS+" scheme"+(nS!==1?"s":""));
  p.push(ls.length+" relation"+(ls.length!==1?"s":""));
  document.getElementById("stats").textContent=p.join(" · ");
}

const tip=document.getElementById("tip");
function showTip(e,d){
  const km={class:"Class",individual:"Individual",concept:"Concept",
            topconcept:"Top Concept",scheme:"Scheme"};
  tip.innerHTML=`<b>${km[d.type]||d.type}</b><br>${d.fullLabel}`
    +`<br><span style="color:#8b949e;font-size:10px">${d.id}</span>`;
  tip.style.display="block";
}
function moveTip(e){ tip.style.left=(e.clientX+14)+"px"; tip.style.top=(e.clientY+10)+"px"; }
function hideTip(){ tip.style.display="none"; }
function updatePinMarker(sel){ sel.classed("node-pinned",d=>d.fx!=null); }

updateStats(nodes,links);

linkSel=linkG.selectAll("path")
  .data(links,d=>`${d.source}|${d.target}|${d.type}`)
  .join("path")
  .attr("class",d=>`link link-${d.type}`)
  .style("stroke",d=>d.type==="broader"&&d._cluster?broaderStroke(d._cluster):null)
  .attr("marker-end",d=>{
    if(d.type==="broader"&&d._cluster&&clusterMarkerId[d._cluster])
      return `url(#${clusterMarkerId[d._cluster]})`;
    return `url(#arr-${d.type})`;
  });

linkLabelSel=linkG.selectAll("text")
  .data(links.filter(d=>d.label),d=>`${d.source}|${d.target}|${d.type}`)
  .join("text").attr("class","link-label").text(d=>d.label);

nodeSel=nodeG.selectAll("g")
  .data(nodes,d=>d.id)
  .join(enter=>{
    const g=enter.append("g")
      .attr("class",d=>`node node-${d.type}`)
      .call(d3.drag()
        .on("start",(e,d)=>{
          if(!e.active) sim.alphaTarget(0.3).restart();
          d.fx=d.x; d.fy=d.y;
          if(d.type==="topconcept"){
            // Carry the whole subtree as a rigid group.
            const sub=getSubtree(d.id).filter(n=>n!==d);
            d._dragSub=sub.map(n=>({n,dx:n.x-d.x,dy:n.y-d.y}));
            sub.forEach(n=>{ n.fx=n.x; n.fy=n.y; });
          }
        })
        .on("drag",(e,d)=>{
          d.fx=e.x; d.fy=e.y;
          if(d._dragSub)
            d._dragSub.forEach(({n,dx,dy})=>{ n.fx=e.x+dx; n.fy=e.y+dy; });
        })
        .on("end",(e,d)=>{
          if(!e.active) sim.alphaTarget(0);
          d._dragSub=null;
          updatePinMarker(nodeSel);  // sticky: fx/fy kept
        }))
      .on("click",(_,d)=>{ highlighted=highlighted===d.id?null:d.id; applyHighlight(); })
      .on("dblclick",(_,d)=>{
        // Unpin whole subtree for top concepts, just the node otherwise.
        (d.type==="topconcept"?getSubtree(d.id):[d])
          .forEach(n=>{ n.fx=null; n.fy=null; });
        updatePinMarker(nodeSel);
        sim.alpha(0.3).restart();
      })
      .on("mouseover",showTip).on("mousemove",moveTip).on("mouseout",hideTip);

    g.each(function(d){
      const s=d3.select(this);
      const fill=nodeFill(d), stroke=nodeStroke(d);
      if(d.type==="class"||d.type==="scheme"){
        const root=isRootClass(d);
        if(root){
          s.append("rect").attr("x",-CLS_W/2-7).attr("y",-CLS_H/2-7)
            .attr("width",CLS_W+14).attr("height",CLS_H+14).attr("rx",12)
            .attr("fill","none").attr("stroke",stroke).attr("stroke-width",1.5)
            .attr("stroke-dasharray","5 3").attr("opacity",0.55);
        }
        s.append("rect").attr("x",-CLS_W/2).attr("y",-CLS_H/2)
          .attr("width",CLS_W).attr("height",CLS_H).attr("rx",7)
          .style("fill",fill).style("stroke",stroke)
          .style("stroke-width",root?"2.5px":"1.5px");
      } else if(d.type==="topconcept"){
        s.append("ellipse").attr("rx",TC_RX+6).attr("ry",TC_RY+6)
          .attr("fill","none").attr("stroke",stroke).attr("stroke-width",1)
          .attr("stroke-dasharray","4 3").attr("opacity",0.5);
        s.append("ellipse").attr("rx",TC_RX).attr("ry",TC_RY)
          .style("fill",fill).style("stroke",stroke).style("stroke-width","2.5px");
      } else {
        s.append("ellipse").attr("rx",IND_RX).attr("ry",IND_RY)
          .style("fill",fill).style("stroke",stroke);
      }
      // Image thumbnail clipped to node shape
      if(d.img){
        if(d.type==="class"||d.type==="scheme"){
          s.append("image").attr("href",d.img)
            .attr("x",-CLS_W/2).attr("y",-CLS_H/2)
            .attr("width",CLS_W).attr("height",CLS_H)
            .attr("preserveAspectRatio","xMidYMid slice").attr("opacity",0.45)
            .style("clip-path","inset(0 round 7px)");
        } else {
          const rx=d.type==="topconcept"?TC_RX:IND_RX;
          const ry=d.type==="topconcept"?TC_RY:IND_RY;
          s.append("image").attr("href",d.img)
            .attr("x",-rx).attr("y",-ry)
            .attr("width",rx*2).attr("height",ry*2)
            .attr("preserveAspectRatio","xMidYMid slice").attr("opacity",0.45)
            .style("clip-path","ellipse(50% 50% at center)");
        }
      }
      s.append("circle").attr("class","pin")
        .attr("cx",d.type==="class"||d.type==="scheme"?CLS_W/2-6:IND_RX-6)
        .attr("cy",d.type==="class"||d.type==="scheme"?-CLS_H/2+6:-IND_RY+6)
        .attr("r",4).attr("fill","#f59e0b").attr("stroke","#0d1117").attr("stroke-width",1.5);
      s.append("text").text(d.label);
    });
    return g;
  });

// ── Dynamic cluster legend ────────────────────────────────────────────────────
const cl=document.getElementById("cluster-legend");
if(topConcepts.length>0){
  const h=document.createElement("h4"); h.textContent="Trees"; cl.appendChild(h);
  topConcepts.forEach(tc=>{
    const hue=clusterHue[tc.id];
    const fill=`hsl(${hue},65%,28%)`, stroke=`hsl(${hue},90%,60%)`;
    const row=document.createElement("div"); row.className="lr";
    row.innerHTML=`<div class="lbox" style="background:${fill};border:2px solid ${stroke};`
      +`border-radius:50%"></div><span style="font-size:11px">${tc.fullLabel||tc.label}</span>`;
    cl.appendChild(row);
  });
}
// (OWL class trees not listed individually — colour visible on nodes)

sim.nodes(nodes);
sim.force("link").links(links);
sim.alpha(1).restart();

sim.on("tick",()=>{
  linkSel.attr("d",edgePath);
  linkLabelSel
    .attr("x",d=>(d.source.x+d.target.x)/2)
    .attr("y",d=>(d.source.y+d.target.y)/2);
  nodeSel.attr("transform",d=>`translate(${d.x},${d.y})`);
});

document.addEventListener("keydown",e=>{
  if(e.key==="Escape"){ highlighted=null; applyHighlight(); }
  if(e.key==="f"){
    nodes.forEach(n=>{ n.fx=null; n.fy=null; });
    seedPositions();           // re-seeds and re-pins top concepts at their lanes
    updatePinMarker(nodeSel);
    sim.alpha(0.9).restart();
  }
});

})();
</script>
</body>
</html>
"""
