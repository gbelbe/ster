"use strict";
// Text helpers (render.js). Everything an agent writes goes through them before it reaches the page.
const test = require("node:test");
const assert = require("node:assert/strict");
const { esc, md, sparql, toolQuestion, stepQuestion, connectionLost } = require("../agent_app/static/render.js");

test("escaping covers the five characters that matter, and null is empty", () => {
  assert.equal(esc(`<a href="x" onclick='y'>&</a>`), "&lt;a href=&quot;x&quot; onclick=&#39;y&#39;&gt;&amp;&lt;/a&gt;");
  assert.equal(esc(null), "");
  assert.equal(esc(undefined), "");
  assert.equal(esc(12), "12");
});

// ---------------------------------------------------------------- markup in an answer must never run
test("raw HTML in an answer is shown as text", () => {
  for (const evil of ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "<iframe src=//evil></iframe>", "<svg onload=alert(1)>"]) {
    const out = md(evil);
    assert.ok(!/<(script|img|iframe|svg)\b/i.test(out), evil);
    assert.ok(out.includes("&lt;"), evil);
  }
});

test("markup is neutralised in every block type", () => {
  const evil = "<img src=x onerror=alert(1)>";
  const doc = `# ${evil}\n\n- ${evil}\n\n1. ${evil}\n\n| h |\n|---|\n| ${evil} |\n\n\`\`\`\n${evil}\n\`\`\`\n\n**${evil}** \`${evil}\``;
  assert.ok(!/<img/i.test(md(doc)));
});

test("only http and https links are links", () => {
  assert.match(md("[ok](https://example.org/a?b=c)"), /<a href="https:\/\/example\.org\/a\?b=c" target="_blank" rel="noopener">ok<\/a>/);
  assert.match(md("[ok](http://example.org)"), /<a href="http:\/\/example\.org"/);
  for (const bad of ["javascript:alert(1)", "data:text/html,<script>1</script>", "vbscript:x", "//evil.example", "ftp://x"]) {
    assert.ok(!md(`[x](${bad})`).includes("<a "), bad);
  }
});

test("a quote inside a link cannot break out of the attribute", () => {
  const out = md('[x](https://a.example/"onmouseover="alert(1))');
  assert.ok(!/\sonmouseover=/i.test(out));
});

test("link text is escaped too", () => {
  assert.ok(!/<b>/.test(md("[<b>x</b>](https://example.org)")));
});

// ---------------------------------------------------------------- the markdown that is supported
test("headings keep their level, shifted below the page's own", () => {
  assert.equal(md("# A"), "<h3>A</h3>");
  assert.equal(md("## A"), "<h4>A</h4>");
  assert.equal(md("#### A"), "<h6>A</h6>");
});

test("paragraphs, with a soft line break joined", () => {
  assert.equal(md("one\ntwo\n\nthree"), "<p>one two</p><p>three</p>");
});

test("bold, italic and code", () => {
  assert.equal(md("**b** *i* `c`"), "<p><strong>b</strong> <em>i</em> <code>c</code></p>");
});

test("code spans keep their content literally", () => {
  assert.equal(md("`a < b`"), "<p><code>a &lt; b</code></p>");
});

test("unordered and ordered lists", () => {
  assert.equal(md("- a\n- b"), "<ul><li>a</li><li>b</li></ul>");
  assert.equal(md("* a\n* b"), "<ul><li>a</li><li>b</li></ul>");
  assert.equal(md("1. a\n2) b"), "<ol><li>a</li><li>b</li></ol>");
});

test("fenced code is kept as written", () => {
  assert.equal(md("```\nSELECT *\n  WHERE {}\n```"), "<pre><code>SELECT *\n  WHERE {}</code></pre>");
});

test("an unclosed fence takes the rest of the text instead of hanging", () => {
  assert.equal(md("```\nabc"), "<pre><code>abc</code></pre>");
});

test("tables", () => {
  const out = md("| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |");
  assert.match(out, /<th>a<\/th><th>b<\/th>/);
  assert.match(out, /<td>3<\/td><td>4<\/td>/);
  assert.equal((out.match(/<tr>/g) || []).length, 3);
});

test("a pipe line without a separator row is just text", () => {
  assert.ok(!md("| a | b |").includes("<table"));
});

test("empty and missing input", () => {
  assert.equal(md(""), "");
  assert.equal(md(null), "");
  assert.equal(md("\n\n  \n"), "");
});

test("a very long list of lines does not take long", () => {
  const started = Date.now();
  md(Array.from({ length: 5000 }, (_, i) => `- item ${i}`).join("\n"));
  assert.ok(Date.now() - started < 1000);
});

