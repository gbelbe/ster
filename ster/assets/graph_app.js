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
// ── Busy indicator ───────────────────────────────────────────────────────────
// Every call this view makes goes through fetch, so counting in flight here
// covers search, class expansion, explore/extend, node detail and the live
// refresh at once — and covers whatever is added next, which wrapping eleven
// call sites by hand would not.
//
// Shown only after a delay: most of these answer in tens of milliseconds, and an
// indicator that flashes on every keystroke is worse than none. The version poll
// is excluded because it runs on a timer — a light that blinks by itself tells
// you nothing about what you just did.
const _BUSY_DELAY_MS=250;
const _BUSY_SILENT=/\/api\/version/;
let _busyCount=0,_busyTimer=null;
function _busyRefresh(){
  const el=document.getElementById('busy');
  if(!el)return;
  if(_busyCount>0){
    if(!_busyTimer)_busyTimer=setTimeout(()=>{el.classList.add('on');},_BUSY_DELAY_MS);
  }else{
    clearTimeout(_busyTimer);_busyTimer=null;
    el.classList.remove('on');
  }
}
function busy(message){
  const msg=document.getElementById('busy-msg');
  if(msg&&message)msg.textContent=message;
  _busyCount++;_busyRefresh();
  let done=false;
  return()=>{if(done){return;}done=true;_busyCount=Math.max(0,_busyCount-1);_busyRefresh();};
}
// fetch accepts three things, and each keeps its URL somewhere different.
// Named rather than nested in a conditional chain: the chain read as one
// expression while actually being three unrelated lookups, and a fourth input
// type would have made it worse. Anything else yields '' so the caller falls
// through to the untouched fetch.
function _fetchUrl(target){
  if(typeof target==='string')return target;
  if(target instanceof URL)return target.href;
  if(target instanceof Request)return target.url;
  return '';
}
(function wrapFetch(){
  const raw=globalThis.fetch.bind(globalThis);
  globalThis.fetch=function(...args){
    const url=_fetchUrl(args[0]);
    if(!url.includes('/api/')||_BUSY_SILENT.test(url))return raw(...args);
    const end=busy(url.includes('/api/search')?'Searching\u2026':'Loading\u2026');
    return raw(...args).finally(end);
  };
})();

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
  {selector:'node',style:{'label':'data(label)','text-halign':'center','text-valign':'center','color':'#000000','font-family':'system-ui,sans-serif','text-wrap':'wrap','text-max-width':'80px','font-size':12}},
  {selector:'node[type="class"]',style:{'shape':'ellipse','width':84,'height':84,'background-color':'#a9c7ea','border-color':'#3c6ebf','border-width':2,'font-weight':600}},
  // A class whose individuals are collapsed says how many it holds, and wears a
  // dashed border to read as openable. Once expanded and capped it says what it
  // withheld — "200 of 1027" — so the omission stays on screen rather than
  // passing by in a toast nobody was looking at.
  {selector:'node[individualCount > 0]',style:{
    'border-style':'dashed','border-width':3,'label':classCountLabel}},
  {selector:'node[type="class"][rootClass=1]',style:{'width':104,'height':104,'background-color':'#93b8e4','border-color':'#2f5896','border-width':5,'font-size':13,'text-max-width':'92px'}},
  {selector:'node[type="individual"]',style:{'shape':'ellipse','width':68,'height':68,'background-color':'#c6e2f5','border-color':'#4a90c4','border-width':1.5}},
  {selector:'node[type="scheme"]',style:{'shape':'ellipse','width':88,'height':88,'background-color':'#cbb8f9','border-color':'#7c3aed','border-width':2,'font-weight':600}},
  {selector:'node[type="topconcept"]',style:{'shape':'ellipse','width':72,'height':72,'background-color':'#8fd6ef','border-color':'#0e7490','border-width':2}},
  {selector:'node[type="concept"]',style:{'shape':'ellipse','width':56,'height':56,'background-color':'#9fe3b6','border-color':'#166534','border-width':1.5}},
  {selector:'node[type="datatype"]',style:{'shape':'round-rectangle','background-color':'#fef3c7','border-color':'#f59e0b','border-width':1.5,'color':'#92400e','font-size':10,'padding':'4px 8px','width':'label','height':22}},
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
  // ── Level of detail ────────────────────────────────────────────────────────
  // Last in the sheet on purpose: Cytoscape resolves equal specificity by order,
  // so these win over the per-type rules above without having to restate any of
  // them. Text is what costs — every label is a shaped, measured, background-
  // boxed draw — so it goes first, and the shapes stay navigable.
  {selector:'edge.lod-quiet',style:{'label':'','target-arrow-shape':'none'}},
  {selector:'node.lod-quiet',style:{'label':'','width':20,'height':20,'border-width':1}},
  // Whatever you point at is still worth reading. The label is hoisted above the
  // shrunken node rather than centred in it, because at 20px nothing fits inside.
  {selector:'node.lod-reveal',style:{'label':'data(label)','text-valign':'top',
    'text-margin-y':-4,'font-size':11,'color':'#0f172a','text-background-color':'#fff',
    'text-background-opacity':.92,'text-background-padding':'2px','z-index':30}},
  {selector:'edge.lod-reveal',style:{'label':'data(label)','target-arrow-shape':'triangle',
    'font-size':10,'text-background-color':'#fff','text-background-opacity':.92,
    'text-background-padding':'3px','z-index':30}},
  // ── Kin: every other use of the same relation ──────────────────────────────
  // Last, so it outranks both the per-type colours and the dimming — the point
  // of picking one edge is to see the others, which means they have to show
  // through whatever else is currently receding them.
  {selector:'edge.kin',style:{'line-color':'#d97706','target-arrow-color':'#d97706',
    'width':3,'opacity':1,'z-index':40,'events':'yes'}},
  {selector:'node.kin-end',style:{'border-color':'#d97706','border-width':3,
    'opacity':1,'z-index':35}},
  // ── Depth in the hierarchy ─────────────────────────────────────────────────
  // Weight falls off with distance from a root, so the shape of the thing is
  // readable before any of it is. "Order" is the codebase's own word: first
  // order is a root class (the existing ft-first-order filter uses exactly this
  // set), second is its direct children, and so on down.
  //
  // These sit after the level-of-detail rules on purpose. Shedding labels is
  // right for the long tail and wrong for the handful of nodes that carry the
  // structure, so the top two orders keep their names whatever the node count —
  // which is what makes a 1,400-node graph still say what it is at a glance.
  {selector:'node.ord1',style:{'border-width':5,'font-size':15,'font-weight':700,'z-index':20}},
  {selector:'node.ord2',style:{'border-width':3,'font-size':12,'z-index':15}},
  {selector:'node.ord3',style:{'border-width':2,'font-size':11,'opacity':.82,'z-index':10}},
  {selector:'node.ord4',style:{'border-width':1,'font-size':10,'opacity':.6,'z-index':5}},
  {selector:'node.lod-quiet.ord1',style:{'label':'data(label)','width':84,'height':84,
    'text-valign':'center','font-size':14}},
  {selector:'node.lod-quiet.ord2',style:{'label':'data(label)','width':56,'height':56,
    'text-valign':'center','font-size':11}},
];
// fcose (cytoscape-fcose, layered on layout-base + cose-base) replaces the
// plain cose force layout used here through Phase 0: cose's per-iteration cost
// grows faster than linearly in node count, which made the layout pass itself
// the dominant cost once a taxonomy's default view stopped being scoped down
// (see docs/architecture/graph-editor.md). fcose keeps cose's node/edge
// vocabulary (nodeRepulsion, idealEdgeLength, edgeElasticity, gravity, numIter)
// so this is a like-for-like tuning carry-over, not a re-tune; quality:'default'
// runs its full spring-embedder + incremental refinement passes (as opposed to
// 'draft', which skips refinement for raw speed at the cost of layout quality).
// nodeDimensionsIncludeLabels is the one that matters. Node styles above are
// fixed pixel sizes — an 84px circle for a class — while labels wrap to 74px and
// spill past the shape, so without it fcose packs circles smaller than the ones
// actually drawn and optimises a picture nobody sees. The raised repulsion and
// edge length are what pay off as graphs grow: on an expanded class with
// hundreds of individuals on screen they take another ~20% off.
//
// Measured over 8 graphs (10-429 nodes) x 5 runs, scoring
// 2*nodeOverlaps + 2*labelOverlaps + edgeCrossings. The previous settings won
// none of the 8 and placed last on the four largest; these won 5 and cut the
// score by a median 27%. Below ~20 nodes the differences are noise.
function makeLayout(){
  return {name:'fcose',animate:false,fit:true,padding:40,randomize:true,
    quality:'default',nodeRepulsion:12000,idealEdgeLength:180,edgeElasticity:100,
    gravity:60,numIter:1000,packComponents:true,
    nodeDimensionsIncludeLabels:true,nodeSeparation:150};
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
// The spinner is in the markup already showing, so the page is never blank while
// a large payload is parsed and laid out. It comes down when the first layout
// settles — or immediately, when saved positions meant there was no layout to
// wait for.
function hideSpinner(){
  const el=document.getElementById('graph-spinner');
  if(el)el.hidden=true;
}
function showSpinner(message){
  const el=document.getElementById('graph-spinner');
  if(!el)return;
  const msg=document.getElementById('graph-spinner-msg');
  if(msg&&message)msg.textContent=message;
  el.hidden=false;
}
function runLayout(){
  const l=cy.layout(makeLayout());
  l.one('layoutstop',()=>{_saveState();hideSpinner();});
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
      hideSpinner();
      return;
    }
  }catch(err){console.debug('Unable to restore graph state:',err);}
  runLayout();
  // fcose does not always emit layoutstop; never leave the page behind a veil
  setTimeout(hideSpinner,20000);
})();

