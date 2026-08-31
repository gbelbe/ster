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
<main>
  <div id="map"></div>
  <aside><table id="table"></table></aside>
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

const valueOf = p => measureCol === null ? 1 : (num(rows[p.row][measureCol]) ?? 0);

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
  const values = uris.map(u => `<${u}>`).join(' ');
  const found = await runQuery(
    `SELECT ?s ?lat ?long WHERE { VALUES ?s { ${values} } ` +
    `?s <${WGS}lat> ?lat ; <${WGS}long> ?long }`);
  const by = new Map(found.rows.map(r => [r[0], [num(r[1]), num(r[2])]]));
  const out = [];
  data.forEach((r, i) => {
    const hit = r.find(c => by.has(c));
    if (hit) {
      const [lat, long] = by.get(hit);
      const named = r.find(c => !isUri(c));
      out.push({ row:i, lat, long, uri:hit, label: named ? plain(named) : short(hit) });
    }
  });
  return out;
}

const inScope = p => scope === null || rows[p.row][groupBy] === scope;
const ramp = (v, lo, hi) => hi === lo ? RAMP[RAMP.length-1]
  : RAMP[Math.min(RAMP.length-1, Math.floor((v - lo) / (hi - lo) * RAMP.length))];

function draw() {
  if (layer) map.removeLayer(layer);
  const visible = points.filter(inScope);
  /* Ungrouped, or drilled into one group: every row is its own marker. */
  const grouped = groupBy !== null && scope === null;
  const groups = new Map();
  for (const p of visible) {
    const key = grouped ? (rows[p.row][groupBy] || '—') : String(p.row);
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
    return mark;
  });
  layer = L.featureGroup(marks).addTo(map);
  const bounds = layer.getBounds();
  if (bounds.isValid()) map.fitBounds(bounds, { padding:[40,40] });

  document.getElementById('table').innerHTML =
    `<thead><tr><th>${grouped ? 'group' : 'item'}</th>` +
    `<th class="num">${MEASURE_NAME()}</th></tr></thead><tbody>` +
    [...groups.entries()]
      .map(([k, m]) => [grouped ? short(k) : m[0].label,
                        m.reduce((a, p) => a + valueOf(p), 0)])
      .sort((a, b) => b[1] - a[1])
      .map(([name, total]) =>
        `<tr><td>${name}</td><td class="num">${fmt.format(total)}</td></tr>`).join('') +
    '</tbody>';
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
