// ster graph application layer — interaction, styling, filtering, live
// update, and detail-panel logic built on top of the vendored Cytoscape.js.
// This file is intentionally separate from the library: upgrading Cytoscape
// (see _CY_VERSION in viz_vowl.py) must never overwrite this code. It uses
// only the public global `cytoscape(...)` factory and documented cy.* API,
// and reads its per-render data from the injected `globalThis.__STER_GRAPH__`.

// Deferred: only invoked once the Relations tab is actually opened (see the
// boot script in viz_vowl.py's HTML template) — building the full Cytoscape
// graph and running its force layout is expensive on a large ontology, and
// paying that cost on every page load even when the Taxonomie tab is what's
// shown by default made large-taxonomy pages take a very long time to render.
function initSterRelationsGraph(){
try{
const graphData=globalThis.__STER_GRAPH__.data;
const taxoMeta=globalThis.__STER_GRAPH__.meta;
const API_TOKEN=globalThis.__STER_GRAPH__.token;
const panelEl=document.getElementById('detail-panel');
let panelVisible=true;
let W=globalThis.innerWidth-(panelVisible?panelEl.getBoundingClientRect().width:0);
// Small DOM-builder helper — the detail/overview panel and the hover tooltip
// used to be assembled as HTML strings (escaping each dynamic value on the
// way in) and dropped in via innerHTML; building them as real nodes instead
// means nothing dynamic ever passes through the HTML parser, so there is
// nothing to escape or to get wrong escaping.
// Split out of el() purely to keep its Cognitive Complexity down.
function applyElProps(node,props){
  for(const k in props){
    const v=props[k];
    if(v==null)continue;
    if(k==='class')node.className=v;
    else if(k==='text')node.textContent=v;
    else node.setAttribute(k,v);
  }
}
// Split out of el() purely to keep its Cognitive Complexity down. `[children]`
// wraps a bare (non-array) child so `.flat()` normalizes both call shapes —
// el('span',{},child) and el('div',{},[child1,child2]) — to one flat array.
function appendElChildren(node,children){
  for(const c of [children].flat())if(c!=null)node.append(c);
}
function el(tag,props,children){
  const node=document.createElement(tag);
  if(props)applyElProps(node,props);
  if(children)appendElChildren(node,children);
  return node;
}
function buildElements(data){
  return[
    // No `detail` here: it is fetched per node on click (see loadDetail).
    ...data.nodes.map(n=>({group:'nodes',data:{id:n.id,label:n.label,type:n.type,readOnly:n.readOnly||0,rootClass:n.rootClass||0,superclass:n.superclass||0,individualCount:n.individualCount||0,shownCount:0}})),
    ...data.edges.map(e=>({group:'edges',data:{id:e.id,source:e.source,target:e.target,type:e.type,label:e.label||'',cardinality:e.cardinality||''}})),
  ];
}
// What a class with collapsed individuals is called: its name, then how many it
// holds — or, once expanded against the cap, how many of them are actually
// drawn. Spelled out rather than nested in a ternary, because "200 of 1027" and
// "(17)" are two different statements and read better as two.
function classCountLabel(ele){
  const held=ele.data('individualCount');
  const shown=ele.data('shownCount');
  const name=ele.data('label');
  if(shown&&shown<held)return name+'\n'+shown+' of '+held;
  return name+'\n('+held+')';
}
const CY_STYLE=[
  // Dark text with a white halo: a long label wraps past the node onto the white
  // canvas, where white text was invisible. The halo keeps it legible on top of a
  // dark node too, so one colour works both on and off the shape.
  {selector:'node',style:{'label':'data(label)','text-halign':'center','text-valign':'center','color':'#0f172a','text-outline-color':'#ffffff','text-outline-width':2.5,'text-outline-opacity':1,'font-family':'system-ui,sans-serif','text-wrap':'wrap','text-max-width':'80px','font-size':12}},
  {selector:'node[type="class"]',style:{'shape':'ellipse','width':84,'height':84,'background-color':'#3c6ebf','border-color':'#5a87cc','border-width':2,'font-weight':600}},
  // A class whose individuals are collapsed says how many it holds, and wears a
  // dashed border to read as openable. Once expanded and capped it says what it
  // withheld — "200 of 1027" — so the omission stays on screen rather than
  // passing by in a toast nobody was looking at.
  {selector:'node[individualCount > 0]',style:{
    'border-style':'dashed','border-width':3,'label':classCountLabel}},
  {selector:'node[type="class"][rootClass=1]',style:{'width':104,'height':104,'border-color':'#6694d1','border-width':5,'font-size':13,'text-max-width':'92px'}},
  {selector:'node[type="individual"]',style:{'shape':'ellipse','width':68,'height':68,'background-color':'#7fb8e0','border-color':'#4a90c4','border-width':1.5,'color':'#0f172a'}},
  {selector:'node[type="scheme"]',style:{'shape':'ellipse','width':88,'height':88,'background-color':'#7c3aed','border-color':'#a78bfa','border-width':2,'font-weight':600}},
  {selector:'node[type="topconcept"]',style:{'shape':'ellipse','width':72,'height':72,'background-color':'#0e7490','border-color':'#22d3ee','border-width':2}},
  {selector:'node[type="concept"]',style:{'shape':'ellipse','width':56,'height':56,'background-color':'#166534','border-color':'#4ade80','border-width':1.5}},
  {selector:'node[type="datatype"]',style:{'shape':'round-rectangle','background-color':'#fef3c7','border-color':'#f59e0b','border-width':1.5,'color':'#92400e','font-size':10,'padding':'4px 8px','width':'label','height':22}},
  // Read-only: defined in a context file, not this one. Desaturated with a
  // dashed border — visibly present in the graph, visibly not yours to edit.
  {selector:'node[readOnly=1]',style:{'border-style':'dashed','border-width':2,'opacity':.55}},
  {selector:'node.searched',style:{'overlay-color':'#fbbf24','overlay-opacity':.45,'overlay-padding':7}},
  // Dimming recedes a node; it must not take it out of play. Nodes once carried
  // events:'no' here, so a click on a dimmed one fell through to the canvas and
  // cleared the selection — reaching a neighbour meant starting over. They stay
  // clickable, and .hovered below is what stops an unseen node stealing a click.
  {selector:'node.dimmed',style:{'opacity':.15}},
  // The node under the cursor is always fully readable, whatever else is dimmed,
  // so you see what you are about to select before committing to it.
  {selector:'node.hovered',style:{'opacity':1,'overlay-color':'#2563eb','overlay-opacity':.25,'overlay-padding':6,'z-index':999}},
  {selector:'node.hidden',style:{'display':'none'}},
  {selector:'edge',style:{'curve-style':'bezier','width':1.5,'target-arrow-shape':'triangle'}},
  {selector:'edge[type="subClassOf"]',style:{'line-color':'#94a3b8','target-arrow-color':'#94a3b8','target-arrow-fill':'hollow'}},
  {selector:'edge[type="objectProperty"]',style:{'line-color':'#818cf8','target-arrow-color':'#818cf8','label':'data(label)','font-size':10,'color':'#4f46e5','text-background-color':'white','text-background-opacity':1,'text-background-padding':'3px','text-border-width':1,'text-border-color':'#818cf8','text-border-opacity':1}},
  {selector:'edge[type="datatypeProperty"]',style:{'line-color':'#f59e0b','target-arrow-color':'#f59e0b','line-style':'dashed','line-dash-pattern':[4,3],'label':'data(label)','font-size':10,'color':'#92400e','text-background-color':'white','text-background-opacity':1,'text-background-padding':'3px','text-border-width':1,'text-border-color':'#f59e0b','text-border-opacity':1}},
  {selector:'edge[type="instanceOf"]',style:{'line-color':'#c4b5fd','target-arrow-color':'#c4b5fd','line-style':'dotted','opacity':.5,'width':1}},
  {selector:'edge[type="broader"]',style:{'line-color':'#6b7280','target-arrow-color':'#6b7280','line-style':'dashed'}},
  {selector:'edge[type="inScheme"]',style:{'line-color':'#a78bfa','target-arrow-color':'#a78bfa','line-style':'dotted','opacity':.6,'width':1}},
  {selector:'edge.dimmed',style:{'opacity':.04,'events':'no'}},
  {selector:'edge.hidden',style:{'display':'none'}},
];
function makeLayout(){
  return {name:'cose',animate:false,fit:true,padding:40,randomize:false,
    nodeRepulsion:4500,nodeOverlap:10,idealEdgeLength:100,edgeElasticity:100,
    gravity:60,numIter:1000,initialTemp:200,coolingFactor:.95,minTemp:1};
}
// Create cy without running any layout — positions applied below
// textureOnViewport / hideEdgesOnViewport keep pan+zoom smooth on big graphs by
// drawing a cached bitmap instead of re-rendering every element per frame;
// minZoomedFontSize stops Cytoscape laying out text that is too small to read,
// which is both the biggest render cost and the worst of the clutter.
const cy=cytoscape({container:document.getElementById('cy'),elements:buildElements(graphData),style:CY_STYLE,layout:{name:'preset',animate:false},wheelSensitivity:0.3,minZoom:0.05,maxZoom:8,pixelRatio:globalThis.devicePixelRatio||1,textureOnViewport:true,hideEdgesOnViewport:true,minZoomedFontSize:8});

// ── Graph state persistence (positions + viewport, survives browser/ster restart) ──
// Keyed per-path AND guarded by a signature of the current node set, so a
// different ontology (or an expanded subgraph) served at the same URL never
// restores stale positions. The version prefix invalidates any state saved by
// older builds that persisted the pre-layout pile-up.
const _stateKey='ster_state_v2_'+location.pathname;
function _graphSig(){
  const ids=cy.nodes().map(n=>n.id()).sort().join('|');
  let h=0;for(let i=0;i<ids.length;i++){h=Math.trunc(h*31+(ids.codePointAt(i)??0));}
  return cy.nodes().size()+':'+h;
}
function _saveState(){
  try{
    const pos=[];
    for(const n of cy.nodes()){const p=n.position();pos.push({id:n.id(),x:p.x,y:p.y});}
    localStorage.setItem(_stateKey,JSON.stringify({sig:_graphSig(),pos,zoom:cy.zoom(),pan:cy.pan()}));
  }catch(err){console.debug('Unable to save graph state:',err);}
}
let _saveTimer;
function _debouncedSave(){clearTimeout(_saveTimer);_saveTimer=setTimeout(_saveState,400);}

// cose is asynchronous: persist positions only once the layout settles,
// otherwise we'd save the initial origin pile-up and restore clutter next time.
function runLayout(){
  const l=cy.layout(makeLayout());
  l.one('layoutstop',_saveState);
  l.run();
}

// On load: restore saved state for THIS graph, else run a fresh layout.
(function(){
  try{
    const s=JSON.parse(localStorage.getItem(_stateKey)||'null');
    if(s?.pos?.length&&s.sig===_graphSig()){
      const posMap={};
      for(const p of s.pos){posMap[p.id]={x:p.x,y:p.y};}
      for(const n of cy.nodes()){if(posMap[n.id()])n.position(posMap[n.id()]);}
      cy.viewport({zoom:s.zoom||1,pan:s.pan||{x:0,y:0}});
      return;
    }
  }catch(err){console.debug('Unable to restore graph state:',err);}
  runLayout();
})();

cy.on('viewport',_debouncedSave);
cy.on('dragfree','node',_debouncedSave);

// ── Smart graph update (live refresh — preserves positions and viewport) ──────
function applyGraphUpdate(d){
  const z=cy.zoom(),p=cy.pan();
  const prevPos={};
  for(const n of cy.nodes()){prevPos[n.id()]={...n.position()};}
  cy.elements().remove();
  cy.add(buildElements(d));
  for(const n of cy.nodes()){
    if(prevPos[n.id()]){n.position(prevPos[n.id()]);}
    else{
      const nbrs=n.neighborhood('node').filter(nb=>!!prevPos[nb.id()]);
      if(nbrs.length){
        let x=0,y=0;
        for(const nb of nbrs){x+=nb.position().x;y+=nb.position().y;}
        n.position({x:x/nbrs.length+(Math.random()-.5)*80,y:y/nbrs.length+(Math.random()-.5)*80});  // NOSONAR - cosmetic layout jitter, not a security context
      }
    }
  }
  cy.viewport({zoom:z,pan:p});
  Object.assign(graphData,d);
  applyIndivVis();
  for(const t of hiddenEdgeTypes){cy.edges('[type="'+t+'"]').addClass('hidden');}
  refreshSuperclassesBtn();
  applySuperclassVis();
  _saveState();
}

function zoomBy(f){const c=cy.container();cy.zoom({level:cy.zoom()*f,renderedPosition:{x:c.clientWidth/2,y:c.clientHeight/2}});}

// ── Tooltip ───────────────────────────────────────────────────────────────────
const tipEl=document.getElementById('tip');
const KM={class:'Class',individual:'Individual',concept:'Concept',topconcept:'Top Concept',scheme:'Scheme'};
// Hovering lights the node up and turns the cursor into a pointer: every node is
// a click target, so the one under the cursor has to be unmistakable — including
// when it is dimmed, which is the only reason dimmed nodes can stay clickable.
cy.on('mouseover','node',e=>{
  const d=e.target.data();
  e.target.addClass('hovered');
  cy.container().style.cursor='pointer';
  tipEl.replaceChildren(
    el('b',{text:KM[d.type]||d.type}),document.createElement('br'),
    document.createTextNode(d.label),document.createElement('br'),
    el('span',{style:'color:#64748b;font-size:10px',text:d.id}),
  );
  tipEl.style.display='block';
});
cy.on('mousemove','node',e=>{tipEl.style.left=(e.originalEvent.clientX+14)+'px';tipEl.style.top=(e.originalEvent.clientY+10)+'px';});
cy.on('mouseout','node',e=>{
  e.target.removeClass('hovered');
  cy.container().style.cursor='';
  tipEl.style.display='none';
});

// ── Individuals toggle ────────────────────────────────────────────────────────
const classIndMap={};
const hiddenIndivClasses=new Set();
function initIndividualFilters(){
  for(const e of cy.edges('[type="instanceOf"]').toArray()){
    const c=e.data('target');
    classIndMap[c]=classIndMap[c]||[];
    classIndMap[c].push(e.data('source'));
  }
  if(!Object.keys(classIndMap).length){
    const b=document.getElementById('ft-individuals');
    if(b)b.style.display='none';
  }
}
initIndividualFilters();
function applyIndivVis(){
  for(const n of cy.nodes('[type="individual"]')){
    const e=cy.edges('[source="'+n.id()+'"][type="instanceOf"]').first();
    if(hiddenIndivClasses.has(e.data('target'))){n.addClass('hidden');}else{n.removeClass('hidden');}
  }
  for(const e of cy.edges('[type="instanceOf"]')){if(hiddenIndivClasses.has(e.data('target'))){e.addClass('hidden');}else{e.removeClass('hidden');}}
}
function toggleAllIndividuals(){
  const ks=Object.keys(classIndMap);
  if(!ks.length)return;
  const allHid=ks.every(c=>hiddenIndivClasses.has(c));
  if(allHid){for(const c of ks)hiddenIndivClasses.delete(c);}else{for(const c of ks)hiddenIndivClasses.add(c);}
  applyIndivVis();
  const nowHid=ks.every(c=>hiddenIndivClasses.has(c));
  const ftBtn=document.getElementById('ft-individuals');
  if(ftBtn){if(nowHid)ftBtn.classList.remove('active');else ftBtn.classList.add('active');}
  const btn=document.getElementById('btn-toggle-indivs');
  if(btn)btn.textContent=nowHid?'Show all individuals':'Hide all individuals';
}
// ── Class-order toggles ───────────────────────────────────────────────────────
const firstOrderIds=new Set(cy.nodes('[type="class"][rootClass=1]').map(n=>n.id()));
const secondOrderIds=new Set();
function initClassOrderFilters(){
  for(const e of cy.edges('[type="subClassOf"]')){
    if(firstOrderIds.has(e.data('target')))secondOrderIds.add(e.data('source'));
  }
  if(!firstOrderIds.size){
    const b=document.getElementById('ft-first-order');
    if(b)b.style.display='none';
  }
  if(!secondOrderIds.size){
    const b=document.getElementById('ft-second-order');
    if(b)b.style.display='none';
  }
}
initClassOrderFilters();

let firstOrderHidden=false;
let secondOrderHidden=false;

function _restoreClassEdges(id){
  for(const e of cy.edges('[source="'+id+'"]')){
    if(!cy.$('#'+CSS.escape(e.data('target'))).hasClass('hidden'))e.removeClass('hidden');
  }
  for(const e of cy.edges('[target="'+id+'"]')){
    if(!cy.$('#'+CSS.escape(e.data('source'))).hasClass('hidden'))e.removeClass('hidden');
  }
}
function _applyClassOrderVis(ids,hidden){
  for(const id of ids){
    const n=cy.$('#'+CSS.escape(id));
    if(hidden){
      n.addClass('hidden');
      cy.edges('[source="'+id+'"]').addClass('hidden');
      cy.edges('[target="'+id+'"]').addClass('hidden');
    }else{
      n.removeClass('hidden');
      _restoreClassEdges(id);
    }
  }
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
// ── Edge type toggle ──────────────────────────────────────────────────────────
const hiddenEdgeTypes=new Set();
function toggleEdgeType(t){
  const btn=document.getElementById('ft-'+t);
  if(hiddenEdgeTypes.has(t)){hiddenEdgeTypes.delete(t);btn?.classList.add('active');}
  else{hiddenEdgeTypes.add(t);btn?.classList.remove('active');}
  for(const e of cy.edges('[type="'+t+'"]')){if(hiddenEdgeTypes.has(t))e.addClass('hidden');else e.removeClass('hidden');}
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
  for(const n of cy.nodes()){
    if(matched.has(n)){n.removeClass('dimmed').addClass('searched');}
    else{n.addClass('dimmed').removeClass('searched');}
  }
  for(const e of cy.edges()){
    const s=cy.$('#'+CSS.escape(e.data('source')));
    const tg=cy.$('#'+CSS.escape(e.data('target')));
    if(!s.hasClass('dimmed')&&!tg.hasClass('dimmed')){e.removeClass('dimmed');}else{e.addClass('dimmed');}
  }
  countEl.textContent=matched.length+' match'+(matched.length===1?'':'es');
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
globalThis.addEventListener('load',()=>document.getElementById('search-box').focus());
// Enter on the search box acts on the first match exactly like clicking it.
document.getElementById('search-box').addEventListener('keydown',e=>{
  if(e.key!=='Enter')return;
  const t=e.target.value.trim().toLowerCase();
  if(!t)return;
  const matched=cy.nodes().filter(n=>n.data('label').toLowerCase().includes(t)||n.data('id').toLowerCase().includes(t));
  if(matched.length){e.preventDefault();activateNode(matched.first().data('id'));}
});

// ── Click / activate ──────────────────────────────────────────────────────────
// Activating a node (Enter on a search match) expands its relations by default:
// individuals → object-property relations, classes → linked classes. Node types
// without an expansion endpoint fall back to the detail panel.
// Select: pin the node in the panel and dim everything but its direct
// neighbourhood. Selecting the same node again clears it.
function selectNode(uri){
  clearSearch();
  const n=cy.$('#'+CSS.escape(uri));
  if(!n.length)return;
  if(highlighted===uri){highlighted=null;applyHighlight();showDefault();return;}
  highlighted=uri;applyHighlight();togglePanel(true);showDetail(n.data());
}
// Activate (search Enter): expand when the node type supports it, else select.
function activateNode(uri){
  clearSearch();
  const n=cy.$('#'+CSS.escape(uri));
  if(!n.length)return;
  if(API_TOKEN&&_EXPLORE_ENDPOINT[n.data('type')]){exploreOrExtend(uri);return;}
  selectNode(uri);
}
// Clicking a node selects it; it never swaps the graph out. Replacing the whole
// view is a deliberate action and stays on the hover overlay ("explore/extend
// relations"), so a stray click cannot lose your place. Tapping empty canvas
// clears the selection.
// ── Collapsed individuals ─────────────────────────────────────────────────────
// A file of a thousand shops opened with 1,993 nodes, of which 1,968 were
// individuals — 98.7% of the graph and 98.5% of the payload, on every refresh
// tick, laid out by a force algorithm whose cost grows far faster than linearly
// in that count. So the server sends classes only above a threshold, each
// carrying how many individuals it holds, and they arrive a class at a time.
//
// Expansions accumulate: opening a second class keeps the first open, so two can
// be compared. Clicking an open class puts it away again.
const _expanded=new Set();
function toggleClassIndividuals(node){
  const uri=node.id();
  if(_expanded.has(uri)){
    cy.remove(cy.nodes().filter(n=>n.data('ofClass')===uri));
    _expanded.delete(uri);node.data('shownCount',0);_saveState();return;
  }
  if(!API_TOKEN)return;
  _expanded.add(uri);
  fetch('/api/class-individuals?uri='+encodeURIComponent(uri),{headers:{'Authorization':'Bearer '+API_TOKEN}})
    .then(r=>r.ok?r.json():null)
    .then(d=>{
      if(!d){_expanded.delete(uri);return;}
      const fp=node.position();
      const fresh=d.nodes.filter(n=>!cy.$('#'+CSS.escape(n.id)).length);
      const added=cy.add([
        ...fresh.map(n=>({group:'nodes',data:{id:n.id,label:n.label,type:'individual',readOnly:n.readOnly||0,rootClass:0,superclass:0,individualCount:0,shownCount:0,ofClass:uri}})),
        ...d.edges.filter(e=>!cy.$('#'+CSS.escape(e.id)).length)
                  .map(e=>({group:'edges',data:{id:e.id+'@'+uri,source:e.source,target:e.target,type:e.type,label:'',cardinality:''}})),
      ]);
      node.data('shownCount',d.shown);
      _seedAndSpread(added.nodes(),fp);
    })
    .catch(err=>{console.debug('Unable to expand class:',err);_expanded.delete(uri);});
}
// Clicking a class that holds collapsed individuals opens it as well as selecting
// it. This adds nodes rather than replacing the view, so it does not lose your
// place the way explore/extend deliberately can.
cy.on('tap','node',e=>{
  const n=e.target;
  if(n.data('individualCount'))toggleClassIndividuals(n);
  selectNode(n.id());
});
cy.on('tap',function(e){if(e.target===cy){highlighted=null;applyHighlight();showDefault();}});

// ── Panel ─────────────────────────────────────────────────────────────────────
function togglePanel(show){
  const was=panelVisible;
  panelVisible=show===undefined?!panelVisible:show;
  if(panelVisible===was)return;
  panelEl.style.display=panelVisible?'':'none';
  // Keep the button visible always and flip it into a reopen toggle when the
  // panel is closed — otherwise closing the panel hides its only control and
  // strands it shut (no visible way back).
  const _pc=document.getElementById('panel-close');
  _pc.textContent=panelVisible?'×':'‹';
  _pc.title=panelVisible?'Close panel (Esc)':'Show details (Esc)';
  W=globalThis.innerWidth-(panelVisible?panelEl.getBoundingClientRect().width:0);
  document.getElementById('stats').style.left=(W/2)+'px';
  cy.resize();
}
document.getElementById('panel-close').addEventListener('click',()=>togglePanel());
const _offBannerClose=document.getElementById('offline-banner-close');
if(_offBannerClose)_offBannerClose.addEventListener('click',()=>{const b=document.getElementById('offline-banner');if(b)b.remove();});
document.getElementById('zoom-in').addEventListener('click',()=>zoomBy(1.3));
document.getElementById('zoom-fit').addEventListener('click',()=>{try{localStorage.removeItem(_stateKey);}catch(err){console.debug('Unable to clear graph state:',err);}runLayout();});
document.getElementById('zoom-out').addEventListener('click',()=>zoomBy(0.77));
document.getElementById('ft-individuals').addEventListener('click',toggleAllIndividuals);
document.getElementById('ft-first-order').addEventListener('click',toggleFirstOrderClasses);
document.getElementById('ft-second-order').addEventListener('click',toggleSecondOrderClasses);
// A named function rather than an inline loop, because the containing IIFE is
// the whole file: an early exit at its top level abandons every wiring step
// below — the panel wrappers, the hover overlay and live refresh — for any
// ontology missing one of these edge types. A pure-SKOS thesaurus has no
// instanceOf edges, which used to disable all of it. Inside a function the worst
// an early exit can do is skip the rest of this one step.
function wireEdgeTypeFilters(){
  for(const [t,id] of [['instanceOf','ft-instanceOf'],['inScheme','ft-inScheme'],['datatypeProperty','ft-datatypeProperty']]){
    const btn=document.getElementById(id);
    if(!btn)continue;
    if(cy.edges('[type="'+t+'"]').length===0){btn.style.display='none';continue;}
    btn.addEventListener('click',()=>toggleEdgeType(t));
  }
}
wireEdgeTypeFilters();
const _scBtn=document.getElementById('ft-superclasses');
if(_scBtn)_scBtn.addEventListener('click',toggleSuperclasses);
refreshSuperclassesBtn();
// Every panel button is now wired with addEventListener at creation (see
// renderDetail/individualToggleNodes/detailRelationsNodes) rather than an
// inline onclick attribute, so navigateTo no longer needs a global wrapper
// for markup to call into — kept anyway as a small, harmless debug/test hook.
globalThis._sterNav=navigateTo;
// The Taxonomie tab's own asset (taxonomy_app.js) shares this panel but owns no
// part of its open/close state — it calls this to make sure a click always
// reveals the panel, exactly like every click handler in this file already does.
globalThis._sterShowPanel=function(){togglePanel(true);};

// ── Explore: swap in a focused subgraph for a node ────────────────────────────
// Server-only. Individuals → object-property relations; classes → linked
// classes (superclasses + object-property domain/range). The previous graph is
// saved so Escape restores the original view.
let _savedGraph=null;
// The node type the current exploration started from. When it is 'individual',
// object properties are shown between individuals, so extending a class brings in
// only its subClassOf trail (subclass_only) — no redundant T-Box object-property
// links. A class-rooted session shows those links.
let _rootType=null;
// Concepts and top concepts share one endpoint: the broader chain for context
// plus the direct narrower, so each explore/extend walks exactly one level down
// rather than dumping a whole subtree.
const _EXPLORE_ENDPOINT={individual:'/api/individual-relations',class:'/api/class-links',
  concept:'/api/concept-relations',topconcept:'/api/concept-relations'};
function exploreNode(uri){
  if(!API_TOKEN)return;
  const node=cy.$('#'+CSS.escape(uri));
  if(!node.length)return;
  const endpoint=_EXPLORE_ENDPOINT[node.data('type')];
  if(!endpoint)return;
  _rootType=node.data('type');
  fetch(endpoint+'?uri='+encodeURIComponent(uri),{headers:{'Authorization':'Bearer '+API_TOKEN}})
    .then(r=>r.ok?r.json():null)
    .then(d=>{
      if(!d?.nodes?.length)return;
      if(!_savedGraph){_savedGraph={els:cy.elements().jsons(),zoom:cy.zoom(),pan:cy.pan()};}
      cy.elements().remove();
      cy.add(buildElements(d));
      cy.layout(makeLayout()).run();
      refreshSuperclassesBtn();
      applySuperclassVis();
      const n=cy.$('#'+CSS.escape(uri));
      // The expanded subgraph IS the focus: show every node. Dimming to the
      // focus node's immediate neighbourhood used to blur the superclass trail
      // and the related individuals' classes/superclasses. Clear the highlight
      // so nothing is dimmed; the detail panel still pins the focus.
      if(n.length){highlighted=null;applyHighlight();togglePanel(true);showDetail(n.data());}
    }).catch(err=>{console.debug('Unable to explore node:',err);});
}
function restoreGraph(){
  if(!_savedGraph)return;
  cy.elements().remove();
  cy.add(_savedGraph.els);
  cy.viewport({zoom:_savedGraph.zoom,pan:_savedGraph.pan});
  _savedGraph=null;_rootType=null;
  refreshSuperclassesBtn();
  applySuperclassVis();
  highlighted=null;applyHighlight();showDefault();
}
// On the full graph, activating a node replaces it with that node's
// neighbourhood (exploreNode). Once a subgraph is open, activating instead
// EXTENDS — the neighbourhood is merged onto the current view, keeping the rest.
function exploreOrExtend(uri){if(_savedGraph)extendNode(uri);else exploreNode(uri);}
// Fetch a node's relations payload (individual or class), or null on failure.
function _fetchRel(type,uri){
  const ep=_EXPLORE_ENDPOINT[type];
  if(!ep)return Promise.resolve(null);
  let url=ep+'?uri='+encodeURIComponent(uri);
  // Individual-rooted session: a class only contributes its subClassOf trail.
  if(type==='class'&&_rootType==='individual')url+='&subclass_only=1';
  return fetch(url,{headers:{'Authorization':'Bearer '+API_TOKEN}})
    .then(r=>r.ok?r.json():null).catch(err=>{console.debug('Unable to fetch relations:',err);return null;});
}
// Seed the new nodes near their anchors, then spread them without piling up: pin
// the existing graph and run a force pass over the newcomers only, then unpin.
// fit:false keeps the current viewport; locked nodes stay exactly put.
function _seedAndSpread(addedNodes,fp){
  if(addedNodes.empty()){_saveState();return;}
  for(const n of addedNodes){
    const anchors=n.neighborhood('node').filter(nb=>!addedNodes.contains(nb));
    let x=fp.x,y=fp.y;
    if(anchors.length){
      x=0;y=0;
      for(const a of anchors){const p=a.position();x+=p.x;y+=p.y;}
      x/=anchors.length;y/=anchors.length;
    }
    n.position({x:x+(Math.random()-.5)*40,y:y+(Math.random()-.5)*40});  // NOSONAR - cosmetic layout jitter, not a security context
  }
  const existing=cy.nodes().difference(addedNodes);
  existing.lock();
  const l=cy.layout({name:'cose',animate:false,fit:false,randomize:false,
    nodeRepulsion:5000,nodeOverlap:20,idealEdgeLength:110,edgeElasticity:100,
    gravity:50,numIter:600,coolingFactor:.95,minTemp:1});
  l.one('layoutstop',()=>{existing.unlock();_saveState();});
  l.run();
}

// ── Extend: merge a node's neighbourhood onto the current subgraph ─────────────
let _mergeCtr=0;
const sigOf=(s,t,ty,l)=>s+'\u0001'+t+'\u0001'+ty+'\u0001'+(l||'');
function _addMergedEdges(edges,onlyVisible,haveEdges){
  const fresh=[];
  for(const e of edges){
    const sig=sigOf(e.source,e.target,e.type,e.label);
    if(haveEdges.has(sig))continue;
    if(onlyVisible&&(cy.getElementById(e.source).empty()||cy.getElementById(e.target).empty()))continue;
    haveEdges.add(sig);
    fresh.push({...e,id:'x'+(_mergeCtr++)});
  }
  if(fresh.length)cy.add(buildElements({nodes:[],edges:fresh}));
}

function extendNode(uri){
  if(!API_TOKEN)return;
  const node=cy.$('#'+CSS.escape(uri));
  if(!node.length)return;
  const endpoint=_EXPLORE_ENDPOINT[node.data('type')];
  if(!endpoint)return;
  // Edges carry per-request ids (e0,e1,...) that collide across fetches, so add
  // them de-duplicated by (source,target,type,label) and re-id'd. onlyVisible
  // keeps only edges whose endpoints are already drawn -- used to bring in the
  // newcomers' own property relations without dragging in further nodes.
  const haveEdges=new Set(cy.edges().map(e=>sigOf(e.data('source'),e.data('target'),e.data('type'),e.data('label'))));
  _fetchRel(node.data('type'),uri).then(d=>{
    if(!d?.nodes?.length)return;
    // Nodes are keyed by URI id -- add only those not already present.
    const existingIds=new Set(cy.nodes().map(n=>n.id()));
    const newNodes=d.nodes.filter(n=>!existingIds.has(n.id));
    const focus=cy.$('#'+CSS.escape(uri));
    const fp=focus.length?focus.position():{x:0,y:0};
    const added=cy.add(buildElements({nodes:newNodes,edges:[]}));
    const addedNodes=added.nodes();
    _addMergedEdges(d.edges,false,haveEdges);
    // Bring in each newcomer's own property edges that link nodes already on
    // screen, so adding a node also adds its relations (no extra nodes pulled in).
    const explorable=addedNodes.filter(nn=>_EXPLORE_ENDPOINT[nn.data('type')]);
    Promise.all(explorable.map(nn=>_fetchRel(nn.data('type'),nn.id()))).then(rs=>{
      for(const rd of rs){if(rd?.edges)_addMergedEdges(rd.edges,true,haveEdges);}
      _seedAndSpread(addedNodes,fp);
      applyIndivVis();
      for(const t of hiddenEdgeTypes){cy.edges('[type="'+t+'"]').addClass('hidden');}
      refreshSuperclassesBtn();
      applySuperclassVis();
      const n=cy.$('#'+CSS.escape(uri));
      if(n.length){highlighted=null;applyHighlight();togglePanel(true);showDetail(n.data());}
    });
  }).catch(err=>{console.debug('Unable to extend node:',err);});
}

// ── Hide a node together with its parent trail ────────────────────────────────
// Individual → drop it, its rdf:type class(es) and their subClassOf superclasses.
// Class → drop it and its subClassOf superclasses. A parent that another still
// -visible node depends on (instanceOf or subClassOf) is kept, transitively.
function collectParentTrail(seeds){
  const parents=new Set();
  const stack=[...seeds];
  while(stack.length){
    const current=stack.pop();
    if(parents.has(current))continue;
    parents.add(current);
    for(const e of cy.edges('[source="'+current+'"][type="subClassOf"]'))stack.push(e.data('target'));
  }
  return parents;
}
function hasVisibleDependency(id,removing){
  for(const e of cy.edges('[target="'+id+'"]')){
    const type=e.data('type');
    if((type==='instanceOf'||type==='subClassOf')&&!removing.has(e.data('source')))return true;
  }
  return false;
}
function releaseSharedParents(parents,removing){
  let changed=true;
  while(changed){
    changed=false;
    for(const id of parents){
      if(!removing.has(id))continue;
      if(hasVisibleDependency(id,removing)){removing.delete(id);changed=true;}
    }
  }
}
function hideNodeAndParents(uri){
  const node=cy.$('#'+CSS.escape(uri));
  if(!node.length)return;
  const type=node.data('type');
  const seeds=[];
  if(type==='individual'){
    for(const e of cy.edges('[source="'+uri+'"][type="instanceOf"]'))seeds.push(e.data('target'));
  }else if(type==='class'){
    for(const e of cy.edges('[source="'+uri+'"][type="subClassOf"]'))seeds.push(e.data('target'));
  }
  const parents=collectParentTrail(seeds);
  // The focus node is always removed; parents start in the removal set then get
  // released when some node outside the set still depends on them (fixpoint).
  const removing=new Set([uri,...parents]);
  releaseSharedParents(parents,removing);
  for(const id of removing)cy.$('#'+CSS.escape(id)).remove();
  refreshSuperclassesBtn();
  applySuperclassVis();
  highlighted=null;applyHighlight();showDefault();
  _saveState();
}

// ── Hover overlay: explore/extend + hide buttons ──────────────────────────────
const exploreBtn=document.getElementById('explore-btn');
const hideBtn=document.getElementById('hide-btn');
let _exploreHoverUri=null,_exploreHideTimer=null;
function _positionExploreBtn(node){
  const bb=node.renderedBoundingBox();
  const cx=(bb.x1+bb.x2)/2;
  // Buttons touch the node (no gap) so the cursor can slide straight onto them
  // without crossing empty canvas: explore/extend hugs the top edge (its bottom
  // sits on the node top), hide hugs the bottom edge (its top sits on the node
  // bottom). The differing transforms are set in CSS (#explore-btn vs #hide-btn).
  exploreBtn.style.left=cx+'px';exploreBtn.style.top=bb.y1+'px';
  if(hideBtn){hideBtn.style.left=cx+'px';hideBtn.style.top=bb.y2+'px';}
}
function _hideOverlay(){exploreBtn.style.display='none';if(hideBtn)hideBtn.style.display='none';}
// The node and its two labels form one hover region: entering any of them keeps
// the overlay up (cancels a pending hide); leaving any of them only *schedules*
// a hide, so sliding label → node → label never flickers the buttons off. The
// overlay disappears only once the cursor has left the node and both labels.
function _cancelHide(){if(_exploreHideTimer){clearTimeout(_exploreHideTimer);_exploreHideTimer=null;}}
function _scheduleHide(){_cancelHide();_exploreHideTimer=setTimeout(_hideOverlay,600);}
if(exploreBtn&&API_TOKEN){
  cy.on('mouseover','node',e=>{
    const t=e.target.data('type');
    if(t!=='individual'&&t!=='class'){_hideOverlay();return;}
    _cancelHide();
    _exploreHoverUri=e.target.data('id');
    // On the full graph the action is "explore" (replace); inside a subgraph it
    // becomes "extend" (merge onto the current view).
    exploreBtn.textContent='⊙ explore relations';
    if(_savedGraph)exploreBtn.textContent='⊕ extend relations';
    _positionExploreBtn(e.target);
    exploreBtn.style.display='block';
    if(hideBtn)hideBtn.style.display='block';
  });
  cy.on('mouseout','node',_scheduleHide);
  cy.on('viewport',_hideOverlay);
  for(const b of [exploreBtn,hideBtn]){
    if(!b)return;
    b.addEventListener('mouseenter',_cancelHide);
    b.addEventListener('mouseleave',_scheduleHide);
  }
  exploreBtn.addEventListener('click',()=>{_hideOverlay();if(_exploreHoverUri)exploreOrExtend(_exploreHoverUri);});
  if(hideBtn)hideBtn.addEventListener('click',()=>{_hideOverlay();if(_exploreHoverUri)hideNodeAndParents(_exploreHoverUri);});
}

// ── Superclasses toggle (subClassOf trail; shown by default) ──────────────────
let superclassesHidden=false;
function applySuperclassVis(){
  for(const n of cy.nodes('[superclass=1]')){superclassesHidden?n.addClass('hidden'):n.removeClass('hidden');}
  for(const e of cy.edges('[type="subClassOf"]')){
    const s=cy.$('#'+CSS.escape(e.data('source'))),t=cy.$('#'+CSS.escape(e.data('target')));
    const touchesSuper=(s.length&&s.data('superclass')===1)||(t.length&&t.data('superclass')===1);
    if(superclassesHidden&&touchesSuper)e.addClass('hidden');else e.removeClass('hidden');
  }
}
function refreshSuperclassesBtn(){
  const btn=document.getElementById('ft-superclasses');
  if(!btn)return;
  btn.style.display=cy.nodes('[superclass=1]').size()?'':'none';
}
function toggleSuperclasses(){
  superclassesHidden=!superclassesHidden;
  const btn=document.getElementById('ft-superclasses');
  applySuperclassVis();
  if(btn){superclassesHidden?btn.classList.remove('active'):btn.classList.add('active');}
}

// ── Keyboard ──────────────────────────────────────────────────────────────────
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){if(!panelVisible){togglePanel(true);return;}const sb=document.getElementById('search-box');if(sb?.value){clearSearch();return;}if(_savedGraph){restoreGraph();return;}if(highlighted){highlighted=null;applyHighlight();showDefault();}else togglePanel();}
  if(e.key==='f'){try{localStorage.removeItem(_stateKey);}catch(err){console.debug('Unable to clear graph state:',err);}runLayout();}
  if(e.key==='+'){zoomBy(1.3);}
  if(e.key==='-'){zoomBy(.77);}
});

// ── Stats ─────────────────────────────────────────────────────────────────────
// n===1 ? singular-suffix : plural-suffix, e.g. _plural(3,'','es') -> 'es'.
function _plural(n,singular,plural){return n===1?singular:plural;}
(function(){
  const c=taxoMeta.counts,p=[];
  if(c.classes)p.push(c.classes+' class'+_plural(c.classes,'','es'));
  if(c.individuals)p.push(c.individuals+' individual'+_plural(c.individuals,'','s'));
  if(c.properties)p.push(c.properties+' propert'+_plural(c.properties,'y','ies'));
  if(c.schemes)p.push(c.schemes+' scheme'+_plural(c.schemes,'','s'));
  if(c.top_concepts)p.push(c.top_concepts+' top concept'+_plural(c.top_concepts,'','s'));
  if(c.concepts)p.push(c.concepts+' concept'+_plural(c.concepts,'','s'));
  document.getElementById('stats').textContent=p.join(' · ');
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
function overviewRows(counts){
  const rows=[];
  for(const [label,count] of counts){
    if(count)rows.push(el('div',{class:'dp-row'},[el('span',{text:label}),el('span',{text:String(count)})]));
  }
  return rows;
}
function individualToggleNodes(){
  const classes=Object.keys(classIndMap);
  if(!classes.length)return [];
  const allHid=classes.every(c=>hiddenIndivClasses.has(c));
  const btn=el('button',{id:'btn-toggle-indivs',class:'dp-indiv-btn',text:allHid?'Show all individuals':'Hide all individuals'});
  btn.addEventListener('click',toggleAllIndividuals);
  const hint=el('div',{class:'dp-hint',text:'Click a class to view details and highlight connections.'});
  return [btn,hint];
}
// nodeSvg/edgeLine (above) return SVG markup picked from a small hardcoded
// lookup table keyed by a handful of literal type strings ster itself
// controls — never anything from the loaded ontology — so parsing that fixed
// markup here carries no more risk than a literal template in the source.
function iconEl(svgMarkup){
  const wrap=document.createElement('span');
  wrap.innerHTML=svgMarkup;
  return wrap.firstChild;
}
function legendNodes(hasRoot,hasSub,ntypes,etypes){
  const nodes=[el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'Legend'})];
  const nodeLegend=[['class-root','Root Class',hasRoot],['class-sub','Class',hasSub],['individual','Individual',ntypes.has('individual')],['topconcept','Top Concept',ntypes.has('topconcept')],['concept','Concept',ntypes.has('concept')],['scheme','Scheme',ntypes.has('scheme')]];
  const hasReadOnly=cy.nodes('[readOnly=1]').length>0;
  for(const [type,label,show] of nodeLegend){
    if(!show)continue;
    nodes.push(el('div',{class:'lr'},[iconEl(nodeSvg(type)),document.createTextNode(label)]));
    if(type==='individual')nodes.push(...individualToggleNodes());
  }
  if(hasReadOnly)nodes.push(el('div',{class:'lr',style:'opacity:.55'},[iconEl(nodeSvg('concept')),document.createTextNode('read-only (context file)')]));
  nodes.push(el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'Relations'}));
  const edgeLegend=[['subClassOf','subClassOf'],['objectProperty','objectProperty'],['datatypeProperty','datatypeProperty'],['instanceOf','rdf:type'],['broader','broader'],['inScheme','inScheme']];
  for(const [type,label] of edgeLegend){
    if(etypes.has(type))nodes.push(el('div',{class:'lr'},[iconEl(edgeLine(type)),document.createTextNode(label)]));
  }
  return nodes;
}
function showDefault(){
  highlighted=null;
  const counts=[['Classes',cy.nodes('[type="class"]').length],['Individuals',cy.nodes('[type="individual"]').length],['Properties',cy.edges('[type="objectProperty"],[type="datatypeProperty"]').length],['Schemes',cy.nodes('[type="scheme"]').length],['Top Concepts',cy.nodes('[type="topconcept"]').length],['Concepts',cy.nodes('[type="concept"]').length]];
  const rows=overviewRows(counts);
  const hasRoot=cy.nodes('[type="class"][rootClass=1]').length>0,hasSub=cy.nodes('[type="class"][rootClass=0]').length>0;
  const ntypes=new Set(cy.nodes().map(n=>n.data('type')));
  const etypes=new Set(cy.edges().map(e=>e.data('type')));
  const leg=legendNodes(hasRoot,hasSub,ntypes,etypes);
  const panel=el('div',{class:'dp'});
  panel.append(el('div',{class:'dp-h2',text:taxoMeta.title}));
  if(taxoMeta.ontology_uri)panel.append(el('div',{class:'dp-uri',text:taxoMeta.ontology_uri}));
  panel.append(el('div',{class:'dp-sub',style:'margin-top:6px',text:'Overview'}));
  panel.append(el('div',{class:'dp-section'},rows));
  panel.append(...leg);
  panelEl.replaceChildren(panel);
}
showDefault();
function detailLabelsNodes(labels){
  if(!labels.length)return [];
  const nodes=[el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'Labels'})];
  for(const l of labels){
    const row=el('div',{class:'dp-lbl'});
    if(l.lang)row.append(el('span',{class:'dp-lang',text:'['+l.lang+']'}));
    row.append(el('span',{class:l.kind==='alt'?'dp-alt':'dp-pref',text:l.value}));
    nodes.push(row);
  }
  return nodes;
}
function detailCommentsNodes(comments){
  if(!comments.length)return [];
  const nodes=[el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'Comments'})];
  // linkify, not plain text: OWL keeps its prose in rdfs:comment where SKOS
  // uses skos:definition, and a URL should not be clickable on a concept but
  // dead on a class.
  for(const c of comments)nodes.push(el('div',{class:'dp-desc'},linkifyNodes(c.value)));
  return nodes;
}
// Everything below renders values loaded from the user's ontology file, so it
// is untrusted input: build it as DOM nodes (never a markup string) and never
// emit a URL without vetting it.

