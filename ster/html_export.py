"""HTML export via pyLODE.

Chooses the profile automatically based on file content:
  - skos:ConceptScheme present → VocPub  (SKOS vocabulary)
  - owl:Ontology / prof:Profile only     → OntPub (OWL ontology)
  - both present                         → caller passes explicit profile

Generates one HTML file per language for VocPub; a single file for OntPub.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from typing import Literal

Profile = Literal["vocpub", "ontpub"]


@contextlib.contextmanager
def _patch_missing_pyproject():
    """Work around pyLODE 3.x bug: missing pyproject.toml crashes at import time."""
    import pathlib

    _stub = b'[project]\nname = "pylode"\nversion = "3.0.0"\n'
    _orig = pathlib.Path.open

    def _mock(self, mode="r", *args, **kwargs):
        if self.name == "pyproject.toml" and not self.exists():
            return io.BytesIO(_stub) if "b" in str(mode) else io.StringIO(_stub.decode())
        return _orig(self, mode, *args, **kwargs)

    pathlib.Path.open = _mock  # type: ignore[method-assign]
    try:
        yield
    finally:
        pathlib.Path.open = _orig  # type: ignore[method-assign]


# ── Profile detection ─────────────────────────────────────────────────────────


def detect_profile(taxonomy_path: Path) -> Profile | Literal["both"]:
    """Inspect the RDF file and return which pyLODE profile suits it best.

    Returns ``"vocpub"``, ``"ontpub"``, or ``"both"`` when the file contains
    both a skos:ConceptScheme and an owl:Ontology / prof:Profile declaration.
    """
    from rdflib import Graph
    from rdflib.namespace import OWL, PROF, RDF, SKOS

    g = Graph()
    g.parse(str(taxonomy_path))

    has_skos = bool(next(g.subjects(RDF.type, SKOS.ConceptScheme), None))
    has_owl = bool(next(g.subjects(RDF.type, OWL.Ontology), None)) or bool(
        next(g.subjects(RDF.type, PROF.Profile), None)
    )

    if has_skos and has_owl:
        return "both"
    if has_skos:
        return "vocpub"
    return "ontpub"


# ── Language detection (SKOS only) ────────────────────────────────────────────


def _available_languages(taxonomy: object) -> list[str]:
    """Return sorted list of language codes present in a SKOS taxonomy."""
    from .model import Taxonomy

    assert isinstance(taxonomy, Taxonomy)
    langs: set[str] = set()
    for scheme in taxonomy.schemes.values():
        for lbl in scheme.labels:
            langs.add(lbl.lang)
        for desc in scheme.descriptions:
            langs.add(desc.lang)
    for concept in taxonomy.concepts.values():
        for lbl in concept.labels:
            langs.add(lbl.lang)
        for defn in concept.definitions:
            langs.add(defn.lang)
    return sorted(langs)


# ── Language-switcher injection (VocPub / multi-language) ─────────────────────

_SWITCHER_CSS = """
<style>
  #ster-lang-bar {
    background: #2c3e50;
    padding: 10px 24px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    display: flex;
    align-items: center;
    gap: 14px;
    position: sticky;
    top: 0;
    z-index: 1000;
    box-shadow: 0 2px 6px rgba(0,0,0,.35);
  }
  #ster-lang-bar .ster-label { color: #95a5a6; }
  #ster-lang-bar a {
    color: #3498db;
    text-decoration: none;
    padding: 3px 8px;
    border-radius: 4px;
    transition: background .15s;
  }
  #ster-lang-bar a:hover { background: rgba(52,152,219,.25); }
  #ster-lang-bar .ster-current {
    color: #fff;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
    background: rgba(255,255,255,.12);
  }
