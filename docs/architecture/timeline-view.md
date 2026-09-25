# Timeline view — what it does, and how it is put together

> Implemented. `ster/time_shapes.py`, `ster/time_results.py`,
> `ster/timeline_html.py`, `ster/assets/timeline_app.js`, plus the routes and
> bindings listed below.

## What the reader gets

A navigable frieze of everything the open file dates. Zoom runs continuously
from the hour to two centuries, the axis relabelling itself as it goes; drag to
pan. One lane per class, one item per moment.

- **Instants** are boxes, **intervals** are bars. Colour says which, and a
  PROV-O moment is violet whichever shape it takes: the shape still says instant
  or interval, the colour says this is the record of a fact rather than the fact.
- Items carry their metadata: the entity's label, a `schema:image` thumbnail
  where one exists, and the predicate that dated it, so the same entity dated
  twice reads as two facts rather than one blurred one.
- Clicking an item opens the detail panel — URI, the moment, the markdown note —
  and then enriches it from `/api/node-detail`, the endpoint the graph and map
  views already use, so an entity reads the same way wherever it is clicked.
- A chip per lane narrows the frieze to it, with a count. The map's model:
  chips hold what was *picked*, never what was dropped, so every lane stays on
  screen and a pick can be undone. Nothing picked means no filter.
- The query is visible and editable, and re-running redraws.

It refuses to open on a file with no dates at all, saying so. An empty frieze
reads as a broken feature, and the reader cannot tell it apart from one that
failed to load — the rule `anything_located` already applies to the map.