cy.on('viewport',_debouncedSave);
cy.on('dragfree','node',_debouncedSave);

// A class you have opened owns the individuals on screen beneath it, so dragging
// the class carries them along rather than leaving the cluster behind to be
// dragged one node at a time. Only expanded classes do this: an individual that
// arrived some other way is nobody's passenger, and dragging an individual on
// its own never moves anything else.
//
// The delta is measured between drag ticks rather than against the grab point,
// so the followers track the class continuously instead of jumping at the end.
// Everything beneath a node travels with it, at any level: drag a top concept
// and its whole scheme comes; drag one branch and only that branch moves. This
// used to apply to an expanded class and its individuals alone, which meant the
// one arrangement you could rearrange was the one the machine had just made.
//
// "Beneath" is read off the hierarchy edges, all of which point child → parent:
// a subclass names its superclass, a narrower concept its broader, an individual
// its class, a concept its scheme. So the children of a node are the sources of
// its incoming edges of those types.
const _HIERARCHY_EDGES=new Set(['subClassOf','broader','instanceOf','inScheme']);
function _descendantsOf(node){
  const seen=new Set([node.id()]);
  const found=[];
  const queue=[node];
  while(queue.length){
    const current=queue.shift();
    for(const edge of current.incomers('edge').toArray()){
      if(!_HIERARCHY_EDGES.has(edge.data('type')))continue;
      const child=edge.source();
      if(seen.has(child.id()))continue;   // a cycle, or a child with two parents
      seen.add(child.id());
      found.push(child);
      queue.push(child);
    }
  }
  return cy.collection(found);
}
// Walked once when the drag starts, not on every tick: the set cannot change
// mid-drag, and re-walking a deep branch per mouse-move is what would make a
// large graph stutter.
let _dragAnchor=null,_dragFollowers=null;
cy.on('grab','node',e=>{
  const p=e.target.position();
  _dragAnchor={x:p.x,y:p.y};
  _dragFollowers=_descendantsOf(e.target);
});
cy.on('drag','node',e=>{
  if(!_dragAnchor||!_dragFollowers||_dragFollowers.empty())return;
  const p=e.target.position(),dx=p.x-_dragAnchor.x,dy=p.y-_dragAnchor.y;
  if(!dx&&!dy)return;
  _dragAnchor={x:p.x,y:p.y};
  _dragFollowers.positions(n=>{const q=n.position();return{x:q.x+dx,y:q.y+dy};});
});
cy.on('free','node',()=>{_dragAnchor=null;_dragFollowers=null;});

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
// A node is read in the context of the hierarchy it belongs to, so a click lights
// three things: the node, everything one step away (its related classes and
// individuals), and the whole subClassOf chain above it. An individual's chain
// starts at the classes it instantiates, since it has no superclass of its own.
function _highlightSeeds(node){
  const seeds=[node.id()];
  for(const e of cy.edges('[source="'+node.id()+'"][type="instanceOf"]'))seeds.push(e.data('target'));
  return seeds;
}
function parentChain(seeds){
  const chain=new Set();
  const stack=[...seeds];
  while(stack.length){
    const current=stack.pop();
    if(chain.has(current))continue;
    chain.add(current);
    for(const e of cy.edges('[source="'+current+'"][type="subClassOf"]'))stack.push(e.data('target'));
  }
  return chain;
}
function applyHighlight(){
  if(!highlighted){cy.elements().removeClass('dimmed');return;}
  const n=cy.$('#'+CSS.escape(highlighted));
  cy.elements().addClass('dimmed');
  n.neighborhood().add(n).removeClass('dimmed');
  const chain=parentChain(_highlightSeeds(n));
  for(const id of chain)cy.$('#'+CSS.escape(id)).removeClass('dimmed');
  // Only the rungs joining two lit nodes: an edge to a node that stays dimmed
  // would draw a line into the dark.
  for(const e of cy.edges('[type="subClassOf"]')){
    if(chain.has(e.data('source'))&&chain.has(e.data('target')))e.removeClass('dimmed');
  }
}