</style>
"""


def _lang_switcher_html(stem: str, current: str, all_langs: list[str]) -> str:
    items = []
    for lang in all_langs:
        label = lang.upper()
        if lang == current:
            items.append(f'<span class="ster-current">{label}</span>')
        else:
            items.append(f'<a href="{stem}_{lang}.html">{label}</a>')
    links = "\n    ".join(items)
    return (
        f"{_SWITCHER_CSS}\n"
        f'<div id="ster-lang-bar">\n'
        f'  <span class="ster-label">Language:</span>\n'
        f"  {links}\n"
        f"</div>"
    )


def _inject_switcher(html: str, stem: str, current: str, all_langs: list[str]) -> str:
    """Insert the language bar immediately after the opening <body> tag."""
    bar = _lang_switcher_html(stem, current, all_langs)
    tag = "<body>"
    idx = html.lower().find(tag)
    if idx == -1:
        return bar + "\n" + html
    return html[: idx + len(tag)] + "\n" + bar + html[idx + len(tag) :]


# ── Core export ───────────────────────────────────────────────────────────────


def generate_html(
    taxonomy_path: Path,
    output_dir: Path,
    languages: list[str] | None = None,
    profile: Profile | None = None,
) -> list[Path]:
    """Generate HTML documentation via pyLODE.

    Parameters
    ----------
    taxonomy_path:
        Source RDF file.
    output_dir:
        Directory where HTML files are written. Created if absent.
    languages:
        Language codes for VocPub multi-language export. Ignored for OntPub.
        Defaults to all languages detected in the file.
    profile:
        ``"vocpub"`` (SKOS) or ``"ontpub"`` (OWL). Auto-detected if omitted.

    Returns
    -------
    List of Path objects for the files written.

    Raises
    ------
    RuntimeError
        If pyLODE is not installed.
    """
    with _patch_missing_pyproject():
        try:
            from pylode import OntPub, VocPub  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "pyLODE is not installed.\nRun:  pip install pylode\nThen try again."
            )

    if profile is None:
        detected = detect_profile(taxonomy_path)
        profile = "vocpub" if detected == "both" else detected  # type: ignore[assignment]

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = taxonomy_path.stem
    created: list[Path] = []

    import logging

    # Silence pyLODE's INFO/DEBUG chatter (root logger + asyncio).
    _root_level = logging.root.level
    _asyncio_logger = logging.getLogger("asyncio")
    _asyncio_level = _asyncio_logger.level
    logging.root.setLevel(logging.WARNING)
    _asyncio_logger.setLevel(logging.WARNING)

    try:
        if profile == "ontpub":
            vp = OntPub(ontology=str(taxonomy_path.resolve()))
            html = vp.make_html()
            out_path = output_dir / f"{stem}.html"
            out_path.write_text(html, encoding="utf-8")
            created.append(out_path)

        else:  # vocpub
            from .store import load as _load

            taxonomy = _load(taxonomy_path)
            if languages is None:
                languages = _available_languages(taxonomy)
            if not languages:
                languages = ["en"]

            multi = len(languages) > 1
            for lang in languages:
                try:
                    vp = VocPub(  # type: ignore[assignment]
                        ontology=str(taxonomy_path.resolve()), default_language=lang
                    )
                except TypeError:
                    vp = VocPub(ontology=str(taxonomy_path.resolve()))  # type: ignore[assignment]
                html = vp.make_html()

                if multi:
                    html = _inject_switcher(html, stem, lang, languages)
                    out_path = output_dir / f"{stem}_{lang}.html"
                else:
                    out_path = output_dir / f"{stem}.html"

                out_path.write_text(html, encoding="utf-8")
                created.append(out_path)

    finally:
        logging.root.setLevel(_root_level)
        _asyncio_logger.setLevel(_asyncio_level)

    return created


# ── WEF-style transformation-map site generator ───────────────────────────────

import html as _html
import json as _json
import re as _re


def _md_to_html(text: str) -> str:
    """Render Markdown to HTML; falls back to escaped plain text."""
    try:
        import markdown as _markdown  # type: ignore[import]

        return _markdown.markdown(text, extensions=["nl2br", "fenced_code", "tables"])
    except ImportError:
        escaped = _html.escape(text).replace("\n", "<br>")
        return f"<p>{escaped}</p>"


def _video_embed_url(url: str) -> tuple[str, str] | None:
    """Derive an embeddable (iframe_src, platform) from a YouTube or Vimeo URL."""
    m = _re.search(r"youtube\.com/watch\?.*v=([A-Za-z0-9_-]+)", url)
    if m:
        return f"https://www.youtube.com/embed/{m.group(1)}", "youtube"
    m = _re.search(r"youtu\.be/([A-Za-z0-9_-]+)", url)
    if m:
        return f"https://www.youtube.com/embed/{m.group(1)}", "youtube"
    m = _re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]+)", url)
    if m:
        return f"https://www.youtube.com/embed/{m.group(1)}", "youtube"
    m = _re.search(r"vimeo\.com/(\d+)", url)
    if m:
        return f"https://player.vimeo.com/video/{m.group(1)}", "vimeo"
    return None


# ── Design tokens & shared CSS ────────────────────────────────────────────────

_CSS = """\
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#020c20;--surf:#06142e;--surf2:#0c2248;--surf3:#112c58;
  --border:#1a3870;--border2:#254880;
  --accent:#1472ff;--accent2:#00d4ff;--accent3:#00ffcc;
  --text:#cce0f8;--muted:#4d6a99;--faint:#1a3060;
  --radius:10px;
  --font:-apple-system,BlinkMacSystemFont,'Segoe UI','Inter',sans-serif;
}
html{scroll-behavior:smooth}
body{font-family:var(--font);background:var(--bg);color:var(--text);
     min-height:100vh;line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:var(--accent2);text-decoration:none}
a:hover{text-decoration:underline}

/* ── Topbar ── */
.topbar{position:fixed;top:0;left:0;right:0;z-index:300;height:52px;
  background:rgba(2,12,32,.92);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:0;padding:0}
.topbar-logo{padding:0 24px;font-size:15px;font-weight:800;color:#fff;
  letter-spacing:-.02em;display:flex;align-items:center;gap:8px;
  border-right:1px solid var(--border);height:100%;flex-shrink:0}
.topbar-logo .dot{width:8px;height:8px;border-radius:50%;background:var(--accent2)}
.topbar-bc{padding:0 20px;font-size:12px;color:var(--muted);
  display:flex;align-items:center;gap:6px;overflow:hidden}
