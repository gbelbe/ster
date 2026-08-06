// ster graph application layer — interaction, styling, filtering, live
// update, and detail-panel logic built on top of the vendored Cytoscape.js.
// This file is intentionally separate from the library: upgrading Cytoscape
// (see _CY_VERSION in viz_vowl.py) must never overwrite this code. It uses
// only the public global `cytoscape(...)` factory and documented cy.* API,
// and reads its per-render data from the injected `window.__STER_GRAPH__`.

(function(){
try{
const graphData=window.__STER_GRAPH__.data;
const taxoMeta=window.__STER_GRAPH__.meta;
const API_TOKEN=window.__STER_GRAPH__.token;
const panelEl=document.getElementById('detail-panel');
let panelVisible=true;
let W=window.innerWidth-(panelVisible?panelEl.getBoundingClientRect().width:0);
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function buildElements(data){
  return[
    ...data.nodes.map(n=>({group:'nodes',data:{id:n.id,label:n.label,type:n.type,detail:n.detail||{},rootClass:n.rootClass||0,superclass:n.superclass||0}})),
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
// Keyed per-path AND guarded by a signature of the current node set, so a
// different ontology (or an expanded subgraph) served at the same URL never
// restores stale positions. The version prefix invalidates any state saved by
// older builds that persisted the pre-layout pile-up.
const _stateKey='ster_state_v2_'+location.pathname;
function _graphSig(){
  const ids=cy.nodes().map(n=>n.id()).sort().join('|');
  let h=0;for(let i=0;i<ids.length;i++){h=(h*31+ids.charCodeAt(i))|0;}
  return cy.nodes().size()+':'+h;
}
function _saveState(){
  try{
    const pos=[];
    cy.nodes().forEach(n=>{const p=n.position();pos.push({id:n.id(),x:p.x,y:p.y});});
    localStorage.setItem(_stateKey,JSON.stringify({sig:_graphSig(),pos,zoom:cy.zoom(),pan:cy.pan()}));
  }catch(_){}
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
      s.pos.forEach(p=>{posMap[p.id]={x:p.x,y:p.y};});
      cy.nodes().forEach(n=>{if(posMap[n.id()])n.position(posMap[n.id()]);});
      cy.viewport({zoom:s.zoom||1,pan:s.pan||{x:0,y:0}});
      return;
    }
  }catch(_){}
  runLayout();
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
  refreshSuperclassesBtn();
  applySuperclassVis();
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
// ── Class-order toggles ───────────────────────────────────────────────────────
const firstOrderIds=new Set(cy.nodes('[type="class"][rootClass=1]').map(n=>n.id()));
const secondOrderIds=new Set();
function initClassOrderFilters(){
  cy.edges('[type="subClassOf"]').forEach(e=>{
    if(firstOrderIds.has(e.data('target')))secondOrderIds.add(e.data('source'));
  });
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
// ── Edge type toggle ──────────────────────────────────────────────────────────
const hiddenEdgeTypes=new Set();
function toggleEdgeType(t){
  const btn=document.getElementById('ft-'+t);
  if(hiddenEdgeTypes.has(t)){hiddenEdgeTypes.delete(t);btn?.classList.add('active');}
  else{hiddenEdgeTypes.add(t);btn?.classList.remove('active');}
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
function activateNode(uri){
  clearSearch();
  const n=cy.$('#'+CSS.escape(uri));
  if(!n.length)return;
  if(API_TOKEN&&_EXPLORE_ENDPOINT[n.data('type')]){exploreOrExtend(uri);return;}
  if(highlighted===uri){highlighted=null;applyHighlight();showDefault();return;}
  highlighted=uri;applyHighlight();togglePanel(true);showDetail(n.data());
}
// Clicking a node itself does nothing: expansion is driven only by the hover
// overlay ("explore/extend relations", "hide node + parents"). Tapping empty
// canvas still clears the current selection.
cy.on('tap',function(e){if(e.target===cy){highlighted=null;applyHighlight();showDefault();}});

// ── Panel ─────────────────────────────────────────────────────────────────────
function togglePanel(show){
  const was=panelVisible;
  panelVisible=show!==undefined?show:!panelVisible;
  if(panelVisible===was)return;
  panelEl.style.display=panelVisible?'':'none';
  // Keep the button visible always and flip it into a reopen toggle when the
  // panel is closed — otherwise closing the panel hides its only control and
  // strands it shut (no visible way back).
  const _pc=document.getElementById('panel-close');
  _pc.textContent=panelVisible?'×':'‹';
  _pc.title=panelVisible?'Close panel (Esc)':'Show details (Esc)';
  W=window.innerWidth-(panelVisible?panelEl.getBoundingClientRect().width:0);
  document.getElementById('stats').style.left=(W/2)+'px';
  cy.resize();
}
document.getElementById('panel-close').addEventListener('click',()=>togglePanel());
const _offBannerClose=document.getElementById('offline-banner-close');
if(_offBannerClose)_offBannerClose.addEventListener('click',()=>{const b=document.getElementById('offline-banner');if(b)b.remove();});
document.getElementById('zoom-in').addEventListener('click',()=>zoomBy(1.3));
document.getElementById('zoom-fit').addEventListener('click',()=>{try{localStorage.removeItem(_stateKey);}catch(_){}runLayout();});
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
const _scBtn=document.getElementById('ft-superclasses');
if(_scBtn)_scBtn.addEventListener('click',toggleSuperclasses);
refreshSuperclassesBtn();
// Expose wrappers for dynamically-created panel buttons (which run in global scope)
window._sterNav=navigateTo;
window._sterBack=function(){highlighted=null;applyHighlight();showDefault();};
window._sterToggleIndiv=toggleAllIndividuals;

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
const _EXPLORE_ENDPOINT={individual:'/api/individual-relations',class:'/api/class-links'};
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
    }).catch(()=>{});
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
    .then(r=>r.ok?r.json():null).catch(()=>null);
}
// Seed the new nodes near their anchors, then spread them without piling up: pin
// the existing graph and run a force pass over the newcomers only, then unpin.
// fit:false keeps the current viewport; locked nodes stay exactly put.
function _seedAndSpread(addedNodes,fp){
  if(addedNodes.empty()){_saveState();return;}
  addedNodes.forEach(n=>{
    const anchors=n.neighborhood('node').filter(nb=>!addedNodes.contains(nb));
    let x=fp.x,y=fp.y;
    if(anchors.length){x=0;y=0;anchors.forEach(a=>{const p=a.position();x+=p.x;y+=p.y;});x/=anchors.length;y/=anchors.length;}
    n.position({x:x+(Math.random()-.5)*40,y:y+(Math.random()-.5)*40});
  });
  const existing=cy.nodes().difference(addedNodes);
  existing.lock();
  const l=cy.layout({name:'cose',animate:false,fit:false,randomize:false,
    nodeRepulsion:5000,nodeOverlap:20,idealEdgeLength:110,edgeElasticity:100,
    gravity:50,numIter:600,coolingFactor:0.95,minTemp:1.0});
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
      hiddenEdgeTypes.forEach(t=>cy.edges('[type="'+t+'"]').addClass('hidden'));
      refreshSuperclassesBtn();
      applySuperclassVis();
      const n=cy.$('#'+CSS.escape(uri));
      if(n.length){highlighted=null;applyHighlight();togglePanel(true);showDetail(n.data());}
    });
  }).catch(()=>{});
}