- Two date inputs, **After**/**Before**, bound the frieze to a range — either
  alone, or both for "between". They filter *moments*, not entities, and they
  reissue only `POST /api/timeline` for the query's existing rows, not the
  SPARQL query itself. Set, they also become vis-timeline's own `min`/`max`
  options, so panning cannot drag past a bound the data has already been
  trimmed to — one native feature doing what a second custom guard would
  otherwise have to.

## Why the bound cannot live in the SPARQL query

The obvious way to ask for "events after 2025" is a `FILTER` on the date in the
query itself. It does not work here, and the reason is structural rather than a
missing feature: the query's job is to pick *entities* — the rows carry URIs, or
`?entity`/`?date` pairs where only the URI survives into `timeline_items`. Once
an entity is picked, every one of its moments is resolved and drawn, because
that is the one property `timeline_items` promises (`test_one_item_per_moment_
not_per_entity`). A document approved in 2022 and re-read in 2026 is one entity
with two moments; a `FILTER(?date >= "2025")` that matches its 2026 moment picks
the *entity*, and the entity brings its 2022 moment along for free. Narrowing the
query cannot narrow what a chosen entity shows — only narrowing the moments
themselves can, which is why `after`/`before` are a separate parameter to
`timeline_items`, applied after resolution, rather than something expressed in
SPARQL. See `time_shapes._moment_in_range` and its tests
(`test_an_entity_dated_twice_can_lose_only_its_earlier_moment` et al.) for the
case this exists to get right.

An interval is judged by overlap, not containment: kept whole the instant either
end touches the requested range, never clipped to it — a five-year permit is
still "in range" for a "since 2025" query even though it started in 2022.

## The rule that decides what is drawn

`geo_shapes` keys on the literal's **datatype**, and that works because a
`geo:wktLiteral` carries its own completeness: the literal alone is a shape. The
same trick applied to time gets you halfway and then lies. `xsd:date` announces
that a value is a date; it says nothing about the date's *role*, and a role is
what an interval is made of.

Measured on a real file before the rule was written: **47 dated entities, 6
carrying two dates each, of which exactly one was an interval.** The other five
paired a document's own date with the date it was consulted. A PLU approved in
2022 and read in 2026 is not a four-year event. A rule inferring spans from
adjacency would have drawn five bars out of six wrong.

So the rule is in two halves:

**Datatypes place a point.** Any literal typed `xsd:date`, `xsd:dateTime`,
`xsd:dateTimeStamp`, `xsd:gYear` or `xsd:gYearMonth`, under *any* predicate,
becomes an instant. A registry of predicate names would be endless; a registry
of five datatypes catches every vocabulary, including ones written later.
`xsd:time` and `xsd:duration` are excluded on purpose: a time with no date and a
length with no anchor cannot be placed on an axis.

**Declarations make a span.** An interval exists only where the pair of
predicates is stated — by a standard vocabulary, or by the file itself:

```turtle
@prefix st: <https://ster.dev/ns/time#> .

ant:Delai st:interval [ st:from ant:debuteLe ; st:to ant:expireLe ] .
```

Recognised without declaration: `schema:startDate`/`endDate` (both the http and
https spellings, since real files carry either), `prov:startedAtTime`/
`endedAtTime`, and OWL-Time's `time:hasBeginning`/`hasEnd`. Deliberately *not*
paired: `dcterms:created`/`modified`, which are two events in a life rather than
the ends of one span.

A pair naming the same predicate at both ends is refused rather than trusted: it
is one date written twice, and it draws a zero-length bar nobody can see or
click. Found by writing exactly that declaration while testing — the same shape
of guard as `geo_shapes` refusing a symmetric property as containment.

**Lanes come from the class**, not the predicate: an entity's most specific
declared type, minus any a sibling declaration implies. A file gains a lane by
gaining a class, with no code change.

**Reach is inward.** Asking for the timeline "of" an entity returns what points
*at* it, up to three hops — never what it points to. A procedure carries no date
of its own; its deposit, its deadline and its decision carry them all. Following
links outward walks up the model and back down somebody else's branch, which is
how a selection ends up owning every date in the file.

## How it fits together

```
   TUI                    SPARQL screen              MCP agent
   t → action_open_        ctrl+t → action_          get_timeline
   timeline                timeline                  {uri?, limit?}
   (tui/app/_actions)      (tui/query_screen)        (mcp_server → mcp_context)
        │                        │                        │
        │  tui/query.timeline_url(sparql, focus)          │ in-process:
        │  tui/query.dated_count(graph, result)           │ same resolution,
        └────────────┬───────────┘                        │ returns items + url
                     ▼                                    ▼
      ┌──────────────────────────────────────────────────────────────┐
      │                      ster's HTTP server (api.py)             │
      │                                                              │
      │  GET  /timeline?q=&focus=   → timeline_html.render_timeline_ │
      │       page: no-cache, token embedded, never in the URL       │
      │  POST /api/sparql_query     → rows for the page's query      │
      │  POST /api/timeline {uris}  → {items, lanes, span}           │
      │  GET  /api/node-detail?uri= → the shared detail panel        │
      │  POST /mcp                  → JSON-RPC, incl. get_timeline   │
      └───────────────┬──────────────────────────────────────────────┘
                      │ resolution happens here, once, never in JS
        ┌─────────────▼───────────────┐      ┌──────────────────────┐
        │  time_shapes.py             │      │  time_results.py     │
        │   moments_of / is_dated     │◄─────│   timeline / result_ │
        │   declared_pairs            │      │   uris / dated_count │
        │   dated_from / lane_of      │      └──────────────────────┘
        │   timeline_items / span_of  │
        └─────────────┬───────────────┘
                      │ label_of · image_of · most_specific_types
                      │ reachable_inward · vendored
              ┌───────▼────────┐
              │ viz_shared.py  │  ← geo_* will import this too (viz-layout.md)
              └────────────────┘

   browser page
   ┌──────────────────────────────────────────────────────────────────┐
   │ vis-timeline 7.7.3   inlined from ~/.cache/ster (JS + CSS)       │  vendored
   ├──────────────────────────────────────────────────────────────────┤
   │ assets/timeline_app.js   fetch → render → filter → detail        │  app
   ├──────────────────────────────────────────────────────────────────┤
   │ window.__STER_TIMELINE__ = { token, after, before }              │  data
   └──────────────────────────────────────────────────────────────────┘
```

The three browser layers are the separation `viz_vowl` already keeps with
Cytoscape: swapping the library must never touch the application code, and
neither of them holds ontology data.

## Endpoints

| Route | Auth | Returns |
|---|---|---|
| `GET /timeline` | open | The page. `q` primes the editor, `focus` makes the server build a query over what that entity stands over, `after`/`before` prime the range inputs |
| `POST /api/timeline` | bearer | `{items, lanes, span}` for the URIs sent, filtered to `after`/`before` when given |
| `POST /api/sparql_query` | bearer | The page's own query runs here, not through `/mcp` — MCP is how an agent talks to the server, and a page is not an agent. Also takes `after`/`before`, which bound `view_count`/`view_url` when `view: "timeline"` |
| `GET /api/node-detail` | bearer | Shared with the graph and map detail panels |

The page is open and embeds its token, exactly as `/viz` and `/map` do: it keeps
credentials out of browser history while letting the page call the server.

`/timeline` sends `Cache-Control: no-cache, no-store, must-revalidate`. Without
it a browser keeps serving yesterday's inlined app layer after an edit — a
confusing failure the author hits before any user does.

## MCP

`get_timeline` takes an optional `uri` and `limit` and returns the items, their
count, whether they were truncated, the span, and **the page's URL**. Both,
because an agent that can only describe the data makes the reader go looking,
and one that can only hand over a link cannot reason about what it sent. They
come from the same resolution the page uses, so a claim the agent makes and a
bar the reader sees cannot disagree.

`get_timeline`, `run_sparql` and `open_view` all also take optional `after`/
`before` (any `xsd:date`/`dateTime`/`gYear` form, compared lexically so
precision may differ on either side). One parameter shape across all three,
`view_links.DateRange`, so an agent reaches the same range filter whichever tool
it started from. `open_view`'s returned `url` carries the bound as `&after=`/
`&before=` query params, so reopening the link later reproduces the same
bounded view rather than the unbounded one a bare `?q=` would.

## Dependencies this view adds

| What | Version | Where pinned | How it is loaded |
|---|---|---|---|
| vis-timeline (JS) | 7.7.3 | `timeline_html._VIS_VERSION` | Downloaded once from cdnjs into `~/.cache/ster`, then inlined into the page |
| vis-timeline (CSS) | 7.7.3 | same | same — the first vendored asset in ster that needs a stylesheet |

No new Python dependency: the module uses `rdflib` and the standard library only.
If the download fails the page falls back to a CDN `<script src=…>` tag rather
than rendering blank, so a first run without network degrades instead of
breaking; a cached run needs no network at all.

`vis` is declared as a browser global in `eslint.config.js`, beside `cytoscape`
and `d3`.

## Extending

- **A new interval** — declare the pair with `st:interval`. No code change.
- **A new lane** — give the entities a class. No code change.
- **Thumbnails** — `schema:image` (or whatever `store.IMAGE_PREDICATES` lists).
- **A different default view** — `timeline_html.DEFAULT_TIMELINE_QUERY`.

## Tests

`tests/unit/test_time_shapes.py` (14) pins the rule, including the two traps it
exists to avoid: two unrelated dates staying two instants, and a self-referring
pair being refused. `test_time_results.py` (9) covers stated date columns, both
languages' column names, and dating a row through its entity when the query
never mentioned time. `test_timeline_page.py` (8) covers the routes and runs
`node --check` over both the rendered page and the asset — the hole
`test_map_page_syntax.py` documents, closed for this view from the start.