.topbar-bc a{color:var(--muted)}
.topbar-bc a:hover{color:var(--accent2)}
.topbar-bc .sep{color:var(--faint)}
.topbar-bc .cur{color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* ── Type badges ── */
.badge{display:inline-flex;align-items:center;gap:5px;
  font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;
  padding:3px 10px;border-radius:20px}
.badge::before{content:'';width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.8}
.badge-class     {background:rgba(20,114,255,.15);color:#5aa0ff;border:1px solid rgba(20,114,255,.3)}
.badge-individual{background:rgba(255,140,0,.12);color:#ffaa44;border:1px solid rgba(255,140,0,.25)}
.badge-concept   {background:rgba(0,212,255,.12);color:#44d8ff;border:1px solid rgba(0,212,255,.25)}
.badge-topconcept{background:rgba(0,255,200,.1); color:#00ffcc;border:1px solid rgba(0,255,200,.25)}
.badge-scheme    {background:rgba(160,80,255,.12);color:#cc80ff;border:1px solid rgba(160,80,255,.25)}

/* ── Index layout ── */
.index-root{height:100vh;display:flex;flex-direction:column;padding-top:52px}
.index-header{position:absolute;top:68px;left:36px;z-index:10;pointer-events:none}
.index-header h1{font-size:28px;font-weight:800;color:#fff;letter-spacing:-.03em;margin-bottom:6px}
.index-header p{font-size:13px;color:var(--muted);max-width:320px}
#index-net{flex:1;width:100%}
.index-legend{position:absolute;bottom:24px;left:36px;z-index:10;
  display:flex;gap:18px;flex-wrap:wrap}
.leg{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted)}
.leg-dot{width:10px;height:10px;border-radius:50%}
.index-hint{position:absolute;bottom:24px;right:24px;font-size:11px;color:var(--faint)}

/* ── Entity page layout: full-height split ── */
html,body{height:100%}
.page-root{
  display:grid;
  grid-template-columns:1fr 420px;
  grid-template-rows:100vh;
  padding-top:52px;
  height:100vh;
}
@media(max-width:860px){
  .page-root{grid-template-columns:1fr;grid-template-rows:50vh auto}
}

/* Left: graph pane */
.graph-pane{
  position:relative;
  background:var(--bg);
  border-right:1px solid var(--border);
  overflow:hidden;
}
#page-net{width:100%;height:100%;display:block}

/* graph overlay: legend bottom-left */
.graph-legend{
  position:absolute;bottom:20px;left:20px;z-index:10;
  display:flex;gap:14px;flex-wrap:wrap;pointer-events:none;
}

/* Right: scrollable info panel */
.info-pane{
  overflow-y:auto;
  background:var(--surf);
  display:flex;flex-direction:column;
}

/* entity header at top of info pane */
.entity-header{
  padding:32px 28px 24px;
  border-bottom:1px solid var(--border);
  background:var(--surf2);
  flex-shrink:0;
}
.entity-header .badge{margin-bottom:14px}
.entity-header h1{
  font-size:26px;font-weight:800;color:#fff;
  letter-spacing:-.03em;line-height:1.2;
  margin-bottom:0;
}

/* hero image (optional, inside info pane) */
.entity-img{
  width:100%;max-height:220px;object-fit:cover;
  display:block;flex-shrink:0;
  border-bottom:1px solid var(--border);
}

/* info pane content area */
.info-content{padding:24px 28px;flex:1}

/* sidebar boxes */
.sbox{border-top:1px solid var(--border);padding:14px 28px}
.sbox h4{font-size:10px;font-weight:700;text-transform:uppercase;
  letter-spacing:.1em;color:var(--muted);margin-bottom:8px}
.sbox ul{list-style:none}
.sbox li{padding:5px 0;border-bottom:1px solid var(--faint);font-size:13px}
.sbox li:last-child{border-bottom:none}
.sbox a{color:var(--text)}
.sbox a:hover{color:var(--accent2)}
.uri-chip{font-size:10px;color:var(--muted);word-break:break-all;
  padding:8px 10px;margin:10px 28px 16px;display:block;
  background:var(--bg);border-radius:6px;border:1px solid var(--border)}

/* description */
.desc{font-size:15px;line-height:1.8;color:#99bbd8;margin-bottom:28px}
.desc h1,.desc h2,.desc h3{color:#d8eeff;margin:20px 0 8px;font-weight:700}
.desc h2{font-size:17px}.desc h3{font-size:14px}
.desc p{margin-bottom:12px}
.desc ul,.desc ol{margin:0 0 12px 20px}
.desc code{background:var(--surf2);border:1px solid var(--border);
  border-radius:4px;padding:1px 5px;font-size:13px}
.desc pre{background:var(--surf);border:1px solid var(--border);
  border-radius:8px;padding:12px 16px;overflow-x:auto;margin:14px 0}
.desc blockquote{border-left:3px solid var(--accent2);padding:8px 16px;
  color:var(--muted);margin:14px 0;background:var(--surf);border-radius:0 6px 6px 0}
.desc strong{color:#c0dcf8}
.desc table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}
.desc th{background:var(--surf2);color:#fff;padding:7px 10px;text-align:left}
.desc td{border-top:1px solid var(--border);padding:7px 10px}

/* video */
.video-wrap{position:relative;padding-bottom:56.25%;height:0;
  border-radius:var(--radius);overflow:hidden;margin-bottom:28px;
  border:1px solid var(--border)}
.video-wrap iframe{position:absolute;top:0;left:0;width:100%;height:100%;border:0}

/* external link card */
.link-card{display:flex;align-items:center;gap:14px;
  background:var(--surf);border:1px solid var(--border);
  border-radius:var(--radius);padding:14px 18px;margin-bottom:10px;
  transition:border-color .15s,background .15s}
.link-card:hover{border-color:var(--accent2);background:var(--surf2);text-decoration:none}
.link-card .lc-icon{font-size:18px;flex-shrink:0;opacity:.7}
.link-card .lc-label{font-size:10px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;margin-bottom:2px}
.link-card .lc-url{font-size:13px;color:var(--accent2)}

/* section heading */
.sec-head{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;
  color:var(--muted);margin:36px 0 14px;padding-bottom:8px;
  border-bottom:1px solid var(--border)}

/* topic cards grid */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));
  gap:10px;margin-bottom:28px}
.tcard{position:relative;height:130px;border-radius:var(--radius);overflow:hidden;
  display:block;border:1px solid var(--border);background:var(--surf2);
  transition:border-color .2s,transform .2s}
.tcard:hover{border-color:var(--accent2);transform:translateY(-3px);text-decoration:none}
.tcard .tc-img{position:absolute;inset:0;width:100%;height:100%;
  object-fit:cover;opacity:.3;transition:opacity .2s}
.tcard:hover .tc-img{opacity:.45}
.tcard .tc-ov{position:absolute;inset:0;
  background:linear-gradient(to top,rgba(2,12,32,.95) 30%,rgba(6,21,48,.3))}
.tcard .tc-body{position:absolute;bottom:0;left:0;right:0;padding:10px 12px}
.tcard .tc-type{font-size:9px;text-transform:uppercase;letter-spacing:.1em;
  color:var(--muted);margin-bottom:4px}
.tcard .tc-name{font-size:13px;font-weight:700;color:#fff;line-height:1.25}
"""

# ── D3 network JavaScript ─────────────────────────────────────────────────────

_TYPE_COLORS = {
    "class": "#1472ff",
    "individual": "#ff8c00",
    "concept": "#00d4ff",
    "topconcept": "#00ffcc",
    "scheme": "#b060ff",
}

_D3_SHARED = """\
const TYPE_COLOR={class:"#1472ff",individual:"#ff8c00",concept:"#00d4ff",
  topconcept:"#00ffcc",scheme:"#b060ff"};
function nodeColor(d){return TYPE_COLOR[d.type]||"#1472ff"}
"""

_D3_INDEX = (
    """\
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script>
(function(){
const data=__GRAPH_DATA__;
const W=window.innerWidth,H=window.innerHeight-52;
"""
    + _D3_SHARED
    + """\
const isRoot=d=>d.type==="class"&&d.rootClass;
const safeId=id=>id.replace(/\\W/g,"_");

const svg=d3.select("#index-net").append("svg")
  .attr("width",W).attr("height",H)
  .style("display","block");

const g=svg.append("g");
svg.call(d3.zoom().scaleExtent([.15,5])
  .on("zoom",e=>g.attr("transform",e.transform)));

// Background click deselects
let selected=null;
svg.on("click",()=>{
  if(selected){
    selected=null;
    nodeG.selectAll("circle.main").attr("fill-opacity",d=>isRoot(d)?0.22:0.12)
      .attr("stroke-opacity",d=>isRoot(d)?0.8:0.4);
    linkG.attr("stroke-opacity",0.25);
    tooltip.style("display","none");
  }
});

const sim=d3.forceSimulation(data.nodes)
  .force("link",d3.forceLink(data.links).id(d=>d.id).distance(d=>{
    const s=data.nodes.find(n=>n.id===d.source||n.id===d.source?.id);
    return(s&&s.type==="class")?140:90;
  }).strength(0.35))
  .force("charge",d3.forceManyBody().strength(d=>isRoot(d)?-800:-280))
  .force("center",d3.forceCenter(W/2,H/2))
  .force("collision",d3.forceCollide(d=>isRoot(d)?50:28));

const linkG=g.append("g").selectAll("line").data(data.links).join("line")
  .attr("stroke","#1a3870").attr("stroke-width",1).attr("stroke-opacity",.25);

const nodeG=g.append("g").selectAll("g").data(data.nodes).join("g")
  .style("cursor","pointer")
  .on("click",function(e,d){
    e.stopPropagation();
    selected=d.id;
    nodeG.selectAll("circle.main")
      .attr("fill-opacity",n=>n.id===d.id?0.7:0.06)
      .attr("stroke-opacity",n=>n.id===d.id?1:0.15);
    const nbrs=new Set([d.id,...data.links
      .filter(l=>(l.source.id||l.source)===d.id||(l.target.id||l.target)===d.id)
      .flatMap(l=>[(l.source.id||l.source),(l.target.id||l.target)])]);
    linkG.attr("stroke-opacity",l=>{
      const s=l.source.id||l.source,t=l.target.id||l.target;
      return(s===d.id||t===d.id)?0.7:0.05;
    });
    tooltip.style("display","block")
      .style("left",(e.clientX+12)+"px").style("top",(e.clientY-8)+"px")
      .html("<b>"+d.label+"</b><br><span>"+d.type+"</span>"+
        (d.href&&d.href!="#"?"<br><a href=\\""+d.href+"\\">Open →</a>":""));
  })
  .call(d3.drag()
    .on("start",(e,d)=>{if(!e.active)sim.alphaTarget(.3).restart();d.fx=d.x;d.fy=d.y})
    .on("drag", (e,d)=>{d.fx=e.x;d.fy=e.y})
    .on("end",  (e,d)=>{if(!e.active)sim.alphaTarget(0);d.fx=null;d.fy=null}));

// Root class halo
nodeG.filter(d=>isRoot(d))
  .append("circle")
  .attr("r",48)
  .attr("fill","none")
  .attr("stroke",d=>nodeColor(d))
  .attr("stroke-width",1)
  .attr("stroke-opacity",.15)
  .attr("stroke-dasharray","5 4");

// Image thumbnail (clipped to circle, underneath color overlay)
nodeG.filter(d=>d.img).append("image")
  .attr("href",d=>d.img)
  .attr("x",d=>-(isRoot(d)?34:20))
  .attr("y",d=>-(isRoot(d)?34:20))
  .attr("width",d=>(isRoot(d)?34:20)*2)
  .attr("height",d=>(isRoot(d)?34:20)*2)
  .attr("preserveAspectRatio","xMidYMid slice")
  .attr("opacity",0.85)
  .style("clip-path","circle(50% at center)");

nodeG.append("circle").attr("class","main")
  .attr("r",d=>isRoot(d)?34:20)
  .attr("fill",d=>nodeColor(d))
  .attr("fill-opacity",d=>d.img?(isRoot(d)?0.35:0.25):isRoot(d)?0.22:0.12)
  .attr("stroke",d=>nodeColor(d))
  .attr("stroke-width",d=>isRoot(d)?1.5:1)
  .attr("stroke-opacity",d=>isRoot(d)?0.8:0.4);

nodeG.append("text")
  .text(d=>{const l=d.label;return l.length>22?l.slice(0,20)+"…":l})
  .attr("text-anchor","middle").attr("dy","0.35em")
  .attr("font-size",d=>isRoot(d)?"12px":"10px")
  .attr("font-weight",d=>isRoot(d)?"700":"400")
  .attr("fill",d=>isRoot(d)?"#c8e0ff":"#4d6a99")
  .attr("pointer-events","none");

sim.on("tick",()=>{
  linkG.attr("x1",d=>d.source.x).attr("y1",d=>d.source.y)
       .attr("x2",d=>d.target.x).attr("y2",d=>d.target.y);
  nodeG.attr("transform",d=>"translate("+d.x+","+d.y+")");
});

// Tooltip
const tooltip=d3.select("body").append("div")
  .style("position","fixed").style("display","none")
  .style("background","#06142e").style("border","1px solid #1a3870")
  .style("border-radius","8px").style("padding","10px 14px")
  .style("font-size","13px").style("color","#cce0f8")
  .style("z-index","500")
  .style("max-width","220px").style("line-height","1.5");
tooltip.on("click",e=>e.stopPropagation());
})();
</script>
"""
)

_D3_PAGE = (
    """\
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script>
(function(){
const data=__GRAPH_DATA__;
const el=document.getElementById("page-net");
if(!el||!data.nodes.length)return;
const rect=el.getBoundingClientRect();
const W=rect.width||window.innerWidth-420,H=rect.height||window.innerHeight-52;
"""
    + _D3_SHARED
    + """\
const svg=d3.select("#page-net").append("svg")
  .attr("width",W).attr("height",H).style("display","block");

const focusNode=data.nodes.find(n=>n.focus);
if(focusNode){focusNode.fx=W/2;focusNode.fy=H/2}

const sim=d3.forceSimulation(data.nodes)
  .force("link",d3.forceLink(data.links).id(d=>d.id).distance(130).strength(.5))
  .force("charge",d3.forceManyBody().strength(d=>d.focus?-900:-320))
  .force("center",d3.forceCenter(W/2,H/2))
  .force("collision",d3.forceCollide(d=>d.focus?44:28));

const linkG=svg.append("g").selectAll("line").data(data.links).join("line")
  .attr("stroke","#1a3870").attr("stroke-width",1).attr("stroke-opacity",.5);

const nodeG=svg.append("g").selectAll("g").data(data.nodes).join("g")
  .style("cursor",d=>d.href&&d.href!="#"&&!d.focus?"pointer":"default")
  .on("click",(e,d)=>{if(d.href&&d.href!="#"&&!d.focus)window.location=d.href})
  .call(d3.drag()
    .on("start",(e,d)=>{if(!e.active)sim.alphaTarget(.3).restart();d.fx=d.x;d.fy=d.y})
    .on("drag", (e,d)=>{d.fx=e.x;d.fy=e.y})
    .on("end",  (e,d)=>{
      if(!e.active)sim.alphaTarget(0);
      if(d.focus){d.fx=W/2;d.fy=H/2}else{d.fx=null;d.fy=null}
    }));

// Focus halo
nodeG.filter(d=>d.focus).append("circle")
  .attr("r",30).attr("fill","none")
  .attr("stroke",d=>nodeColor(d)).attr("stroke-width",1)
  .attr("stroke-opacity",.3).attr("stroke-dasharray","4 3");

// Image thumbnail
nodeG.filter(d=>d.img).append("image")
  .attr("href",d=>d.img)
  .attr("x",d=>-(d.focus?20:13))
  .attr("y",d=>-(d.focus?20:13))
  .attr("width",d=>(d.focus?20:13)*2)
  .attr("height",d=>(d.focus?20:13)*2)
  .attr("preserveAspectRatio","xMidYMid slice")
  .attr("opacity",0.85)
  .style("clip-path","circle(50% at center)");

nodeG.append("circle")
  .attr("r",d=>d.focus?20:13)
  .attr("fill",d=>nodeColor(d))
  .attr("fill-opacity",d=>d.img?(d.focus?0.4:0.25):d.focus?0.75:0.18)
  .attr("stroke",d=>nodeColor(d))
  .attr("stroke-width",d=>d.focus?2:1)
  .attr("stroke-opacity",d=>d.focus?1:0.6);

nodeG.append("text")
  .text(d=>{const l=d.label;return l.length>16?l.slice(0,14)+"…":l})
  .attr("text-anchor","middle")
  .attr("dy",d=>d.focus?36:26)
  .attr("font-size",d=>d.focus?"11px":"9px")
  .attr("font-weight",d=>d.focus?"700":"400")
  .attr("fill",d=>d.focus?"#c8e0ff":"#4d6a99")
  .attr("pointer-events","none");

sim.on("tick",()=>{
  linkG.attr("x1",d=>d.source.x).attr("y1",d=>d.source.y)
       .attr("x2",d=>d.target.x).attr("y2",d=>d.target.y);
  nodeG.attr("transform",d=>"translate("+d.x+","+d.y+")");
});
})();
</script>
"""
)

# ── HTML templates ─────────────────────────────────────────────────────────────

_INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{site_name}</title>
<style>{css}</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-logo"><div class="dot"></div>{site_name}</div>
  <div class="topbar-bc"><span class="cur">Transformation Map</span></div>
</div>
<div class="index-root" style="position:relative">
  <div class="index-header">
    <h1>{site_name}</h1>
    <p>{subtitle}</p>
  </div>
  <div id="index-net" style="flex:1;width:100%;position:relative"></div>
  <div class="index-legend">
    <div class="leg"><div class="leg-dot" style="background:#1472ff"></div>Class</div>
    <div class="leg"><div class="leg-dot" style="background:#ff8c00"></div>Individual</div>
    <div class="leg"><div class="leg-dot" style="background:#00d4ff"></div>Concept</div>
    <div class="leg"><div class="leg-dot" style="background:#00ffcc"></div>Top Concept</div>
  </div>
  <div class="index-hint">Click a node to explore · scroll to zoom · drag to pan</div>
</div>
{d3_script}
</body>
</html>
"""

_PAGE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — {site_name}</title>
<style>{css}</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-logo"><div class="dot"></div><a href="index.html" style="color:inherit">{site_name}</a></div>
  <div class="topbar-bc">{breadcrumb}</div>
</div>
<div class="page-root">

  <!-- Left: graph pane -->
  <div class="graph-pane">
    <div id="page-net"></div>
    <div class="graph-legend">
      <div class="leg"><div class="leg-dot" style="background:#1472ff"></div>Class</div>
      <div class="leg"><div class="leg-dot" style="background:#ff8c00"></div>Individual</div>
      <div class="leg"><div class="leg-dot" style="background:#00d4ff"></div>Concept</div>
    </div>
  </div>

  <!-- Right: info panel -->
  <div class="info-pane">
    <div class="entity-header">
      <div class="badge badge-{badge_cls}">{badge_label}</div>
      <h1>{title}</h1>
    </div>
    {hero_img}
    <div class="info-content">
      {description}
      {videos}
      {ext_links}
      {related}
    </div>
    {sidebar}
    <div class="uri-chip">{uri}</div>
  </div>

</div>
{d3_script}
</body>
</html>
"""

# ── Graph data builders ───────────────────────────────────────────────────────


def _entity_kind(taxonomy: object, uri: str) -> str:
    from .model import Taxonomy

    assert isinstance(taxonomy, Taxonomy)
    if uri in taxonomy.concepts:
        return "topconcept" if taxonomy.concepts[uri].top_concept_of else "concept"
    if uri in taxonomy.owl_classes:
        return "class"
    if uri in taxonomy.owl_individuals:
        return "individual"
    if uri in taxonomy.schemes:
        return "scheme"
    return "class"


def _full_graph_json(taxonomy: object, slug_map: dict[str, str], label_fn: object) -> str:
    from .model import Taxonomy

    assert isinstance(taxonomy, Taxonomy)
    assert callable(label_fn)

    nodes: dict[str, dict] = {}
    links: list[dict] = []
    root_classes = {uri for uri, c in taxonomy.owl_classes.items() if not c.sub_class_of}

    def _img(uri: str) -> str:
        if uri in taxonomy.concepts:
            imgs = taxonomy.concepts[uri].schema_images
        elif uri in taxonomy.owl_classes:
            imgs = taxonomy.owl_classes[uri].schema_images
        elif uri in taxonomy.owl_individuals:
            imgs = taxonomy.owl_individuals[uri].schema_images
        else:
            imgs = []
        return imgs[0] if imgs else ""

    def add(uri: str) -> None:
        if uri in nodes:
            return
        nodes[uri] = {
            "id": uri,
            "label": label_fn(uri),
            "type": _entity_kind(taxonomy, uri),
            "href": slug_map.get(uri, "#"),
            "focus": False,
            "rootClass": uri in root_classes,
            "img": _img(uri),
        }

    for uri in taxonomy.concepts:
        add(uri)
    for uri in taxonomy.owl_classes:
        add(uri)
    for uri in taxonomy.owl_individuals:
        add(uri)

    for uri, concept in taxonomy.concepts.items():
        for b in concept.broader:
            if b in nodes:
                links.append({"source": uri, "target": b})
    for uri, cls in taxonomy.owl_classes.items():
        for p in cls.sub_class_of:
            if p in nodes:
                links.append({"source": uri, "target": p})
    for uri, ind in taxonomy.owl_individuals.items():
        for t in ind.types:
            if t in nodes:
                links.append({"source": uri, "target": t})

    return _json.dumps({"nodes": list(nodes.values()), "links": links})


def _neighborhood_json(
    taxonomy: object, focus_uri: str, slug_map: dict[str, str], label_fn: object
) -> str:
    from .model import Taxonomy

    assert isinstance(taxonomy, Taxonomy)
    assert callable(label_fn)

    nodes: dict[str, dict] = {}
    links: list[dict] = []

    def _img2(uri: str) -> str:
        if uri in taxonomy.concepts:
            imgs = taxonomy.concepts[uri].schema_images
        elif uri in taxonomy.owl_classes:
            imgs = taxonomy.owl_classes[uri].schema_images
        elif uri in taxonomy.owl_individuals:
            imgs = taxonomy.owl_individuals[uri].schema_images
        else:
            imgs = []
        return imgs[0] if imgs else ""

    def add(uri: str, focus: bool = False) -> None:
        if uri in nodes:
            return
        nodes[uri] = {
            "id": uri,
            "label": label_fn(uri),
            "type": _entity_kind(taxonomy, uri),
            "href": slug_map.get(uri, "#"),
            "focus": focus,
            "img": _img2(uri),
        }

    add(focus_uri, focus=True)

    concept = taxonomy.concepts.get(focus_uri)
    if concept:
        for u in concept.broader + concept.narrower + concept.related:
            add(u)
            links.append({"source": focus_uri, "target": u})

    cls = taxonomy.owl_classes.get(focus_uri)
    if cls:
        for u in cls.sub_class_of:
            add(u)
            links.append({"source": focus_uri, "target": u})
        for u, c in taxonomy.owl_classes.items():
            if focus_uri in c.sub_class_of:
                add(u)
                links.append({"source": u, "target": focus_uri})
        for u, ind in taxonomy.owl_individuals.items():
            if focus_uri in ind.types:
                add(u)
                links.append({"source": u, "target": focus_uri})

    ind_maybe = taxonomy.owl_individuals.get(focus_uri)
    if ind_maybe:
        ind = ind_maybe
        for u in ind.types:
            add(u)
            links.append({"source": focus_uri, "target": u})
        for _, val_uri in ind.property_values:
            add(val_uri)
            links.append({"source": focus_uri, "target": val_uri})

    return _json.dumps({"nodes": list(nodes.values()), "links": links})


# ── Render helpers ────────────────────────────────────────────────────────────


def _slug(uri: str) -> str:
    for sep in ("#", "/"):
        if sep in uri:
            part = uri.rsplit(sep, 1)[-1]
            if part:
                return _re.sub(r"[^\w-]", "_", part)
    return _re.sub(r"[^\w-]", "_", uri)


def _esc(s: str) -> str:
    return _html.escape(s)


def _render_hero_img(entity: object) -> str:
    imgs: list[str] = getattr(entity, "schema_images", [])
    if not imgs:
        return ""
    return f'<img class="entity-img" src="{_esc(imgs[0])}" alt="">'


def _render_description(entity: object, lang: str) -> str:
    text = ""
    defs = getattr(entity, "definitions", None)
    if defs:
        for d in defs:
            if d.lang == lang:
                text = d.value
                break
        if not text:
            text = defs[0].value
    if not text:
        cmts = getattr(entity, "comments", None)
        if cmts:
            for c in cmts:
                if c.lang == lang:
                    text = c.value
                    break
            if not text:
                text = cmts[0].value
    return f'<div class="desc">{_md_to_html(text)}</div>' if text else ""


_YT_ALLOW = (
    "accelerometer; autoplay; clipboard-write; encrypted-media; "
    "gyroscope; picture-in-picture; web-share"
)
_VIMEO_ALLOW = "autoplay; fullscreen; picture-in-picture"


def _render_videos(entity: object) -> str:
    parts = []
    for url in getattr(entity, "schema_videos", []):
        result = _video_embed_url(url)
        if result:
            embed, platform = result
            allow = _YT_ALLOW if platform == "youtube" else _VIMEO_ALLOW
            parts.append(
                f'<div class="video-wrap">'
                f'<iframe src="{_esc(embed)}" frameborder="0" '
                f'allow="{allow}" allowfullscreen loading="lazy"></iframe>'
                f"</div>"
            )
    return "\n".join(parts)


def _render_ext_links(entity: object) -> str:
    parts = []
    for url in getattr(entity, "schema_urls", []):
        display = url if len(url) <= 55 else url[:52] + "…"
        parts.append(
            f'<a class="link-card" href="{_esc(url)}" target="_blank" rel="noopener">'
            f'<span class="lc-icon">↗</span>'
            f'<div><div class="lc-label">External link</div>'
            f'<div class="lc-url">{_esc(display)}</div></div>'
            f"</a>"
        )
    return "\n".join(parts)


def _tcard(label: str, type_label: str, href: str, img_url: str = "") -> str:
    img_tag = f'<img class="tc-img" src="{_esc(img_url)}" alt="" loading="lazy">' if img_url else ""
    return (
        f'<a class="tcard" href="{href}">'
        f"{img_tag}"
        f'<div class="tc-ov"></div>'
        f'<div class="tc-body">'
        f'<div class="tc-type">{_esc(type_label)}</div>'
        f'<div class="tc-name">{_esc(label)}</div>'
        f"</div></a>"
    )


def _sbox(title: str, items: list[tuple[str, str]]) -> str:
    if not items:
        return ""
    lis = "".join(f'<li><a href="{h}">{_esc(l)}</a></li>' for l, h in items)
    return f'<div class="sbox"><h4>{_esc(title)}</h4><ul>{lis}</ul></div>'


def _bc(parts: list[tuple[str, str | None]]) -> str:
    out = []
    for i, (label, href) in enumerate(parts):
        if i:
            out.append('<span class="sep">›</span>')
        if href:
            out.append(f'<a href="{href}">{_esc(label)}</a>')
        else:
            out.append(f'<span class="cur">{_esc(label)}</span>')
    return "".join(out)


# ── Main generator ────────────────────────────────────────────────────────────


def generate_site(
    taxonomy_path: Path,
    output_dir: Path,
    lang: str = "en",
    site_name: str | None = None,
) -> list[Path]:
    """Generate a WEF Transformation Map-style static hub site.

    One page per concept / class / individual, plus an index page with a
    full-screen interactive D3 force network.  Each entity page shows:
    - Hero band (image background if schema:image is set)
    - Markdown description (rdfs:comment / skos:definition)
    - Video embed (schema:video — YouTube / Vimeo)
    - External link cards (schema:url)
    - Interactive neighbourhood network (D3, sticky right panel)
    - Related entity cards grid

    Returns list of Path objects for files written.
    """
    from .store import load as _load

    taxonomy = _load(taxonomy_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Site name
    if site_name is None:
        if taxonomy.schemes:
            site_name = next(iter(taxonomy.schemes.values())).title(lang) or taxonomy_path.stem
        elif taxonomy.ontology_label:
            site_name = taxonomy.ontology_label
        else:
            site_name = taxonomy_path.stem

    # Slug map
    slug_map: dict[str, str] = {}
    for uri in (
        list(taxonomy.concepts) + list(taxonomy.owl_classes) + list(taxonomy.owl_individuals)
    ):
        slug_map[uri] = _slug(uri) + ".html"

    # Image map: uri → first schema:image URL
    img_map: dict[str, str] = {}
    for uri, c in taxonomy.concepts.items():
        if c.schema_images:
            img_map[uri] = c.schema_images[0]
    for uri, cls in taxonomy.owl_classes.items():
        if cls.schema_images:
            img_map[uri] = cls.schema_images[0]
    for uri, ind in taxonomy.owl_individuals.items():
        if ind.schema_images:
            img_map[uri] = ind.schema_images[0]

    created: list[Path] = []

    def label(uri: str) -> str:
        c = taxonomy.concepts.get(uri)
        if c:
            return c.pref_label(lang)
        cls = taxonomy.owl_classes.get(uri)
        if cls:
            return cls.label(lang)
        ind = taxonomy.owl_individuals.get(uri)
        if ind:
            return ind.label(lang)
        return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] or uri

    def href(uri: str) -> str:
        return slug_map.get(uri, "#")

    def d3_script_page(focus_uri: str) -> str:
        gdata = _neighborhood_json(taxonomy, focus_uri, slug_map, label)
        return _D3_PAGE.replace("__GRAPH_DATA__", gdata)

    # ── Concept pages ─────────────────────────────────────────────────────────
    for uri, concept in taxonomy.concepts.items():
        title = concept.pref_label(lang)
        is_top = bool(concept.top_concept_of)
        badge_cls = "topconcept" if is_top else "concept"
        badge_label = "Top Concept" if is_top else "Concept"

        bc_items: list[tuple[str, str | None]] = [
            (site_name, "index.html"),
        ]
        if concept.broader:
            p = concept.broader[0]
            bc_items.append((label(p), href(p)))
        bc_items.append((title, None))

        sidebar = ""
        if concept.broader:
            sidebar += _sbox("Broader", [(label(u), href(u)) for u in concept.broader])
        if concept.related:
            sidebar += _sbox("Related", [(label(u), href(u)) for u in concept.related[:10]])

        related = ""
        if concept.narrower:
            cards = "".join(
                _tcard(label(u), "Concept", href(u), img_map.get(u, "")) for u in concept.narrower
            )
            related = (
                f'<div class="sec-head">Narrower concepts</div><div class="cards">{cards}</div>'
            )

        page = _PAGE_HTML.format(
            title=_esc(title),
            site_name=_esc(site_name),
            css=_CSS,
            breadcrumb=_bc(bc_items),
            badge_cls=badge_cls,
            badge_label=badge_label,
            hero_img=_render_hero_img(concept),
            description=_render_description(concept, lang),
            videos=_render_videos(concept),
            ext_links=_render_ext_links(concept),
            related=related,
            sidebar=sidebar,
            uri=_esc(uri),
            d3_script=d3_script_page(uri),
        )
        out = output_dir / slug_map[uri]
        out.write_text(page, encoding="utf-8")
        created.append(out)

    # ── Class pages ───────────────────────────────────────────────────────────
    for uri, rdf_class in taxonomy.owl_classes.items():
        title = rdf_class.label(lang)

        bc_items = [(site_name, "index.html")]
        if rdf_class.sub_class_of:
            p = rdf_class.sub_class_of[0]
            bc_items.append((label(p), href(p)))
        bc_items.append((title, None))

        subclasses = [u for u, c in taxonomy.owl_classes.items() if uri in c.sub_class_of]
        instances = [u for u, ind in taxonomy.owl_individuals.items() if uri in ind.types]

        sidebar = ""
        if rdf_class.sub_class_of:
            sidebar += _sbox("Superclasses", [(label(u), href(u)) for u in rdf_class.sub_class_of])
        if subclasses:
            sidebar += _sbox("Subclasses", [(label(u), href(u)) for u in subclasses[:12]])

        related = ""
        if subclasses:
            cards = "".join(
                _tcard(label(u), "Class", href(u), img_map.get(u, "")) for u in subclasses
            )
            related += f'<div class="sec-head">Subclasses</div><div class="cards">{cards}</div>'
        if instances:
            cards = "".join(
                _tcard(label(u), "Individual", href(u), img_map.get(u, "")) for u in instances
            )
            related += f'<div class="sec-head">Individuals</div><div class="cards">{cards}</div>'

        page = _PAGE_HTML.format(
            title=_esc(title),
            site_name=_esc(site_name),
            css=_CSS,
            breadcrumb=_bc(bc_items),
            badge_cls="class",
            badge_label="Class",
            hero_img=_render_hero_img(rdf_class),
            description=_render_description(rdf_class, lang),
            videos=_render_videos(rdf_class),
            ext_links=_render_ext_links(rdf_class),
            related=related,
            sidebar=sidebar,
            uri=_esc(uri),
            d3_script=d3_script_page(uri),
        )
        out = output_dir / slug_map[uri]
        out.write_text(page, encoding="utf-8")
        created.append(out)

    # ── Individual pages ──────────────────────────────────────────────────────
    for uri, individual in taxonomy.owl_individuals.items():
        title = individual.label(lang)

        bc_items = [(site_name, "index.html")]
        if individual.types:
            t = individual.types[0]
            bc_items.append((label(t), href(t)))
        bc_items.append((title, None))

        sidebar = ""
        if individual.types:
            sidebar += _sbox("Instance of", [(label(u), href(u)) for u in individual.types])
        if individual.property_values:
            prop_items = []
            for prop_uri, val_uri in individual.property_values:
                prop = taxonomy.owl_properties.get(prop_uri)
                plbl = prop.label(lang) if prop else prop_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                prop_items.append((f"{plbl}: {label(val_uri)}", href(val_uri)))
            sidebar += _sbox("Properties", prop_items[:12])

        page = _PAGE_HTML.format(
            title=_esc(title),
            site_name=_esc(site_name),
            css=_CSS,
            breadcrumb=_bc(bc_items),
            badge_cls="individual",
            badge_label="Individual",
            hero_img=_render_hero_img(individual),
            description=_render_description(individual, lang),
            videos=_render_videos(individual),
            ext_links=_render_ext_links(individual),
            related="",
            sidebar=sidebar,
            uri=_esc(uri),
            d3_script=d3_script_page(uri),
        )
        out = output_dir / slug_map[uri]
        out.write_text(page, encoding="utf-8")
        created.append(out)

    # ── Index page ────────────────────────────────────────────────────────────
    total = len(taxonomy.concepts) + len(taxonomy.owl_classes) + len(taxonomy.owl_individuals)
    subtitle = f"{total} entities across {len(taxonomy.owl_classes)} classes"
    if taxonomy.schemes:
        first_scheme = next(iter(taxonomy.schemes.values()))
        descs = first_scheme.descriptions
        if descs:
            subtitle = descs[0].value.split("\n")[0].lstrip("#").strip()

    full_gdata = _full_graph_json(taxonomy, slug_map, label)
    d3_index = _D3_INDEX.replace("__GRAPH_DATA__", full_gdata)

    index_page = _INDEX_HTML.format(
        site_name=_esc(site_name),
        css=_CSS,
        subtitle=_esc(subtitle[:120]),
        d3_script=d3_index,
    )
    index_path = output_dir / "index.html"
    index_path.write_text(index_page, encoding="utf-8")
    created.append(index_path)

    return created