// ── Search ────────────────────────────────────────────────────────────────────
// Whole-ontology matches from /api/search for the term currently in the box —
// the client-side filter below only ever sees cy.nodes(), i.e. whatever is
// already on the canvas, and once the default view is scoped (Phase 0) most
// of a large ontology isn't there. Kept alongside the local filter rather
// than replacing it: the local filter is instant and needs no round trip for
// the common case (the thing you're looking for is already on screen).
let _serverMatches=[];
let _searchReqId=0;
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
  _searchServerWhole(t,matched.length);
}
// Debounced (typing settles before it fires) and request-ordered (reqId): a
// fast typist's earlier, slower response must never overwrite a later one's
// count. Folds an "elsewhere" note into the same count text rather than
// adding a second results list, so there is still exactly one search UI.
function _searchServerWhole(term,localCount){
  if(!API_TOKEN){_serverMatches=[];return;}
  const reqId=++_searchReqId;
  clearTimeout(_searchServerWhole._t);
  _searchServerWhole._t=setTimeout(()=>_fetchServerMatches(term,localCount,reqId),250);
}
// Split out of _searchServerWhole purely to keep nesting shallow (Sonar
// S2004): a request-scoped helper per pipeline stage instead of one
// four-deep chain of inline closures. Behaviour is unchanged.
function _fetchServerMatches(term,localCount,reqId){
  fetch('/api/search?q='+encodeURIComponent(term),{headers:{'Authorization':'Bearer '+API_TOKEN}})
    .then(r=>r.ok?r.json():null)
    .then(d=>_applyServerMatches(d,localCount,reqId))
    .catch(err=>{console.debug('Unable to search server-side:',err);});
}
function _applyServerMatches(d,localCount,reqId){
  if(reqId!==_searchReqId)return; // a newer keystroke has already superseded this
  _serverMatches=d?.results||[];
  const onCanvas=new Set(cy.nodes().map(n=>n.id()));
  const extra=_serverMatches.filter(r=>!onCanvas.has(r.id)).length;
  const countEl=document.getElementById('search-count');
  if(!countEl)return;
  if(!countEl.textContent.startsWith(String(localCount)+' '))return;
  // The server caps what it returns, so "+50 elsewhere" on a term matching
  // 7,888 things read as "there are 50 more" when there were 7,838 more than
  // that. Say how many there actually are whenever the list was cut.
  if(d?.truncated)countEl.textContent+=' (showing '+_serverMatches.length+' of '+d.total+')';
  else if(extra)countEl.textContent+=' (+'+extra+' elsewhere)';
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
  _serverMatches=[];
  _searchReqId++; // invalidate any in-flight server search
}
document.getElementById('search-box').addEventListener('input',e=>searchNodes(e.target.value));
document.getElementById('search-clear').addEventListener('click',clearSearch);
globalThis.addEventListener('load',()=>document.getElementById('search-box').focus());
// Enter on the search box acts on the first match exactly like clicking it.
// When nothing on the canvas matches, fall back to the whole-ontology result
// (if the debounced /api/search already came back) and bring it onto the
// canvas the same way exploring a node does.
document.getElementById('search-box').addEventListener('keydown',e=>{
  if(e.key!=='Enter')return;
  const t=e.target.value.trim().toLowerCase();
  if(!t)return;
  const matched=cy.nodes().filter(n=>n.data('label').toLowerCase().includes(t)||n.data('id').toLowerCase().includes(t));
  if(matched.length){e.preventDefault();activateNode(matched.first().data('id'));return;}
  const onCanvas=new Set(cy.nodes().map(n=>n.id()));
  const hit=_serverMatches.find(r=>!onCanvas.has(r.id));
  if(hit){e.preventDefault();clearSearch();exploreNode(hit.id,hit.type);}
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
      const fresh=d.nodes.filter(n=>!cy.$('#'+CSS.escape(n.id)).length);
      const added=cy.add([
        ...fresh.map(n=>({group:'nodes',data:{id:n.id,label:n.label,type:'individual',readOnly:n.readOnly||0,rootClass:0,superclass:0,individualCount:0,shownCount:0,ofClass:uri}})),
        ...d.edges.filter(e=>!cy.$('#'+CSS.escape(e.id)).length)
                  .map(e=>({group:'edges',data:{id:e.id+'@'+uri,source:e.source,target:e.target,type:e.type,label:'',cardinality:''}})),
      ]);
      node.data('shownCount',d.shown);
      // Past a handful, the instanceOf spokes stop telling you anything you
      // cannot already see — every member of the disc belongs to the class at
      // its centre — and they cost a line each across the densest part of the
      // picture. The nodes keep their `ofClass`, so dragging the class still
      // carries them and collapsing still finds them.
      if(added.nodes().length>_RING_EDGES_UP_TO)added.edges().addClass('hidden');
      _ringAround(node,added.nodes());
      _settleRing(node,added.nodes());
    })
    .catch(err=>{console.debug('Unable to expand class:',err);_expanded.delete(uri);});
}
// Clicking inspects, it does not reshape: opening a class's individuals is the
// overlay button's job, so a click can never move the graph under you.
// ── Level of detail ──────────────────────────────────────────────────────────
// A graph too big to read is still worth navigating, so detail is shed in the
// order it costs: edge labels and arrowheads first (every label is a shaped,
// measured, background-boxed draw, and arrowheads are per-edge geometry), then
// node labels, with the nodes themselves shrunk to dots.
//
// This is how the large-graph viewers stay usable — Cytoscape Desktop and Gephi
// both drop labels before anything else — and it is worth being clear about the
// trade: past the second threshold the picture shows structure, not names. The
// names come back for whatever you point at, and the detail panel always has
// them in full.
//
// Thresholds are node counts, not edge counts: edges follow from nodes here,
// and one number the reader can reason about beats two that interact.
// Defaults match ster/api_server.py GRAPH_VIZ_DEFAULTS; the injected values are
// what ster setup → Graph Viz last saved. The fallback matters for the offline
// export, which carries no config.
const _lodCfg=globalThis.__STER_GRAPH__.lod||{};
const LOD_QUIET_EDGES_ABOVE=_lodCfg.lodEdges||300;
const LOD_QUIET_NODES_ABOVE=_lodCfg.lodNodes||800;
// Three states per layer, not two. 'auto' follows the thresholds; 'on' and
// 'off' are what the buttons set, and once set they stick — a graph that keeps
// overruling you the moment it grows is worse than one that never helped.
let _edgeLabelMode='auto',_nodeLabelMode='auto';
function _quiet(mode,count,threshold){
  if(mode==='on')return false;
  if(mode==='off')return true;
  return count>threshold;
}
// Distance from a root, capped at 4 — past that the difference stops being
// legible and the classes would just multiply. Roots are the nodes nothing in
// the hierarchy points down to: root classes, schemes, and anything orphaned.
// The walk reuses _HIERARCHY_EDGES, so "below" means the same thing here as it
// does when you drag a branch.
const _MAX_ORDER=4;
// One step down the hierarchy: everything directly beneath *frontier* that the
// walk has not already placed. Lifted out of applyHierarchyOrders because two
// nested loops and two guards, inside a while, inside a batch callback, were
// most of that function's cognitive load while being none of its subject — the
// walk reads as three lines once this has a name.
//
// *seen* is updated here rather than returned alongside: a node reachable from
// two parents belongs to the shallower order, and marking it the moment it is
// first taken is what guarantees that.
function _hierarchyChildren(frontier,seen){
  const next=[];
  for(const node of frontier.toArray()){
    for(const edge of node.incomers('edge').toArray()){
      if(!_HIERARCHY_EDGES.has(edge.data('type')))continue;
      const child=edge.source();
      if(seen.has(child.id()))continue;
      seen.add(child.id());
      next.push(child);
    }
  }
  return next;
}
function applyHierarchyOrders(){
  const roots=cy.nodes().filter(n=>
    n.outgoers('edge').filter(e=>_HIERARCHY_EDGES.has(e.data('type'))).empty());
  cy.batch(()=>{
    cy.nodes().removeClass('ord1 ord2 ord3 ord4');
    let frontier=roots,order=1;
    const seen=new Set(roots.map(n=>n.id()));
    while(!frontier.empty()&&order<=_MAX_ORDER){
      frontier.addClass('ord'+order);
      if(order===_MAX_ORDER)break;
      frontier=cy.collection(_hierarchyChildren(frontier,seen));
      order++;
    }
    // Whatever the walk never reached — a cycle with no entry point, or a node
    // hanging off no hierarchy at all — reads as the far tail rather than as a
    // root, which is what leaving it unclassed would have made it look like.
    cy.nodes().filter(n=>!seen.has(n.id())).addClass('ord4');
  });
}
function applyLevelOfDetail(){
  const n=cy.nodes().length;
  cy.batch(()=>{
    cy.edges()[_quiet(_edgeLabelMode,n,LOD_QUIET_EDGES_ABOVE)?'addClass':'removeClass']('lod-quiet');
    cy.nodes()[_quiet(_nodeLabelMode,n,LOD_QUIET_NODES_ABOVE)?'addClass':'removeClass']('lod-quiet');
  });
  _refreshLodButtons();
  applyHierarchyOrders();
}
// The button reads as struck-through when the labels are off, exactly like the
// edge-type filters beside it, so the bar means one thing throughout.
function _refreshLodButtons(){
  const n=cy.nodes().length;
  const pairs=[['ft-edge-labels',_edgeLabelMode,LOD_QUIET_EDGES_ABOVE],
               ['ft-node-labels',_nodeLabelMode,LOD_QUIET_NODES_ABOVE]];
  for(const [id,mode,threshold] of pairs){
    const btn=document.getElementById(id);
    if(!btn)continue;
    const shown=!_quiet(mode,n,threshold);
    btn.classList[shown?'add':'remove']('active');
    btn.title=mode==='auto'
      ?'Automatic — hidden above '+threshold+' nodes (ster setup → Graph Viz). Click to force.'
      :'Forced '+(mode==='on'?'on':'off')+'. Click to cycle.';
  }
}
// auto → off → on → auto. Starting with 'off' because the reason to touch this
// button on a big graph is almost always to quieten it further, and on a small
// one 'off' is the only state that differs from what you already see.
function _cycleLod(which){
  const next={auto:'off',off:'on',on:'auto'};
  if(which==='edge')_edgeLabelMode=next[_edgeLabelMode];
  else _nodeLabelMode=next[_nodeLabelMode];
  applyLevelOfDetail();
}
// Recomputed whenever the graph changes size — expansion, explore, live refresh
// — rather than only at first draw, since that is exactly when a graph crosses
// a threshold. Class changes do not fire add/remove, so this cannot re-enter.
cy.on('add remove',()=>{clearTimeout(_lodTimer);_lodTimer=setTimeout(applyLevelOfDetail,60);});
let _lodTimer=null;

