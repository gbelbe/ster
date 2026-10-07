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

from .branding import FAVICON_LINK_TAG
from .viz_shared import embed_style

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ster — query map</title>
__FAVICON__
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
#facets { display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center;
           padding:6px 12px; border-bottom:1px solid var(--line); background:var(--panel); }
#facets:empty { display:none; border:0; padding:0; }
#facets.folded { display:none; }
.facet { display:flex; align-items:center; gap:6px; }
.facet > .name { color:var(--muted); font-size:11px; text-transform:uppercase;
                 letter-spacing:.04em; margin-right:2px; }
.fval { display:inline-flex; align-items:center; gap:5px; padding:2px 8px; cursor:pointer;
        border:1px solid var(--line); border-radius:999px; background:transparent;
        font:inherit; font-size:12px; color:var(--ink); }
.fval:hover { border-color:var(--accent); }
.fval.on { background:var(--accent); border-color:var(--accent); color:#fff; }
.fclear { border:0; background:none; color:var(--muted); cursor:pointer;
          font:inherit; font-size:11px; text-decoration:underline; }
/* Operator marks laid on a shape. Offsets are in screen pixels, not degrees,
   so several on one country stay side by side at every zoom instead of piling
   onto the same point as you zoom out. */
/* The attribute has to beat the class: a UA's [hidden]{display:none} loses to
   any rule that sets display, so .seg stayed laid out while "hidden". */
[hidden] { display:none !important; }
/* The number a place stands for, printed on it. The span is centred on its point; a dark pill keeps
   it readable on a pale shape and on a dark one alike. */
.figure-label { pointer-events:none; }
.figure-label span { position:absolute; transform:translate(-50%,-50%); white-space:nowrap;
                     font:700 13px system-ui,sans-serif; color:#fff; background:rgba(0,0,0,.62);
                     border-radius:9px; padding:1px 7px; box-shadow:0 1px 3px rgba(0,0,0,.4); }
.badge-row { display:flex; flex-wrap:wrap; gap:3px; align-items:center;
             justify-content:center; pointer-events:none; }
.badge-row img { object-fit:contain; background:#fff; border:1px solid rgba(0,0,0,.25);
                 border-radius:3px; padding:1px; box-shadow:0 1px 3px rgba(0,0,0,.3); }
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
  /* Building a map of a thousand places takes about a second, and a blank grey
     panel for a second reads as broken. This says which of the two waits you
     are in — the query, or placing what it returned — so the pause is legible
     rather than merely absent. */
  #loading { position:absolute; inset:0; z-index:700; display:none;
             align-items:center; justify-content:center; flex-direction:column; gap:14px;
             background:rgba(255,255,255,.82); color:#3c4a52; font-size:13.5px; }
  #loading.on { display:flex; }
  #loading .spin { width:26px; height:26px; border:2.5px solid #d8e0e4;
                   border-top-color:#3c6ebf; border-radius:50%;
                   animation:spin .8s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) {
    #loading .spin { animation:none; border-top-color:#3c6ebf; }
  }
  .hint { position:absolute; left:50%; transform:translateX(-50%); bottom:22px; z-index:500;
          background:rgba(22,25,29,.86); color:#fff; padding:7px 14px; border-radius:20px;
          font-size:13px; pointer-events:none; transition:opacity .3s; }
</style>
__EMBED__
</head>
<body>
<header>
  <h1>Query map</h1>
  <span class="sub" id="sub">—</span>
  <span class="sub">Show</span>
  <div class="seg" id="mode"><button>Levels</button><button>Everything</button></div>
  <span class="sub" id="seg-label">Cluster by</span>
  <div class="seg" id="seg"></div>
  <button id="fold">Hide filters</button>
  <div class="crumbs" id="crumbs"></div>
  <button id="toggle">Show query</button>
  <div class="scale" id="scale"></div>
</header>
<section id="query-panel" class="closed">
  <textarea id="q" spellcheck="false">__QUERY__</textarea>
  <div id="query-bar">
    <button class="primary" id="run">Run  (ctrl+⏎)</button>
    <span id="msg"></span>
  </div>
</section>
<div id="facets"></div>
<nav id="nav"></nav>
<main>
  <div id="map"><div id="loading"><div class="spin"></div><span id="loading-text"></span></div></div>
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
let showAll = __SHOW_ALL__;  // draw every result beneath the focus, not one tier
/* What the panel describes, which is not always what the map is filtered to. A
   leaf — a store, or any place in a file with no hierarchy at all — can be
   selected without being drilled into: filtering the map by it would hide its
   siblings and leave one dot with no way back. */
let selected = null;
const levelsOf = ps => [...new Set(ps.map(p => p.level ?? 0))].sort((a, b) => a - b);
/* Where the map starts being a map. Opening on the broadest level meant opening
   on one continent: a single shape filling the screen, answering nothing you
   could not have been told in a sentence. The first level holding two things is
   where comparison begins, so that is where it opens.

   Counted over drawable places only — a level of three cities none of which
   carries coordinates draws nothing, and opening there would show a blank map.
   Falls back to the broadest *drawable* level when no level has two, since one
   shape still beats none — falling back over every level, drawable or not,
   could land on a grouping tier with no geometry of its own (a commune, say)
   and draw nothing at all, silently sitting at the map's hardcoded default
   view instead. */
