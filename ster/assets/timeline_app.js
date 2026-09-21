/* ster — timeline application layer.
 *
 * Reads everything from window.__STER_TIMELINE__ and talks to the same server
 * that served the page. Kept free of vis-timeline internals beyond the public
 * Timeline/DataSet constructors, so the vendored library can be swapped without
 * touching this file — the separation graph_app.js already keeps with Cytoscape.
 */
(function () {
  'use strict';

  var CFG = window.__STER_TIMELINE__ || {};
  var TOKEN = CFG.token || '';
  var state = { items: [], lanes: [], hidden: {}, showAuxiliary: false, timeline: null, groups: null, data: null };

  function el(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function status(text) { el('status').textContent = text; }

  function headers() {
    var h = { 'Content-Type': 'application/json' };
    if (TOKEN) h.Authorization = 'Bearer ' + TOKEN;
    return h;
  }

  /* The query runs through the server's own read-only endpoint, not /mcp:
     MCP is how an agent talks to this server, a page is not an agent. */
  async function runQuery(sparql) {
    var r = await fetch('/api/sparql_query', {
      method: 'POST', headers: headers(), body: JSON.stringify({ query: sparql })
    });
    if (!r.ok) throw new Error('query failed: ' + r.status);
    return r.json();
  }

  async function resolve(uris) {
    var r = await fetch('/api/timeline', {
      method: 'POST', headers: headers(), body: JSON.stringify({ uris: uris })
    });
    if (!r.ok) throw new Error('timeline failed: ' + r.status);
    return r.json();
  }

  function urisOf(result) {
    var seen = {}, out = [];
    (result.rows || []).forEach(function (row) {
      row.forEach(function (cell) {
        if (typeof cell === 'string' && /^(https?:\/\/|urn:)/.test(cell) && !seen[cell]) {
          seen[cell] = 1; out.push(cell);
        }
      });
    });
    return out;
  }

  /* An item's body is HTML, which is the whole reason for choosing a DOM-based
     timeline: a thumbnail and a label come straight from the metadata with no
     rendering code of ster's own. */
  function content(item) {
    var img = item.image
      ? '<img class="thumb" src="' + esc(item.image) + '" alt="" loading="lazy">' : '';
    return img + '<span class="lbl">' + esc(item.label) + '</span>' +
      '<span class="pred">· ' + esc(item.predicateLabel) + '</span>';
  }

  function tooltip(item) {
    var when = item.end ? item.start + ' → ' + item.end : item.start;
    var note = item.note ? '\n\n' + item.note.slice(0, 400) : '';
    return item.label + '\n' + item.predicateLabel + ' : ' + when + note;
  }

  function visible() {
    return state.items.filter(function (i) {
      return !state.hidden[i.group] && (state.showAuxiliary || !i.auxiliary);
    });
  }

  function draw() {
    var groups = [];
    var seen = {};
    visible().forEach(function (i) {
      if (!seen[i.group]) { seen[i.group] = 1; groups.push({ id: i.group, content: esc(i.groupLabel) }); }
    });
    var items = visible().map(function (i) {
      return {
        id: i.id, group: i.group, start: i.start,
        end: i.end || undefined,
        type: i.end ? 'range' : 'box',
        content: content(i), title: tooltip(i),
        className: i.kind
      };
    });
    var container = el('tl');
    if (state.timeline) state.timeline.destroy();
    state.groups = new vis.DataSet(groups);
    state.data = new vis.DataSet(items);
    state.timeline = new vis.Timeline(container, state.data, state.groups, {
      /* vis-timeline sanitises item content and strips attributes it does not
         know, which silently removed every class and left the label and the
         predicate running together. Narrowing the filter rather than disabling
         it: ster escapes every value it interpolates, and the library still
         guards against anything a label smuggles in. */
      xss: {
        disabled: false,
        filterOptions: {
          whiteList: { span: ['class'], img: ['src', 'class', 'alt', 'loading'] }
        }
      },
      stack: true, zoomKey: '', orientation: 'top',
      margin: { item: 6, axis: 12 },
      tooltip: { followMouse: true, overflowMethod: 'flip' },
      zoomMin: 1000 * 60 * 60,            /* an hour */
      zoomMax: 1000 * 60 * 60 * 24 * 365 * 200  /* two centuries */
    });
    state.timeline.on('select', function (props) {
      var id = props.items && props.items[0];
      if (!id) return;
      var hit = state.items.filter(function (i) { return i.id === id; })[0];
      if (hit) detail(hit);
    });
    if (items.length) state.timeline.fit();
    status(items.length + ' moments · ' + groups.length + ' couloirs');
  }

  function lanes() {
    var box = el('lanes');
    box.innerHTML = '';
    var counts = {};
    visible().forEach(function (item) {
      if (!counts[item.group]) counts[item.group] = { uri: item.group, label: item.groupLabel, count: 0 };
      counts[item.group].count++;
    });
    Object.keys(counts).sort(function (a, b) {
      return counts[a].label.localeCompare(counts[b].label);
    }).forEach(function (uri) {
      var lane = counts[uri];
      var b = document.createElement('button');
      b.className = 'ftbtn' + (state.hidden[lane.uri] ? '' : ' active');
      b.textContent = lane.label + ' (' + lane.count + ')';
      b.onclick = function () {
        state.hidden[lane.uri] = !state.hidden[lane.uri];
        lanes(); draw();
      };
      box.appendChild(b);
    });
  }

  /* Detail comes from /api/node-detail — the same endpoint the graph and map
     views use, so one entity reads the same way wherever it is clicked. */
  async function detail(item) {
    var panel = el('panel');
    panel.style.display = 'block';
    panel.innerHTML = '<div class="dp"><div class="dp-h2">' + esc(item.label) + '</div>' +
      '<div class="dp-uri">' + esc(item.uri) + '</div>' +
      '<div class="dp-row"><span>' + esc(item.predicateLabel) + '</span><span>' +
      esc(item.end ? item.start + ' → ' + item.end : item.start) + '</span></div>' +
      (item.note ? '<pre class="dp-note">' + esc(item.note) + '</pre>' : '') + '</div>';
    try {
      var r = await fetch('/api/node-detail?uri=' + encodeURIComponent(item.uri), { headers: headers() });
      if (!r.ok) return;
      var d = await r.json();
      if (d && d.html) panel.innerHTML += d.html;
    } catch (e) { /* the panel already says the useful part */ }
  }

  async function load() {
    status('interrogation…');
    try {
      var result = await runQuery(el('q').value);
      var uris = urisOf(result);
      if (!uris.length) { status('aucune entité dans le résultat'); return; }
      var data = await resolve(uris);
      state.items = data.items || [];
      state.lanes = data.lanes || [];
      state.hidden = {};
      state.showAuxiliary = false;
      el('toggle-auxiliary').classList.remove('active');
      if (!state.items.length) { status('aucune donnée temporelle sur ces entités'); return; }
      lanes(); draw();
    } catch (e) {
      status('erreur : ' + e.message);
    }
  }

  el('run').onclick = load;
  el('fit').onclick = function () { if (state.timeline) state.timeline.fit(); };
  el('toggle-q').onclick = function () {
    var box = el('qbox');
    box.style.display = box.style.display === 'none' ? 'block' : 'none';
  };
  el('toggle-auxiliary').onclick = function () {
    state.showAuxiliary = !state.showAuxiliary;
    this.classList.toggle('active', state.showAuxiliary);
    lanes(); draw();
  };
  el('panel-close').onclick = function () { el('panel').style.display = 'none'; };
  load();
})();
