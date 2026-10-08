"use strict";
// Chart choice, map hint and frise model (viz.js). Run: node --test agent-app/tests/*.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const Viz = require("../agent_app/static/viz.js");

const NS = "https://example.org/onto#";
const THEME = { series: ["#1", "#2", "#3", "#4", "#5", "#6", "#7", "#8"], ink: "#000", ink2: "#111", ink3: "#999", line: "#ddd", surface: "#fff", bg: "#fff" };
const table = (columns, rows) => Viz.profile(columns, rows);
const kinds = p => Viz.candidates(p).map(c => c.kind);
const rec = p => Viz.candidates(p).find(c => c.rec)?.kind;
const seq = (n, f) => Array.from({ length: n }, (_, i) => f(i));

test.beforeEach(() => Viz.setI18n(k => k, "en"));

test("columns are typed from their values", () => {
  const p = table(["name", "n", "postalCode", "opened", "lat", "long", "empty", "code0"],
    [["A", "3", "59000", "2020-05-01", "50.1", "3.2", "", "007"], ["B", "-4.5", "62000", "2021-01-02", "49.9", "2.1", "", "012"]]);
  const type = Object.fromEntries(p.cols.map(c => [c.name, c.type]));
  assert.deepEqual(type, { name: "cat", n: "num", postalCode: "cat", opened: "time", lat: "lat", long: "lon", empty: "empty", code0: "cat" });
});

test("digits that name something are not measures", () => {
  for (const name of ["postal_code", "zip", "siret", "phone", "id", "uri"]) {
    assert.equal(table([name], [["12345"], ["67890"]]).cols[0].type, "cat", name);
  }
});

test("a year column is time only when its name says so, a number otherwise", () => {
  assert.equal(table(["year"], [["2020"], ["2021"]]).cols[0].type, "time");
  assert.equal(table(["stores"], [["2020"], ["2021"]]).cols[0].type, "num");
});

test("an IRI column that pairs one to one with a plain text column is an id, not something to plot", () => {
  const p = table(["s", "whatever", "n"], [[NS + "a", "A", "3"], [NS + "b", "B", "5"], [NS + "c", "C", "2"]]);
  assert.equal(p.cols[0].hidden, true);
  assert.deepEqual(p.cats.map(c => c.name), ["whatever"]);
});

test("an IRI column is kept when nothing labels it", () => {
  const p = table(["s", "n"], [[NS + "a", "3"], [NS + "b", "5"]]);
  assert.equal(p.cols[0].hidden, false);
});

const CASES = [
  ["one value", ["n"], [["18"]], ["kpi"], "kpi"],
  ["category and count, few rows", ["brand", "n"], [["A", "30"], ["B", "13"], ["C", "4"]], ["bar", "donut"], "bar"],
  ["category and count, many rows", ["brand", "n"], seq(12, i => ["B" + i, String(100 - i)]), ["bar"], "bar"],
  ["negative values rule out a doughnut", ["k", "d"], [["a", "5"], ["b", "-2"], ["c", "3"]], ["bar"], "bar"],
  ["several measures", ["c", "a", "b", "d"], [["x", "1", "2", "3"], ["y", "4", "5", "6"]], ["grouped", "stacked"], "grouped"],
  ["two categories and a measure", ["brand", "country", "n"], [["L", "FR", "3"], ["L", "ES", "5"], ["B", "FR", "2"], ["B", "ES", "1"]], ["grouped", "stacked"], "grouped"],
  ["a date and a measure", ["year", "n"], [["2021", "1"], ["2022", "2"], ["2023", "3"]], ["line", "bar"], "line"],
  ["a date and a measure, two points", ["year", "n"], [["2021", "1"], ["2022", "2"]], ["line", "bar"], "bar"],
  ["two measures, many rows", ["name", "a", "b"], seq(8, i => ["n" + i, String(i), String(i * 3)]), ["grouped", "stacked", "scatter"], "grouped"],
  ["names only", ["store"], [["A"], ["B"]], [], undefined],
  ["postal codes are labels", ["store", "postalCode"], [["A", "59000"], ["B", "62000"]], [], undefined],
  ["no rows", ["a", "b"], [], [], undefined],
];
for (const [name, cols, rows, expected, recommended] of CASES) {
  test(`which charts fit: ${name}`, () => {
    const p = table(cols, rows);
    assert.deepEqual(kinds(p), expected);
    assert.equal(rec(p), recommended);
  });
}

test("two categories with too many series produce no chart", () => {
  const p = table(["a", "b", "n"], seq(10, i => ["a" + i, "b" + i, "1"]));
  assert.deepEqual(kinds(p), []);
});

test("exactly one candidate is flagged recommended when there are several", () => {
  const list = Viz.candidates(table(["brand", "n"], [["A", "3"], ["B", "2"]]));
  assert.equal(list.filter(c => c.rec).length, 1);
});