// ---------------------------------------------------------------- SPARQL highlighting
test("SPARQL keeps its text and wraps the parts worth colouring", () => {
  const out = sparql("SELECT ?s WHERE { ?s a <http://x/y> . } # note");
  assert.match(out, /<span class="t-kw">SELECT<\/span>/);
  assert.match(out, /<span class="t-var">\?s<\/span>/);
  assert.match(out, /<span class="t-iri">&lt;http:\/\/x\/y&gt;<\/span>/);
  assert.match(out, /<span class="t-cmt"># note<\/span>/);
  assert.equal(
    out,
    '<span class="t-kw">SELECT</span> <span class="t-var">?s</span> <span class="t-kw">WHERE</span> { <span class="t-var">?s</span> <span class="t-kw">a</span> <span class="t-iri">&lt;http://x/y&gt;</span> . } <span class="t-cmt"># note</span>',
  );
});

test("prefixed names, strings and language tags", () => {
  const out = sparql('?s rdfs:label "Bonjour"@fr');
  assert.match(out, /<span class="t-iri">rdfs:label<\/span>/);
  assert.match(out, /<span class="t-str">&quot;Bonjour&quot;@fr<\/span>/);
});

test("keywords are found in any case, and only as whole words", () => {
  assert.match(sparql("select distinct ?x"), /<span class="t-kw">select<\/span> <span class="t-kw">distinct<\/span>/);
  assert.ok(!sparql("selection").includes("t-kw"));
});

test("markup inside a query is never interpreted", () => {
  const out = sparql('SELECT "<img src=x onerror=alert(1)>" <b>');
  assert.ok(!/<img|<b>/.test(out));
});

test("text between tokens is escaped (a bare < or > is not an IRI)", () => {
  const out = sparql("FILTER(?a < 3 && ?b > 2) ?a <img src=x onerror=alert(1)> ?b");
  assert.ok(!/<img/.test(out));
  assert.match(out, /&lt; 3 &amp;&amp; /);
});

test("text after the last token is escaped", () => {
  assert.equal(sparql("?s & <"), '<span class="t-var">?s</span> &amp; &lt;');
});

test("a comment is shown as text, markup and all", () => {
  const out = sparql("# <img src=x onerror=alert(1)>\nSELECT");
  assert.ok(!/<img/.test(out));
  assert.match(out, /<span class="t-cmt"># &lt;img/);
});

test("an empty or missing query is empty", () => {
  assert.equal(sparql(""), "");
  assert.equal(sparql(null), "");
});

test("a call's question is the one ster recorded, else its question argument", () => {
  const call = (input, trace) => ({ name: "run_sparql", input, trace });
  assert.equal(toolQuestion(call({ query: "SELECT 1", question: "from the argument" }, { agent_question: "from the trace" })), "from the trace");
  assert.equal(toolQuestion(call({ query: "SELECT 1", question: "  from the argument " })), "from the argument");
  assert.equal(toolQuestion(call({ query: "SELECT 1" })), "");
  assert.equal(toolQuestion(call({ query: "SELECT 1", question: 42 })), "");
  assert.equal(toolQuestion({ name: "get_overview", input: {} }), "");
  assert.equal(toolQuestion({ name: "get_overview" }), "");
});

test("a step shows each distinct question of its calls once", () => {
  const call = q => ({ name: "run_sparql", input: { query: "SELECT 1", question: q } });
  assert.equal(stepQuestion([call("A"), call("B"), call("A")]), "A · B");
  assert.equal(stepQuestion([call(""), call("B")]), "B");
  assert.equal(stepQuestion([]), "");
});

test("a conversation whose ster was restarted has lost its connection", () => {
  const turns = [{ ster_started: "2026-01-01T10:00:00Z" }, { ster_started: "2026-01-01T10:00:00Z" }];
  assert.equal(connectionLost(turns, "2026-01-01T10:00:00Z"), false);
  assert.equal(connectionLost(turns, "2026-01-01T12:00:00Z"), true);
});

test("the last answer that knows its ster decides", () => {
  const turns = [{ ster_started: "A" }, { ster_started: "B" }, {}];
  assert.equal(connectionLost(turns, "B"), false);
  assert.equal(connectionLost(turns, "A"), true);
});

test("nothing is claimed when either side does not know", () => {
  assert.equal(connectionLost([], "A"), false);
  assert.equal(connectionLost(undefined, "A"), false);
  assert.equal(connectionLost([{}], "A"), false);
  assert.equal(connectionLost([{ ster_started: "A" }], null), false);
});
