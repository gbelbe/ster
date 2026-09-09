"""The standalone HTML page template (_HTML_TEMPLATE) that wraps the VOWL graph data."""

from __future__ import annotations

from ..branding import FAVICON_LINK_TAG
from ..viz import (
    _label_for,  # noqa: F401  (re-exported for potential callers)
)

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
__FAVICON__
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f1f5f9;color:#1e293b;font-family:system-ui,-apple-system,sans-serif;display:flex;overflow:hidden}
/* #cy and #treemap share the same flex slot, stacked via position:absolute, so
   Cytoscape always measures a real (non-zero) container size even when its tab
   starts inactive — toggling `visibility` (not `display`) never resizes the box.
   #app-toolbar floats on top of both (like #view-tabs did before it), so #cy's
   own rect and size are untouched — explore-btn/individuals-btn are positioned by
   graph_app.js relative to #cy and must never have that rect change. */
#view-stage{position:relative;flex:1;height:100vh}
#cy,#treemap{position:absolute;inset:0;height:100%;background:#fff}
#treemap{overflow:hidden}
.view-relations,.view-taxonomy{visibility:hidden;pointer-events:none}
body[data-active-view="relations"] .view-relations{visibility:visible;pointer-events:auto}
body[data-active-view="taxonomy"] .view-taxonomy{visibility:visible;pointer-events:auto}
#app-toolbar{position:absolute;top:0;left:0;right:0;height:44px;z-index:32;display:flex;align-items:center;gap:16px;padding:0 12px;background:#f8fafc;border-bottom:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,.06);overflow:hidden}
#view-tabs{display:flex;gap:4px;flex-shrink:0}
.vt-btn{background:none;border:none;color:#64748b;cursor:pointer;font-size:12px;font-weight:600;padding:6px 12px;border-radius:6px}
.vt-btn.active{background:#2563eb;color:#fff}
.vt-btn:hover:not(.active){background:#e2e8f0}
/* The breadcrumb/scheme/depth filters are taxonomy-specific (Relations has no
   equivalent concept), so unlike the shared search box they get their own
   sub-bar rather than crowding the shared top bar — collapsed entirely
   (`display`, not `visibility`) when not the active view, so Relations gets
   the full canvas back instead of an empty reserved strip. */
#tm-subbar{position:absolute;top:44px;left:0;right:0;height:32px;z-index:31;display:none;align-items:center;gap:16px;padding:0 12px;background:#f8fafc;border-bottom:1px solid #e2e8f0;overflow:hidden}
body[data-active-view="taxonomy"] #tm-subbar{display:flex}
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
#individuals-btn{position:absolute;display:none;transform:translate(-50%,0);z-index:40;background:#64748b;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:11px;font-weight:600;padding:4px 10px;box-shadow:0 2px 8px rgba(0,0,0,.25);white-space:nowrap}
#individuals-btn:hover{background:#475569}
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
.dp-editable{margin:2px 0}.dp-editable-view{display:flex;align-items:baseline;gap:6px}.dp-edit-btn{background:none;border:none;color:#94a3b8;cursor:pointer;font-size:11px;padding:0;line-height:1;flex-shrink:0}.dp-edit-btn:hover{color:#475569}.dp-editable-edit{margin:4px 0}.dp-edit-input{width:100%;font:inherit;color:#1e293b;border:1px solid #cbd5e1;border-radius:4px;padding:4px 6px;background:#fff;resize:vertical}.dp-edit-actions{display:flex;gap:6px;margin-top:5px}.dp-edit-save{background:#2563eb;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:11px;padding:3px 10px}.dp-edit-save:hover{background:#1d4ed8}.dp-edit-save:disabled{opacity:.6;cursor:default}.dp-edit-cancel{background:none;border:1px solid #cbd5e1;color:#475569;border-radius:4px;cursor:pointer;font-size:11px;padding:3px 10px}.dp-edit-cancel:hover{background:#f1f5f9}.dp-edit-err{color:#dc2626;font-size:10px;margin-top:4px}
.dp-rel-remove{background:none;border:none;color:#94a3b8;cursor:pointer;font-size:13px;line-height:1;padding:0 0 0 6px;flex-shrink:0}.dp-rel-remove:hover{color:#dc2626}.dp-rel-remove:disabled{opacity:.5;cursor:default}.dp-rel-add{margin-top:8px;padding-top:8px;border-top:1px dashed #e2e8f0}.dp-picker{position:relative;margin:4px 0}.dp-picker-input{width:100%;font:inherit;font-size:11px;color:#1e293b;border:1px solid #cbd5e1;border-radius:4px;padding:4px 6px;background:#fff}.dp-picker-list{position:absolute;left:0;right:0;top:100%;z-index:50;background:#fff;border:1px solid #e2e8f0;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,.12);max-height:160px;overflow-y:auto;margin-top:2px}.dp-picker-opt{display:block;width:100%;text-align:left;background:none;border:none;cursor:pointer;font-size:11px;padding:5px 8px;color:#1e293b}.dp-picker-opt:hover{background:#f1f5f9}.dp-picker-opt .dp-uri{font-size:9px;color:#94a3b8}
.dp-a{color:#3b82f6;text-decoration:none;word-break:break-all}
.dp-a:hover{text-decoration:underline}
.dp-fig{margin:8px 0}
/* min-height keeps a still-loading image from collapsing to nothing, which reads
   as "this concept has no media" until the bytes arrive. */
.dp-img,.dp-video{max-width:100%;height:auto;border-radius:6px;display:block;background:#f1f5f9;min-height:40px}
.dp-video{width:100%}
.dp-cap{font-size:10px;color:#94a3b8;margin-top:3px}
.dp-broken{font-size:10px;color:#94a3b8;font-style:italic;padding:8px;border:1px dashed #cbd5e1;border-radius:6px;text-align:center}
.lr{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:11px;color:#334155}
#search-wrap{display:flex;align-items:center;gap:6px;background:#fff;border:1px solid #e2e8f0;border-radius:6px;padding:4px 10px;flex:1;max-width:420px}
#search-box{border:none;background:transparent;outline:none;font-size:13px;color:#1e293b;width:100%}
#search-box::placeholder{color:#94a3b8}
#search-count,#tm-search-count{font-size:11px;color:#64748b;white-space:nowrap;min-width:52px}
#search-clear{background:none;border:none;color:#94a3b8;cursor:pointer;font-size:16px;line-height:1;padding:0 2px;display:none;flex-shrink:0}
#search-clear:hover{color:#475569}
#offline-banner{position:fixed;top:48px;left:50%;transform:translateX(-50%);z-index:35;display:flex;align-items:center;gap:10px;background:#fef3c7;color:#92400e;border:1px solid #fcd34d;border-radius:8px;padding:6px 12px;font-size:12px;line-height:1.4;box-shadow:0 2px 8px rgba(0,0,0,.08);max-width:80vw}
#offline-banner code{background:#fde68a;padding:0 4px;border-radius:3px;font-size:11px}
#offline-banner-close{flex-shrink:0;background:none;border:none;color:#92400e;cursor:pointer;font-size:16px;line-height:1;padding:0 2px}
#offline-banner-close:hover{color:#451a03}
#tm-breadcrumb{display:flex;align-items:center;gap:4px;font-size:12px;color:#475569;overflow-x:auto;white-space:nowrap;flex:1;min-width:0}
#tm-breadcrumb button{background:none;border:none;color:#3b82f6;cursor:pointer;font-size:12px;padding:0;flex-shrink:0}
#tm-breadcrumb button:hover{text-decoration:underline}
#tm-filters{display:flex;align-items:center;gap:10px;font-size:11px;color:#475569;flex-shrink:0}
#tm-filters select{font-size:11px;border:1px solid #cbd5e1;border-radius:4px;background:#fff;color:#334155}
</style>
</head>
<body>
__OFFLINE_BANNER__
<div id="view-stage">
<div id="app-toolbar">
<div id="view-tabs"><button class="vt-btn" data-view="taxonomy">Taxonomie</button><button class="vt-btn" data-view="relations">Relations</button></div>
<div id="search-wrap"><svg width="14" height="14" viewBox="0 0 14 14" fill="none" style="flex-shrink:0;opacity:.5"><circle cx="5.5" cy="5.5" r="4" stroke="#475569" stroke-width="1.5"/><line x1="8.5" y1="8.5" x2="13" y2="13" stroke="#475569" stroke-width="1.5" stroke-linecap="round"/></svg><input id="search-box" type="search" placeholder="Search…" autocomplete="off" spellcheck="false" autofocus><span id="search-count" class="view-relations"></span><span id="tm-search-count" class="view-taxonomy"></span><button id="search-clear" title="Clear (Esc)">\xd7</button></div>
</div>
<div id="tm-subbar">
<div id="tm-breadcrumb"></div>
<div id="tm-filters"><label>Scheme <select id="tm-filter-scheme"></select></label><label>Depth ≤ <select id="tm-filter-depth"></select></label><label>Layout <select id="tm-filter-layout"><option value="horizontal" selected>Horizontal</option><option value="radial">Radial</option></select></label></div>
</div>
<div id="cy" class="view-relations"></div>
<div id="treemap" class="view-taxonomy"></div>
</div>
<div id="detail-panel"></div>
<button id="panel-close" title="Close panel (Esc)">\xd7</button>
<div id="stats" class="view-relations"></div>
<div id="hint" class="view-relations">drag\xb7pan\xb7scroll→zoom \xb7 f: layout \xb7 click: details \xb7 esc: close<span style="color:#cbd5e1"> │ </span><button class="ftbtn active" id="ft-individuals">individuals</button><button class="ftbtn active" id="ft-first-order">1st order</button><button class="ftbtn active" id="ft-second-order">2nd order</button><button class="ftbtn active" id="ft-instanceOf">rdf:type</button><button class="ftbtn active" id="ft-superclasses">superclasses</button><button class="ftbtn active" id="ft-inScheme">inScheme</button><button class="ftbtn active" id="ft-datatypeProperty">datatype</button>__SHOW_ALL_BTN__</div>
<button id="explore-btn" class="view-relations">&#8857; explore relations</button><button id="individuals-btn" class="view-relations">&#8853; show individuals</button>
<div id="zoom-ctrl" class="view-relations"><button id="zoom-in" title="Zoom in (+)">+</button><button id="zoom-out" title="Zoom out (−)">&#8722;</button><button id="zoom-fit" title="Fit all (f)">Recenter</button></div>
<div id="tip" class="view-relations"></div>
__CY_SCRIPT__
__LAYOUT_BASE_SCRIPT__
__COSE_BASE_SCRIPT__
__FCOSE_SCRIPT__
__EXPAND_COLLAPSE_SCRIPT__
__D3_SCRIPT__
__D3_PATH_SCRIPT__
__D3_SHAPE_SCRIPT__
__STER_DATA_SCRIPT__
<script>
__STER_APP_JS__
</script>
<script>
__STER_TREEMAP_JS__
</script>
<script>
(function(){
  var g=globalThis.__STER_GRAPH__||{};
  var tax=g.taxonomy||null;
  var hasTax=!!(tax && tax.nodes && Object.keys(tax.nodes).length);
  var hasRel=!!(g.data && g.data.nodes && g.data.nodes.length);
  var body=document.body;
  var tabs=document.getElementById('view-tabs');
  if(!hasTax || !hasRel){
    // Nothing to switch between (e.g. an OWL-only file) — hide the tabs, but
    // the toolbar itself (and its shared search box) stays, exactly as the
    // search box worked before the Taxonomie tab existed.
    tabs.style.display='none';
  }
  var initial=hasTax?'taxonomy':'relations';
  body.dataset.activeView=initial;
  // The Relations tab's Cytoscape graph (and its force layout) is expensive
  // to build on a large ontology, so it is only built the first time the tab
  // is actually shown — not on every page load — see initSterRelationsGraph
  // in graph_app.js.
  var relInit=false;
  function ensureRelations(){
    if(relInit)return;
    relInit=true;
    if(typeof initSterRelationsGraph==='function')initSterRelationsGraph();
  }
  if(initial==='relations')ensureRelations();
  var btns=[].slice.call(document.querySelectorAll('.vt-btn'));
  btns.forEach(function(btn){
    btn.classList.toggle('active',btn.dataset.view===initial);
    btn.addEventListener('click',function(){
      body.dataset.activeView=btn.dataset.view;
      btns.forEach(function(b){b.classList.toggle('active',b===btn);});
      if(btn.dataset.view==='relations')ensureRelations();
    });
  });
})();
</script>
</body>
</html>
"""

_HTML_TEMPLATE = _HTML_TEMPLATE.replace("__FAVICON__", FAVICON_LINK_TAG)