function openingLevel(pts) {
  const drawable = pts.filter(p => p.lat !== null && p.long !== null);
  for (const lvl of levelsOf(drawable)) {
    if (drawable.filter(p => (p.level ?? 0) === lvl).length >= 2) return lvl;
  }
  return levelsOf(drawable)[0] ?? levelsOf(pts)[0] ?? 0;
}
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
/* Every place at the same level, under the same parent, as the one in focus —
   the places you could step sideways to. Empty at the top, where there is no
   focus and nothing to step beside. */
function siblingsOfFocus() {
  if (focus === null) return [];
  const here = points.find(p => p.uri === focus);
  if (!here) return [];
  return points.filter(p => (p.level ?? 0) === (here.level ?? 0)
                            && (p.parent ?? null) === (here.parent ?? null));
}
/* The filter strip. Rebuilt on every draw, because which facets discriminate
   depends on where you are: drill into one country and the values that do not
   trade there disappear, and a facet left with a single value disappears with
   them. A logo is shown beside the name when the ontology offers one. */
/* Whoever operates in a place, drawn on its shape. One marker holds the whole
   row, so the browser lays the logos out side by side and they cannot overlap
   however far out you zoom — the alternative, a marker each nudged by a few
   degrees, collides the moment the scale changes. */
let badgeLayer = null;
let badgeVisible = [];

/* Kept within a narrow band so a mark on Cyprus and a mark on Ukraine read as
   the same kind of thing. Below the floor they are unrecognisable; above the
   ceiling they start to cover the country they sit on. */
const FIGURE_LIFT = 36;  // px above the centre of a shape, clear of its two rows of logos
const PIN = 18;          // a store icon, big enough to read at street zoom
const BADGE_MIN = 11;
const BADGE_MAX = 22;
const BADGE_GAP = 3;
const BADGE_PER_ROW_MAX = 4;   // beyond this a single row starves each mark

/* How many rows the marks are laid out on. Two at most: a third is thinner
   than the shape it sits on at any zoom worth reading, and the marks stop
   saying which brand. Splitting is what buys the size back — eight logos in one
   row across France are 8px each and unreadable; in two rows they are 17px. */
const BADGE_ROWS_MAX = 2;

function badgeRows(count) {
  return count > BADGE_PER_ROW_MAX ? BADGE_ROWS_MAX : 1;
}

function badgeSize(shape, count) {
  /* Measure the shape as it is on screen, not in degrees: a country's pixel
     width is what decides whether three logos fit inside it, and that changes
     with every zoom. */
  try {
    const b = L.geoJSON(shape).getBounds();
    if (!b.isValid()) return 0;
    const nw = map.latLngToContainerPoint(b.getNorthWest());
    const se = map.latLngToContainerPoint(b.getSouthEast());
    const wide = Math.abs(se.x - nw.x), tall = Math.abs(se.y - nw.y);
    /* Per row, not per logo: the marks share the width between the ones on
       their own line, and share the height between the lines. */
    const rows = badgeRows(count);
    const perRow = Math.ceil(count / rows);
    const perLogo = (wide * 0.8 - BADGE_GAP * (perRow - 1)) / perRow;
    const size = Math.floor(Math.min(perLogo, (tall * 0.6 - BADGE_GAP * (rows - 1)) / rows));
    return size < BADGE_MIN ? 0 : Math.min(size, BADGE_MAX);   // 0: no room at all
  } catch { return 0; }
}

function addBadges(visible) {
  badgeVisible = visible;
  if (badgeLayer) { map.removeLayer(badgeLayer); badgeLayer = null; }
  const rows = visible
    .filter(p => p.shape && (p.badges || []).length && p.lat !== null)
    .map(p => {
      const imgs = p.badges
        .map(b => ({ b, src: safeUrl(b.image || '') }))
        .filter(x => x.src)
        .slice(0, 8);                       // a shape is not a contact sheet
      if (!imgs.length) return null;
      const size = badgeSize(p.shape, imgs.length);
      if (!size) return null;               // too small to sit inside its shape
      const rows = badgeRows(imgs.length);
      const perRow = Math.ceil(imgs.length / rows);
      const width = perRow * size + BADGE_GAP * (perRow - 1);
      const height = rows * size + BADGE_GAP * (rows - 1);
      const html = `<div class="badge-row" style="gap:${BADGE_GAP}px;width:${width}px">` +
        imgs.map(({ b, src }) =>
        `<img src="${plain(src)}" alt="${plain(b.label)}" title="${plain(b.label)}"` +
        ` style="width:${size}px;height:${size}px">`
      ).join('') + `</div>`;
      return L.marker([p.lat, p.long], {
        interactive: false,
        icon: L.divIcon({ html, className: '', iconSize: [width, height],
                          iconAnchor: [width / 2, height / 2] }),
      });
    })
    .filter(Boolean);
  if (rows.length) badgeLayer = L.layerGroup(rows).addTo(map);
}

