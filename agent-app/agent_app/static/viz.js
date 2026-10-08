/* Choosing a chart for a SPARQL result table.
 *
 *   Viz.profile(columns, rows)        -> what each column is (measure, category, date, ...)
 *   Viz.candidates(profile)           -> the charts that fit, best first, with the reason
 *   Viz.config(kind, profile, theme)  -> a Chart.js config (or {kpi} for a single figure)
 *
 * The rules, in the order they are tried:
 *   one row, a measure ........................ key figure
 *   a date column + a measure ................. line, or bars
 *   one category + one measure ................ bars; doughnut too when 2-6 positive parts
 *   one category + 2-4 measures ............... grouped bars, stacked bars
 *   two categories + one measure .............. grouped bars, stacked bars (the smaller one is the series)
 *   2+ measures, many rows .................... scatter
 *   latitude + longitude, or places ster can locate ... no chart: the ster map is embedded (mapHint)
 *   dates ..................................... friseItems/friseModel build a time frise
 * Anything else gets no chart: the table in the timeline already shows it.
 * No DOM here, so it can be tested under node.
 */
(function (root) {
  "use strict";

  const isNum = v => /^-?\d+(\.\d+)?$/.test(String(v).trim()) && !/^-?0\d/.test(String(v).trim());
  const ISO = /^\d{4}(-\d{2}(-\d{2})?)?(T.*)?$/;
  const CODEISH = /(postal|postcode|zip|code|phone|siret|siren|ean|(^|_)id$|uri|iri)/i; // digits that name, not count
  const TIMEISH = /(year|annee|année|date|month|mois|time|jour|day|week|semaine|quarter|trimestre)/i;
  const LAT = /^(lat|latitude)$/i, LON = /^(lon|lng|long|longitude)$/i;
  const isIri = v => /^https?:\/\//.test(String(v));

  /** Readable end of an IRI: ...#store-brico-depot-fr-lille -> store-brico-depot-fr-lille */
  function local(v) {
    let s = String(v ?? "");
    if (isIri(s)) { s = s.split("#").pop(); if (s.includes("/")) s = s.split("/").pop(); try { s = decodeURIComponent(s); } catch { /* keep raw */ } }
    return s;
  }

  /* Words and number/date formats come from the page: Viz.setI18n(t, locale). Without it keys are shown as they are. */
  let T = k => k, LOC = "en", _nf = null;
  const NF = () => (_nf ||= new Intl.NumberFormat(LOC, { maximumFractionDigits: 2 }));
  function setI18n(t, loc) { T = t; LOC = loc; _nf = null; }

  function profile(columns, rows) {
    const cols = columns.map((name, i) => {
      const vals = rows.map(r => r[i]).filter(v => v !== "" && v != null);
      const iso = vals.length && vals.every(v => ISO.test(String(v)));
      let type = "cat";
      if (!vals.length) type = "empty";
      else if (LAT.test(name) && vals.every(isNum)) type = "lat";
      else if (LON.test(name) && vals.every(isNum)) type = "lon";
      else if (iso && (TIMEISH.test(name) || vals.some(v => /^\d{4}-\d{2}/.test(String(v))))) type = "time";
      else if (vals.every(isNum) && !CODEISH.test(name)) type = "num";
      return { name, i, type, uniq: new Set(vals).size, iri: vals.length > 0 && vals.every(isIri), hidden: false };
    });
    // an IRI column that only repeats a label column is an id, not something to plot; the label
    // is whichever plain-text category column pairs one-to-one with it, whatever it is called
    const plain = cols.filter(c => c.type === "cat" && !c.iri);
    cols.forEach(c => { if (c.iri && c.uniq > 1 && plain.some(l => l.uniq === c.uniq)) c.hidden = true; });
    const pick = t => cols.filter(c => c.type === t && !c.hidden);
    return { columns, rows, cols, nums: pick("num"), cats: pick("cat"), times: pick("time"), lat: pick("lat")[0], lon: pick("lon")[0], n: rows.length };
  }

  const numAt = (r, c) => Number(r[c.i]);
  const catAt = (r, c) => (c.iri ? local(r[c.i]) : String(r[c.i] ?? ""));

  function candidates(p) {
    const out = [], add = (kind, why, rec) => out.push({ kind, label: T("kind." + kind), why, rec: !!rec });
    const { nums, cats, times, n } = p;
    if (!n) return out;
    if (nums.length && n === 1 && !times.length) {
      add("kpi", nums.length === 1 ? T("why.kpi_single") : T("why.kpi_many", { n: nums.length }), true);
    } else if (times.length && nums.length) {
      add("line", T("why.line"), n >= 3);
      add("bar", T("why.bar_period"), n < 3);
    } else if (cats.length === 1 && nums.length === 1) {
      const vals = p.rows.map(r => numAt(r, nums[0])), pos = vals.every(v => v >= 0) && vals.reduce((a, b) => a + b, 0) > 0;
      add("bar", n > 20 ? T("why.bar_many") : T("why.bar_cats", { n }), true);
      if (n >= 2 && n <= 6 && pos) add("donut", T("why.donut", { n }), false);
    } else if (cats.length === 1 && nums.length >= 2 && nums.length <= 4) {
      add("grouped", T("why.grouped_measures", { n: nums.length }), true);
      add("stacked", T("why.stacked_sum"), false);
    } else if (cats.length === 2 && nums.length === 1) {
      const [series, x] = [...cats].sort((a, b) => a.uniq - b.uniq);
      if (series.uniq <= 6 && x.uniq <= 30) {
        add("grouped", T("why.grouped_series", { series: series.name, x: x.name }), true);
        add("stacked", T("why.stacked_series", { series: series.name, x: x.name }), false);
      }
    }
    if (nums.length >= 2 && n >= 6 && !times.length && !out.some(c => c.kind === "scatter")) add("scatter", T("why.scatter", { a: nums[0].name, b: nums[1].name }), cats.length === 0);
    if (out.length && !out.some(c => c.rec)) out[0].rec = true;
    return out;
  }

  /** Rows that sit on a map: lat/long columns, or at least two distinct entities ster could locate
   *  (`located`, counted by the bridge through ster's /api/locate). One place repeated on every row
   *  is a filter echoed back, not a result: the map would draw a single dot. */
  function mapHint(p, located) {
    return !!(p.lat && p.lon) || (located || 0) >= 2;
  }

  /** Names where an IRI belonged: the text cells that are neither numbers nor addresses, once each. ster looks them
   *  up as labels, to say whether the rows name places or dated things that an IRI-less query hid. */
  function labelsOf(rows) {
    const set = new Set();
    for (const r of rows || []) for (const c of r) {
      const v = String(c ?? "").trim();
      if (v.length >= 3 && v.length <= 80 && !isIri(v) && !/^-?[\d.,\s]+$/.test(v)) set.add(v);
    }
    return [...set].slice(0, 300);
  }

  /* ---------------- time frise ---------------- */
  const DAY = 864e5;
  // Annotation dates: who made the data and when, not what the data is about. Shown only on request.
  const PROV = /(www\.w3\.org\/ns\/prov#|\b(prov|dcterms|dct|dc):(startedAtTime|endedAtTime|generatedAtTime|invalidatedAtTime|created|modified|issued|date|available))/i;
  const parseT = v => { if (v == null || v === "") return NaN; const s = String(v).trim(); return /^\d{4}$/.test(s) ? Date.UTC(+s, 0, 1) : Date.parse(s); };
  const hasTime = v => /T\d\d:/.test(String(v));

  /** Dated rows of a result table: one date column is an instant, two are a start and an end. */
  function friseItems(p, query) {
    if (!p.times.length) return [];
    const prov = PROV.test(query || ""), [a, b] = p.times;
    const label = p.cats[0] || p.cols.find(c => c.iri && !c.hidden), lane = p.cats.length > 1 && p.cats[1].uniq <= 8 ? p.cats[1] : null;
    return p.rows.map((r, i) => ({
      label: label ? (label.iri ? local(r[label.i]) : String(r[label.i] ?? "")) : (p.nums[0] ? `${p.nums[0].name} ${r[p.nums[0].i]}` : T("chart.row", { n: i + 1 })),
      lane: lane ? String(r[lane.i] ?? "") : "", start: r[a.i], end: b ? r[b.i] : null, provenance: prov, note: b ? `${a.name} → ${b.name}` : a.name
    })).filter(x => !Number.isNaN(parseT(x.start)));
  }
  /** Dates ster found on the result's entities (/api/timeline items). */
  function entityItems(items) {
    return (items || []).map(it => ({ label: it.label, lane: it.groupLabel || "", start: it.start, end: it.end, provenance: !!(it.provenance || it.auxiliary), note: it.predicateLabel || "", uri: it.uri }));
  }

  function ticks(min, max) {
    const span = max - min, out = [], d0 = new Date(min);
    const push = (ms, label) => { if (ms >= min && ms <= max) out.push({ ms, pos: (ms - min) / span * 100, label }); };
    if (span > 2.5 * 365 * DAY) {
      const yrs = span / (365 * DAY), step = [1, 2, 5, 10, 20, 50, 100, 200].find(s => yrs / s <= 8) || 500;
      for (let y = Math.ceil(d0.getUTCFullYear() / step) * step; Date.UTC(y, 0, 1) <= max; y += step) push(Date.UTC(y, 0, 1), String(y));
    } else if (span > 75 * DAY) {
      const step = [1, 2, 3, 6].find(s => span / (30 * DAY) / s <= 8) || 12;
      let y = d0.getUTCFullYear(), m = Math.ceil(d0.getUTCMonth() / step) * step;
      for (;;) { y += Math.floor(m / 12); m %= 12; const ms = Date.UTC(y, m, 1); if (ms > max) break; push(ms, new Date(ms).toLocaleDateString(LOC, { month: "short", year: "numeric", timeZone: "UTC" })); m += step; }
    } else if (span > 3 * DAY) {
      const step = [1, 2, 7, 14].find(s => span / DAY / s <= 8) || 30;
      for (let ms = Math.ceil(min / (step * DAY)) * step * DAY; ms <= max; ms += step * DAY) push(ms, new Date(ms).toLocaleDateString(LOC, { day: "numeric", month: "short", timeZone: "UTC" }));
    } else {
      const H = 36e5, step = [1, 2, 3, 6, 12].find(s => span / H / s <= 8) || 24;
      for (let ms = Math.ceil(min / (step * H)) * step * H; ms <= max; ms += step * H) push(ms, new Date(ms).toLocaleTimeString(LOC, { hour: "2-digit", minute: "2-digit" }));
    }
    return out;
  }

  /** Positions for a frise: lanes by group, items packed into rows so labels do not overlap (W = assumed pixel width). */
  function friseModel(items, W = 700) {
    let pts = items.map(it => { const s = parseT(it.start); let e = it.end ? parseT(it.end) : NaN; if (!(e > s)) e = NaN; return Object.assign({}, it, { s, e }); }).filter(x => !Number.isNaN(x.s));
    if (!pts.length) return null;
    const truncated = pts.length > 200 ? pts.length : 0; pts = pts.slice(0, 200);
    const first = pts.reduce((a, b) => b.s < a.s ? b : a), lastP = pts.reduce((a, b) => (Number.isNaN(b.e) ? b.s : b.e) > (Number.isNaN(a.e) ? a.s : a.e) ? b : a);
    const from = first.start, to = Number.isNaN(lastP.e) ? lastP.start : lastP.end;
    let min = Math.min(...pts.map(x => x.s)), max = Math.max(...pts.map(x => Number.isNaN(x.e) ? x.s : x.e));
    if (max === min) { min -= DAY / 2; max += DAY / 2; } else { const pad = (max - min) * 0.04; min -= pad; max += pad; }
    const span = max - min, order = [], byLane = new Map();
    pts.forEach(x => { const k = x.lane || T("chart.dates"); if (!byLane.has(k)) { byLane.set(k, []); order.push(k); } byLane.get(k).push(x); });
    const lanes = order.map(label => {
      const list = byLane.get(label).sort((a, b) => a.s - b.s), ends = [];
      const placed = list.map(x => {
        const left = (x.s - min) / span, x0 = left * W, x1 = Number.isNaN(x.e) ? x0 + 10 : Math.max((x.e - min) / span * W, x0 + 6);
        const txt = String(x.label).length * 6.3 + 8, flip = left > 0.78, lo = flip ? x0 - txt : x0, hi = flip ? x1 : x1 + txt;
        let row = ends.findIndex(e => e + 6 < lo); if (row < 0) { row = ends.length; ends.push(0); } ends[row] = hi;
        return { label: x.label, note: x.note, start: x.start, end: x.end, provenance: x.provenance, uri: x.uri, left: left * 100, width: Number.isNaN(x.e) ? null : (x.e - x.s) / span * 100, row, flip };
      });
      return { label, count: list.length, rows: ends.length, items: placed };
    });
    return { min, max, from, to, ticks: ticks(min, max), lanes, truncated };
  }
  const fmtT = (v) => { const t = parseT(v); if (Number.isNaN(t)) return String(v); const s = String(v).trim(); return /^\d{4}$/.test(s) ? s : new Date(t).toLocaleString(LOC, hasTime(v) ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium", timeZone: "UTC" }); };

  /* ---------------- Chart.js configs ---------------- */
  const NONE = "rgba(0,0,0,0)";

  function baseOptions(t, legend) {
    return {
      responsive: true, maintainAspectRatio: false, animation: false,
      layout: { padding: { top: 4, right: 30 } },
      plugins: {
        legend: { display: legend, position: "bottom", labels: { color: t.ink2, usePointStyle: true, pointStyle: "rect", boxWidth: 9, boxHeight: 9, padding: 14, font: { size: 12 } } },
        tooltip: { backgroundColor: t.ink, titleColor: t.bg, bodyColor: t.bg, padding: 8, cornerRadius: 6, boxPadding: 4, callbacks: { label: c => `${c.dataset.label ? c.dataset.label + ": " : ""}${NF().format(c.parsed.y ?? c.parsed.x ?? c.parsed)}` } }
      }
    };
  }
  const axis = (t, o = {}) => Object.assign({ ticks: { color: t.ink3, font: { size: 11 }, callback: v => typeof v === "number" ? NF().format(v) : v }, grid: { color: t.line, drawTicks: false }, border: { color: t.line } }, o);
  /** Category axis: no grid, and no number formatter (Chart.js hands it the index, not the label). */
  const noGrid = (t, o = {}) => { const a = axis(t, Object.assign({ grid: { display: false } }, o)); delete a.ticks.callback; return a; };

  /** Writes the value at the end of each bar when there are few enough bars to read. */
  const valueLabels = (t, horizontal) => ({
    id: "valueLabels",
    afterDatasetsDraw(chart) {
      if (chart.data.datasets.length !== 1 || chart.data.labels.length > 15) return;
      const { ctx } = chart; ctx.save(); ctx.fillStyle = t.ink2; ctx.font = "11px 'Instrument Sans', system-ui, sans-serif"; ctx.textBaseline = "middle";
      chart.getDatasetMeta(0).data.forEach((bar, i) => {
        const v = chart.data.datasets[0].data[i], s = NF().format(v);
        if (horizontal) { ctx.textAlign = "left"; ctx.fillText(s, bar.x + 6, bar.y); } else { ctx.textAlign = "center"; ctx.textBaseline = "bottom"; ctx.fillText(s, bar.x, bar.y - 4); }
      });
      ctx.restore();
    }
  });

  function foldTop(pairs, keep, t) {
    if (pairs.length <= keep + 5) return { pairs, colors: pairs.map(() => t.series[0]) };
    const top = pairs.slice(0, keep), rest = pairs.slice(keep);
    top.push([T("chart.others", { n: rest.length }), rest.reduce((a, b) => a + b[1], 0)]);
    return { pairs: top, colors: top.map((_, i) => i === keep ? t.ink3 : t.series[0]) };
  }

  function config(kind, p, t) {
    const { nums, cats, times, rows } = p, S = t.series;
    if (kind === "kpi") {
      const r = rows[0], lead = cats[0];
      return { kpi: nums.map(c => ({ label: lead ? `${catAt(r, lead)} · ${c.name}` : c.name, value: NF().format(numAt(r, c)) })) };
    }
    if (kind === "bar" && !times.length) {
      const c = cats[0], m = nums[0];
      const sorted = rows.map(r => [catAt(r, c), numAt(r, m)]).sort((a, b) => b[1] - a[1]);
      const { pairs, colors } = foldTop(sorted, 15, t);
      const horizontal = pairs.length > 5 || Math.max(...pairs.map(x => x[0].length)) > 10;
      const o = baseOptions(t, false);
      o.indexAxis = horizontal ? "y": "x";
      o.scales = horizontal ? { x: axis(t, { beginAtZero: true }), y: noGrid(t) } : { x: noGrid(t), y: axis(t, { beginAtZero: true }) };
      return { type: "bar", height: horizontal ? Math.max(120, pairs.length * 28 + 36) : 280, plugins: [valueLabels(t, horizontal)], options: o,
        data: { labels: pairs.map(x => x[0]), datasets: [{ label: m.name, data: pairs.map(x => x[1]), backgroundColor: colors, borderRadius: 4, borderSkipped: false, maxBarThickness: 22 }] } };
    }
    if (kind === "bar" && times.length) { // one bar per period
      const tc = times[0], sorted = [...rows].sort((a, b) => String(a[tc.i]).localeCompare(String(b[tc.i])));
      const o = baseOptions(t, nums.length > 1); o.scales = { x: noGrid(t), y: axis(t, { beginAtZero: true }) };
      return { type: "bar", height: 280, plugins: [valueLabels(t, false)], options: o,
        data: { labels: sorted.map(r => String(r[tc.i])), datasets: nums.slice(0, 4).map((m, i) => ({ label: m.name, data: sorted.map(r => numAt(r, m)), backgroundColor: S[i], borderRadius: 4, borderSkipped: false, maxBarThickness: 28 })) } };
    }
    if (kind === "donut") {
      const c = cats[0], m = nums[0], pairs = rows.map(r => [catAt(r, c), numAt(r, m)]).sort((a, b) => b[1] - a[1]), total = pairs.reduce((a, b) => a + b[1], 0);
      const o = baseOptions(t, true); o.cutout = "62%";
      o.plugins.legend.position = "right";
      o.plugins.tooltip.callbacks.label = ctx => `${ctx.label} : ${NF().format(ctx.parsed)} (${Math.round(ctx.parsed / total * 100)} %)`;
      const center = { id: "center", afterDraw(chart) {
        const a = chart.chartArea; if (!a) return; const { ctx } = chart; ctx.save(); ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillStyle = t.ink; ctx.font = "600 22px 'Instrument Sans', system-ui, sans-serif"; ctx.fillText(NF().format(total), (a.left + a.right) / 2, (a.top + a.bottom) / 2 - 6);
        ctx.fillStyle = t.ink3; ctx.font = "11px 'Instrument Sans', system-ui, sans-serif"; ctx.fillText(m.name, (a.left + a.right) / 2, (a.top + a.bottom) / 2 + 14); ctx.restore(); } };
      return { type: "doughnut", height: 260, plugins: [center], options: o,
        data: { labels: pairs.map(x => x[0]), datasets: [{ data: pairs.map(x => x[1]), backgroundColor: pairs.map((_, i) => S[i]), borderColor: t.surface, borderWidth: 2 }] } };
    }
    if (kind === "grouped" || kind === "stacked") {
      const stacked = kind === "stacked"; let labels, datasets;
      if (cats.length === 2) { // pivot: the category with fewer values becomes the series
        const [sc, xc] = [...cats].sort((a, b) => a.uniq - b.uniq), m = nums[0];
        labels = [...new Set(rows.map(r => catAt(r, xc)))];
        datasets = [...new Set(rows.map(r => catAt(r, sc)))].map((s, i) => ({ label: s, data: labels.map(l => rows.filter(r => catAt(r, xc) === l && catAt(r, sc) === s).reduce((a, r) => a + numAt(r, m), 0)), backgroundColor: S[i] }));
      } else {
        const c = cats[0]; labels = rows.map(r => catAt(r, c));
        datasets = nums.map((m, i) => ({ label: m.name, data: rows.map(r => numAt(r, m)), backgroundColor: S[i] }));
      }
      datasets.forEach(d => Object.assign(d, { borderRadius: stacked ? 2 : 4, borderSkipped: false, maxBarThickness: 26, borderColor: stacked ? t.surface : NONE, borderWidth: stacked ? 2 : 0 }));
      const horizontal = labels.length > 6 || Math.max(...labels.map(l => l.length)) > 10, o = baseOptions(t, true);
      o.indexAxis = horizontal ? "y": "x";
      const val = axis(t, { beginAtZero: true, stacked }), cat = noGrid(t, { stacked });
      o.scales = horizontal ? { x: val, y: cat } : { x: cat, y: val };
      return { type: "bar", height: horizontal ? Math.max(160, labels.length * (stacked ? 28 : 18 * datasets.length) + 70) : 300, options: o, data: { labels, datasets } };
    }
    if (kind === "line") {
      const tc = times[0], sorted = [...rows].sort((a, b) => String(a[tc.i]).localeCompare(String(b[tc.i]))), labels = [...new Set(sorted.map(r => String(r[tc.i])))];
      let datasets;
      if (cats.length === 1 && nums.length === 1) datasets = [...new Set(sorted.map(r => catAt(r, cats[0])))].slice(0, 6).map((s, i) => ({ label: s, data: labels.map(l => { const r = sorted.find(r => String(r[tc.i]) === l && catAt(r, cats[0]) === s); return r ? numAt(r, nums[0]) : null; }), color: S[i] }));
      else datasets = nums.slice(0, 4).map((m, i) => ({ label: m.name, data: labels.map(l => { const r = sorted.find(r => String(r[tc.i]) === l); return r ? numAt(r, m) : null; }), color: S[i] }));
      datasets.forEach(d => { const last = d.data.length - 1; Object.assign(d, { borderColor: d.color, backgroundColor: d.color, borderWidth: 2, tension: 0, spanGaps: true, pointRadius: d.data.map((_, i) => i === last ? 4 : 0), pointHoverRadius: 5 }); });
      const o = baseOptions(t, datasets.length > 1); o.scales = { x: noGrid(t), y: axis(t) }; o.interaction = { mode: "index", intersect: false };
      return { type: "line", height: 280, options: o, data: { labels, datasets } };
    }
    if (kind === "scatter") {
      const xc = nums[0], yc = nums[1], lc = cats[0];
      const pts = rows.map(r => ({ x: numAt(r, xc), y: numAt(r, yc), l: lc ? catAt(r, lc) : "" }));
      const o = baseOptions(t, false);
      o.plugins.tooltip.callbacks.label = c => `${c.raw.l ? c.raw.l + " · ": ""}${xc.name} ${NF().format(c.raw.x)}, ${yc.name} ${NF().format(c.raw.y)}`;
      o.scales = { x: axis(t, { title: { display: true, text: xc.name, color: t.ink3 } }), y: axis(t, { title: { display: true, text: yc.name, color: t.ink3 } }) };
      return { type: "scatter", height: 300, options: o, data: { datasets: [{ data: pts, backgroundColor: S[0], borderColor: t.surface, borderWidth: 1.5, pointRadius: 5, pointHoverRadius: 7 }] } };
    }
    return null;
  }

  const api = { profile, candidates, config, mapHint, labelsOf, friseItems, entityItems, friseModel, fmtT, local, setI18n };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.Viz = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
