// ster taxonomy application layer — radial collapsible tree render, search,
// filter, breadcrumb and detail-panel logic for the Taxonomie tab.
//
// Rendering is hand-built SVG, matching the classic D3 "radial tidy tree"
// look (https://observablehq.com/@d3/radial-tree/2): curved links computed
// with the same control-point construction d3-shape's `linkRadial` uses,
// tangential labels flipped on the left half so they never render upside
// down, and simple wheel/drag pan-zoom on an SVG <g> transform. Node/link
// *positions* are computed with the vendored d3-hierarchy's `d3.tree()`
// (a radial tidy-tree layout — angle allocated per branch proportional to
// its leaf count) exactly as before; this file adds no rendering dependency
// beyond that already-vendored layout engine — no Cytoscape, no d3-shape,
// no d3-selection, no d3-zoom. It is intentionally separate from
// d3-hierarchy: upgrading it (see _D3_HIERARCHY_VERSION in viz_vowl.py)
// must never overwrite this code. It uses only the public
// `d3.hierarchy`/`d3.tree` factories and reads its per-render data from the
// injected `globalThis.__STER_GRAPH__.taxonomy`.
//
// Model: collapsed by default beyond the scheme level, so a large taxonomy
// never dumps thousands of nodes at once. Clicking an expandable node toggles
// its children open/closed; collapsing a node also resets the expand state
// of everything under it, so re-opening it later starts collapsed again.