function drawFacets() {
  const el = document.getElementById('facets');
  if (!el) return;
  const groups = facetsInView();
  if (!groups.length) { el.innerHTML = ''; return; }
  const anyChosen = [...chosen.values()].some(s => s.size);
  /* Geography leads the strip: it says where you are looking, and the rest say
     what you are looking at. Its chips navigate rather than filter — picking a
     country goes there, the way clicking its shape does — so they carry
     data-geo and never enter `chosen`. */
  const geo = geographyInView().map(tier =>
    `<span class="facet"><span class="name">${plain(tier.kind)}</span>` +
    tier.places.map(a =>
      `<button class="fval" data-geo="${plain(a.uri)}">${plain(a.label || short(a.uri))}</button>`
    ).join('') + '</span>').join('');

  el.innerHTML = geo + groups.map(gr => {
    const meta = facetCatalogue[gr.cls] || { values: {} };
    const want = chosen.get(gr.cls) || new Set();
    const buttons = gr.values
      .map(v => ({ v, m: meta.values[v] || { label: short(v), image: '' } }))
      .sort((a, b) => a.m.label.localeCompare(b.m.label))
      .map(({ v, m }) =>
        `<button class="fval${want.has(v) ? ' on' : ''}" data-cls="${plain(gr.cls)}"` +
        ` data-val="${plain(v)}">${plain(m.label)}</button>`).join('');
    return `<span class="facet"><span class="name">${plain(gr.label)}</span>${buttons}</span>`;
  }).join('') + (anyChosen ? `<button class="fclear">clear filters</button>` : '');

  /* Same drill the map performs, so the two ways in cannot disagree. */
  el.classList.toggle('folded', readFold());
  for (const b of el.querySelectorAll('.fval[data-geo]')) {
    b.addEventListener('click', () => {
      const place = byUri.get(b.dataset.geo);
      if (!place) return;
      const next = childLevel(place);
      if (next === null) return;
      selected = place.uri;
      focus = place.uri;
      level = next;
      draw(true);
    });
  }
  for (const b of el.querySelectorAll('.fval:not([data-geo])')) {
    b.addEventListener('click', () => {
      const cls = b.dataset.cls, val = b.dataset.val;
      const set = chosen.get(cls) || new Set();
      if (set.has(val)) set.delete(val); else set.add(val);
      if (set.size) chosen.set(cls, set); else chosen.delete(cls);
      draw(false); drawNav(); drawFacets(); drawTree();
    });
  }
  el.querySelector('.fclear')?.addEventListener('click', () => {
    chosen.clear(); draw(false); drawNav(); drawFacets(); drawTree();
  });
}