// ── Hide a node together with its parent trail ────────────────────────────────
// Individual → drop it, its rdf:type class(es) and their subClassOf superclasses.
// Class → drop it and its subClassOf superclasses. A parent that another still
// -visible node depends on (instanceOf or subClassOf) is kept, transitively.
function hideNodeAndParents(uri){
  const node=cy.$('#'+CSS.escape(uri));
  if(!node.length)return;
  const type=node.data('type');
  const seeds=[];
  if(type==='individual'){
    cy.edges('[source="'+uri+'"][type="instanceOf"]').forEach(e=>seeds.push(e.data('target')));
  }else if(type==='class'){
    cy.edges('[source="'+uri+'"][type="subClassOf"]').forEach(e=>seeds.push(e.data('target')));
  }
  // Collect the transitive subClassOf parent trail above the seeds.
  const parents=new Set();
  const stack=[...seeds];
  while(stack.length){
    const c=stack.pop();
    if(parents.has(c))continue;
    parents.add(c);
    cy.edges('[source="'+c+'"][type="subClassOf"]').forEach(e=>stack.push(e.data('target')));
  }
  // The focus node is always removed; parents start in the removal set then get
  // released when some node outside the set still depends on them (fixpoint).
  const removing=new Set([uri,...parents]);
  let changed=true;
  while(changed){
    changed=false;
    parents.forEach(id=>{
      if(!removing.has(id))return;
      let depended=false;
      cy.edges('[target="'+id+'"]').forEach(e=>{
        const et=e.data('type');
        if((et==='instanceOf'||et==='subClassOf')&&!removing.has(e.data('source')))depended=true;
      });
      if(depended){removing.delete(id);changed=true;}
    });
  }
  removing.forEach(id=>cy.$('#'+CSS.escape(id)).remove());
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
  [exploreBtn,hideBtn].forEach(b=>{
    if(!b)return;
    b.addEventListener('mouseenter',_cancelHide);
    b.addEventListener('mouseleave',_scheduleHide);
  });
  exploreBtn.addEventListener('click',()=>{_hideOverlay();if(_exploreHoverUri)exploreOrExtend(_exploreHoverUri);});
  if(hideBtn)hideBtn.addEventListener('click',()=>{_hideOverlay();if(_exploreHoverUri)hideNodeAndParents(_exploreHoverUri);});
}