(function(){
try{
const taxo=globalThis.__STER_GRAPH__?.taxonomy;
// Nothing to render: OWL-only taxonomy, or a query-result view that never
// carries a taxonomy payload at all. This is the file's only job, so an early
// return here skips nothing else the page depends on.
if(!taxo?.nodes||!Object.keys(taxo.nodes).length)return;

const API_TOKEN=globalThis.__STER_GRAPH__.token;
const stage=document.getElementById('treemap');
const panelEl=document.getElementById('detail-panel');
const breadcrumbEl=document.getElementById('tm-breadcrumb');
// The search box itself is shared with the Relations tab (graph_app.js owns
// its wiring too); only the result-count display is taxonomy-specific.
const searchBox=document.getElementById('search-box');
const searchClear=document.getElementById('search-clear');
const searchCount=document.getElementById('tm-search-count');
const schemeSelect=document.getElementById('tm-filter-scheme');
const depthSelect=document.getElementById('tm-filter-depth');
const layoutSelect=document.getElementById('tm-filter-layout');

const SUPER='__ster_overview__';
// Which nodes currently show their children. Schemes and concepts alike are
// tracked by URI; the invisible SUPER root is always "expanded" (its
// children — the schemes — are the first ring, always visible).
const expanded=new Set();
// The last node selected (clicked, or reached via the breadcrumb) — drives
// the breadcrumb trail and the detail panel. Null until a first selection.
let selected=null;

function schemeByUri(uri){return taxo.schemes.find(s=>s.uri===uri);}

function conceptTile(uri){
  const n=taxo.nodes[uri];
  return {id:uri,label:n.label,depth:n.depth,descendantCount:n.descendantCount,
    schemeUri:n.schemeUri,hasChildren:(n.children||[]).length>0};
}
function schemeTile(s){
  const total=(s.roots||[]).reduce((acc,r)=>acc+1+(taxo.nodes[r]?.descendantCount||0),0);
  return {id:s.uri,label:s.title,depth:-1,descendantCount:total,
    schemeUri:s.uri,hasChildren:(s.roots||[]).length>0};
}
function directChildrenOf(uri){
  if(uri===SUPER)return taxo.schemes.map(schemeTile);
  const scheme=schemeByUri(uri);
  if(scheme)return (scheme.roots||[]).map(conceptTile);
  const n=taxo.nodes[uri];
  return n?(n.children||[]).map(conceptTile):[];
}
function labelOf(uri){
  if(uri===SUPER)return 'Overview';
  const scheme=schemeByUri(uri);
  if(scheme)return scheme.title;
  const n=taxo.nodes[uri];
  return n?n.label:uri;
}
function tileDataFor(uri){
  const scheme=schemeByUri(uri);
  if(scheme)return schemeTile(scheme);
  return taxo.nodes[uri]?conceptTile(uri):null;
}
function parentUriOf(uri){
  const n=taxo.nodes[uri];
  if(n)return n.parent||n.schemeUri;
  if(schemeByUri(uri))return SUPER;
  return null;
}
// Share of the parent's total (1 + descendantCount) — a stat in the detail
// panel, independent of how the tree is currently laid out on screen.
function percentOfParent(uri){
  const scheme=schemeByUri(uri);
  if(scheme){
    const allSchemes=taxo.schemes.reduce((a,s)=>a+schemeTile(s).descendantCount,0)||1;
    return Math.round(100*schemeTile(scheme).descendantCount/allSchemes);
  }
  const n=taxo.nodes[uri];
  if(!n)return null;
  const parentUri=n.parent||n.schemeUri;
  const totalW=rankedChildren(parentUri).reduce((a,c)=>a+c.weight,0)||1;
  return Math.round(100*(1+n.descendantCount)/totalW);
}

// ── Content analysis (detail-panel "Analysis" section) ──────────────────────
function rankedChildren(uri){
  return directChildrenOf(uri)
    .map(k=>({id:k.id,label:k.label,weight:1+k.descendantCount}))
    .sort((a,b)=>b.weight-a.weight);
}
function computeAnalysis(uri){
  const ranked=rankedChildren(uri);
  return {childCount:ranked.length,topChildren:ranked};
}

// ── Colour per top-level scheme, cycling through a small fixed palette ──────
const PALETTE=['#2563eb','#059669','#d97706','#7c3aed','#dc2626','#0891b2','#65a30d','#db2777'];
const schemeColor=new Map(taxo.schemes.map((s,i)=>[s.uri,PALETTE[i%PALETTE.length]]));
function hexToRgb(hex){const n=Number.parseInt(hex.slice(1),16);return[(n>>16)&255,(n>>8)&255,n&255];}
function mix(hex,hex2,t){
  const a=hexToRgb(hex),b=hexToRgb(hex2);
  return 'rgb('+a.map((v,i)=>Math.round(v+(b[i]-v)*t)).join(',')+')';
}
function nodeColor(schemeUri,depth){
  const base=schemeColor.get(schemeUri)||'#64748b';
  return mix(base,'#ffffff',Math.min(Math.max(depth,0)*0.1,0.5));
}

// ── Expand/collapse state ────────────────────────────────────────────────
// Collapsing a node also forgets the expand state of everything below it, so
// a later re-expand always starts from "just this node's direct children" —
// no stale deep state sitting invisibly under a collapsed ancestor.
function collapse(uri){
  expanded.delete(uri);
  for(const child of directChildrenOf(uri)){
    if(expanded.has(child.id))collapse(child.id);
  }
}
function toggle(uri){
  if(expanded.has(uri))collapse(uri);
  else expanded.add(uri);
}
// Expand every ancestor of *uri* (used when jumping to it via the
// breadcrumb) without touching sibling branches' own expand state.
function ensureExpandedTo(uri){
  let p=parentUriOf(uri);
  while(p&&p!==SUPER){expanded.add(p);p=parentUriOf(p);}
  if(p===SUPER)expanded.add(SUPER);
}

// ── Tree build (respects expand state + the depth filter) ──────────────────
function buildNode(info,maxDepth){
  const within=maxDepth===null||info.depth<0||info.depth<maxDepth;
  const open=info.hasChildren&&within&&(maxDepth!==null||info.id===SUPER||expanded.has(info.id));
  if(open){
    const kids=directChildrenOf(info.id).map(k=>buildNode(k,maxDepth));
    return {...info,children:kids};
  }
  return {...info};
}

// ── SVG scaffold ─────────────────────────────────────────────────────────
const SVG_NS='http://www.w3.org/2000/svg';
const TOOLBAR_H=44,SUBBAR_H=32;
const RING_STEP=100; // minimum px of radius added per depth level (radial mode)
const MIN_ARC=13; // px of circumference a set of siblings must give each other, or their labels collide at the anchor (radial mode)
const MAX_RING_JUMP=RING_STEP*6; // cap on how far MIN_ARC is allowed to push a ring out (radial mode) — see assignRadii
const NODE_GAP=18; // px between two adjacent siblings' rows (horizontal mode) — fixed, not adaptive: unlike a radial ring, a row never has to share its space with anything else
const LEVEL_GAP=200; // px per depth level (horizontal mode) — generous enough for a typical label's width

if(!document.getElementById('tt-style')){
  const style=document.createElement('style');
  style.id='tt-style';
  style.textContent=`
#treemap{position:relative;overflow:hidden}
#tt-svg{width:100%;height:100%;display:block;cursor:grab}
#tt-svg.tt-panning{cursor:grabbing}
.tt-link{fill:none;stroke:#cbd5e1;stroke-width:1}
.tt-node circle{stroke:#fff;stroke-width:1;cursor:pointer}
.tt-node text{font:10px system-ui,sans-serif;fill:#334155;paint-order:stroke;stroke:#fff;stroke-width:3px;cursor:pointer}
.tt-node.tt-collapsed circle{stroke-width:2;stroke-dasharray:2,2;stroke:#94a3b8}
.tt-node.tt-selected circle{stroke:#0f172a;stroke-width:2}
.tt-node.tt-dimmed{opacity:.2}
.tt-node:hover circle{stroke:#2563eb;stroke-width:2}
`;
  document.head.appendChild(style);
}
stage.innerHTML='';
const svg=document.createElementNS(SVG_NS,'svg');
svg.id='tt-svg';
const viewport=document.createElementNS(SVG_NS,'g');
viewport.id='tt-viewport';
const linksLayer=document.createElementNS(SVG_NS,'g');
const nodesLayer=document.createElementNS(SVG_NS,'g');
viewport.appendChild(linksLayer);
viewport.appendChild(nodesLayer);
svg.appendChild(viewport);
stage.appendChild(svg);

// ── Pan/zoom (hand-rolled — no d3-zoom) ─────────────────────────────────────
let tx=0,ty=0,vk=1;
let _firstRender=true;
function applyTransform(){
  viewport.setAttribute('transform','translate('+tx+','+ty+') scale('+vk+')');
}
let panning=false,panStartX=0,panStartY=0,panTx0=0,panTy0=0;
svg.addEventListener('mousedown',evt=>{
  if(evt.target.closest('.tt-node'))return; // let node clicks through untouched
  panning=true;panStartX=evt.clientX;panStartY=evt.clientY;panTx0=tx;panTy0=ty;
  svg.classList.add('tt-panning');
});
globalThis.addEventListener('mousemove',evt=>{
  if(!panning)return;
  tx=panTx0+(evt.clientX-panStartX);
  ty=panTy0+(evt.clientY-panStartY);
  applyTransform();
});
globalThis.addEventListener('mouseup',()=>{panning=false;svg.classList.remove('tt-panning');});
svg.addEventListener('wheel',evt=>{
  evt.preventDefault();
  const rect=svg.getBoundingClientRect();
  const mx=evt.clientX-rect.left,my=evt.clientY-rect.top;
  const factor=evt.deltaY<0?1.1:1/1.1;
  const newK=Math.min(8,Math.max(0.05,vk*factor));
  const px=(mx-tx)/vk,py=(my-ty)/vk;
  tx=mx-px*newK;ty=my-py*newK;vk=newK;
  applyTransform();
},{passive:false});

function pointRadial(angle,radius){
  return [radius*Math.cos(angle-Math.PI/2),radius*Math.sin(angle-Math.PI/2)];
}
// Sets each node's own .x (its angle, radians) by splitting its parent's
// angular slice among its children — the sibling with more descendants gets
// a bigger share, but by sqrt(descendant count) rather than the count
// itself. d3.tree()'s own layout gives each *leaf* equal angular width,
// which means a subtree's share of the circle is exactly proportional to
// how many leaves it has — fine when every branch is in the same ballpark,
// but with a handful of one-item branches sitting next to a nine-item one,
// that nine-item branch is 9 of the ~17 total leaves and swallows half the
// circle for itself, stretching its own children far apart even though
// there's nothing dense about them. Square-rooting the weight keeps bigger
// branches visibly bigger without letting the gap run away like that.
// Fraction of each node's angular span spent on gaps between its children
// rather than on the children themselves — without this, two different
// branches' children sit shoulder to shoulder at the boundary with nothing
// to tell them apart, since the split above is otherwise gap-free (each
// child's slice starts exactly where its previous sibling's ends). Spending
// a *fraction* of the span, rather than a fixed angle, keeps this working
// at every level: few children (a handful of top-level branches) get a
// generously visible gap each, many children (hundreds of concepts under
// one scheme) get a tiny one each — it never eats a fixed chunk regardless
// of how many gaps there are to fit.
const GAP_FRACTION=0.15;
function assignRadialAngles(root){
  root.count(); // sets node.value = number of leaf descendants (>=1)
  root.x0=0;root.x1=2*Math.PI;
  (function recurse(node){
    const kids=node.children;
    if(!kids?.length)return;
    const weights=kids.map(k=>Math.sqrt(k.value));
    const total=weights.reduce((a,b)=>a+b,0)||1;
    const span=node.x1-node.x0;
    const gapEach=kids.length>1?(GAP_FRACTION*span)/(kids.length-1):0;
    const available=span*(1-GAP_FRACTION);
    let acc=node.x0;
    for(let i=0;i<kids.length;i++){
      const w=weights[i]/total*available;
      kids[i].x0=acc;kids[i].x1=acc+w;acc+=w+gapEach;
      recurse(kids[i]);
    }
  })(root);
  for(const d of root.descendants())d.x=(d.x0+d.x1)/2;
}
// Sets each node's own .y (its radius, px) — recursively, per branch: a
// parent's own children all share one radius, sized to *their own* narrowest
// angular slice (from assignRadialAngles above), not to how packed some
// unrelated branch elsewhere happens to be at the same nominal depth. A
// single shared radius per depth (this function's previous shape) breaks in
// two opposite ways once branches stop being roughly the same size: sized to
// the taxonomy's average density, a handful of siblings sitting right next
// to a much busier branch get a radius too small for *that* branch's own
// children, and their labels collide; sized to accommodate the single
// densest branch anywhere in the tree, every simple branch gets dragged out
// to the same huge radius for nothing. Doing this per-branch means a dense
// pocket only pushes its own descendants further out — everything else
// keeps normal spacing. MAX_RING_JUMP still caps how far any one jump can
// push things out, because a handful of branches really are dense enough
// (70+ siblings squeezed into an already-narrow slice) that satisfying
// MIN_ARC exactly would blow the whole canvas out to a size nothing else on
// it benefits from — better to let that one pocket stay a little tight than
// to zoom every other branch out to specks to make room for it.
function assignRadii(root){
  (function recurse(node,parentRadius){
    node.y=parentRadius;
    const kids=node.children;
    if(!kids?.length)return;
    let minWidth=Infinity;
    for(const k of kids)minWidth=Math.min(minWidth,k.x1-k.x0);
    const needed=MIN_ARC/Math.max(minWidth,1e-6);
    const childRadius=Math.min(parentRadius+MAX_RING_JUMP,Math.max(parentRadius+RING_STEP,needed));
    for(const k of kids)recurse(k,childRadius);
  })(root,0);
}
// Position computation is the one thing that genuinely differs between the
// two modes; everything after (styling, click handling, search, detail
// panel) reads the same screenX/screenY off each node however it got there.
function computeLayoutPositions(root,mode){
  const pos=new Map(); // uri -> [screenX, screenY]
  if(mode==='horizontal'){
    const layout=d3.tree().nodeSize([NODE_GAP,LEVEL_GAP]).separation((a,b)=>(a.parent===b.parent?1:2));
    layout(root);
    // nodeSize spaces nodes but doesn't centre them vertically — recentre so
    // the root sits on the horizontal midline instead of at a corner.
    let minX=Infinity,maxX=-Infinity;
    for(const d of root.descendants()){minX=Math.min(minX,d.x);maxX=Math.max(maxX,d.x);}
    const midX=(minX+maxX)/2;
    for(const d of root.descendants())pos.set(d,[d.y,d.x-midX]);
  }else{
    assignRadialAngles(root);
    assignRadii(root);
    for(const d of root.descendants())pos.set(d,pointRadial(d.x,d.y));
  }
  return pos;
}

// Curved links: vendored d3-shape's own `linkRadial`/`linkHorizontal` path
// generators, not a hand-rolled reimplementation — a previous hand-rolled
// version of the radial one shipped a real bug (interpolating control points
// at the wrong midpoint produced a "teardrop" loop near the centre). Since
// d3-hierarchy is already vendored for the layout math, using its sibling
// module for the one thing it does better costs little.
// Radial: default accessors read angle off `.x` and radius off `.y`, which is
// exactly what assignRadialAngles/assignRadii already store on each node —
// no extra accessor wiring needed. Horizontal: the two ends are plain screen
// pixels from *pos*, not node.x/node.y — custom accessors read those instead
// of the (differently scaled) raw tree() output.
function linkPathGenerator(mode,pos){
  if(mode==='horizontal')return d3.linkHorizontal().x(d=>pos.get(d)[0]).y(d=>pos.get(d)[1]);
  return d3.linkRadial().angle(d=>d.x).radius(d=>d.y);
}

// One tree node's <g> (circle + label), positioned and classed for the
// current mode/search/selection state. Split out of render() so each node's
// own handful of conditionals — selection, dimming, collapsed marker, label
// side — aren't nested inside render()'s own per-node loop.
function buildTreeNodeElement(d,{mode,pos,dim,maxDepth}){
  const data=d.data;
  const [sx,sy]=pos.get(d);
  const count=1+data.descendantCount;
  const hasR=data.hasChildren?7:5;

  const g=document.createElementNS(SVG_NS,'g');
  const classes=['tt-node'];
  if(data.id===selected)classes.push('tt-selected');
  if(dim)classes.push('tt-dimmed');
  if(data.hasChildren&&!expanded.has(data.id)&&maxDepth===null)classes.push('tt-collapsed');
  g.setAttribute('class',classes.join(' '));
  // Radial: rotate to the node's angle, then push out to its radius — any
  // further local x-offset (the label) then reads as purely radial.
  // Horizontal: no rotation, label always sits to the node's right, same as
  // the plain translate already used for its position.
  const onLeft=mode==='radial'&&d.x>=Math.PI;
  g.setAttribute('transform',mode==='horizontal'
    ?'translate('+sx+','+sy+')'
    :'rotate('+(d.x*180/Math.PI-90)+') translate('+d.y+',0)');
  g.dataset.uri=data.id;

  const circle=document.createElementNS(SVG_NS,'circle');
  circle.setAttribute('r',String(hasR));
  circle.setAttribute('fill',nodeColor(data.schemeUri,Math.max(data.depth,0)));
  g.appendChild(circle);

  const text=document.createElementNS(SVG_NS,'text');
  const label=data.label+(count>1?' ('+count+')':'');
  text.textContent=label;
  if(onLeft){
    text.setAttribute('transform','rotate(180) translate(-'+(hasR+4)+',0)');
    text.setAttribute('text-anchor','end');
  }else{
    text.setAttribute('transform','translate('+(hasR+4)+',0)');
    text.setAttribute('text-anchor','start');
  }
  text.setAttribute('dominant-baseline','middle');
  g.appendChild(text);

  g.addEventListener('click',()=>onNodeClick(data.id));
  return g;
}

// First-render fit: from the elements' own measured extent (post-insertion
// getBBox, in the same coordinate space the pan/zoom transform acts on)
// rather than a hand-estimated radius — it's exact in both modes, labels
// (including the long ones on a wide horizontal ring) included.
function fitStageToContent(){
  const bbox=nodesLayer.getBBox();
  const rect=stage.getBoundingClientRect();
  const availW=rect.width||800,availH=rect.height||600;
  const usableH=Math.max(availH-TOOLBAR_H-SUBBAR_H,100);
  const pad=40;
  const boxW=Math.max(bbox.width,1),boxH=Math.max(bbox.height,1);
  vk=Math.min(1,Math.max(0.05,Math.min((availW-pad*2)/boxW,(usableH-pad*2)/boxH)));
  tx=availW/2-(bbox.x+bbox.width/2)*vk;
  ty=TOOLBAR_H+SUBBAR_H+usableH/2-(bbox.y+bbox.height/2)*vk;
  applyTransform();
}

function render(){
  const maxDepth=depthSelect.value===''?null:Number(depthSelect.value);
  const mode=layoutSelect.value||'horizontal';
  const rootInfo={id:SUPER,label:'Overview',depth:-2,descendantCount:0,schemeUri:null,hasChildren:taxo.schemes.length>0};
  const rootObj=buildNode(rootInfo,maxDepth);
  const root=d3.hierarchy(rootObj);

  const pos=computeLayoutPositions(root,mode);
  const linkPath=linkPathGenerator(mode,pos);

  const q=(searchBox.value||'').trim().toLowerCase();
  let matched=0,total=0;
  const linkFrag=document.createDocumentFragment();
  const nodeFrag=document.createDocumentFragment();
  for(const d of root.descendants()){
    if(d.depth===0)continue; // skip the invisible SUPER root itself
    total++;
    const dim=Boolean(q)&&!(d.data.label||'').toLowerCase().includes(q);
    if(q&&!dim)matched++;

    // link to parent — in radial mode the parent's radius-0 point projects
    // to the centre regardless of angle, so the invisible root needs no
    // special-casing there either.
    const path=document.createElementNS(SVG_NS,'path');
    path.setAttribute('class','tt-link');
    path.setAttribute('d',linkPath({source:d.parent,target:d}));
    linkFrag.appendChild(path);

    nodeFrag.appendChild(buildTreeNodeElement(d,{mode,pos,dim,maxDepth}));
  }

  linksLayer.replaceChildren(linkFrag);
  nodesLayer.replaceChildren(nodeFrag);

  if(_firstRender){
    fitStageToContent();
    _firstRender=false;
  }
  searchCount.textContent=q?matched+'/'+total:'';
  renderBreadcrumb();
  renderFilters();
}

function onNodeClick(uri){
  const data=tileDataFor(uri);
  if(!data)return;
  selected=uri;
  showDetail(data,percentOfParent(uri));
  if(data.hasChildren)toggle(uri);
  render();
}

// Built with DOM APIs (createElement/textContent), not an innerHTML template
// string — a label is taxonomy content, not markup, so there is nothing to
// escape once it never passes through the HTML parser at all.
function renderBreadcrumb(){
  const trail=[];
  let cur=selected;
  while(cur){trail.unshift(cur);const p=parentUriOf(cur);cur=p===SUPER?null:p;}
  breadcrumbEl.replaceChildren();
  for(const [i,uri] of trail.entries()){
    const btn=document.createElement('button');
    btn.dataset.uri=uri;
    btn.textContent=labelOf(uri);
    btn.addEventListener('click',()=>{
      ensureExpandedTo(uri);
      selected=uri;
      const data=tileDataFor(uri);
      if(data)showDetail(data,percentOfParent(uri));
      render();
    });
    breadcrumbEl.appendChild(btn);
    if(i<trail.length-1)breadcrumbEl.appendChild(document.createTextNode(' / '));
  }
}

function populateSchemeOptions(){
  const allOpt=document.createElement('option');allOpt.value='';allOpt.textContent='All';
  schemeSelect.appendChild(allOpt);
  for(const s of taxo.schemes){
    const o=document.createElement('option');o.value=s.uri;o.textContent=s.title;
    schemeSelect.appendChild(o);
  }
}

// How many nodes sit at each depth, and the deepest "Depth ≤N" cut that
// still stays under *budget* total nodes summed from the top. "All" (empty
// value → maxDepth=null in render()) means *no* depth cap — buildNode then
// falls back to the normal collapse-respecting behaviour, same as never
// touching this filter, so it's always safe regardless of taxonomy size. A
// *numeric* choice is the dangerous one: unlike a manual click — which only
// ever opens one node's own direct children, at most a few dozen even on the
// biggest taxonomy we've tested against — "Depth ≤N" force-opens *every*
// node down to N regardless of collapse state (see buildNode). On a wide
// taxonomy that's thousands of nodes in a single render, which is what was
// freezing the tab: GEMET alone puts 2144 nodes at depth 2, and 3361 already
// open by depth ≤1.
function safeDepthBudget(budget){
  const depthCounts=new Map();
  let maxDepth=0;
  for(const n of Object.values(taxo.nodes)){
    depthCounts.set(n.depth,(depthCounts.get(n.depth)||0)+1);
    if(n.depth>maxDepth)maxDepth=n.depth;
  }
  let cumulative=0,safeMaxDepth=-1;
  for(let i=0;i<=maxDepth;i++){
    cumulative+=depthCounts.get(i)||0;
    if(cumulative>budget)break;
    safeMaxDepth=i;
  }
  return {maxDepth,safeMaxDepth};
}

// Only offer the numeric depth options that can't blow past a node budget
// the browser can build and lay out in one go — deeper browsing on a
// taxonomy this wide still works, just one manual click at a time, the way
// it always has.
function populateDepthOptions(){
  const SAFE_DEPTH_NODE_BUDGET=1500;
  const allDepthOpt=document.createElement('option');allDepthOpt.value='';allDepthOpt.textContent='All';
  depthSelect.appendChild(allDepthOpt);
  const {maxDepth,safeMaxDepth}=safeDepthBudget(SAFE_DEPTH_NODE_BUDGET);
  for(let i=0;i<=safeMaxDepth;i++){
    const o=document.createElement('option');o.value=String(i);o.textContent=String(i);
    depthSelect.appendChild(o);
  }
  if(safeMaxDepth<maxDepth){
    const note=document.createElement('option');note.value='';note.disabled=true;
    note.textContent=safeMaxDepth<0?'(too wide — expand nodes by hand)':'(deeper: expand nodes by hand)';
    depthSelect.appendChild(note);
  }
}

function renderFilters(){
  if(schemeSelect.options.length)return; // populate once
  populateSchemeOptions();
  populateDepthOptions();
}

schemeSelect.addEventListener('change',()=>{
  if(schemeSelect.value){
    expanded.add(SUPER);expanded.add(schemeSelect.value);
    selected=schemeSelect.value;
  }
  render();
});
depthSelect.addEventListener('change',()=>render());
if(layoutSelect)layoutSelect.addEventListener('change',()=>{_firstRender=true;render();});
searchBox.addEventListener('input',()=>render());
// The shared clear button (owned by graph_app.js) sets the box's value
// directly without dispatching an `input` event — listen for the click
// itself too, or the tree would stay dimmed after a Relations-tab clear.
if(searchClear)searchClear.addEventListener('click',()=>render());
globalThis.addEventListener('resize',()=>render());

// ── Detail panel ──────────────────────────────────────────────────────────
// Small, deliberately duplicated fetch (mirrors graph_app.js's loadDetail:
// live API when a token is present, the static `_detail.json` companion
// otherwise) rather than sharing code across the two independent assets.
// Small DOM-builder helpers — the detail panel used to be assembled as an
// HTML string (escaping each dynamic value on the way in) and dropped in via
// innerHTML; building it as real nodes instead means nothing dynamic ever
// passes through the HTML parser, so there's nothing to escape or to get
// wrong escaping.
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
function detailRow(label,value){
  return el('div',{class:'dp-row'},[el('span',{text:label}),el('span',{text:String(value)})]);
}
let _bulkDetailPromise=null;
function bulkDetail(){
  if(_bulkDetailPromise)return _bulkDetailPromise;
  const url=globalThis.location.pathname.replace(/_vowl\.html$/,'_detail.json');
  _bulkDetailPromise=fetch(url,{cache:'no-store'}).then(r=>r.ok?r.json():{}).catch(()=>({}));
  return _bulkDetailPromise;
}
async function fetchDetail(uri){
  try{
    if(API_TOKEN){
      const r=await fetch('/api/node-detail?uri='+encodeURIComponent(uri),{headers:{'Authorization':'Bearer '+API_TOKEN}});
      return r.ok?await r.json():null;
    }
    return (await bulkDetail())[uri]||null;
  }catch(err){
    console.debug('Taxonomy detail fetch failed:',err);
    return null;
  }
}
let _detailSeq=0;
function showDetail(data,pct){
  // The panel is shared with the Relations tab, which owns its open/close
  // state (graph_app.js's togglePanel) — force it open so a click here can
  // never render into a panel the user (or a prior Relations session) left
  // closed.
  if(typeof globalThis._sterShowPanel==='function')globalThis._sterShowPanel();
  const seq=++_detailSeq;
  renderDetail(data,null,pct);
  fetchDetail(data.id).then(det=>{if(seq===_detailSeq)renderDetail(data,det,pct);});
}
// Other labels + description, when the async /detail fetch has resolved —
// split out of renderDetail purely to keep its Cognitive Complexity down.
function appendDetailExtras(panel,det){
  const otherLabels=(det.labels||[]).filter(l=>l.kind!=='pref');
  if(otherLabels.length){
    panel.append(el('hr',{class:'dp-hr'}));
    panel.append(el('div',{class:'dp-sub',text:'Other labels'}));
    for(const l of otherLabels){
      panel.append(el('div',{class:'dp-lbl'},[
        el('span',{class:'dp-lang',text:l.lang}),
        el('span',{class:'dp-'+l.kind,text:l.value}),
      ]));
    }
  }
  if(det.description){
    panel.append(el('hr',{class:'dp-hr'}));
    panel.append(el('div',{class:'dp-desc',text:det.description}));
  }
}

// "Main children" ranked list — split out of renderDetail purely to keep
// its Cognitive Complexity down.
function appendDetailMainChildren(panel,analysis){
  if(!analysis.topChildren.length)return;
  const totalW=analysis.topChildren.reduce((a,c)=>a+c.weight,0)||1;
  const shown=analysis.topChildren.slice(0,6);
  panel.append(el('div',{class:'dp-sub',style:'margin-top:8px',text:'Main children'}));
  for(const c of shown){
    const p=Math.round(100*c.weight/totalW);
    // Clicking a main child selects it and opens its branch, exactly like
    // clicking its own node would.
    const btn=el('button',{class:'dp-link','data-uri':c.id,text:c.label});
    btn.addEventListener('click',()=>onNodeClick(c.id));
    panel.append(el('div',{class:'dp-row'},[btn,el('span',{text:c.weight+' ('+p+'%)'})]));
  }
  const rest=analysis.topChildren.length-shown.length;
  if(rest>0)panel.append(el('div',{class:'dp-row'},[el('span',{text:'+'+rest+' others'}),el('span',{})]));
}

// Depth/children/descendants counts + "Main children" — split out of
// renderDetail purely to keep its Cognitive Complexity down.
function appendDetailAnalysis(panel,data,pct){
  const analysis=computeAnalysis(data.id);
  panel.append(el('hr',{class:'dp-hr'}));
  panel.append(el('div',{class:'dp-sub',text:'Analysis'}));
  panel.append(detailRow('Depth',Math.max(data.depth,0)));
  panel.append(detailRow('Direct children',analysis.childCount));
  panel.append(detailRow('Total descendants',data.descendantCount));
  if(pct!==null&&pct!==undefined)panel.append(detailRow('Share of parent',pct+'%'));
  appendDetailMainChildren(panel,analysis);
}

function renderDetail(data,det,pct){
  const kind=data.depth===-1?'scheme':'concept';
  const panel=el('div',{class:'dp'});
  panel.append(el('span',{class:'dp-badge dp-'+kind,text:kind==='scheme'?'Scheme':'Concept'}));
  panel.append(el('div',{class:'dp-h3',text:data.label}));
  panel.append(el('div',{class:'dp-uri',text:data.id}));
  if(det)appendDetailExtras(panel,det);
  appendDetailAnalysis(panel,data,pct);
  panelEl.replaceChildren(panel);
}

render();
}catch(err){
  const el=document.createElement('div');
  el.style.cssText='position:fixed;inset:0;background:rgba(220,38,38,.95);color:white;padding:24px;font-family:monospace;font-size:13px;z-index:200;white-space:pre-wrap;overflow:auto';
  el.textContent='Taxonomy tree error — see browser console (F12):\n\n'+(err.stack||err);
  document.body.appendChild(el);
}
})();