function drawNav() {
  const el = document.getElementById('nav');
  if (!points.length) { el.innerHTML = ''; return; }
  const trail = crumbTrail();
  const shown = atLevel();
  const here = points.find(p => p.uri === focus);
  const levelName = here ? plain(here.kind || '') : (shown.length ? plain(shown[0].kind || '') : '');

  const crumbs = [`<a data-up="">All</a>`];
  trail.forEach((p, i) => {
    const last = i === trail.length - 1;
    crumbs.push(`<span class="sep">›</span>` + (last
      ? `<span class="here">${plain(p.label)}</span>`
      : `<a data-up="${i}">${plain(p.label)}</a>`));
  });

  /* The places beside you, as chips — not the ones beneath you. The map already
     draws the children and they are clickable there, so listing them again put
     seventy shop buttons above a map of seventy shops. Moving *sideways* is the
     one move the map cannot offer, so that is what the strip is for: every place
     at your level, the one you are in pressed, click another to switch to it. */
  const beside = siblingsOfFocus();
  const chips = beside
    .slice()
    .sort((a, b) => valueOf(b) - valueOf(a) || a.label.localeCompare(b.label))
    .map((p, i) => {
      const leaf = !hasChildren(p);
      const current = p.uri === focus ? ' current' : '';
      return `<button class="chip${current}${leaf ? ' leaf' : ''}"` +
             ` aria-pressed="${p.uri === focus}"` +
             ` data-chip="${i}">${plain(p.label)}<span class="n">${fmt.format(valueOf(p))}</span></button>`;
    }).join('');

  el.innerHTML = `<span class="trail" id="crumbs">${crumbs.join('')}</span>` +
                 (levelName ? `<span class="lvl">${levelName}</span>` : '') +
                 `<span class="chips">${chips}</span>`;

  for (const a of el.querySelectorAll('#crumbs a')) {
    a.addEventListener('click', () => {
      const idx = a.dataset.up;
      if (idx === '') { level = openingLevel(points); focus = null; selected = null; draw(); return; }
      const target = trail[Number(idx)];
      const next = childLevel(target);
      level = next === null ? target.level : next;
      focus = target.uri;
      selected = target.uri;
      draw();
    });
  }
  const ordered = beside.slice().sort((a, b) => valueOf(b) - valueOf(a) || a.label.localeCompare(b.label));
  for (const btn of el.querySelectorAll('.chip')) {
    const p = ordered[Number(btn.dataset.chip)];
    /* A step sideways: same depth, different branch. Clicking the one you are
       already in re-centres on it rather than doing nothing. A leaf still only
       selects — moving focus onto something with nothing beneath it empties the
       map, which is the bug #146 fixed and this must not undo. */
    btn.addEventListener('click', () => {
      const next = childLevel(p);
      selected = p.uri;
      if (next === null) { drawDetail(); drawNav(); return; }  // a leaf: select, do not descend
      focus = p.uri;
      level = next;
      draw(true);
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
  if (selected === null) { el.innerHTML = ''; return; }
  const here = points.find(p => p.uri === selected);
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
  const det = await nodeDetail(selected);
  if (selected !== here.uri) return;              // drilled on while fetching
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
      rows.push({ place: p, depth, open, current: p.uri === selected });
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
/* What the map draws, and the only place the two modes differ.

   A level answers "what is inside here"; Everything answers "show me all of
   them", which no query can stand in for — the server adds every containing
   place back as context so the drill-down has a hierarchy, so a leaf-only
   query arrives with its containers attached and the map opens on those.

   "All of them" means the leaves: a place nothing else sits inside. Not the
   query's rows — the default query asks for everything that can be drawn, so
   its rows include the very countries and regions the reader is trying to see
   past, and drawing those puts the flags back on top of the stores.

   Leaf-ness is read from the ancestor chains the server already sends, so it
   holds for stores, sensors or branches without this file naming any of them.
   A branch that bottoms out early is its own leaf — a country with no stores
   draws as that country, which is the truthful answer to "show me what is in
   there". The focus still filters, because drilling in should still mean
   something.

   Not called `visible`: draw() declares a local `const visible` for its own
   coordinate-filtered list, and a function of that name is read six lines
   before that const initialises — the temporal dead zone, which throws on every
   draw and leaves an empty map with a working switch. */
function placesToDraw() {
  if (!showAll) return atLevel();
  return points.filter(p => !containers.has(p.uri)
                            && (focus === null || descendsFrom(p, focus)));
}

/* Outlines when there are few enough to read; dots otherwise. The cost and the
   clutter scale with how many are drawn, not with the zoom — zoom 7 alone hid
   every country in the demo, because a country is legible long before that. */
const SHAPE_LIMIT = 40;
const SHAPE_ZOOM = 7;
/* Drawing a continent's worth of places at once is a question of DOM nodes, not
   of how many there are. Two measurements on 1,453 stores: as <div><img> pins
   over SVG circles, a draw took 3,746ms and the renderer stalled; as bare <img>
   pins over one canvas, 215ms. So the pictures are never rationed — a store
   looks like itself at every zoom — and the cost is kept down where it actually
   sits. The circles share one canvas for the same reason: 1,453 SVG paths is
   1,453 DOM nodes, one <canvas> is one. */
const dotCanvas = L.canvas({ padding: 0.5 });
let shapeMode = false;
const wantsShapes = () => {
  const withShapes = placesToDraw().filter(p => p.shape).length;
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
map.on('zoomend', () => {
  if (wantsShapes() !== shapeMode) { draw(false); return; }
  addBadges(badgeVisible);   // same shapes, different pixel size
});
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

/* A place pulled in only to group the results has no row of its own, so it has
   no value in any result column. Reading rows[null] for one threw a TypeError
   out of draw(), and the whole map came back empty with nothing on screen to
   say why. Defined before its first use, and used for every row lookup. */
/* A place passes the filter when it satisfies every *active* facet. Within one
   facet the chosen values are alternatives; across facets they are conditions —
   which is how faceted search has always behaved. */
function passesFilters(p) {
  for (const [cls, want] of chosen) {
    if (!want.size) continue;
    const has = (facetsBeneath.get(p.uri) || {})[cls] || [];
    if (!has.some(v => want.has(v))) return false;
  }
  return true;
}

/* A continent holds no brand of its own; its stores do. So filtering by brand
   has to keep the continent — otherwise choosing one at the top level emptied
   the map completely, which is exactly what it did. Each place is therefore
   judged on everything beneath it as well as itself.

   Built once per result by walking each place's ancestors, which the server
   already sends: O(places x depth) rather than comparing every pair. */
const facetsBeneath = new Map();

/* Every URI that something else sits inside, so a leaf is a point that is not
   in here. Built in the same pass as the facet index rather than asked per
   point: hasChildren() scans all points, which is one scan per point and so
   quadratic on a file this size. */
const containers = new Set();

function indexFacets() {
  facetsBeneath.clear();
  containers.clear();
  const add = (uri, facets) => {
    let into = facetsBeneath.get(uri);
    if (!into) { into = {}; facetsBeneath.set(uri, into); }
    for (const [cls, values] of Object.entries(facets || {})) {
      const seen = into[cls] || (into[cls] = []);
      for (const v of values) if (!seen.includes(v)) seen.push(v);
    }
  };
  for (const p of points) {
    add(p.uri, p.facets);
    for (const ancestor of (p.ancestors || [])) { add(ancestor, p.facets); containers.add(ancestor); }
  }
  indexGeography();
}

/* Geography as a row of chips, so the hierarchy is reachable without hunting
   for a shape on the map. Not derived from the ontology's vocabulary: a tier is
   named by the class ster already resolved for the place — Continent, Country,
   AdministrativeArea here, whatever an ontology calls its own tiers elsewhere.

   Built from the ancestor chains the payload already carries, so this costs a
   pass over points and no extra request. `byUri` is the same points array keyed
   for lookup, because resolving an ancestor by scanning points is the quadratic
   shape this file has been bitten by before. */
const byUri = new Map();
const geoTiers = new Map();   // class name -> Map(uri -> the place)

function indexGeography() {
  byUri.clear(); geoTiers.clear();
  for (const p of points) byUri.set(p.uri, p);
  for (const p of points) {
    for (const uri of (p.ancestors || [])) {
      const place = byUri.get(uri);
      if (!place) continue;
      const kind = place.kind || 'Place';
      let tier = geoTiers.get(kind);
      if (!tier) geoTiers.set(kind, tier = new Map());
      tier.set(uri, place);
    }
  }
}

/* The tier worth offering from where the reader is standing: the nearest one
   below the focus that holds a choice.

   The nearest, not every tier below. Offering them all put all 96 regions of
   six countries in one row at the top level — a list nobody reads, and one that
   answers a question the reader has not asked yet. Narrowing as you descend is
   what the drill-down already does; this is the same move in chips.

   A tier holding one place is skipped rather than shown, for the reason the
   other facets skip one: it cannot discriminate, and the breadcrumb already
   says where you are. That is why a single-continent file offers countries
   first. */
function geographyInView() {
  const floor = focus === null ? -1 : (byUri.get(focus)?.level ?? 0);
  const tiers = [];
  for (const [kind, tier] of geoTiers) {
    const places = [...tier.values()].filter(a =>
      a.uri !== focus &&
      (focus === null || descendsFrom(a, focus)) &&
      (a.level ?? 0) > floor);
    if (places.length > 1) {
      places.sort((a, b) => (a.label || '').localeCompare(b.label || ''));
      tiers.push({ kind, places, level: places[0].level ?? 0 });
    }
  }
  tiers.sort((a, b) => a.level - b.level);
  return tiers.slice(0, 1);
}

/* What the menu offers *here*. Recomputed from the places in view, so drilling
   into a country drops the values that do not trade there — and drops the whole
   facet when only one value is left, because a facet that cannot discriminate
   is not a facet. */
function facetsInView() {
  const shown = placesToDraw();
  /* The level branch grows its scope to the descendants of the tier, because a
     country carries no facets of its own. Everything mode already draws the
     leaves, so expanding them asks descendsFrom about every pair of places to
     learn nothing it does not already have. */
  const under = showAll ? shown
    : points.filter(p => shown.some(s => p === s || descendsFrom(p, s.uri)));
  const out = [];
  for (const [cls, meta] of Object.entries(facetCatalogue)) {
    const seen = new Set();
    for (const p of under)
      for (const v of ((facetsBeneath.get(p.uri) || {})[cls] || [])) seen.add(v);
    const active = chosen.get(cls);
    if (active) for (const v of active) seen.add(v);   // keep a chosen value visible
    if (seen.size > 1) out.push({ cls, label: meta.label, values: [...seen] });
  }
  return out.sort((a, b) => a.label.localeCompare(b.label));
}

const rowOf = p => (p.row === null || p.row === undefined) ? null : rows[p.row];

/* A place's own contribution: nothing for one that is only there to group. */
const ownValue = p => rowOf(p) === null ? 0
  : (measureCol === null ? 1 : (num(rowOf(p)[measureCol]) ?? 0));
/* What a place is worth on the map: itself plus everything under it. That is
   what makes a country meaningful when the query returned stores — it shows how
   many it holds — and it is why a place with nothing beneath it and no row of
   its own never reaches the map at all. */
const valueOf = p => points.reduce(
  (total, q) => total + (((q === p || descendsFrom(q, p.uri)) && passesFilters(q))
                          ? ownValue(q) : 0), 0);

/* Re-running goes through the server's own read-only query endpoint, so the
   page never needs its own query engine and cannot mutate the ontology.

   /api/sparql_query, not /mcp: MCP is how an agent talks to this server, and a page
   this same server rendered has no business speaking an agent protocol back to
   it. The JSON-RPC envelope also cost about 48ms a call to wrap an answer that
   then had to be parsed back out of a tool-result string. */
async function runQuery(sparql) {
  const response = await fetch('/api/sparql_query', {
    method: 'POST',
    headers: { 'Content-Type':'application/json', 'Authorization': 'Bearer ' + TOKEN },
    body: JSON.stringify({ query: sparql })
  });
  const parsed = await response.json();
  if (parsed.error) throw new Error(parsed.message || parsed.error);
  if (!response.ok) throw new Error('query failed');
  return parsed;
}


const isUri = v => typeof v === 'string' && /^(https?:|urn:)/.test(v);
const num = v => { const n = Number(v); return Number.isFinite(n) ? n : null; };
const short = v => String(v).split(/[#/]/).filter(Boolean).pop();
/* SPARQL results stringify a literal with its language tag ("Brest"@fr); the
   tag is machinery, not part of the name the reader wants to see. */
const plain = v => String(v).replace(/@[a-zA-Z]{2,3}(-[a-zA-Z0-9]+)*$/, '');
const MEASURE_NAME = () => measureCol === null ? 'rows' : columns[measureCol];
/* With no measure column chosen the total is just how many rows landed here, so
   a single shop read "rows 1" — a label for a number that counts nothing. Show
   it when it was asked for, or when it actually aggregates something. */
function measureLine(total) {
  if (measureCol === null && total <= 1) return '';
  return `<br>${MEASURE_NAME()} ${fmt.format(total)}`;
}

/* The figure printed on a place: what it totals, when that says something. A lone row with no
   measure chosen would only print "1", a label for a number that counts nothing (see measureLine). */
function figureOf(total, measured) {
  return (!measured && total <= 1) ? null : fmt.format(total);
}

/* Coordinates come from bare lat/long columns, else by asking the graph about a
   URI in the row. Only WGS84 — nothing here knows what the data is about. */
async function locate(cols, data) {
  const li = cols.findIndex(c => ['lat','latitude'].includes(c.toLowerCase()));
  const gi = cols.findIndex(c => ['long','lon','lng','longitude'].includes(c.toLowerCase()));
  if (li >= 0 && gi >= 0) {
    const points = data.map((r, i) => {
      /* Keep the row's URI: it names the point when no plain label is present,
         and lets the cluster control exclude the column that located it. */
      const uri = r.find(isUri) || null;
      const named = r.find((c, j) => j !== li && j !== gi && c && !isUri(c));
      return { row:i, lat:num(r[li]), long:num(r[gi]),
               label: named ? plain(named) : (uri ? short(uri) : `row ${i + 1}`), uri };
    }).filter(p => p.lat !== null && p.long !== null);
    /* The coordinates came from the columns, but what a place *is* — its picture, the filters it
       belongs to, the logos it carries — is the ontology's to say. Ask the server about the rows that
       name an entity, and keep the columns' coordinates. Without this a query selecting ?lat ?long drew
       plain dots, however much the ontology said about each store. */
    const named = [...new Set(points.map(p => p.uri).filter(Boolean))];
    if (named.length) {
      const known = new Map((await locateOnServer(named)).map(p => [p.uri, p]));
      for (const p of points) {
        const found = known.get(p.uri);
        if (found) Object.assign(p, { icon: found.icon || '', facets: found.facets || {}, badges: found.badges || [] });
      }
    }
    return points;
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
         them here left every level drawn at once with no error to show for it.
         `mapped` rides along too: an unmapped place counts but is never drawn. */
      out.push({ row:i, lat:found.lat, long:found.long, uri:hit, shape:found.shape,
                 level:found.level ?? 0, parent:found.parent ?? null, kind:found.kind || '',
                 ancestors:found.ancestors || [], result:true, figures:found.figures || [],
                 facets:found.facets || {}, badges:found.badges || [],
                 icon:found.icon || '',
                 label: named ? plain(named) : (found.label || short(hit)) });
    }
  });
  /* The places that contain the results, so a query for stores can be grouped by
     city and country. They are context, not rows: they carry no measure, and a
     city holding no result is never among them. */
  for (const p of placed) {
    if (used.has(p.uri) || p.result) continue;
    out.push({ row:null, lat:p.lat, long:p.long, uri:p.uri, shape:p.shape,
               facets:p.facets || {}, badges:p.badges || [],
               icon:p.icon || '',
               level:p.level ?? 0, parent:p.parent ?? null, kind:p.kind || '',
               ancestors:p.ancestors || [], result:false, figures:p.figures || [],
               label:p.label || short(p.uri) });
  }
  return out;
}

let overlayLayers = [];      // declared by the file, offered in the layer menu
let facetCatalogue = {};     // class → {label, values:{uri:{label,image}}}, from the server
const chosen = new Map();    // class → Set of chosen value URIs
async function locateOnServer(uris) {
  const response = await fetch('/api/locate', {
    method: 'POST',
    headers: { 'Content-Type':'application/json', 'Authorization': 'Bearer ' + TOKEN },
    body: JSON.stringify({ uris })
  });
  if (!response.ok) return [];
  const body = await response.json();
  overlayLayers = body.layers || [];
  facetCatalogue = body.facets || {};
  return body.places || [];
}

const inScope = p => scope === null || (rowOf(p)?.[groupBy] ?? null) === scope;
const ramp = (v, lo, hi) => hi === lo ? RAMP[RAMP.length-1]
  : RAMP[Math.min(RAMP.length-1, Math.floor((v - lo) / (hi - lo) * RAMP.length))];

function draw(fit = true) {
  if (layer) map.removeLayer(layer);
  shapeMode = wantsShapes();
  /* Clustering by a result column is an alternative to the hierarchy, not a
     filter inside it: it answers "where are my rows", so it reads the whole
     result rather than the level currently drilled to. Intersecting the two
     emptied the map wherever the level held only context places. */
  const source = (groupBy !== null ? points.filter(p => rowOf(p) !== null) : placesToDraw())
    .filter(passesFilters);
  /* Counting and plotting are different questions. A place with no coordinates
     is real and belongs in every total; drawing it would put NaN into Leaflet
     and take the whole layer down. So it is filtered out here, at the point of
     drawing, and nowhere else. */
  const visible = source.filter(inScope).filter(p => p.lat !== null && p.long !== null);
  /* Ungrouped, or drilled into one group: every row is its own marker. */
  const grouped = groupBy !== null && scope === null;
  const groups = new Map();
  for (const p of visible) {
    /* Keyed by URI, not row index: a place pulled in to group the results has no
       row of its own, and keying on that collapsed every one of them into a
       single "null" group — five countries drawn as one dot. */
    const key = grouped ? (rowOf(p)?.[groupBy] || '—') : (p.uri || 'row:' + p.row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(p);
  }
  const sizes = [...groups.values()].map(m => m.reduce((a, p) => a + valueOf(p), 0));
  const lo = Math.min(...sizes, 1), hi = Math.max(...sizes, 1);

  const figures = [];   // the number printed on each place, drawn above the shapes and dots
  const marks = [...groups.entries()].map(([key, members]) => {
    const lat = members.reduce((a, p) => a + p.lat, 0) / members.length;
    const long = members.reduce((a, p) => a + p.long, 0) / members.length;
    const name = grouped ? short(key) : members[0].label;
    const total = members.reduce((a, p) => a + valueOf(p), 0);
    const figure = figureOf(total, measureCol !== null);
    /* A lone place with a picture is drawn as that picture, unless it is drawn as its outline (a
       country has a flag *and* a shape; the shape wins, so the number goes on it). */
    const lone = !grouped && members.length === 1 ? members[0] : null;
    const drawnAsPicture = lone !== null && !!lone.icon && !(shapeMode && lone.shape);
    if (figure !== null && !drawnAsPicture) {
      /* A place that carries logos has them centred on the same point: lift the number clear of them. */
      const lift = members.some(m => (m.badges || []).length > 0) ? FIGURE_LIFT : 0;
      figures.push(L.marker([lat, long], {
        icon: L.divIcon({ className: 'figure-label', html: `<span>${figure}</span>`,
                         iconSize: [0, 0], iconAnchor: [0, lift] }),
        interactive: false, keyboard: false,
      }));
    }
    const mark = L.circleMarker([lat, long], {
      renderer: dotCanvas,
      radius: 6 + Math.sqrt(total) * 4, color:'#fff', weight:2,
      fillColor: ramp(total, lo, hi), fillOpacity:0.92
    }).bindTooltip(`<b>${name}</b>` + measureLine(total) +
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
      selected = only.uri;
      if (next === null) { drawDetail(); drawNav(); return; }  // a leaf: select, do not descend
      level = next;
      focus = only.uri;
      draw(true);
    };
    if (!grouped && only) mark.on('click', drill);
    /* One row, its own geometry, and few enough to read: draw the shape and keep
       the marker's tooltip and colour so both modes look like one map. */
    if (!grouped && shapeMode && only && only.shape) {
      const layer = L.geoJSON(only.shape, {
        style: { color:'#fff', weight:2, fillColor: ramp(total, lo, hi), fillOpacity:0.72 }
      }).bindTooltip(`<b>${name}</b>` + (only.kind ? ` <i>${plain(only.kind)}</i>` : '') +
                     measureLine(total) +
                     (hasChildren(only) ? '<br><i>click to open</i>' : ''),
                     { direction:'top', sticky:true });
      if (hasChildren(only)) layer.on('click', drill);
      return layer;
    }
    /* A place that carries its own picture is drawn as that picture rather than
       a dot. What a store looks like is the ontology's to say — ster only reads
       whichever image predicate it used and honours it. */
    if (!grouped && only && only.icon) {
      /* L.icon, not L.divIcon: an <img> element on its own rather than an <img>
         inside a <div>. Half the DOM per store, which is the difference between
         a continent's worth of them drawing and the renderer stalling. */
      const pin = L.marker([lat, long], {
        icon: L.icon({
          iconUrl: only.icon, iconSize: [PIN, PIN], iconAnchor: [PIN / 2, PIN / 2],
        }),
        alt: name, keyboard: false,
      }).bindTooltip(`<b>${name}</b>` + (only.kind ? ` <i>${plain(only.kind)}</i>` : '') +
                     measureLine(total), { direction:'top' });
      pin.on('click', drill);
      return pin;
    }
    return mark;
  });
  layer = L.featureGroup([...marks, ...figures]).addTo(map);
  addBadges(visible);
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
      /* Barely any padding: the place you opened should fill the pane, not sit
         in a frame of sea. 40px each side cost about a sixth of the view on a
         laptop. What is left is the aspect ratio — a tall country in a wide
         pane cannot touch all four edges without cropping it, and cropping the
         thing you just asked to see is worse than a margin. */
      map.fitBounds(bounds, { padding:[8,8], maxZoom:14 });
    }
  }

  drawNav();
  drawDetail();
  drawFacets();
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

/* Folding the filter strip. It is five rows deep on a rich file and pushes the
   map down the page; a reader who has set their filters wants the map back.

   Remembered across reloads, because a fold that forgets is a fold you set
   every time. localStorage is per-browser and may throw outright where site
   data is blocked, so every touch of it is guarded and the strip simply starts
   open when it cannot be read. */
const FOLD_KEY = 'ster.map.filters.folded';

function readFold() {
  try { return localStorage.getItem(FOLD_KEY) === '1'; } catch { return false; }
}

function foldControls() {
  const button = document.getElementById('fold');
  const strip = document.getElementById('facets');
  if (!button || !strip) return;
  const paint = folded => {
    strip.classList.toggle('folded', folded);
    button.textContent = folded ? 'Show filters' : 'Hide filters';
    button.setAttribute('aria-expanded', folded ? 'false' : 'true');
  };
  paint(readFold());
  button.addEventListener('click', () => {
    const folded = !strip.classList.contains('folded');
    paint(folded);
    try { localStorage.setItem(FOLD_KEY, folded ? '1' : '0'); } catch { /* not stored */ }
  });
}

/* The switch, and the link that carries it. Level and focus are deliberately
   untouched: flipping back should land the reader where they were standing,
   not at the top of the map. */
function modeControls() {
  const box = document.getElementById('mode');
  const [levels, everything] = box.children;
  const paint = () => {
    levels.classList.toggle('on', !showAll);
    everything.classList.toggle('on', showAll);
  };
  const pick = want => {
    if (showAll === want) return;
    showAll = want;
    paint();
    rememberMode();
    render();
  };
  levels.addEventListener('click', () => pick(false));
  everything.addEventListener('click', () => pick(true));
  paint();
}

/* replaceState, not pushState: flipping a switch is not a navigation, and
   undoing it should not cost a press of Back. The parameter is dropped rather
   than set to a falsy value, so a shared link carries the mode it is in
   instead of accumulating a stale one. */
function rememberMode() {
  const url = new URL(window.location);
  if (showAll) url.searchParams.set('show', 'all');
  else url.searchParams.delete('show');
  history.replaceState(null, '', url);
}

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
  /* One option is not a choice. The default query returns the locating column
     and a label, so nothing else is ever offered and the control sat there
     permanently pressed. A query that returns another URI column — a brand
     beside its stores — brings it back on its own. */
  const useful = options.length > 1;
  seg.hidden = !useful;
  document.getElementById('seg-label').hidden = !useful;
  seg.innerHTML = options.map(o => `<button>${o.name}</button>`).join('');
  [...seg.children].forEach((b, n) => b.addEventListener('click', () => {
    groupBy = options[n].i; scope = null;
    [...seg.children].forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    render();
  }));
  if (seg.firstChild) seg.firstChild.classList.add('on');
  modeControls();
  foldControls();
}

/* Two waits, not one: the query runs, then every row it returned has to be
   placed. Naming the phase you are in is the whole value — a spinner alone says
   only "something". */
function loading(text) {
  const box = document.getElementById('loading');
  if (!box) return;
  box.classList.toggle('on', text !== null);
  if (text !== null) document.getElementById('loading-text').textContent = text;
}

async function run() {
  const msg = document.getElementById('msg');
  msg.className = ''; msg.textContent = 'running…';
  loading('running the query…');
  try {
    const result = await runQuery(document.getElementById('q').value);
    columns = result.columns || [];
    rows = result.rows || [];
    groupBy = null; scope = null;
    measureCol = findMeasure(columns, rows);
    loading(`placing ${rows.length} row${rows.length === 1 ? '' : 's'}…`);
    points = await locate(columns, rows);
    /* Open on the broadest level the result offers — one continent outline, not
       every country and city piled on top of it. */
    addOverlayControl();
    indexFacets();
    level = openingLevel(points);
    focus = null;
    selected = null;
      document.getElementById('sub').textContent =
      `${rows.length} row(s) · ${points.length} mappable`;
    clusterControls();
    render();
    msg.textContent = points.length ? '' : 'no row in this result carries WGS84 coordinates';
  } catch (err) {
    msg.className = 'bad'; msg.textContent = String(err.message || err);
  } finally {
    // finally, not the happy path: a query that throws must not leave the map
    // behind a veil that never lifts.
    loading(null);
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
_PAGE = _PAGE.replace("__FAVICON__", FAVICON_LINK_TAG)


# What the page shows around the map itself; hidden when it is embedded in another page.
_EMBED_HIDDEN = ("header", "#query-panel", "aside")


def render_map_html(query: str, token: str, show_all: bool = False, embed: bool = False) -> str:
    """The ``/map`` page, primed with *query* and able to re-run it via *token*.

    *show_all* opens the page drawing every result beneath the focus rather than
    one tier of the hierarchy, so a link can be shared in either mode.

    *embed* hides the header, the query box and the details panel, for showing the map inside
    another page: the map, its clustering and its drill-down are unchanged.
    """
    return (
        _PAGE.replace("__QUERY__", _escape(query))
        .replace("__TOKEN__", json.dumps(token))
        .replace("__SHOW_ALL__", "true" if show_all else "false")
        .replace("__EMBED__", embed_style(_EMBED_HIDDEN) if embed else "")
    )


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