// Whatever is selected reads normally, along with the edges touching it: a node
// with no visible label and no visible connections is not something you can
// explore from.
function revealAround(ele){
  cy.batch(()=>{
    cy.elements('.lod-reveal').removeClass('lod-reveal');
    cy.edges('.kin').removeClass('kin');
    cy.nodes('.kin-end').removeClass('kin-end');
    if(!ele)return;
    ele.addClass('lod-reveal');
    if(ele.isNode())ele.connectedEdges().addClass('lod-reveal').connectedNodes().addClass('lod-reveal');
    else ele.connectedNodes().addClass('lod-reveal');
  });
}

cy.on('tap','node',e=>{
  revealAround(e.target);
  selectNode(e.target.id());
});
// Edges were not clickable before. Under level of detail an unlabelled arrow is
// unreadable unless you can ask it what it is, so a tap reveals it and names it
// in the panel.
cy.on('tap','edge',e=>{
  revealAround(e.target);
  selectEdge(e.target);
});
cy.on('tap',function(e){if(e.target===cy){highlighted=null;revealAround(null);applyHighlight();showDefault();}});

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
const _elBtn=document.getElementById('ft-edge-labels');
if(_elBtn)_elBtn.addEventListener('click',()=>_cycleLod('edge'));
const _nlBtn=document.getElementById('ft-node-labels');
if(_nlBtn)_nlBtn.addEventListener('click',()=>_cycleLod('node'));
applyLevelOfDetail();
// Every panel button is now wired with addEventListener at creation (see
// renderDetail/individualToggleNodes/detailRelationsNodes) rather than an
// inline onclick attribute, so navigateTo no longer needs a global wrapper
// for markup to call into — kept anyway as a small, harmless debug/test hook.
// The show-all button is rendered server-side (see _render.py) and fires
// before this module's own handlers exist, so it reaches the spinner globally.
globalThis.showSpinner=showSpinner;
_wireStaleBanner();
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
// typeOverride lets a caller that has a node type but no cy node yet (a
// whole-ontology search hit not currently on the canvas) explore it anyway;
// every on-canvas caller omits it and the type is read off the cy node as
// before.
function exploreNode(uri,typeOverride){
  if(!API_TOKEN)return;
  const node=cy.$('#'+CSS.escape(uri));
  const type=typeOverride||node.data('type');
  const endpoint=_EXPLORE_ENDPOINT[type];
  if(!endpoint)return;
  _rootType=type;
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
// Individuals of one class are a set, not a cloud. Seeding them all at the
// class's own position (their only anchor is the class, so that is where the
// averaging below puts them) left them piled on it and on each other: the
// class's own overlay buttons ended up underneath its individuals, and the
// cluster read as a blob rather than as members of something.
//
// Seed them on a ring instead. The radius grows with the count so the ring
// never has to overlap itself, and fcose still runs afterwards to resolve
// collisions with the rest of the graph — but starting from a configuration
// that already reads as "these belong to that".
// Concentric rings, each packed as tightly as its own circumference allows,
// rather than one ring holding everything. A single ring has to grow its radius
// linearly with the count — 200 individuals at 68px put the ring 2,900px out,
// a circle so wide the class at its centre and the members on its rim are never
// on screen together. Ring k sits one node-width beyond ring k-1 and seats as
// many as fit, so the same 200 land inside ~550px.
//
// Alternate rings are rotated half a slot so members sit in the gaps of the ring
// inside them, which is what makes the cluster read as a disc rather than as
// spokes.
const _RING_EDGES_UP_TO=10;
function _ringAround(centre,nodes){
  const n=nodes.length;
  if(!n)return;
  const cp=centre.position();
  const centreRadius=Math.max(centre.width(),centre.height())/2;
  let widest=0;
  for(const m of nodes)widest=Math.max(widest,Math.max(m.width(),m.height()));
  const step=widest*1.05;                       // touching, with a hair of air
  let placed=0,ring=0;
  while(placed<n){
    const radius=centreRadius+widest/2+ring*step;
    const capacity=Math.max(1,Math.floor((2*Math.PI*radius)/step));
    const count=Math.min(capacity,n-placed);
    const offset=(ring%2)?Math.PI/count:0;
    for(let i=0;i<count;i++){
      const angle=(2*Math.PI*i)/count+offset-Math.PI/2;
      nodes[placed+i].position({x:cp.x+radius*Math.cos(angle),y:cp.y+radius*Math.sin(angle)});
    }
    placed+=count;
    ring++;
  }
}
// The ring is the whole point, so it is kept: running a force pass over it
// pulled members back onto the class (fcose aims for its ideal edge length from
// the class centre, which is shorter than the ring's radius once a class holds
// more than a handful). Instead the ring is nudged off whatever it happens to
// land on — each member steps outward along its own spoke until it clears the
// existing graph — which preserves the circle while resolving collisions.
function _settleRing(centre,nodes){
  if(nodes.empty()){_saveState();return;}
  const others=cy.nodes().difference(nodes).difference(centre);
  const cp=centre.position();
  for(const m of nodes){
    const p=m.position();
    let dx=p.x-cp.x,dy=p.y-cp.y;
    const len=Math.hypot(dx,dy)||1;
    dx/=len;dy/=len;
    const mr=Math.max(m.width(),m.height())/2;
    for(let step=0;step<24;step++){
      const q=m.position();
      const hit=others.filter(o=>{
        const op=o.position();
        return Math.hypot(op.x-q.x,op.y-q.y)<mr+Math.max(o.width(),o.height())/2;
      });
      if(hit.empty())break;
      m.position({x:q.x+dx*mr*1.2,y:q.y+dy*mr*1.2});
    }
  }
  _saveState();
}
function _seedAndSpread(addedNodes,fp,preseeded){
  if(addedNodes.empty()){_saveState();return;}
  for(const n of preseeded?[]:addedNodes){
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
  // fcose (see makeLayout() above) — randomize:false plus the locked existing
  // nodes is exactly its documented incremental-layout use: only the newcomers
  // added by explore/merge get force-placed, the rest of the graph stays put.
  const l=cy.layout({name:'fcose',animate:false,fit:false,randomize:false,
    quality:'default',nodeRepulsion:12000,idealEdgeLength:180,edgeElasticity:100,
    gravity:50,numIter:600,nodeDimensionsIncludeLabels:true,nodeSeparation:150});
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

// ── Hover overlay: explore/extend + individuals buttons ───────────────────────
const exploreBtn=document.getElementById('explore-btn');
const individualsBtn=document.getElementById('individuals-btn');
let _exploreHoverUri=null,_exploreHideTimer=null;
function _positionExploreBtn(node){
  const bb=node.renderedBoundingBox();
  const cx=(bb.x1+bb.x2)/2;
  // Buttons touch the node (no gap) so the cursor can slide straight onto them
  // without crossing empty canvas: explore/extend hugs the top edge (its bottom
  // sits on the node top), individuals hugs the bottom edge (its top sits on the
  // node bottom). The transforms are set in CSS (#explore-btn vs #individuals-btn).
  exploreBtn.style.left=cx+'px';exploreBtn.style.top=bb.y1+'px';
  if(individualsBtn){individualsBtn.style.left=cx+'px';individualsBtn.style.top=bb.y2+'px';}
}
function _hideOverlay(){_cancelRetarget();exploreBtn.style.display='none';if(individualsBtn)individualsBtn.style.display='none';}
// Which buttons a node earns. Both actions need the API — explore fetches
// relations, and opening a class fetches the individuals the server withheld —
// so an offline page offers neither rather than offering a dead button. A class
// holding nothing withheld has nothing to show, so it gets no button either, and
// one already open is offered the way back instead.
function _showOverlay(node){
  if(!API_TOKEN){_hideOverlay();return;}
  // On the full graph the action is "explore" (replace); inside a subgraph it
  // becomes "extend" (merge onto the current view).
  exploreBtn.textContent=_savedGraph?'\u2295 extend relations':'\u2299 explore relations';
  _positionExploreBtn(node);
  exploreBtn.style.display='block';
  if(!individualsBtn)return;
  individualsBtn.textContent=_expanded.has(node.data('id'))
    ?'\u2296 hide individuals'
    :'\u2295 show individuals';
  individualsBtn.style.display=node.data('individualCount')?'block':'none';
}
// The node and its two labels form one hover region: entering any of them keeps
// the overlay up (cancels a pending hide); leaving any of them only *schedules*
// a hide, so sliding label → node → label never flickers the buttons off. The
// overlay disappears only once the cursor has left the node and both labels.
function _cancelHide(){if(_exploreHideTimer){clearTimeout(_exploreHideTimer);_exploreHideTimer=null;}}
function _scheduleHide(){_cancelHide();_exploreHideTimer=setTimeout(_hideOverlay,600);}
// The buttons hug the node's edges, but in a crowded graph the short trip onto
// one still crosses whatever node is stacked over that edge. Handing the overlay
// to that node the instant the cursor touches it moves the buttons out from
// under a cursor already on its way to them — you reach for "show individuals"
// and it becomes a different class's button, or leaves entirely.
//
// So a *different* node only takes the overlay after a grace period: long enough
// to cross a node in passing, short enough that deliberately hovering a
// neighbour still feels immediate. Landing on a button cancels the pending
// switch outright, and while the cursor is on a button no node can claim it —
// that is the case the grace period exists to protect.
const _RETARGET_GRACE_MS=260;
let _retargetTimer=null,_onOverlayBtn=false;
function _cancelRetarget(){if(_retargetTimer){clearTimeout(_retargetTimer);_retargetTimer=null;}}
if(exploreBtn&&API_TOKEN){
  cy.on('mouseover','node',e=>{
    const t=e.target.data('type');
    if(t!=='individual'&&t!=='class'){_hideOverlay();return;}
    _cancelHide();
    const node=e.target,uri=node.data('id');
    // Back on the node the overlay already belongs to: nothing to switch.
    if(uri===_exploreHoverUri){_cancelRetarget();_showOverlay(node);return;}
    // Cursor is on a button — a node underneath it does not get to interrupt.
    if(_onOverlayBtn)return;
    if(_exploreHoverUri&&exploreBtn.style.display==='block'){
      _cancelRetarget();
      _retargetTimer=setTimeout(()=>{
        _retargetTimer=null;_exploreHoverUri=uri;_showOverlay(node);
      },_RETARGET_GRACE_MS);
      return;
    }
    _exploreHoverUri=uri;
    _showOverlay(node);
  });
  cy.on('mouseout','node',_scheduleHide);
  cy.on('viewport',_hideOverlay);
  for(const b of [exploreBtn,individualsBtn]){
    // `continue`, not `return`: a missing button must skip its own wiring, not
    // abandon the rest of this function.
    if(!b)continue;
    b.addEventListener('mouseenter',()=>{_onOverlayBtn=true;_cancelRetarget();_cancelHide();});
    b.addEventListener('mouseleave',()=>{_onOverlayBtn=false;_scheduleHide();});
  }
  exploreBtn.addEventListener('click',()=>{_hideOverlay();if(_exploreHoverUri)exploreOrExtend(_exploreHoverUri);});
  if(individualsBtn)individualsBtn.addEventListener('click',()=>{_hideOverlay();if(_exploreHoverUri)toggleClassIndividuals(cy.$('#'+CSS.escape(_exploreHoverUri)));});
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
  // Which build drew this. Cheap to show, and it is the one fact you cannot
  // get from looking at the page: a server started from another install keeps
  // serving its own build until it is stopped, so "I updated ster and this is
  // still old" is usually a second install rather than a stale cache.
  const ver=globalThis.__STER_GRAPH__.sterVersion;
  if(ver)p.push('ster '+ver);
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
  for(const [type,label,show] of nodeLegend){
    if(!show)continue;
    nodes.push(el('div',{class:'lr'},[iconEl(nodeSvg(type)),document.createTextNode(label)]));
    if(type==='individual')nodes.push(...individualToggleNodes());
  }
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
// ── Phase 4: relation add/remove ────────────────────────────────────────────
// Canvas drag-to-create (cytoscape-edgehandles/-edge-editing) was investigated
// and dropped for this pass — both need a browser dependency the plain
// <script> vendoring here can't supply without pulling in more libraries (see
// the matching comment in ster/api.py's _register_mutation_routes). This is
// the panel-based equivalent instead: a small search-backed picker plus
// explicit Add/Remove, built on the same /api/search endpoint Phase 2 added.
function _searchPicker(placeholder,types){
  const wrap=el('div',{class:'dp-picker'});
  const input=el('input',{class:'dp-picker-input',type:'text',placeholder:placeholder,autocomplete:'off'});
  const list=el('div',{class:'dp-picker-list'});
  list.hidden=true;
  wrap.append(input,list);
  const state={selected:null,reqId:0};
  wrap.getSelected=()=>state.selected;
  function clearList(){list.replaceChildren();list.hidden=true;}
  input.addEventListener('input',()=>{
    state.selected=null;
    const q=input.value.trim();
    if(!q){clearList();return;}
    const id=++state.reqId;
    fetch('/api/search?q='+encodeURIComponent(q)+'&types='+encodeURIComponent(types),{headers:{'Authorization':'Bearer '+API_TOKEN}})
      .then(r=>r.ok?r.json():null)
      .then(d=>_applyPickerResults(d,id,state,input,list,clearList))
      .catch(err=>{console.debug('Unable to search picker candidates:',err);});
  });
  // A short delay lets the option's own click register before the list is torn
  // down — losing focus on the input would otherwise close it first.
  input.addEventListener('blur',()=>setTimeout(clearList,150));
  return wrap;
}
// Split out of _searchPicker purely to keep nesting shallow (Sonar S2004):
// applying results and building each option row are their own functions
// instead of one five-deep chain of inline closures. Behaviour is unchanged.
function _applyPickerResults(d,id,state,input,list,clearList){
  if(id!==state.reqId)return; // a newer keystroke already superseded this
  const results=(d?.results||[]).slice(0,10);
  if(!results.length){clearList();return;}
  list.replaceChildren(...results.map(r=>_pickerOptionRow(r,state,input,clearList)));
  list.hidden=false;
}
function _pickerOptionRow(r,state,input,clearList){
  const row=el('button',{class:'dp-picker-opt',type:'button'},[
    el('span',{class:'dp-pref',text:r.label}),
    el('span',{class:'dp-uri',style:'margin-left:6px',text:r.id}),
  ]);
  row.addEventListener('click',()=>{state.selected=r;input.value=r.label;clearList();});
  return row;
}
// errEl is required, not optional: a refused removal used to go to console.debug
// only, so the × re-enabled itself and the relation stayed put with no message —
// indistinguishable from a broken button. The add forms already surface
// err.message, and _postJson has unwrapped the server's `detail` all along.
function _relationRemoveBtn(onRemove,errEl){
  const btn=el('button',{class:'dp-rel-remove',title:'Remove',text:'×'});
  btn.addEventListener('click',()=>{
    btn.disabled=true;errEl.textContent='';
    onRemove().catch(err=>{errEl.textContent=err.message||'Remove failed.';btn.disabled=false;});
  });
  return btn;
}
function _individualRelationAddForm(d){
  const propPicker=_searchPicker('Property…','property');
  const targetPicker=_searchPicker('Target individual…','individual');
  const addBtn=el('button',{class:'dp-edit-save',text:'Add relation'});
  const errEl=el('div',{class:'dp-edit-err'});
  addBtn.addEventListener('click',()=>{
    const prop=propPicker.getSelected(),target=targetPicker.getSelected();
    if(!prop||!target){errEl.textContent='Pick a property and a target first.';return;}
    addBtn.disabled=true;errEl.textContent='';
    _postJson('/api/relation',{ind_uri:d.id,prop_uri:prop.id,target_uri:target.id}).then(()=>{
      _detailCache.delete(d.id);
      if(highlighted===d.id)showDetail(d);
    }).catch(err=>{errEl.textContent=err.message||'Add failed.';addBtn.disabled=false;});
  });
  return el('div',{class:'dp-rel-add'},[propPicker,targetPicker,addBtn,errEl]);
}
function _classParentAddForm(d){
  const targetPicker=_searchPicker('Superclass…','class');
  const addBtn=el('button',{class:'dp-edit-save',text:'Add superclass'});
  const errEl=el('div',{class:'dp-edit-err'});
  addBtn.addEventListener('click',()=>{
    const target=targetPicker.getSelected();
    if(!target){errEl.textContent='Pick a class first.';return;}
    addBtn.disabled=true;errEl.textContent='';
    _postJson('/api/class-parent',{child_uri:d.id,parent_uri:target.id}).then(()=>{
      _detailCache.delete(d.id);
      if(highlighted===d.id)showDetail(d);
    }).catch(err=>{errEl.textContent=err.message||'Add failed.';addBtn.disabled=false;});
  });
  return el('div',{class:'dp-rel-add'},[targetPicker,addBtn,errEl]);
}
function detailRelationsNodes(d,relations){
  const canEdit=_canEdit(d);
  if(!relations.length&&!canEdit)return [];
  const nodes=[el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'Relations'})];
  for(const r of relations){
    const lbl=r.label||r.uri,inG=cy.$('#'+CSS.escape(r.uri)).length>0;
    const row=el('div',{class:'dp-rel'},el('span',{class:'dp-rel-tag',text:r.rel}));
    const relErr=el('div',{class:'dp-edit-err'});
    if(inG){
      const btn=el('button',{class:'dp-link',text:lbl});
      btn.addEventListener('click',()=>navigateTo(r.uri));
      row.append(btn);
    }else{
      row.append(el('span',{text:lbl}));
    }
    // Only the two Phase 4 command-backed relation kinds are removable here:
    // an individual's object-property value (carries propUri) and a class's
    // subClassOf link. Everything else (rdf:type, broader, equivalentClass, …)
    // has no matching command in this slice, so it stays display-only.
    if(canEdit&&r.propUri){
      row.append(_relationRemoveBtn(()=>_postJson('/api/relation/remove',{ind_uri:d.id,prop_uri:r.propUri,target_uri:r.uri}).then(()=>{
        _detailCache.delete(d.id);
        if(highlighted===d.id)showDetail(d);
      }),relErr));
    }else if(canEdit&&r.rel==='subClassOf'){
      row.append(_relationRemoveBtn(()=>_postJson('/api/class-parent/remove',{child_uri:d.id,parent_uri:r.uri}).then(()=>{
        _detailCache.delete(d.id);
        if(highlighted===d.id)showDetail(d);
      }),relErr));
    }
    nodes.push(row,relErr);
  }
  if(canEdit&&d.type==='individual')nodes.push(_individualRelationAddForm(d));
  else if(canEdit&&d.type==='class')nodes.push(_classParentAddForm(d));
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
// An edge has no URI of its own and no /api/node-detail entry, so its panel is
// built from what the edge already carries plus the labels of the two nodes it
// joins — which is the whole of what an edge *is*. Clicking either end from here
// hands over to the normal node panel.
// Two edges are "the same relation" when they carry the same predicate. The
// payload gives an edge a type and a label and nothing else — no property URI —
// but for an object or datatype property the label *is* the property name, and
// for subClassOf / instanceOf / broader the label is empty and the type is the
// whole of the predicate. So the pair identifies it either way.
function _edgeKey(edge){
  return edge.data('type')+'\u0000'+(edge.data('label')||'');
}
function _edgeKin(edge){
  const key=_edgeKey(edge);
  return cy.edges().filter(e=>_edgeKey(e)===key);
}
function selectEdge(edge){
  clearSearch();
  highlighted=null;
  applyHighlight();
  togglePanel(true);
  // Picking one use of a relation shows every use of it: which individuals share
  // a property is a question about the predicate, not about the pair you clicked.
  const kin=_edgeKin(edge);
  cy.batch(()=>{
    kin.addClass('kin').addClass('lod-reveal');
    kin.connectedNodes().addClass('kin-end').addClass('lod-reveal');
  });
  const src=edge.source(),tgt=edge.target();
  const panel=el('div',{class:'dp'});
  const back=el('button',{class:'dp-back',text:'← Overview'});
  back.addEventListener('click',()=>{revealAround(null);showDefault();});
  panel.append(back);
  const type=edge.data('type')||'edge';
  panel.append(el('span',{class:'dp-badge dp-'+type,text:KM[type]||type}));
  panel.append(el('div',{class:'dp-lbl',text:edge.data('label')||KM[type]||type}));
  panel.append(el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'From'}));
  panel.append(_edgeEndNode(src));
  panel.append(el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'To'}));
  panel.append(_edgeEndNode(tgt));
  panel.append(...detailKinNodes(edge,kin));
  const card=edge.data('cardinality');
  if(card){
    panel.append(el('hr',{class:'dp-hr'}),el('div',{class:'dp-sub',text:'Cardinality'}));
    panel.append(el('div',{class:'dp-rel',text:card}));
  }
  panelEl.replaceChildren(panel);
}
// Every other use of this relation in the view, listed so the shared structure
// is readable and not only visible: "which individuals share this property" is
// usually the question behind clicking one. Capped, because a common predicate
// can have thousands and a panel that long is not a list, it is a scroll.
const _KIN_LIST_LIMIT=25;
function detailKinNodes(edge,kin){
  const others=kin.filter(e=>e.id()!==edge.id());
  const nodes=[el('hr',{class:'dp-hr'}),
    el('div',{class:'dp-sub',text:'Also used here ('+others.length+')'})];
  if(!others.length){
    nodes.push(el('div',{class:'dp-rel',text:'Nowhere else in this view.'}));
    return nodes;
  }
  for(const e of others.slice(0,_KIN_LIST_LIMIT)){
    const row=el('div',{class:'dp-rel'});
    const btn=el('button',{class:'dp-link',
      text:(e.source().data('label')||e.source().id())+' → '+(e.target().data('label')||e.target().id())});
    btn.addEventListener('click',()=>selectEdge(e));
    row.append(btn);
    nodes.push(row);
  }
  if(others.length>_KIN_LIST_LIMIT){
    nodes.push(el('div',{class:'dp-rel',
      text:'…and '+(others.length-_KIN_LIST_LIMIT)+' more, all highlighted in the graph.'}));
  }
  return nodes;
}
function _edgeEndNode(node){
  const row=el('div',{class:'dp-rel'});
  const btn=el('button',{class:'dp-link',text:node.data('label')||node.data('id')});
  btn.addEventListener('click',()=>{revealAround(node);selectNode(node.data('id'));});
  row.append(btn);
  return row;
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
  panel.append(_editableLabelNode(d));
  panel.append(el('div',{class:'dp-uri',text:d.id}));
  const lbls=det.labels||[],showLbls=[...lbls.filter(l=>l.kind==='pref').slice(1),...lbls.filter(l=>l.kind==='alt'),...lbls.filter(l=>l.kind==='label')];
  panel.append(...detailLabelsNodes(showLbls));
  panel.append(...detailCommentsNodes(det.comments||[]));
  panel.append(...detailDescriptionOrEditNodes(d,det.description));
  panel.append(...detailScopeNodes(det.scopeNote));
  panel.append(...detailRelationsNodes(d,det.relations||[]));
  panel.append(...detailMediaNodes(det.images,det.videos));
  panel.append(...detailUrlsNodes(det.urls));
  panelEl.replaceChildren(panel);
  wireMedia();
}
// ── Editable side panel (Phase 3) ───────────────────────────────────────────
// Only the primary label/description are editable inline, and only in the
// project's default display language (see docs/architecture/graph-editor.md,
// Phase 3 — a language picker for editing is a bigger UI, deliberately left
// out of this slice). `readOnly` marks an entity whose only home is a context
// file; it no longer changes how the node is *drawn* — the picture is the
// merged graph, and where a triple was read from is not a property of the
// graph — but it still gates the edit affordance, because TaxonomyService has
// nowhere on disk to persist a change to such an entity.
const _EDIT_LANG='en';
function _canEdit(d){
  return !!API_TOKEN&&!d.readOnly;
}
// The version this page last saw the server on, sent with every edit so the
// server can refuse one built on a stale read. null until /api/version answers —
// and it stays null on a read-only session, where omitting it means "no check",
// exactly the previous behaviour.
let _docVersion=null;
// ── Has the server been replaced under us? ───────────────────────────────────
// The page bakes in the build that drew it; /api/version reports the build
// answering now. When they differ, ster was updated and restarted while this
// tab stayed open — so what is on screen is the previous build's output, which
// looks perfectly fine and is not. That is the whole of "I updated ster and the
// graph view is still old".
//
// Checked on a timer rather than once: the replacement happens *after* load, or
// it would not be a problem. Read-only sessions carry no token and so cannot
// ask; they also cannot be edited, so the stakes are lower.
const _BUILD_CHECK_MS=30000;
// Raised once the server answers as a build other than the one that drew this
// page. Named rather than inlined in the poll: the banner is the interesting
// half, and a chain of guards nested three deep inside an interval inside a
// fetch is most of the enclosing function's cognitive load for none of its
// meaning.
function _showStaleBuild(mine,theirs){
  const el=document.getElementById('stale');
  const msg=document.getElementById('stale-msg');
  if(msg)msg.textContent='This page was drawn by ster '+mine+'; the server is now '+theirs+'.';
  if(el)el.classList.add('on');
}
function _checkServerBuild(mine){
  return fetch('/api/version',{headers:{'Authorization':'Bearer '+API_TOKEN}})
    .then(r=>r.ok?r.json():null)
    // Optional chaining rather than a `!d||!d.ster` pair: one question asked
    // once, and it reads as the question — is there a build, and is it ours.
    .then(d=>{if(d?.ster&&d.ster!==mine)_showStaleBuild(mine,d.ster);})
    .catch(err=>{console.debug('Unable to check the server build:',err);});
}
// Both halves of the banner, wired in one call. Kept out of the init body
// because a guard there counts against initSterRelationsGraph, which holds the
// whole application and sits permanently on the cognitive-complexity limit —
// so any feature adding a branch there trips the ratchet, whatever it is.
function _wireStaleBanner(){
  _watchForNewBuild();
  const reload=document.getElementById('stale-reload');
  if(reload)reload.addEventListener('click',()=>location.reload());
}
function _watchForNewBuild(){
  const mine=API_TOKEN&&globalThis.__STER_GRAPH__.sterVersion;
  if(!mine)return;
  setInterval(()=>_checkServerBuild(mine),_BUILD_CHECK_MS);
}
function _initDocVersion(){
  if(!API_TOKEN)return;
  fetch('/api/version',{headers:{'Authorization':'Bearer '+API_TOKEN}})
    .then(r=>r.ok?r.json():null)
    .then(d=>{if(typeof d?.version==='number')_docVersion=d.version;})
    .catch(err=>{console.debug('Unable to read document version:',err);});
}
function _postJson(endpoint,body){
  return fetch(endpoint,{
    method:'POST',
    headers:{'Content-Type':'application/json','Authorization':'Bearer '+API_TOKEN},
    body:JSON.stringify(_docVersion===null?body:{...body,base_version:_docVersion}),
  }).then(async r=>{
    if(!r.ok){
      let detail='Save failed.';
      try{const parsed=await r.json();if(parsed?.detail)detail=parsed.detail;}catch{/* ignore */}
      // 409 is the stale-read rejection. The version is left stale on purpose so
      // a blind retry is refused too: the edit that arrived in between is not on
      // this page yet, and overwriting it unseen is what the check exists to stop.
      if(r.status===409)detail='Someone else changed this file since you loaded it. Reload the page to see their edit, then try again.';
      throw new Error(detail);
    }
    const out=await r.json();
    if(typeof out?.version==='number')_docVersion=out.version;
    return out;
  });
}
function _postField(endpoint,uri,value){
  return _postJson(endpoint,{uri:uri,lang:_EDIT_LANG,value:value});
}
// Wraps *displayNode* (the read view) with a ✎ button that swaps in an
// editable control. Only the explicit Save/Cancel buttons act — losing focus
// or pressing Enter never submits, so a stray click can't fire an edit.
function _editableRow(value,displayNode,{multiline,onSave}){
  const wrap=el('div',{class:'dp-editable'});
  const editBtn=el('button',{class:'dp-edit-btn',title:'Edit',text:'✎'});
  const readRow=el('div',{class:'dp-editable-view'},[displayNode,editBtn]);
  wrap.append(readRow);
  editBtn.addEventListener('click',()=>_openEditableRow(wrap,readRow,value,multiline,onSave));
  return wrap;
}
// Split out of _editableRow purely to keep nesting shallow (Sonar S2004):
// each stage (open the editor, submit it) is its own function instead of one
// deeply nested chain of inline closures. Behaviour is unchanged — only the
// explicit Save/Cancel buttons act, never blur or Enter.
function _openEditableRow(wrap,readRow,value,multiline,onSave){
  const input=multiline
    ?el('textarea',{class:'dp-edit-input',rows:'4'})
    :el('input',{class:'dp-edit-input',type:'text'});
  input.value=value;
  const saveBtn=el('button',{class:'dp-edit-save',text:'Save'});
  const cancelBtn=el('button',{class:'dp-edit-cancel',text:'Cancel'});
  const errEl=el('div',{class:'dp-edit-err'});
  const editRow=el('div',{class:'dp-editable-edit'},[input,el('div',{class:'dp-edit-actions'},[saveBtn,cancelBtn]),errEl]);
  wrap.replaceChildren(editRow);
  input.focus();
  cancelBtn.addEventListener('click',()=>wrap.replaceChildren(readRow));
  saveBtn.addEventListener('click',()=>_submitEditableRow(wrap,readRow,input,saveBtn,cancelBtn,errEl,onSave));
}
function _submitEditableRow(wrap,readRow,input,saveBtn,cancelBtn,errEl,onSave){
  saveBtn.disabled=true;cancelBtn.disabled=true;errEl.textContent='';
  onSave(input.value).then(()=>wrap.replaceChildren(readRow)).catch(err=>{
    errEl.textContent=err.message||'Save failed.';
    saveBtn.disabled=false;cancelBtn.disabled=false;
  });
}
function _editableLabelNode(d){
  const display=el('div',{class:'dp-h3',text:d.label});
  if(!_canEdit(d))return display;
  return _editableRow(d.label,display,{multiline:false,onSave:value=>
    _postField('/api/entity-label',d.id,value).then(()=>{
      const n=cy.$('#'+CSS.escape(d.id));
      if(n.length)n.data('label',value);
      d.label=value;
      _detailCache.delete(d.id);
      if(highlighted===d.id)showDetail(d);
    })});
}
function detailDescriptionOrEditNodes(d,description){
  if(!_canEdit(d)){
    if(!description)return [];
    return [el('hr',{class:'dp-hr'}),el('div',{class:'dp-desc'},linkifyNodes(description))];
  }
  const display=el('div',{class:'dp-desc'+(description?'':' dp-hint')},description?linkifyNodes(description):document.createTextNode('No description yet.'));
  return [el('hr',{class:'dp-hr'}),_editableRow(description||'',display,{multiline:true,onSave:value=>
    _postField('/api/entity-description',d.id,value).then(()=>{
      _detailCache.delete(d.id);
      if(highlighted===d.id)showDetail(d);
    })})];
}
function navigateTo(uri){
  const n=cy.$('#'+CSS.escape(uri));if(!n.length)return;
  highlighted=uri;applyHighlight();togglePanel(true);showDetail(n.data());
  cy.animate({center:{eles:n},zoom:Math.max(cy.zoom(),1)},{duration:400});
}

// ── Live refresh ──────────────────────────────────────────────────────────────
function initLiveRefresh(){
  _initDocVersion();
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
