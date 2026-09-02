"""The map page ster serves at ``/map`` — a live view of a SPARQL result.

The page is deliberately ontology-neutral: it asks the server to run whatever
SPARQL is in its editor, then places any row that carries WGS84 coordinates.
Editing the query and re-running happens in the browser, against ``/mcp``'s
``run_sparql`` tool — same origin as this page, so no CORS, and the bearer
token is embedded here rather than travelling in the URL, exactly as the VOWL
graph viewer does.

Layout follows the clustering prototype: query panel under the header (open by
default, since editing it is the point), map centre, groups table right, and a
"cluster by" control built from whatever the result offers. Clicking a cluster
drills into it, with a breadcrumb back out.

Leaflet and the OpenStreetMap tiles come from a CDN, so the page needs a network
connection when opened. Kept in its own module so the HTML lives in one place,
the way :mod:`ster.html_export` isolates pyLODE.
"""

from __future__ import annotations

import html
import json

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ster — query map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
.legend { background: rgba(255,255,255,.92); border: 1px solid #ccc; border-radius: 4px;
          padding: 6px 8px; font: 11px system-ui, sans-serif; color: #111;
          max-height: 44vh; overflow-y: auto; }
.legend-item + .legend-item { margin-top: 8px; border-top: 1px solid #e3e3e3; padding-top: 6px; }
.legend-head { font-weight: 600; margin-bottom: 3px; max-width: 150px; }
.legend img { display: block; max-width: 100%; }
/* The outer tick labels are centred on the ends of the bar, so half of each
   sits past it; the margin is the room they need not to be clipped. */
.ramp { position: relative; display: flex; height: 116px; margin: 8px 0 9px; }
.ramp-bar { width: 13px; border: 1px solid #9aa0a6; border-radius: 2px; }
.ramp-ticks { position: relative; width: 34px; }
/* Each label is centred on its own value, so the numbers line up with the
   colours rather than with evenly spaced rows. */
.ramp-ticks span { position: absolute; left: 4px; transform: translateY(50%);
                   line-height: 1; white-space: nowrap; }
  :root { --ink:#16191d; --muted:#6b7280; --panel:#fff; --line:#e5e7eb; --accent:#1f5b80; }
  * { box-sizing:border-box; }
  html, body { margin:0; height:100%; }
  body { font:14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         color:var(--ink); display:flex; flex-direction:column; }
  header { padding:11px 20px; border-bottom:1px solid var(--line); background:var(--panel);
           display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  h1 { font-size:16px; margin:0; font-weight:600; }
  .sub { color:var(--muted); font-size:13px; }
  button { font:inherit; font-size:13px; padding:4px 12px; border:1px solid var(--line);
           background:#fff; border-radius:6px; cursor:pointer; color:var(--ink); }
  button:hover { background:#f6f7f8; }
  button.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
  .seg { display:flex; border:1px solid var(--line); border-radius:7px; overflow:hidden; }
  .seg button { border:0; border-left:1px solid var(--line); border-radius:0; color:var(--muted);
                padding:5px 13px; }
  .seg button:first-child { border-left:0; }
  .seg button.on { background:var(--accent); color:#fff; font-weight:500; }
  .crumbs { display:flex; align-items:center; gap:6px; font-size:13px; }
  .crumbs button { border:0; background:none; padding:2px 4px; color:var(--accent); }
  .crumbs button:hover { background:#eef4f8; }
  .crumbs button:last-child { color:var(--ink); font-weight:600; cursor:default; }
  .crumbs button:last-child:hover { background:none; }
  .crumbs .sep { color:var(--line); }
  .scale { margin-left:auto; display:flex; align-items:center; gap:8px; font-size:12px;
           color:var(--muted); }
  .sw { width:24px; height:12px; }
  /* Query panel: open by default — editing it is what this page is for. */
  #query-panel { background:#0f1419; border-bottom:1px solid #0b0f13; display:flex;
                 flex-direction:column; max-height:34vh; }
  #query-panel.closed { display:none; }
  #q { background:#0f1419; color:#d6e2ea; border:0; outline:none; resize:vertical;
       padding:13px 20px; min-height:112px; font:12.5px/1.55 ui-monospace, Menlo, monospace; }
  #query-bar { display:flex; align-items:center; gap:14px; padding:7px 20px 11px;
               border-top:1px solid #1b232b; }
  #msg { font-size:12.5px; color:#8fa3b0; }
  #msg.bad { color:#e08a8a; }
  main { flex:1; display:flex; min-height:0; }
  #map { flex:1; min-height:0; }
  .leaflet-interactive:focus { outline:none; }
  aside { width:320px; border-left:1px solid var(--line); overflow:auto; background:var(--panel); }
  /* Navigation lives across the top: where you are, what level that is, and the
     places you can open from here. A tree needs vertical room the map wants. */
  #nav { display:flex; align-items:center; flex-wrap:wrap; gap:6px 10px;
         padding:7px 14px; border-bottom:1px solid var(--line); background:#fafbfc;
         font-size:12px; }
  #nav:empty { display:none; }
  #nav .trail { display:flex; align-items:center; gap:4px; }
  #nav .lvl { font-size:10px; letter-spacing:.05em; text-transform:uppercase;
              color:#6b7bab; background:#eef2fa; border-radius:9px; padding:2px 9px;
              white-space:nowrap; }
  #nav .chips { display:flex; flex-wrap:wrap; gap:5px; }
  #nav .chip { border:1px solid var(--line); background:#fff; border-radius:13px;
               padding:2px 10px; cursor:pointer; font-size:12px; white-space:nowrap; }
  #nav .chip:hover { background:#eef4ff; border-color:#b9cdf3; }
  #nav .chip.current { background:#2563eb; border-color:#2563eb; color:#fff; }
  #nav .chip .n { color:#8a96a8; margin-left:5px; font-size:11px; }
  #nav .chip.current .n { color:#dbe7ff; }
  #nav .chip.leaf { cursor:default; opacity:.85; }
  #crumbs { font-size:12px; line-height:1.9; }
  #crumbs:empty { display:none; }
  #crumbs a { color:#2563eb; cursor:pointer; text-decoration:none; }
  #crumbs a:hover { text-decoration:underline; }
  #crumbs .sep { color:#9aa3ad; margin:0 5px; }
  #crumbs .here { font-weight:600; }
  .lv { color:#9aa3ad; font-size:11px; margin-left:6px; }
  /* Capped and scrollable: the panel's job is the place tree, and a node with an
     image and a dozen properties would otherwise push it off the screen. */
  #detail { border-bottom:1px solid var(--line); font-size:12px; }
  #detail .body { padding:0 12px 12px; }
  #detail.collapsed .body { display:none; }
  #detail .head { display:flex; align-items:baseline; gap:6px; cursor:pointer;
                  padding:10px 12px 6px; }
  #detail .head:hover { background:#f2f6ff; }
  #detail .caret { color:#9aa3ad; width:12px; }
  #detail img.shot { width:100%; border-radius:6px; display:block; margin:6px 0 2px;
                     background:#eef1f4; min-height:28px; }
  #detail video.shot { width:100%; border-radius:6px; display:block; margin:6px 0 2px; }
  #detail .broken { font-size:10px; color:#9aa3ad; font-style:italic; padding:8px;
                    border:1px dashed #ccd2d8; border-radius:6px; text-align:center; margin:6px 0; }
  #detail a { color:#2563eb; word-break:break-all; }
  /* Derived figures sit in their own tinted block with a rule above, so a total
     the map computed is never mistaken for something the file asserts. */
  #detail .derived { margin-top:12px; padding:8px 10px; border-radius:6px;
                     background:#f4f7fb; border:1px solid #e3e9f2; }
  #detail .derived .sub { margin-top:0; color:#6b7bab; }
  #detail .tot-head { font-size:10px; color:#8792a8; font-style:italic; margin:6px 0 2px; }
  #detail .derived .rel { border-bottom-color:#e6ebf3; }
  #detail:empty { display:none; }
  #detail h3 { margin:0; font-size:14px; }
  #detail .kind { color:#9aa3ad; font-size:11px; }
  #detail .uri { color:#9aa3ad; font-size:10px; word-break:break-all; margin-bottom:6px; }
  #detail .counts { margin:6px 0; }
  #detail .pill { display:inline-block; background:#eef4ff; color:#2563eb; border-radius:10px;
                  padding:1px 8px; margin:2px 4px 2px 0; font-size:11px; }
  #detail .rel { display:flex; gap:6px; padding:2px 0; border-bottom:1px solid #f1f3f5; }
  #detail .rel b { color:#6b7480; font-weight:500; min-width:88px; font-size:11px; }
  #detail .sub { color:#9aa3ad; font-size:10px; text-transform:uppercase;
                 letter-spacing:.04em; margin:8px 0 3px; }
  tr.row { cursor:pointer; }
  tr.row:hover { background:#eef4ff; }
  tr.row.current { background:#e6efff; font-weight:600; }
  .tw { display:inline-block; width:14px; color:#9aa3ad; }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th, td { text-align:left; padding:7px 12px; border-bottom:1px solid var(--line); }
  th { position:sticky; top:0; background:#fafbfc; font-weight:600; }
  td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
  tbody tr { cursor:pointer; }
  tbody tr:hover { background:#f2f7fa; }
  .hint { position:absolute; left:50%; transform:translateX(-50%); bottom:22px; z-index:500;
          background:rgba(22,25,29,.86); color:#fff; padding:7px 14px; border-radius:20px;
          font-size:13px; pointer-events:none; transition:opacity .3s; }
</style>
</head>
<body>
<header>
  <h1>Query map</h1>
  <span class="sub" id="sub">—</span>
  <span class="sub">Cluster by</span>
  <div class="seg" id="seg"></div>
  <div class="crumbs" id="crumbs"></div>
  <button id="toggle">Hide query</button>
  <div class="scale" id="scale"></div>
</header>
<section id="query-panel">
  <textarea id="q" spellcheck="false">__QUERY__</textarea>
  <div id="query-bar">
    <button class="primary" id="run">Run  (ctrl+⏎)</button>
    <span id="msg"></span>
  </div>
</section>
<nav id="nav"></nav>
<main>
  <div id="map"></div>
  <aside><div id="detail"></div><table id="table"></table></aside>
</main>
<div class="hint" id="hint"></div>

<script>
const TOKEN = __TOKEN__;
// RDF namespace IRI, not a URL this page fetches. NOSONAR
const WGS = "http://www.w3.org/2003/01/geo/wgs84_pos#";
/* Circle markers need a darker ramp than a polygon fill would: a pale wash
   reads fine over a large area but disappears on a small dot on the basemap. */
const RAMP = ["#9dc3d8", "#6fa9c4", "#3d81a6", "#265f85", "#12405c"];

const map = L.map('map', { scrollWheelZoom:true, minZoom:2 }).setView([48, 2], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom:18,
  attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

const fmt = new Intl.NumberFormat();
let layer = null, rows = [], columns = [], points = [], groupBy = null, scope = null;
/* ── Level of detail ────────────────────────────────────────────────────────
   When a result spans a place hierarchy — a continent, its areas, their
   countries, their cities — drawing every level at once is unreadable: the
   continent's outline swallows the countries and the dots sit on top of both.
   So one level is drawn at a time, and you descend by clicking a shape or by
   zooming in. `level` and `parent` come from the server, which reads them from
   the ontology, so nothing here knows what the levels are called. */
let level = 0;            // which level of the hierarchy is on screen
let focus = null;         // the URI drilled into, or null for "all of this level"
const levelsOf = ps => [...new Set(ps.map(p => p.level ?? 0))].sort((a, b) => a - b);
/* fitBounds moves the map itself, and that fires zoomend a tick later. Without
   this the map's own framing reads as the reader zooming, and the level handler
   undoes the drill it was just asked to perform. */
let selfMoveUntil = 0;
/* Containment, from the server's own walk of the graph. Not reconstructed from
   `parent` here: a grouping level that carries no geometry is never drawn, so
   the chain the client can see has holes exactly where one sits. */
const descendsFrom = (p, uri) => p.uri === uri || (p.ancestors || []).includes(uri);
/* The nearest level below *p* that anything is actually drawn at. A level whose
   places carry no geometry — a grouping tier, say — is skipped rather than
   drilled into, which would land on an empty map. */
function childLevel(p) {
  const below = points.filter(q => q !== p && (q.level ?? 0) > (p.level ?? 0)
                                   && descendsFrom(q, p.uri));
  return below.length ? Math.min(...below.map(q => q.level ?? 0)) : null;
}
const hasChildren = p => childLevel(p) !== null;
/* Levels can have gaps: a grouping tier carrying no geometry is never drawn, so
   the drill moves between the levels that exist rather than by ±1. Snapping to
   the nearest also stops a stale `level` selecting the deepest tier — which
   opened the map on individual stores instead of the continent. */
function snapLevel(wanted) {
  const available = levelsOf(points);
  if (!available.length) return 0;
  return available.reduce(
    (best, cur) => Math.abs(cur - wanted) < Math.abs(best - wanted) ? cur : best,
    available[0]);
}
/* The path down to what is on screen, and the way back up. Built from the
   focused place's own ancestor chain, keeping only the levels that are drawn: a
   grouping tier with no geometry cannot be navigated to, so offering it as a
   step would be a dead link. */
function crumbTrail() {
  if (focus === null) return [];
  const here = points.find(p => p.uri === focus);
  if (!here) return [];
  const up = (here.ancestors || [])
    .map(uri => points.find(p => p.uri === uri))
    .filter(Boolean)
    .reverse();
  return [...up, here];
}
function drawNav() {
  const el = document.getElementById('nav');
  if (!points.length) { el.innerHTML = ''; return; }
  const trail = crumbTrail();
  const shown = atLevel();
  const levelName = shown.length ? plain(shown[0].kind || '') : '';

  const crumbs = [`<a data-up="">All</a>`];
  trail.forEach((p, i) => {
    const last = i === trail.length - 1;
    crumbs.push(`<span class="sep">›</span>` + (last
      ? `<span class="here">${plain(p.label)}</span>`
      : `<a data-up="${i}">${plain(p.label)}</a>`));
  });

  /* The places you can open from here, as chips: the same navigation the map
     offers, for anyone who would rather read a name than find a shape. */
  const chips = shown
    .slice()
    .sort((a, b) => valueOf(b) - valueOf(a) || a.label.localeCompare(b.label))
    .map((p, i) => {
      const leaf = !hasChildren(p);
      return `<button class="chip${p.uri === focus ? ' current' : ''}${leaf ? ' leaf' : ''}"` +
             ` data-chip="${i}">${plain(p.label)}<span class="n">${fmt.format(valueOf(p))}</span></button>`;
    }).join('');

  el.innerHTML = `<span class="trail" id="crumbs">${crumbs.join('')}</span>` +
                 (levelName ? `<span class="lvl">${levelName}</span>` : '') +
                 `<span class="chips">${chips}</span>`;

  for (const a of el.querySelectorAll('#crumbs a')) {
    a.addEventListener('click', () => {
      const idx = a.dataset.up;
      if (idx === '') { level = levelsOf(points)[0] ?? 0; focus = null; draw(); return; }
      const target = trail[Number(idx)];
      const next = childLevel(target);
      level = next === null ? target.level : next;
      focus = target.uri;
      draw();
    });
  }
  const ordered = shown.slice().sort((a, b) => valueOf(b) - valueOf(a) || a.label.localeCompare(b.label));
  for (const btn of el.querySelectorAll('.chip')) {
    const p = ordered[Number(btn.dataset.chip)];
    btn.addEventListener('click', () => {
      const next = childLevel(p);
      if (next !== null) level = next;
      focus = p.uri;
      draw(next !== null);
    });
  }
}
/* What is on screen is a place in the ontology, so the panel shows what the
   ontology knows about it: its own relations, and how much sits beneath it.
   Detail comes from /api/node-detail — the same endpoint the graph view uses,
   rather than a second description of an entity. */
const _detailCache = new Map();
async function nodeDetail(uri) {
  if (_detailCache.has(uri)) return _detailCache.get(uri);
  let det = {};
  try {
    const r = await fetch('/api/node-detail?uri=' + encodeURIComponent(uri),
                          { headers: { 'Authorization': 'Bearer ' + TOKEN } });
    if (r.ok) det = await r.json();
  } catch (err) {
    console.debug('Detail fetch failed:', err);   // never block the panel on it
  }
  _detailCache.set(uri, det);
  return det;
}
/* Everything below *p*, counted per level, so "France" can say how many cities
   and how many stores it holds rather than one undifferentiated number. */
function countsBelow(p) {
  const below = points.filter(q => q !== p && descendsFrom(q, p.uri));
  const byKind = new Map();
  for (const q of below) {
    const key = q.kind || 'place';
    byKind.set(key, (byKind.get(key) || 0) + 1);
  }
  return { total: below.length, byKind: [...byKind.entries()] };
}
/* The layer menu: whatever the file declared, as checkboxes over the basemap.
   Nothing is enabled by default — an overlay the reader did not ask for would
   obscure the shapes the query is about. */
let overlayControl = null;
let legendControl = null;
const legendsOn = new Map();  // label → spec, for every overlay now shown
function addOverlayControl() {
  if (overlayControl) { map.removeControl(overlayControl); overlayControl = null; }
  legendsOn.clear();
  drawLegend();
  if (!overlayLayers.length) return;
  const overlays = {};
  for (const spec of overlayLayers) {
    const safe = safeUrl(String(spec.url).replace(/{[a-z]}/gi, '0'));  // vet before use
    if (!safe) continue;
    const common = {
      opacity: typeof spec.opacity === 'number' ? spec.opacity : 1,
      attribution: spec.attribution || '',
      /* Under the query's own shapes: context belongs behind the answer. */
      pane: 'tilePane',
    };
    /* WMS is a different request shape, not a different URL template — the
       endpoint is a plain URL and the layer names travel as parameters. Most
       public geodata publishes this way rather than as {z}/{x}/{y} tiles. */
    overlays[spec.label] = spec.kind === 'wms'
      ? L.tileLayer.wms(spec.url, Object.assign({
          layers: spec.wmsLayers,
          format: spec.wmsFormat || 'image/png',
          transparent: spec.wmsTransparent !== false,
        }, common))
      : L.tileLayer(spec.url, common);
  }
  if (!Object.keys(overlays).length) return;
  overlayControl = L.control.layers(null, overlays, { collapsed: true }).addTo(map);
}

/* A colour ramp nobody can read is decoration. WMS servers publish the scale
   through GetLegendGraphic, so a layer that paints the map in meaningful colours
   can say what they mean; the legend appears with the layer and leaves with it. */
function drawLegend() {
  if (legendControl) { map.removeControl(legendControl); legendControl = null; }
  if (!legendsOn.size) return;
  legendControl = L.control({ position: 'topleft' });
  legendControl.onAdd = () => {
    const box = L.DomUtil.create('div', 'legend');
    for (const [label, spec] of legendsOn) {
      const item = L.DomUtil.create('div', 'legend-item', box);
      L.DomUtil.create('div', 'legend-head', item).textContent = label;
      if (spec.legendScale?.length > 1) rampBar(item, spec);
      else legendImage(item, label, spec.legendUrl);
    }
    L.DomEvent.disableClickPropagation(box);
    return box;
  };
  legendControl.addTo(map);
}

/* The server's own legend lists every bucket its style defines — for a
   temperature field that is a strip taller than the map is useful. A stated
   ramp says the same thing as a gradient with a few labelled ticks. */
function rampBar(item, spec) {
  const stops = spec.legendScale;
  const lo = stops[0].value, hi = stops[stops.length - 1].value;
  const at = v => hi === lo ? 0 : (v - lo) / (hi - lo) * 100;
  const wrap = L.DomUtil.create('div', 'ramp', item);
  const bar = L.DomUtil.create('div', 'ramp-bar', wrap);
  /* Bottom-up: the cold end belongs at the bottom, as on any thermometer. */
  bar.style.backgroundImage = 'linear-gradient(to top,' +
    stops.map(s => s.color + ' ' + at(s.value).toFixed(1) + '%').join(',') + ')';
  const ticks = L.DomUtil.create('div', 'ramp-ticks', wrap);
  for (const s of stops) {
    const tick = L.DomUtil.create('span', '', ticks);
    tick.textContent = s.value + (spec.legendUnit || '');
    tick.style.bottom = at(s.value) + '%';
  }
}

function legendImage(item, label, url) {
  const img = L.DomUtil.create('img', '', item);
  img.src = url;
  img.alt = label + ' scale';
  /* A legend that fails to load should vanish, not leave a broken icon. */
  img.addEventListener('error', () => item.remove());
}

function trackLegend(name, on) {
  const spec = overlayLayers.find(x => x.label === name);
  if (!spec) return;
  const drawable = (spec.legendScale || []).length > 1 || safeUrl(spec.legendUrl || '');
  if (!drawable) return;
  if (on) legendsOn.set(name, Object.assign({}, spec, { legendUrl: safeUrl(spec.legendUrl || '') }));
  else legendsOn.delete(name);
  drawLegend();
}

/* Only http(s) reaches an href or a src. These values come from the loaded file,
   so a `javascript:` URL in a schema:url would otherwise be a script the reader
   runs by clicking. */
function safeUrl(raw) {
  try {
    const u = new URL(String(raw), location.href);
    if (u.protocol === 'http:' || u.protocol === 'https:') return u.href;
  } catch { /* not a URL */ }
  return '';
}
function extLink(url, text) {
  const safe = safeUrl(url);
  return safe
    ? `<a href="${plain(safe)}" target="_blank" rel="noopener noreferrer">${plain(text)}</a>`
    : plain(text);
}
/* Free text often mentions a URL; split and escape every piece so linkifying
   never widens what markup can get through. */
function linkify(text) {
  return String(text).split(/(https?:\\/\\/[^\\s<>"']+)/g)
    .map((part, i) => i % 2 ? extLink(part, part) : plain(part)).join('');
}
function mediaHtml(det) {
  let h = '';
  for (const src of det.images || []) {
    const safe = safeUrl(src);
    if (safe) h += `<img class="shot" src="${plain(safe)}" alt="" decoding="async" referrerpolicy="no-referrer">`;
  }
  for (const src of det.videos || []) {
    const safe = safeUrl(src);
    if (safe) h += `<video class="shot" src="${plain(safe)}" controls preload="metadata" referrerpolicy="no-referrer"></video>`;
  }
  return h;
}
/* A dead off-site image leaves a collapsed box that reads as "no picture here". */
function wireMedia(el) {
  for (const img of el.querySelectorAll('img.shot')) {
    const fail = () => {
      if (!img.parentNode) return;
      const note = document.createElement('div');
      note.className = 'broken';
      note.textContent = 'image unavailable';
      img.replaceWith(note);
    };
    if (img.complete && img.naturalWidth === 0) fail();
    else img.addEventListener('error', fail, { once: true });
  }
}
function detailBody(here, counts, det) {
  /* Geometry is what the map is already drawing: a coordinate pair repeats it,
     and a WKT polygon would fill the box with a hundred numbers nobody reads. */
  const GEOM_DATATYPES = /wktLiteral|geoJSONLiteral|gmlLiteral|kmlLiteral/;
  const COORD_PROPS = ['lat', 'long', 'lng', 'latitude', 'longitude', 'aswkt', 'asgeojson'];
  const literals = (det.literals || [])
    .filter(l => !COORD_PROPS.includes(l.prop.toLowerCase().replace(/\\s+/g, ''))
                 && !GEOM_DATATYPES.test(l.kind || ''))
    .map(l => `<div class="rel"><b>${plain(l.prop)}</b><span>${plain(l.value)}</span></div>`).join('');
  const comments = (det.comments || []).map(c => `<div>${linkify(c.value)}</div>`).join('');
  const links = (det.urls || []).map(u => `<div>${extLink(u, u)}</div>`).join('');
  const rels = (det.relations || []).map(r =>
    `<div class="rel"><b>${plain(r.rel)}</b><span>${plain(r.label || r.uri)}</span></div>`).join('');
  /* Two kinds of fact, kept apart: what the ontology says about this entity, and
     what the map worked out by adding up the entities under it. Reading a derived
     total as a stated one would be a real misunderstanding, so they do not share
     a section. */
  const stated =
    mediaHtml(det) +
    (det.description ? `<div class="sub">definition</div><div>${linkify(det.description)}</div>` : '') +
    (comments ? `<div class="sub">comment</div>${comments}` : '') +
    (literals ? `<div class="sub">properties</div>${literals}` : '') +
    (links ? `<div class="sub">links</div>${links}` : '') +
    (rels ? `<div class="sub">relations</div>${rels}` : '');

  const below = figuresBelow(here);
  const derived = (counts.total || below.rows.length)
    ? `<section class="derived">` +
      `<div class="sub">calculated — not stated in the ontology</div>` +
      (counts.total
        ? `<div class="counts">` +
          counts.byKind.map(([k, n]) => `<span class="pill">${n} ${plain(k)}</span>`).join('') +
          `</div>`
        : '') +
      (below.rows.length
        ? `<div class="tot-head">summed over ${below.contributors} individual` +
          `${below.contributors === 1 ? '' : 's'} below</div>` +
          below.rows.map(([label, total]) =>
            `<div class="rel"><b>${plain(label)}</b><span>${fmt.format(total)}</span></div>`).join('')
        : '') +
      `</section>`
    : '';

  return `<div class="uri">${plain(here.uri)}</div>` + stated + derived;
}
let detailOpen = true;
/* Every numeric property of everything under *p*, and of p itself, added up.
   No triple says what a country turns over — it is the sum of its stores, and
   the level you have open decides which stores those are. */
function figuresBelow(p) {
  const totals = new Map();
  let contributors = 0;
  for (const q of points) {
    /* Strictly below: a place's own numbers are something the file states, and
       they are shown as such. Adding them in here would have labelled a store's
       own turnover a "total", which is a different claim. */
    if (q === p || !descendsFrom(q, p.uri)) continue;
    let counted = false;
    for (const f of q.figures || []) {
      totals.set(f.label, (totals.get(f.label) || 0) + (Number(f.value) || 0));
      counted = true;
    }
    if (counted) contributors += 1;
  }
  return { rows: [...totals.entries()], contributors };
}
async function drawDetail() {
  const el = document.getElementById('detail');
  if (focus === null) { el.innerHTML = ''; return; }
  const here = points.find(p => p.uri === focus);
  if (!here) { el.innerHTML = ''; return; }
  const counts = countsBelow(here);
  const head = () =>
    `<div class="head"><span class="caret">${detailOpen ? '▾' : '▸'}</span>` +
    `<h3>${plain(here.label)}</h3><span class="kind">${plain(here.kind || '')}</span></div>`;
  const paint = (bodyHtml) => {
    el.className = detailOpen ? '' : 'collapsed';
    el.innerHTML = head() + `<div class="body">${bodyHtml}</div>`;
    el.querySelector('.head').addEventListener('click', () => {
      detailOpen = !detailOpen;
      paint(bodyHtml);
    });
    wireMedia(el);
  };
  paint(`<div class="uri">${plain(here.uri)}</div><div class="sub">loading…</div>`);
  const det = await nodeDetail(focus);
  if (focus !== here.uri) return;              // drilled on while fetching
  paint(detailBody(here, counts, det));
}
/* The panel keeps the whole path open rather than replacing itself each time
   you descend: ancestors and their siblings stay on screen, so stepping back out
   is one click on something already visible instead of a re-run of the query.
   Only the branch you are in expands — the rest stay closed, or the deepest
   level would flood the panel. */
function treeRows() {
  const openPath = crumbTrail().map(p => p.uri);
  const available = levelsOf(points);
  if (!available.length) return [];
  const rows = [];
  const walk = (list, depth) => {
    for (const p of list.sort((a, b) => valueOf(b) - valueOf(a) || a.label.localeCompare(b.label))) {
      const open = openPath.includes(p.uri);
      rows.push({ place: p, depth, open, current: p.uri === focus });
      if (!open) continue;
      const below = childLevel(p);
      if (below !== null) {
        walk(points.filter(q => (q.level ?? 0) === below && descendsFrom(q, p.uri)), depth + 1);
      }
    }
  };
  walk(points.filter(p => (p.level ?? 0) === available[0]), 0);
  return rows;
}
function drawTree(groups, grouped, lo, hi) {
  /* The hierarchy moved to the top bar; the aside is for what the selected place
     *is*. The one exception is the cluster view: grouping by something other than
     place has no hierarchy to navigate, so it keeps its flat table. */
  const table = document.getElementById('table');
  if (!grouped) { table.innerHTML = ''; return; }
  const flat = [...groups.entries()]
    .map(([k, m]) => [short(k), m.reduce((a, p) => a + valueOf(p), 0)])
    .sort((a, b) => b[1] - a[1]);
  table.innerHTML =
    `<thead><tr><th>group</th><th class="num">${MEASURE_NAME()}</th></tr></thead><tbody>` +
    flat.map(([n, t]) => `<tr><td>${n}</td><td class="num">${fmt.format(t)}</td></tr>`).join('') +
    '</tbody>';
}
/* The rows to draw: the active level, narrowed to the focused branch. */
function atLevel() {
  if (!points.length) return points;
  const target = snapLevel(level);
  return points.filter(p => (p.level ?? 0) === target
                            && (focus === null || descendsFrom(p, focus)));
}
/* Outlines when there are few enough to read; dots otherwise. The cost and the
   clutter scale with how many are drawn, not with the zoom — zoom 7 alone hid
   every country in the demo, because a country is legible long before that. */
const SHAPE_LIMIT = 40;
const SHAPE_ZOOM = 7;
let shapeMode = false;
const wantsShapes = () => {
  const withShapes = atLevel().filter(p => p.shape).length;
  if (!withShapes) return false;
  return withShapes <= SHAPE_LIMIT || map.getZoom() >= SHAPE_ZOOM;
};
/* Registered after the state it reads, not before: the callback would not hit
   the temporal dead zone either way, but declaring-then-using is the order that
   stays correct when someone later moves code around. */
/* Zoom does not change the level. It used to, and it fought the click every
   time: fitting the map to what you just opened fires zoomend, which read as
   you zooming and moved the level again — clicking Europe could land on a city
   in Poland. Levels are chosen by clicking; zoom only decides whether an outline
   is legible enough to draw. */
map.on('zoomend', () => { if (wantsShapes() !== shapeMode) draw(false); });
map.on('overlayadd', e => trackLegend(e.name, true));
map.on('overlayremove', e => trackLegend(e.name, false));
let measureCol = null;  // index of the result column to sum, when it has one

/* The first column that is numeric throughout and is not a coordinate — the
   same "first numeric column wins" rule the static renderers use. */
function findMeasure(cols, data) {
  const skip = ['lat','latitude','long','lon','lng','longitude'];
  for (let i = 0; i < cols.length; i++) {
    if (skip.includes(cols[i].toLowerCase())) continue;
    const values = data.map(r => r[i]).filter(v => v !== '' && v !== undefined);
    if (values.length && values.every(v => num(v) !== null)) return i;
  }
  return null;
}

/* A place's own contribution: nothing for one that is only there to group. */
const ownValue = p => p.row === null ? 0
  : (measureCol === null ? 1 : (num(rows[p.row][measureCol]) ?? 0));
/* What a place is worth on the map: itself plus everything under it. That is
   what makes a country meaningful when the query returned stores — it shows how
   many it holds — and it is why a place with nothing beneath it and no row of
   its own never reaches the map at all. */
const valueOf = p => points.reduce(
  (total, q) => total + ((q === p || descendsFrom(q, p.uri)) ? ownValue(q) : 0), 0);

/* Re-running goes through the server's own read-only SPARQL tool, so the page
   never needs its own query engine and cannot mutate the ontology. */
async function runQuery(sparql) {
  const response = await fetch('/mcp', {
    method: 'POST',
    headers: { 'Content-Type':'application/json', 'Authorization': 'Bearer ' + TOKEN },
    body: JSON.stringify({
      jsonrpc:'2.0', id:1, method:'tools/call',
      params:{ name:'run_sparql', arguments:{ query: sparql } }
    })
  });
  const payload = await response.json();
  if (payload.error) throw new Error(payload.error.message || 'query failed');
  const parsed = JSON.parse(payload.result.content[0].text);
  if (parsed.error) throw new Error(parsed.error);
  return parsed;
}

const isUri = v => typeof v === 'string' && /^(https?:|urn:)/.test(v);
const num = v => { const n = Number(v); return Number.isFinite(n) ? n : null; };
const short = v => String(v).split(/[#/]/).filter(Boolean).pop();
/* SPARQL results stringify a literal with its language tag ("Brest"@fr); the
   tag is machinery, not part of the name the reader wants to see. */
const plain = v => String(v).replace(/@[a-zA-Z]{2,3}(-[a-zA-Z0-9]+)*$/, '');
const MEASURE_NAME = () => measureCol === null ? 'rows' : columns[measureCol];

/* Coordinates come from bare lat/long columns, else by asking the graph about a
   URI in the row. Only WGS84 — nothing here knows what the data is about. */
async function locate(cols, data) {
  const li = cols.findIndex(c => ['lat','latitude'].includes(c.toLowerCase()));
  const gi = cols.findIndex(c => ['long','lon','lng','longitude'].includes(c.toLowerCase()));
  if (li >= 0 && gi >= 0) {
    return data.map((r, i) => {
      /* Keep the row's URI: it names the point when no plain label is present,
         and lets the cluster control exclude the column that located it. */
      const uri = r.find(isUri) || null;
      const named = r.find((c, j) => j !== li && j !== gi && c && !isUri(c));
      return { row:i, lat:num(r[li]), long:num(r[gi]),
               label: named ? plain(named) : (uri ? short(uri) : `row ${i + 1}`), uri };
    }).filter(p => p.lat !== null && p.long !== null);
  }
  const uris = [...new Set(data.flat().filter(isUri))];
  if (!uris.length) return [];
  /* Ask the server, rather than querying for wgs:lat/long here: it resolves the
     whole geometry ladder — GeoSPARQL shapes included — with one implementation
     of WKT parsing. Doing it in this file meant every polygon came back
     unmappable however well the Python layer understood it. */
  const placed = await locateOnServer(uris);
  const by = new Map(placed.map(p => [p.uri, p]));
  const out = [];
  const used = new Set();
  data.forEach((r, i) => {
    const hit = r.find(c => by.has(c));
    if (hit) {
      const found = by.get(hit);
      const named = r.find(c => !isUri(c));
      used.add(hit);
      /* Carry level/parent/kind through: the drill-down reads them, and dropping
         them here left every level drawn at once with no error to show for it. */
      out.push({ row:i, lat:found.lat, long:found.long, uri:hit, shape:found.shape,
                 level:found.level ?? 0, parent:found.parent ?? null, kind:found.kind || '',
                 ancestors:found.ancestors || [], result:true, figures:found.figures || [],
                 label: named ? plain(named) : (found.label || short(hit)) });
    }
  });
  /* The places that contain the results, so a query for stores can be grouped by
     city and country. They are context, not rows: they carry no measure, and a
     city holding no result is never among them. */
  for (const p of placed) {
    if (used.has(p.uri) || p.result) continue;
    out.push({ row:null, lat:p.lat, long:p.long, uri:p.uri, shape:p.shape,
               level:p.level ?? 0, parent:p.parent ?? null, kind:p.kind || '',
               ancestors:p.ancestors || [], result:false, figures:p.figures || [],
               label:p.label || short(p.uri) });
  }
  return out;
}

let overlayLayers = [];      // declared by the file, offered in the layer menu
async function locateOnServer(uris) {
  const response = await fetch('/api/locate', {
    method: 'POST',
    headers: { 'Content-Type':'application/json', 'Authorization': 'Bearer ' + TOKEN },
    body: JSON.stringify({ uris })
  });
  if (!response.ok) return [];
  const body = await response.json();
  overlayLayers = body.layers || [];
  return body.places || [];
}

const inScope = p => scope === null || rows[p.row][groupBy] === scope;
const ramp = (v, lo, hi) => hi === lo ? RAMP[RAMP.length-1]
  : RAMP[Math.min(RAMP.length-1, Math.floor((v - lo) / (hi - lo) * RAMP.length))];

function draw(fit = true) {
  if (layer) map.removeLayer(layer);
  shapeMode = wantsShapes();
  const visible = atLevel().filter(inScope);
  /* Ungrouped, or drilled into one group: every row is its own marker. */
  const grouped = groupBy !== null && scope === null;
  const groups = new Map();
  for (const p of visible) {
    /* Keyed by URI, not row index: a place pulled in to group the results has no
       row of its own, and keying on that collapsed every one of them into a
       single "null" group — five countries drawn as one dot. */
    const key = grouped ? (rows[p.row][groupBy] || '—') : (p.uri || 'row:' + p.row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(p);
  }
  const sizes = [...groups.values()].map(m => m.reduce((a, p) => a + valueOf(p), 0));
  const lo = Math.min(...sizes, 1), hi = Math.max(...sizes, 1);

  const marks = [...groups.entries()].map(([key, members]) => {
    const lat = members.reduce((a, p) => a + p.lat, 0) / members.length;
    const long = members.reduce((a, p) => a + p.long, 0) / members.length;
    const name = grouped ? short(key) : members[0].label;
    const total = members.reduce((a, p) => a + valueOf(p), 0);
    const mark = L.circleMarker([lat, long], {
      radius: 6 + Math.sqrt(total) * 4, color:'#fff', weight:2,
      fillColor: ramp(total, lo, hi), fillOpacity:0.92
    }).bindTooltip(`<b>${name}</b><br>${MEASURE_NAME()} ${fmt.format(total)}` +
                   (grouped ? '<br><i>click to open</i>' : ''), { direction:'top' });
    if (grouped) mark.on('click', () => { scope = key; render(); });
    const only = members.length === 1 ? members[0] : null;
    /* Clicking a place descends into it: the next level down, narrowed to that
       branch. Nothing else on the map changes, so the move reads as "open this". */
    /* Descend when the place holds something; otherwise just select it, so a
       leaf — a store — still answers "what is this?" in the panel. */
    const drill = () => {
      if (!only) return;
      const next = childLevel(only);
      if (next !== null) level = next;
      focus = only.uri;
      draw(next !== null);
    };
    if (!grouped && only) mark.on('click', drill);
    /* One row, its own geometry, and few enough to read: draw the shape and keep
       the marker's tooltip and colour so both modes look like one map. */
    if (!grouped && shapeMode && only && only.shape) {
      const layer = L.geoJSON(only.shape, {
        style: { color:'#fff', weight:2, fillColor: ramp(total, lo, hi), fillOpacity:0.72 }
      }).bindTooltip(`<b>${name}</b>` + (only.kind ? ` <i>${plain(only.kind)}</i>` : '') +
                     `<br>${MEASURE_NAME()} ${fmt.format(total)}` +
                     (hasChildren(only) ? '<br><i>click to open</i>' : ''),
                     { direction:'top', sticky:true });
      if (hasChildren(only)) layer.on('click', drill);
      return layer;
    }
    return mark;
  });
  layer = L.featureGroup(marks).addTo(map);
  /* Only on a real redraw: refitting from the zoom handler would move the map
     the reader just moved, and re-fire the handler. */
  if (fit) {
    /* Frame what was opened, not what is inside it: clicking Spain should show
       Spain with its cities on top, rather than zooming to the handful of points
       and losing the country. A place with no outline of its own — a city — has
       nothing to frame but its contents, so it falls back to those. */
    const here = focus === null ? null : points.find(p => p.uri === focus);
    let bounds = null;
    if (here && here.shape) {
      try { bounds = L.geoJSON(here.shape).getBounds(); } catch { bounds = null; }
    }
    if (!bounds || !bounds.isValid()) bounds = layer.getBounds();
    if (bounds && bounds.isValid()) {
      selfMoveUntil = Date.now() + 600;
      map.fitBounds(bounds, { padding:[40,40], maxZoom:14 });
    }
  }

  drawNav();
  drawDetail();
  drawTree(groups, grouped, lo, hi);
  document.getElementById('scale').innerHTML = grouped
    ? `<span>${lo}</span>` + RAMP.map(c => `<span class="sw" style="background:${c}"></span>`).join('') +
      `<span>${hi}</span>` : '';
  const hint = document.getElementById('hint');
  hint.textContent = grouped ? 'Click a cluster to open it' : '';
  hint.style.opacity = grouped ? 1 : 0;
}

function renderCrumbs() {
  const el = document.getElementById('crumbs');
  if (groupBy === null || scope === null) { el.innerHTML = ''; return; }
  el.innerHTML = `<button data-all="1">All</button><span class="sep">›</span>` +
                 `<button>${short(scope)}</button>`;
  el.querySelector('[data-all]').addEventListener('click', () => { scope = null; render(); });
}

function render() { renderCrumbs(); draw(); }

/* Clusterings are whatever the result offers: any URI-valued column that is not
   the one supplying the coordinates. */
function clusterControls() {
  const located = new Set(points.map(p => p.uri));
  const options = [{ i:null, name:'Point' }];
  columns.forEach((c, i) => {
    const values = rows.map(r => r[i]).filter(isUri);
    if (values.length && !values.some(v => located.has(v))) options.push({ i, name:c });
  });
  const seg = document.getElementById('seg');
  seg.innerHTML = options.map(o => `<button>${o.name}</button>`).join('');
  [...seg.children].forEach((b, n) => b.addEventListener('click', () => {
    groupBy = options[n].i; scope = null;
    [...seg.children].forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    render();
  }));
  if (seg.firstChild) seg.firstChild.classList.add('on');
}

async function run() {
  const msg = document.getElementById('msg');
  msg.className = ''; msg.textContent = 'running…';
  try {
    const result = await runQuery(document.getElementById('q').value);
    columns = result.columns || [];
    rows = result.rows || [];
    groupBy = null; scope = null;
    measureCol = findMeasure(columns, rows);
    points = await locate(columns, rows);
    /* Open on the broadest level the result offers — one continent outline, not
       every country and city piled on top of it. */
    addOverlayControl();
    level = levelsOf(points)[0] ?? 0;
    focus = null;
      document.getElementById('sub').textContent =
      `${rows.length} row(s) · ${points.length} mappable`;
    clusterControls();
    render();
    msg.textContent = points.length ? '' : 'no row in this result carries WGS84 coordinates';
  } catch (err) {
    msg.className = 'bad'; msg.textContent = String(err.message || err);
  }
}

document.getElementById('run').addEventListener('click', run);
document.getElementById('q').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); }
});
document.getElementById('toggle').addEventListener('click', e => {
  const panel = document.getElementById('query-panel');
  panel.classList.toggle('closed');
  e.target.textContent = panel.classList.contains('closed') ? 'Show query' : 'Hide query';
});
run();
</script>
</body>
</html>
"""


def render_map_html(query: str, token: str) -> str:
    """The ``/map`` page, primed with *query* and able to re-run it via *token*."""
    return _PAGE.replace("__QUERY__", _escape(query)).replace("__TOKEN__", json.dumps(token))


def _escape(text: str) -> str:
    """Escape a query for embedding in the page.

    The query arrives from ``/map?q=`` and so is untrusted. Escaping quotes as
    well as angle brackets is not needed by the current <textarea> — its content
    can only be closed by ``</textarea``, and ``<`` is already escaped — but the
    placeholder moving into an attribute later would silently turn this into a
    real injection. Using the stdlib escaper also lets static analysis recognise
    the sanitiser instead of reporting a reflected-XSS alert on every build.
    """
    return html.escape(text, quote=True)
