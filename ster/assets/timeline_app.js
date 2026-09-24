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
  /* `chosen` holds the lanes the reader picked, never the ones they dropped —
     the map's model, and the reason its filter strip can be unclicked. An
     opt-out set cannot: the lane leaves the view, the button is rebuilt from
     what is left, and the only control that could bring it back has gone with
     it. Empty means no filter, so the page opens showing everything. */
  var state = {
    items: [], lanes: [], chosen: {}, showAuxiliary: false, timeline: null, groups: null, data: null,
    beside: {}, widths: {}
  };

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

  /* Provenance wins over the instant/interval pair it is drawn with: a reader
     scanning the frieze needs to see at a glance which marks are the record of
     a fact rather than the fact itself, and the shape already says which of the
     two it is. */
  function classOf(item) {
    return item.kind + (item.provenance ? ' provenance' : '') + (state.beside[item.id] ? ' beside' : '');
  }

  /* A label's width on screen, measured once in a hidden item so it picks up
     the same stylesheet the timeline draws with. */
  var measurer = null;
  function labelWidth(item) {
    if (!(item.id in state.widths)) {
      if (!measurer) {
        measurer = document.createElement('div');
        measurer.className = 'vis-item vis-range';
        measurer.style.visibility = 'hidden';
        measurer.innerHTML = '<div class="vis-item-content"></div>';
        document.body.appendChild(measurer);
      }
      measurer.firstChild.innerHTML = content(item);
      state.widths[item.id] = measurer.firstChild.offsetWidth;
    }
    return state.widths[item.id];
  }

  /* A period too short on screen for its label shows the label just past its
     right edge. The `beside` class lets the box overflow, which is
     vis-timeline's own mode for text wider than its item: stacking then
     reserves the label's room, so it never lands on the next item. Checked
     again after every zoom, since a box that was too narrow may now fit. */
  function placeLabels() {
    var win = state.timeline.getWindow();
    var panel = el('tl').querySelector('.vis-panel.vis-center');
    if (!panel) return;
    var pxPerMs = panel.clientWidth / (win.end - win.start);
    var changes = [];
    visible().forEach(function (i) {
      if (!i.end) return;
      var span = (vis.moment(i.end).valueOf() - vis.moment(i.start).valueOf()) * pxPerMs;
      var beside = span < labelWidth(i);
      if (beside !== Boolean(state.beside[i.id])) {
        state.beside[i.id] = beside;
        changes.push({ id: i.id, className: classOf(i) });
      }
    });
    if (changes.length) state.data.update(changes);
  }

  function anyChosen() { return Object.keys(state.chosen).length > 0; }

  /* The auxiliary switch and the lane filter are asked separately, because the
     lane buttons have to be built from everything the switch admits — including
     the lanes nobody picked, which is what keeps them clickable a second time. */
  function admitted() {
    return state.items.filter(function (i) { return state.showAuxiliary || !i.auxiliary; });
  }

  function visible() {
    var filtering = anyChosen();
    return admitted().filter(function (i) { return !filtering || state.chosen[i.group]; });
  }

  function draw() {
    var groups = [];
    var seen = {};
    visible().forEach(function (i) {
      if (!seen[i.group]) { seen[i.group] = 1; groups.push({ id: i.group, content: esc(i.groupLabel) }); }
    });
    /* A period is a box spanning its dates; a single date is a `point` — a dot
       on the date with the label starting beside it. A `box` hung its line from
       the middle of the label and looked like a period of its own. */
    var items = visible().map(function (i) {
      return {
        id: i.id, group: i.group, start: i.start,
        end: i.end || undefined,
        type: i.end ? 'range' : 'point',
        content: content(i), title: tooltip(i),
        className: classOf(i)
      };
    });
    var container = el('tl');
    if (state.timeline) {
      state.timeline.off('rangechanged', placeLabels);
      state.timeline.destroy();
    }
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
    state.timeline.on('rangechanged', placeLabels);
    if (items.length) state.timeline.fit({ animation: false });
    placeLabels();
    status(items.length + ' moments · ' + groups.length + ' lanes');
  }

  /* Every lane the auxiliary switch admits, picked or not. Counts are of what
     that lane would contribute, so they do not move as lanes are chosen — a
     count that changed with the selection would be counting the filter. */
  function lanes() {
    var box = el('lanes');
    box.innerHTML = '';
    var counts = {};
    admitted().forEach(function (item) {
      if (!counts[item.group]) counts[item.group] = { uri: item.group, label: item.groupLabel, count: 0 };
      counts[item.group].count++;
    });
    Object.keys(counts).sort(function (a, b) {
      return counts[a].label.localeCompare(counts[b].label);
    }).forEach(function (uri) {
      var lane = counts[uri];
      var b = document.createElement('button');
      b.className = 'ftbtn' + (state.chosen[lane.uri] ? ' on' : '');
      b.textContent = lane.label + ' (' + lane.count + ')';
      b.onclick = function () {
        if (state.chosen[lane.uri]) delete state.chosen[lane.uri];
        else state.chosen[lane.uri] = 1;
        lanes(); draw();
      };
      box.appendChild(b);
    });
    if (anyChosen()) {
      var clear = document.createElement('button');
      clear.className = 'fclear';
      clear.textContent = 'clear filters';
      clear.onclick = function () { state.chosen = {}; lanes(); draw(); };
      box.appendChild(clear);
    }
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
    status('querying…');
    try {
      var result = await runQuery(el('q').value);
      var uris = urisOf(result);
      if (!uris.length) { status('no entity in the result'); return; }
      var data = await resolve(uris);
      state.items = data.items || [];
      state.beside = {};
      state.widths = {};
      state.lanes = data.lanes || [];
      state.chosen = {};
      state.showAuxiliary = false;
      el('toggle-auxiliary').classList.remove('active');
      if (!state.items.length) { status('no temporal data on these entities'); return; }
      lanes(); draw();
    } catch (e) {
      status('error: ' + e.message);
    }
  }

  el('run').onclick = load;
  el('fit').onclick = function () { if (state.timeline) state.timeline.fit(); };
  /* Toggled through a class, not through style.display: the box is hidden by
     the stylesheet, so its inline display starts empty and the first click of
     a read-and-flip handler only ever wrote back the state it was already in —
     the button looked dead until it was pressed twice. */
  el('toggle-q').onclick = function () {
    this.classList.toggle('active', el('qbox').classList.toggle('open'));
  };
  el('toggle-auxiliary').onclick = function () {
    state.showAuxiliary = !state.showAuxiliary;
    this.classList.toggle('active', state.showAuxiliary);
    lanes(); draw();
  };
  el('panel-close').onclick = function () { el('panel').style.display = 'none'; };
  load();
})();