// ── Superclasses toggle (subClassOf trail; shown by default) ──────────────────
let superclassesHidden=false;
function applySuperclassVis(){
  cy.nodes('[superclass=1]').forEach(n=>{superclassesHidden?n.addClass('hidden'):n.removeClass('hidden');});
  cy.edges('[type="subClassOf"]').forEach(e=>{
    const s=cy.$('#'+CSS.escape(e.data('source'))),t=cy.$('#'+CSS.escape(e.data('target')));
    const touchesSuper=(s.length&&s.data('superclass')===1)||(t.length&&t.data('superclass')===1);
    if(superclassesHidden&&touchesSuper)e.addClass('hidden');else e.removeClass('hidden');
  });
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
  if(e.key==='f'){try{localStorage.removeItem(_stateKey);}catch(_){}runLayout();}
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
  for(const [t,lbl,show] of [['class-root','Root Class',hasRoot],['class-sub','Class',hasSub],['individual','Individual',ntypes.has('individual')],['topconcept','Top Concept',ntypes.has('topconcept')],['concept','Concept',ntypes.has('concept')],['scheme','Scheme',ntypes.has('scheme')]]){
    if(!show)continue;
    leg+='<div class="lr">'+nodeSvg(t)+lbl+'</div>';
    if(t==='individual')leg+=indToggle;
  }
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
  const rels=det.relations||[];if(rels.length){h+='<hr class="dp-hr"><div class="dp-sub">Relations</div>';rels.forEach(r=>{const lbl=r.label||r.uri,inG=cy.$('#'+CSS.escape(r.uri)).length>0;h+='<div class="dp-rel"><span class="dp-rel-tag">'+esc(r.rel)+'</span>';h+=inG?`<button class="dp-link" onclick='window._sterNav(${JSON.stringify(r.uri)})'>${esc(lbl)}</button>`:'<span>'+esc(lbl)+'</span>';h+='</div>';});}
  h+='</div>';panelEl.innerHTML=h;
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
  const dataUrl=window.location.origin+window.location.pathname.replace(/_vowl\.html$/,'_data.json');
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
    }catch(_){ }
  },2500);
}
initLiveRefresh();
}catch(err){
  const el=document.createElement('div');
  el.style.cssText='position:fixed;inset:0;background:rgba(220,38,38,.95);color:white;padding:24px;font-family:monospace;font-size:13px;z-index:200;white-space:pre-wrap;overflow:auto';
  el.textContent='Graph error — see browser console (F12):\n\n'+(err.stack||err);
  document.body.appendChild(el);
}
})();