test("every candidate carries a label and a reason from the catalog function", () => {
  Viz.setI18n((k, p) => `${k}:${JSON.stringify(p || {})}`, "en");
  const [bar, donut] = Viz.candidates(table(["brand", "n"], [["A", "3"], ["B", "2"]]));
  assert.equal(bar.label, 'kind.bar:{}');
  assert.equal(bar.why, 'why.bar_cats:{"n":2}');
  assert.equal(donut.why, 'why.donut:{"n":2}');
});

test("map hint: coordinates, or two located places, never one", () => {
  const withCoords = table(["l", "lat", "long"], [["A", "50", "3"], ["B", "49", "2"]]);
  assert.equal(Viz.mapHint(withCoords, 0), true);
  const iris = table(["s"], [[NS + "a"], [NS + "b"]]);
  assert.equal(Viz.mapHint(iris, 2), true);
  assert.equal(Viz.mapHint(iris, 1), false);   // one place repeated on every row is a filter echoed back
  assert.equal(Viz.mapHint(iris, 0), false);
  assert.equal(Viz.mapHint(iris, undefined), false);
});

// ---------------------------------------------------------------- chart configs
test("a single value becomes a key figure", () => {
  const cfg = Viz.config("kpi", table(["n"], [["18"]]), THEME);
  assert.deepEqual(cfg.kpi, [{ label: "n", value: "18" }]);
});

test("numbers are formatted for the active language", () => {
  Viz.setI18n(k => k, "fr");
  assert.match(Viz.config("kpi", table(["n"], [["1234.5"]]), THEME).kpi[0].value, /1\s?234,5/);
  Viz.setI18n(k => k, "en");
  assert.equal(Viz.config("kpi", table(["n"], [["1234.5"]]), THEME).kpi[0].value, "1,234.5");
});

test("bars are sorted from the largest and use the first series colour", () => {
  const cfg = Viz.config("bar", table(["k", "n"], [["a", "1"], ["b", "9"], ["c", "5"]]), THEME);
  assert.deepEqual(cfg.data.labels, ["b", "c", "a"]);
  assert.deepEqual(cfg.data.datasets[0].data, [9, 5, 1]);
  assert.equal(cfg.data.datasets[0].backgroundColor[0], "#1");
});

test("past twenty bars the tail is folded into one grey 'Others' bar", () => {
  Viz.setI18n((k, p) => (k === "chart.others" ? `Others (${p.n})` : k), "en");
  const cfg = Viz.config("bar", table(["k", "n"], seq(30, i => ["k" + i, String(100 - i)])), THEME);
  assert.equal(cfg.data.labels.length, 16);
  assert.equal(cfg.data.labels.at(-1), "Others (15)");
  assert.equal(cfg.data.datasets[0].backgroundColor.at(-1), "#999");
  const total = seq(30, i => 100 - i).reduce((a, b) => a + b);
  assert.equal(cfg.data.datasets[0].data.reduce((a, b) => a + b), total);   // nothing is lost by folding
});

test("category axis labels are not run through the number formatter", () => {
  // regression: Chart.js hands a category axis the index, and the formatter turned names into 0, 1, 2
  const cfg = Viz.config("bar", table(["k", "n"], seq(8, i => ["name" + i, "1"])), THEME);
  const cat = cfg.options.indexAxis === "y" ? cfg.options.scales.y : cfg.options.scales.x;
  assert.equal(cat.ticks.callback, undefined);
  const value = cfg.options.indexAxis === "y" ? cfg.options.scales.x : cfg.options.scales.y;
  assert.equal(typeof value.ticks.callback, "function");
});

test("many or long labels turn bars horizontal and give them room", () => {
  const many = Viz.config("bar", table(["k", "n"], seq(8, i => ["n" + i, "1"])), THEME);
  assert.equal(many.options.indexAxis, "y");
  assert.ok(many.height >= 8 * 28);
  const few = Viz.config("bar", table(["k", "n"], [["a", "1"], ["b", "2"]]), THEME);
  assert.equal(few.options.indexAxis, "x");
  assert.equal(few.height, 280);
});

test("a doughnut shows parts of the total in the centre", () => {
  const cfg = Viz.config("donut", table(["k", "n"], [["a", "3"], ["b", "1"]]), THEME);
  assert.equal(cfg.type, "doughnut");
  assert.deepEqual(cfg.data.datasets[0].data, [3, 1]);
  assert.equal(cfg.plugins[0].id, "center");
});