// A URL is safe to put in href/src only if it parses and speaks http(s). A
// `javascript:` or `data:` value in a schema:url would otherwise become a script
// the reader runs by clicking. Returns '' when the value cannot be trusted.
function safeUrl(raw){
  try{
    const parsed=new URL(String(raw),globalThis.location.href);
    if(parsed.protocol==='http:'||parsed.protocol==='https:')return parsed.href;
  }catch{/* not a URL — fall through */}
  return '';
}
function extLinkNode(url,text){
  const safe=safeUrl(url);
  if(!safe)return document.createTextNode(text);
  // noopener noreferrer: an ontology can link anywhere, and window.opener would
  // let the target reach back into this page.
  return el('a',{class:'dp-a',href:safe,target:'_blank',rel:'noopener noreferrer',text:text});
}
// Free text (a definition, say) often mentions a URL. Split on URL-looking
// runs and turn each into its own real anchor/text node — nothing here is
// ever concatenated into a markup string, so there is no meta-character to
// smuggle regardless of what the URL or the surrounding text contains.
function linkifyNodes(text){
  const parts=String(text).split(/(https?:\/\/[^\s<>"']+)/g);
  const frag=document.createDocumentFragment();
  for(const [i,p] of parts.entries()){
    if(i%2)frag.append(extLinkNode(p,p));
    else if(p)frag.append(document.createTextNode(p));
  }
  return frag;
}
function detailScopeNodes(scope){
  if(!scope)return [];
  return [el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'Scope note'}),el('div',{class:'dp-desc'},linkifyNodes(scope))];
}
function detailMediaNodes(images,videos){
  const imgs=images||[],vids=videos||[];
  if(!imgs.length&&!vids.length)return [];
  const nodes=[el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'Media'})];
  for(const src of imgs){
    const safe=safeUrl(src);
    if(!safe)continue;
    // referrerpolicy="no-referrer": many image hosts (Wikimedia among them) refuse a
    // request whose Referer is another origin, so without this the picture the
    // ontology points at simply never paints.
    const img=el('img',{class:'dp-img',src:safe,alt:'',decoding:'async',referrerpolicy:'no-referrer'});
    const cap=el('figcaption',{class:'dp-cap'},extLinkNode(safe,'open in a new tab'));
    nodes.push(el('figure',{class:'dp-fig'},[img,cap]));
  }
  for(const src of vids){
    const safe=safeUrl(src);
    if(!safe)continue;
    const vid=el('video',{class:'dp-video',src:safe,controls:'',preload:'metadata',referrerpolicy:'no-referrer'});
    const cap=el('figcaption',{class:'dp-cap'},extLinkNode(safe,'open in a new tab'));
    nodes.push(el('figure',{class:'dp-fig'},[vid,cap]));
  }
  return nodes;
}
// Error handlers are attached here rather than as inline onerror attributes: the
// panel is rebuilt on every selection, and an attribute handler is the first
// thing a future Content-Security-Policy would silently drop.
function wireMedia(){
  for(const img of panelEl.querySelectorAll('.dp-img')){
    // A load that already failed fires no further event — catch it on the spot.
    if(img.complete&&img.naturalWidth===0)mediaFailed(img);
    else img.addEventListener('error',()=>mediaFailed(img),{once:true});
  }
  for(const vid of panelEl.querySelectorAll('.dp-video')){
    vid.addEventListener('error',()=>mediaFailed(vid,'video unavailable'),{once:true});
  }
}
// Ontology media is usually an off-site URL, and a dead one leaves a zero-height
// box that reads as "there is no media here" — say so instead.
function mediaFailed(mediaEl,text){
  const fig=mediaEl.parentNode;
  if(!fig||fig.querySelector('.dp-broken'))return;
  mediaEl.remove();
  const note=document.createElement('div');
  note.className='dp-broken';
  note.textContent=text||'image unavailable';
  fig.prepend(note);
}
function detailUrlsNodes(urls){
  if(!urls?.length)return [];
  const nodes=[el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'Links'})];
  for(const u of urls)nodes.push(el('div',{class:'dp-lbl'},extLinkNode(u,u)));
  return nodes;
}
function detailRelationsNodes(relations){
  if(!relations.length)return [];
  const nodes=[el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'Relations'})];
  for(const r of relations){
    const lbl=r.label||r.uri,inG=cy.$('#'+CSS.escape(r.uri)).length>0;
    const row=el('div',{class:'dp-rel'},el('span',{class:'dp-rel-tag',text:r.rel}));
    if(inG){
      const btn=el('button',{class:'dp-link',text:lbl});
      btn.addEventListener('click',()=>navigateTo(r.uri));
      row.append(btn);
    }else{
      row.append(el('span',{text:lbl}));
    }
    nodes.push(row);
  }
  return nodes;
}
// ── Lazy node detail ────────────────────────────────────────────────────────
// The graph payload carries no per-node detail (91% of its size, and only ever
// read one node at a time). It is fetched on first click: from the API when a
// live server backs the page, otherwise once from the _detail.json companion.
const _detailCache=new Map();
let _detailBulk=null;
function _bulkDetail(){
  if(_detailBulk)return _detailBulk;
  const url=globalThis.location.pathname.replace(/_vowl\.html$/,'_detail.json');
  _detailBulk=fetch(url,{cache:'no-store'}).then(r=>r.ok?r.json():{}).catch(()=>({}));
  return _detailBulk;
}
async function loadDetail(uri){
  if(_detailCache.has(uri))return _detailCache.get(uri);
  let det={};
  try{
    if(API_TOKEN){
      const r=await fetch('/api/node-detail?uri='+encodeURIComponent(uri),{headers:{'Authorization':'Bearer '+API_TOKEN}});
      if(r.ok)det=await r.json();
    }else{
      det=(await _bulkDetail())[uri]||{};
    }
  }catch(err){
    // Never block the panel on a failed fetch — the node's own label, type and
    // URI are already in hand and are what the header shows.
    console.debug('Detail fetch failed:',err);
  }
  _detailCache.set(uri,det);
  return det;
}
function showDetail(d){
  if(!_detailCache.has(d.id)){
    renderDetail(d,{});
    loadDetail(d.id).then(det=>{if(highlighted===d.id)renderDetail(d,det);});
    return;
  }
  renderDetail(d,_detailCache.get(d.id));
}
function renderDetail(d,det){
  const panel=el('div',{class:'dp'});
  const back=el('button',{class:'dp-back',text:'← Overview'});
  back.addEventListener('click',()=>{highlighted=null;applyHighlight();showDefault();});
  panel.append(back);
  panel.append(el('span',{class:'dp-badge dp-'+d.type,text:KM[d.type]||d.type}));
  panel.append(el('div',{class:'dp-h3',text:d.label}));
  panel.append(el('div',{class:'dp-uri',text:d.id}));
  const lbls=det.labels||[],showLbls=[...lbls.filter(l=>l.kind==='pref').slice(1),...lbls.filter(l=>l.kind==='alt'),...lbls.filter(l=>l.kind==='label')];
  panel.append(...detailLabelsNodes(showLbls));
  panel.append(...detailCommentsNodes(det.comments||[]));
  if(det.description){
    panel.append(el('hr',{class:'dp-hr'}));
    panel.append(el('div',{class:'dp-desc'},linkifyNodes(det.description)));
  }
  panel.append(...detailScopeNodes(det.scopeNote));
  panel.append(...detailRelationsNodes(det.relations||[]));
  panel.append(...detailMediaNodes(det.images,det.videos));
  panel.append(...detailUrlsNodes(det.urls));
  panelEl.replaceChildren(panel);
  wireMedia();
}
function navigateTo(uri){
  const n=cy.$('#'+CSS.escape(uri));if(!n.length)return;
  highlighted=uri;applyHighlight();togglePanel(true);showDetail(n.data());
  cy.animate({center:{eles:n},zoom:Math.max(cy.zoom(),1)},{duration:400});
}

// ── Live refresh ──────────────────────────────────────────────────────────────
function initLiveRefresh(){
  if(API_TOKEN){
    const src=new EventSource('/api/events?token='+encodeURIComponent(API_TOKEN));
    src.onmessage=async function(){
      try{
        const resp=await fetch('/api/graph',{headers:{'Authorization':'Bearer '+API_TOKEN}});
        const data=await resp.json();
        applyGraphUpdate(data);
      }catch(err){console.error('Graph refresh failed:',err);}
    };
    return;
  }
  const dataUrl=globalThis.location.origin+globalThis.location.pathname.replace(/_vowl\.html$/,'_data.json');
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
    }catch(err){console.debug('Graph refresh polling failed:',err);}
  },2500);
}
initLiveRefresh();
}catch(err){
  const el=document.createElement('div');
  el.style.cssText='position:fixed;inset:0;background:rgba(220,38,38,.95);color:white;padding:24px;font-family:monospace;font-size:13px;z-index:200;white-space:pre-wrap;overflow:auto';
  el.textContent='Graph error — see browser console (F12):\n\n'+(err.stack||err);
  document.body.appendChild(el);
}
}
globalThis.initSterRelationsGraph=initSterRelationsGraph;