test("grouped and stacked bars: one dataset per measure, stacking only when asked", () => {
  const p = table(["c", "a", "b"], [["x", "1", "2"], ["y", "3", "4"]]);
  const grouped = Viz.config("grouped", p, THEME), stacked = Viz.config("stacked", p, THEME);
  assert.equal(grouped.data.datasets.length, 2);
  assert.equal(grouped.options.scales.y.stacked, false);
  assert.equal(stacked.options.scales.y.stacked, true);
  assert.equal(stacked.data.datasets[0].borderWidth, 2);      // a surface gap between stacked segments
});

test("two categories pivot: the one with fewer values becomes the series", () => {
  const rows = [["L", "FR", "3"], ["L", "ES", "5"], ["B", "FR", "2"], ["B", "ES", "1"], ["C", "FR", "4"], ["C", "ES", "6"]];   // 3 brands, 2 countries
  const cfg = Viz.config("grouped", table(["brand", "country", "n"], rows), THEME);
  assert.deepEqual([...cfg.data.labels].sort(), ["B", "C", "L"]);
  assert.equal(cfg.data.datasets.length, 2);
  assert.deepEqual(cfg.data.datasets.map(d => d.label).sort(), ["ES", "FR"]);
});

test("a line is ordered by time and marks only its last point", () => {
  const cfg = Viz.config("line", table(["year", "n"], [["2023", "3"], ["2021", "1"], ["2022", "2"]]), THEME);
  assert.deepEqual(cfg.data.labels, ["2021", "2022", "2023"]);
  assert.deepEqual(cfg.data.datasets[0].data, [1, 2, 3]);
  assert.deepEqual(cfg.data.datasets[0].pointRadius, [0, 0, 4]);
});

test("a scatter plots the first two measures", () => {
  const cfg = Viz.config("scatter", table(["name", "a", "b"], seq(6, i => ["n" + i, String(i), String(i * 2)])), THEME);
  assert.equal(cfg.data.datasets[0].data[2].x, 2);
  assert.equal(cfg.data.datasets[0].data[2].y, 4);
  assert.equal(cfg.data.datasets[0].data[2].l, "n2");
});

test("an unknown kind has no config", () => {
  assert.equal(Viz.config("nope", table(["k", "n"], [["a", "1"]]), THEME), null);
});

// ---------------------------------------------------------------- frise
test("dated rows become frise items; one date is an instant, two are an interval", () => {
  const inst = Viz.friseItems(table(["store", "opened"], [["Lille", "2004-05-12"], ["Lyon", "2009-03-01"]]), "SELECT");
  assert.deepEqual(inst.map(i => [i.label, i.start, i.end]), [["Lille", "2004-05-12", null], ["Lyon", "2009-03-01", null]]);
  const span = Viz.friseItems(table(["project", "from", "to"], [["A", "2020-01-01", "2021-06-30"]]), "SELECT");
  assert.equal(span[0].end, "2021-06-30");
  assert.equal(span[0].note, "from → to");
});

test("a second category column becomes the lane", () => {
  const items = Viz.friseItems(table(["store", "country", "opened"], [["Lille", "FR", "2004-05-12"], ["Madrid", "ES", "2011-02-10"]]), "");
  assert.deepEqual(items.map(i => i.lane), ["FR", "ES"]);
});

test("annotation dates are recognised from the vocabulary the query uses", () => {
  const p = table(["b", "t"], [[NS + "b1", "2026-09-04T19:12:43+00:00"], [NS + "b2", "2026-09-14T20:20:10+00:00"]]);
  for (const q of ["SELECT ?b ?t WHERE { ?b prov:startedAtTime ?t }", "?x dcterms:modified ?t", "http://www.w3.org/ns/prov#generatedAtTime"]) {
    assert.equal(Viz.friseItems(p, q)[0].provenance, true, q);
  }
  assert.equal(Viz.friseItems(p, "SELECT ?b ?t WHERE { ?b ex:openedOn ?t }")[0].provenance, false);
});

test("ster's own provenance flags are honoured for entity dates", () => {
  const items = Viz.entityItems([{ label: "a", start: "2026-01-01", provenance: true }, { label: "b", start: "2026-01-02", auxiliary: true }, { label: "c", start: "2026-01-03" }]);
  assert.deepEqual(items.map(i => i.provenance), [true, true, false]);
});

test("no dates, no frise items", () => {
  assert.deepEqual(Viz.friseItems(table(["a", "n"], [["x", "1"]]), ""), []);
  assert.equal(Viz.friseModel([]), null);
  assert.equal(Viz.friseModel([{ label: "x", start: "not a date" }]), null);
});

test("the axis scale follows the span", () => {
  const model = (a, b) => Viz.friseModel([{ label: "a", start: a }, { label: "b", start: b }]);
  const labels = m => m.ticks.map(t => t.label);
  assert.deepEqual(labels(model("2004-01-01", "2021-01-01")).slice(0, 2), ["2005", "2010"]);        // years
  assert.match(labels(model("2020-01-01", "2021-06-30"))[0], /2020/);                                  // months
  assert.ok(model("2026-09-04", "2026-09-14").ticks.length >= 3);                                      // days
  assert.ok(model("2026-09-04T08:00:00Z", "2026-09-04T17:45:00Z").ticks.length >= 3);                  // hours
});

test("ticks sit inside the axis and are in order", () => {
  const m = Viz.friseModel([{ label: "a", start: "2004-05-12" }, { label: "b", start: "2021-01-15" }]);
  assert.ok(m.ticks.every(t => t.pos >= 0 && t.pos <= 100));
  assert.deepEqual(m.ticks.map(t => t.ms), [...m.ticks.map(t => t.ms)].sort((a, b) => a - b));
});

test("lanes keep the order they first appear in and count their items", () => {
  const m = Viz.friseModel([{ label: "a", start: "2020-01-01", lane: "FR" }, { label: "b", start: "2021-01-01", lane: "ES" }, { label: "c", start: "2022-01-01", lane: "FR" }]);
  assert.deepEqual(m.lanes.map(l => [l.label, l.count]), [["FR", 2], ["ES", 1]]);
});

test("crowded labels are packed into extra rows instead of overlapping", () => {
  const items = seq(12, i => ({ label: "Store number " + i, start: `2020-01-${String(i + 1).padStart(2, "0")}` }));
  const lane = Viz.friseModel(items).lanes[0];
  assert.ok(lane.rows > 1);
  for (let r = 0; r < lane.rows; r++) {
    const row = lane.items.filter(i => i.row === r).sort((a, b) => a.left - b.left);
    for (let i = 1; i < row.length; i++) assert.ok(row[i].left > row[i - 1].left);
  }
});

test("items near the right edge put their label on the left", () => {
  const m = Viz.friseModel([{ label: "early", start: "2000-01-01" }, { label: "late", start: "2020-01-01" }]);
  const [early, late] = m.lanes[0].items;
  assert.equal(early.flip, false);
  assert.equal(late.flip, true);
});

test("an interval has a width, an instant does not, and an end before the start is an instant", () => {
  const m = Viz.friseModel([{ label: "span", start: "2020-01-01", end: "2021-01-01" }, { label: "dot", start: "2020-06-01" }, { label: "odd", start: "2020-09-01", end: "2020-01-01" }]);
  const by = Object.fromEntries(m.lanes[0].items.map(i => [i.label, i]));
  assert.ok(by.span.width > 0);
  assert.equal(by.dot.width, null);
  assert.equal(by.odd.width, null);
});

test("a single date is given room around it, and the real first and last dates are reported", () => {
  const one = Viz.friseModel([{ label: "x", start: "2020-05-01" }]);
  assert.ok(one.max > one.min);
  const m = Viz.friseModel([{ label: "a", start: "2004-05-12" }, { label: "b", start: "2021-01-15" }]);
  assert.deepEqual([m.from, m.to], ["2004-05-12", "2021-01-15"]);
});

test("a very long list is cut and says how long it was", () => {
  const m = Viz.friseModel(seq(250, i => ({ label: "i" + i, start: "2020-01-01" })));
  assert.equal(m.lanes[0].count, 200);
  assert.equal(m.truncated, 250);
});

test("dates are written for the active language", () => {
  Viz.setI18n(k => k, "en");
  assert.match(Viz.fmtT("2021-05-12"), /May 12, 2021/);
  Viz.setI18n(k => k, "fr");
  assert.match(Viz.fmtT("2021-05-12"), /12 mai 2021/);
  assert.equal(Viz.fmtT("2021"), "2021");
  assert.equal(Viz.fmtT("junk"), "junk");
});

test("local names are read out of IRIs", () => {
  assert.equal(Viz.local(NS + "store-1"), "store-1");
  assert.equal(Viz.local("https://example.org/a/b/c"), "c");
  assert.equal(Viz.local("plain"), "plain");
});

test("names where an IRI belonged are the text cells, once each", () => {
  const rows = [["Store Lille", "Lille", "12", NS + "x"], ["Store Lille", "Arras", "3,5", ""], ["ab", null, "2026-09-01", "  Roubaix  "]];
  assert.deepEqual(Viz.labelsOf(rows), ["Store Lille", "Lille", "Arras", "2026-09-01", "Roubaix"]);
});

test("names are bounded: too short, too long, and more than 300 are dropped", () => {
  assert.deepEqual(Viz.labelsOf([["a", "x".repeat(81)]]), []);
  assert.equal(Viz.labelsOf([Array.from({ length: 400 }, (_, i) => "name " + i)]).length, 300);
  assert.deepEqual(Viz.labelsOf(undefined), []);
});
