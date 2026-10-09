# Architecture: an editable graph view (browser, Cytoscape-based)

Status: **all phases done** (single PR) — see per-phase notes for what's deliberately deferred
Audience: ster maintainers
Related: [core-service.md](core-service.md), [module-layout.md](module-layout.md)

## 1. Why

The goal: display a large ontology, in full, as one browsable and
*editable* graph — filter, search, click a node for a side panel, edit it,
create new relations between nodes.

Two outside options were evaluated and rejected as the core tool:

- **WebVOWL-Legacy** ([paper](https://link.springer.com/chapter/10.1007/978-3-031-99554-5_5),
  [repo](https://github.com/WebVOWL/WebVOWL-Legacy)) — proven, published
  performance work for huge ontologies (O(n²)→O(n) fixes, trie search), but a
  **read-only** standalone app: no editing, no edge creation, no integration
  with ster's live-reload or mutation pipeline. Solves a problem (raw
  visualization at extreme scale) that isn't the one described above.
- **cosmos.gl** (WebGL/GPU rendering engine, MIT core, millions of nodes) — a
  rendering layer only. No built-in edge-creation UI, no node-select
  interactions built for editing. Adopting it would mean building the entire
  interaction layer from scratch on a library this codebase has no
  experience with, while throwing away everything already built.

Neither gets us the one feature that matters most here — editing — for free.
ster's existing `ster/viz_vowl/` + `ster/assets/graph_app.js` (Cytoscape.js)
already has: VOWL visual notation, a working side panel wired to node click
(`showDetail`), live SSE refresh, per-type filtering, a client-side search box
that highlights/dims/activates matches, and individual-count collapsing above
150 individuals (`INDIVIDUAL_COLLAPSE_LIMIT`). Cytoscape also has **official,
maintained extensions for exactly the missing pieces** (edge creation, edge
editing, large-graph layout, subgraph collapsing). Building the editor here
reuses that investment instead of discarding it.

## 2. Scope ("done" for this initiative)

- Filter the graph by node/relation type (already partially there — extend).
- Search across the **whole** ontology, not just what's currently rendered.
- Click a node → side panel shows its detail (already there) **and is
  editable** (new): edit labels/literals, change a class's parent, etc.
- Create a new relation between two existing nodes by drawing it on the
  canvas.
- Edit or delete an existing relation from the canvas.
- Stay usable on the largest real ontologies encountered in practice, not
  just demo-sized ones.

Out of scope for this initiative (call out explicitly, revisit later if
asked): creating brand-new nodes (classes/individuals) directly from the
canvas — start with editing/relating what exists; bulk import; multi-user
concurrent editing beyond what the existing OCC/version check already gives.

## 3. What's already there vs. what's new

| Capability | State |
|---|---|
| VOWL visual notation, legend, per-type filter toggles | done |
| Side panel on node click (read-only) | done |
| Live refresh over SSE | done |
| Client-side search (substring, highlights/dims, Enter-to-activate) | done, but DOM-scoped only (see Phase 2) |
| Individual collapsing above 150 (`INDIVIDUAL_COLLAPSE_LIMIT`) | done |
| Class-level progressive disclosure (whole-graph default vs. focused) | **half-done** — `build_focused_vowl_graph` exists, `/api/graph` doesn't default to it |
| Search across non-rendered nodes | **new** |
| Editable side panel | **new** |
| Create a relation by drawing on the canvas | **new** |
| Edit/delete an existing relation from the canvas | **new** |
| Scalable layout for large ontologies | **new** (currently plain `cose`) |

## 4. Phased plan

### Phase 0 — default to progressive disclosure (days)

`GET /api/graph` (`ster/api.py:~404`) currently always calls the unscoped
`build_vowl_graph`. Make the default view start scoped (root classes only, or
`build_focused_vowl_graph` from a sensible root) and expand on demand, the
same pattern already used for individuals. Ship this alone first and
validate against the largest real ontology available — it may remove most
of the "wall of dots" complaint on its own, before the phases below add
real engineering cost.

**Exit check**: on the largest ontology available today, does the default
view render legibly and stay responsive? If yes, layout work in Phase 1
becomes lower priority.

### Phase 1 — layout & scale (1–2 weeks) — **done**

- Swapped the `cose` layout for
  [`cytoscape-fcose`](https://github.com/iVis-at-Bilkent/cytoscape.js-fcose)
  (same lab as Cytoscape's own bundled `cose-bilkent`, MIT, built for
  large/compound graphs) in both places `graph_app.js` ran a force layout
  (`makeLayout()`, and the incremental `_seedAndSpread` pass after
  explore/merge). `cose`'s force simulation cost grows faster than linearly
  in node count (see the comment already in `_detail.py` about
  individuals) — `fcose` targets exactly that; `layout-base`/`cose-base`
  (fcose's own dependencies) and `fcose` itself are vendored following the
  existing `_js_assets.py` pattern (`_layout_base_script_tag()`,
  `_cose_base_script_tag()`, `_fcose_script_tag()`) and loaded, in that
  order, after `cytoscape` and before the D3 scripts in the HTML template.
- [`cytoscape-expand-collapse`](https://github.com/iVis-at-Bilkent/cytoscape.js-expand-collapse)
  is vendored the same way (`_expand_collapse_script_tag()`) and loaded on
  every render, but **not yet wired into `graph_app.js`** — see the open
  question below. It generalizes the individual-collapsing pattern ster
  already has to the class hierarchy, but the extension's collapse model
  operates on compound (parent/child) nodes, and ster's class hierarchy is
  currently rendered as plain nodes joined by `subClassOf` *edges* (arrows),
  matching VOWL's visual notation. Turning the hierarchy into nested compound
  boxes to make expand-collapse's cues apply would change that visual
  language for every ontology, not just large ones — a product call, not
  just a code one, so it's left open rather than decided unilaterally here.
  Phase 0's progressive disclosure (root-only default + click-to-expand)
  already covers the "don't render everything at once" need this was meant
  to serve; expand-collapse is available to build on top of that once the
  visual-language question is settled.

### Phase 2 — search across the whole ontology (3–5 days) — **done**

There's already a search input (`#search-box` / `searchNodes()` in
`graph_app.js`) — but it only filters `cy.nodes()`, i.e. what's already
rendered. Once Phase 0 ships, most of the ontology won't be rendered by
default, so this box would silently miss most matches.

- Added `GET /api/search?q=` (`ster/viz_vowl/_search.py`,
  `build_search_results`) over the in-memory `Taxonomy` — a linear scan over
  labels/URIs across schemes, classes, individuals and concepts, capped at
  50 results. No indexing infrastructure: at these ontologies' actual scale
  (thousands, not millions of nodes — see `CLASS_COLLAPSE_LIMIT` /
  `INDIVIDUAL_COLLAPSE_LIMIT`) a scan is a handful of milliseconds; revisit
  only if the largest real ontology says otherwise.
- Wired the existing search box to it: `searchNodes()` still filters
  `cy.nodes()` instantly as before (unchanged UX for the common case — the
  match is already on screen), and now also fires a debounced, request-
  ordered call to `/api/search`, folding an "(+N elsewhere)" note into the
  same `#search-count` text rather than adding a second results list.
  Pressing Enter with no on-canvas match falls back to the first
  whole-ontology hit and brings it onto the canvas via `exploreNode()`
  (extended to take an explicit node type, for a match that has no cy node
  yet to read one from) — reusing the same relations endpoints and
  `applyHighlight()` mechanics Phase 0's click-to-expand already uses.

### Phase 3 — editable side panel (1–2 weeks) — **done**

Turned `showDetail()`/`renderDetail()` into a partly-editable form, submitting
through **`TaxonomyService.execute()`** (`ster/core/service.py`) rather than
the ad hoc `assign_handles` → `save_fn` → `broadcaster.notify` pattern the
schema routes (`/api/individuals`, …) still use — this was decided, not
discovered to be a smaller lift than expected:

- Two new endpoints, `POST /api/entity-label` and `POST /api/entity-description`
  (`ster/api.py`, `_register_mutation_routes`), each take `{uri, lang, value}`
  and dispatch to `OwlSetLabel`/`OwlSetComment` for a class, individual or
  property, or `SkosSetLabel`/`SkosSetDefinition` for a SKOS concept —
  reusing the tested `Command` classes already in `ster/core/commands/`
  rather than reimplementing equivalent logic ad hoc.
- The persistence port is genuinely shared, not just conceptually: it moved
  to `ster/core/adapters.py` (`StorePersistence`, wrapping `ster.store.save`)
  so the HTTP API doesn't reach into `ster.tui.app._persistence` for it;
  `ster/tui/app/_persistence.py` now re-exports the same class under its
  historical `_StorePersistence` name so no TUI call site changed.
  `SkosValidatorAdapter` (`ster/core/validation.py`) was already front-end
  agnostic and is used as-is. The mutation backend
  (`TaxonomyWorkspace.from_taxonomy(...)` + `TaxonomyService(...)`) is built
  lazily per session, the first time an edit is attempted, and cached — most
  sessions (read-only viewing, MCP queries) never need it.
- Fixed a real bug this surfaced: `api_server.start_background()` — the path
  `open_in_browser()` actually uses — built its `create_app(...)` call
  without forwarding `file_path`, so the graph opened from `ster`'s normal
  "open Graph view" flow had no file path for a mutation backend to build from. Editing would have silently 503'd
  on the one path people actually use. See
  `test_start_background_forwards_file_path_to_create_app`.
  `serve()` (the standalone `ster serve` CLI path) already passed it correctly.
- Client side (`graph_app.js`): the panel's primary label and description
  each get a ✎ toggle into an inline input/textarea with explicit Save/Cancel
  (never blur or Enter — see `_editableRow`); saving a label also updates the
  on-canvas node's own data so the graph and the panel never disagree, and
  either save invalidates the cached detail so a reopen refetches the
  server's current state. Editing is deliberately scoped to one language
  (`_EDIT_LANG = 'en'`, matching what the panel already shows as the primary
  label/description) — a language picker for editing is a bigger UI, left
  for a later pass. A read-only node (`readOnly=1`, from a context file)
  never gets the affordance: there is nowhere for `TaxonomyService` to
  persist a change to it.
- The `base_version` optimistic-concurrency check (`TaxonomyService.execute`'s
  `base_version` parameter) is now wired end to end, at the API level rather
  than page-local, so any client benefits: `GET /api/version` returns the
  current version and whether the session is editable, and all five mutation
  bodies accept an optional `base_version` (a shared `_VersionedIn` base
  class) — omitted, it keeps the previous no-check behaviour. A stale value
  gets a 409 instead of silently overwriting a change made elsewhere. The
  page reads the version once at load and re-syncs it from each mutation
  response, but deliberately keeps a stale value after a 409 rather than
  adopting the rejection's — a blind retry is refused too, since the edit
  that landed in between isn't on screen yet.

### Phase 4 — create & edit relations (1–2 weeks) — **done, scope revised**

The plan named `cytoscape-edgehandles` and `cytoscape-edge-editing` for
canvas drag-to-create/re-point. Both were investigated for real (not just
read about) before writing any client code, and both turned out to need a
browser dependency this project's plain-`<script>` vendoring doesn't supply:

- `cytoscape-edgehandles`'s published UMD bundle literal-`require()`s
  `lodash.memoize`/`lodash.throttle` in its CommonJS branch, and in its
  plain-`<script>` fallback branch reads them off a global `root["_"]`
  (i.e. it expects a full lodash already on the page as `window._`).
  Vendoring it alone, as the plan assumed, would throw
  `TypeError: Cannot read properties of undefined` on load and never
  register.
- `cytoscape-edge-editing`'s `package.json` lists `konva` (`^7.0.3`) as a
  peer dependency it draws its anchor-point UI with — same problem, a second
  library away from working.

Shipping either unvendored-but-referenced would be worse than not shipping
it: a console error on every graph page load for a feature that does
nothing. Rather than quietly dropping "create relations" (the original ask
this phase exists for — creating new relations/links between nodes), it was
rebuilt panel-based instead, reusing Phase 3's editable-row pattern and
Phase 2's `/api/search`:

- `/api/search` gained a `types` filter (comma-separated node types) and
  OWL properties as a searchable-but-not-rendered candidate type
  (`ster/viz_vowl/_search.py`) — needed so the relation picker below can
  search "just properties" or "just individuals" instead of everything.
- Four new endpoints, following Phase 3's `TaxonomyService`-routed pattern
  exactly: `POST /api/relation` / `POST /api/relation/remove`
  (`OwlSetIndividualValue` / `OwlRemoveIndividualValue` — an object-property
  value between two individuals) and `POST /api/class-parent` /
  `POST /api/class-parent/remove` (`OwlMoveClass(replace=False)` /
  `OwlRemoveSuperclass` — a `subClassOf` link between two classes, added
  alongside any existing superclasses rather than replacing them).
- Client (`graph_app.js`): `detailRelationsNodes` now takes the node too, not
  just its relations, so it can gate on `_canEdit(d)`. Each existing relation
  that has a matching command — an individual's object-property value
  (carries a `propUri`) or a class's `subClassOf` link — gets a "×" remove
  button; everything else (`rdf:type`, `broader`, `equivalentClass`, …) has
  no command in this slice and stays display-only, deliberately, rather than
  a button that would error. An "Add relation" form (individuals) or "Add
  superclass" form (classes) appears at the bottom, built from
  `_searchPicker` — a small autocomplete backed by `/api/search?types=…` —
  so picking a property or a target is search-driven rather than
  copy-pasting a URI.
- `ster/viz.py`'s `_detail_individual` now carries `propUri` on each
  object-property relation dict (additive; existing `rel`/`uri`/`label`
  fields are unchanged) — needed so the panel knows *which* property to call
  `/api/relation/remove` with, since `rel` there is the property's display
  label, not its URI.

**Left open, not silently skipped**: reviving true canvas drag-to-create
would mean either vendoring lodash (memoize+throttle, or all of it) and
konva alongside the two extensions, or finding lighter-weight equivalents —
worth doing if the panel-based picker turns out too slow for a large,
relation-heavy ontology, but that is a call to make once there is real usage
to look at, not a guess made now. `OwlAddPropertyClass` /
`OwlRemovePropertyClass` (a property's domain/range) were named in the
original plan but have no editor surface yet — domain/range is a property-
level edit, not a between-two-nodes relation, and didn't fit this slice's
"pick two nodes, link them" shape; a property detail view would be the more
natural place for it, not attempted here.

### Ongoing — scale validation

**Not yet done** — this is the one item all four phases were staged ahead
of, not something to run automatically: load-test against the largest real
ontology available, not a synthetic one.
If it's still unusable with progressive disclosure + `fcose` + collapsing,
that's the trigger to revisit `cosmos.gl` — as a **rendering-layer swap under
the same interaction code**, not a rewrite, since the editing UX (Phases
2–4) is already built and shouldn't need to move. This remains a product
call, not this doc's — see §1 and the decisions below.

## 5. Effort summary

| Phase | Estimate |
|---|---|
| 0 — default to progressive disclosure | days |
| 1 — layout & scale (`fcose` + `expand-collapse`) | 1–2 weeks |
| 2 — whole-ontology search | 3–5 days |
| 3 — editable side panel | 1–2 weeks |
| 4 — create/edit relations (panel-based, not canvas — see Phase 4) | 1–2 weeks |

Rough total: **5–7 weeks** of focused work, mostly additive to the existing
stack (no new language/runtime, no second toolchain). Compare to adopting
WebVOWL-Legacy as the base: similar or greater effort just to reach parity on
editing, plus a permanent second app (Node/Webpack/Java tooling) with no
editing story of its own — see §1.

## 6. Decisions & open questions

- **`TaxonomyService` wiring** (Phase 3/4) — **done**: routed through it,
  via a shared `StorePersistence` adapter (moved to `ster/core/adapters.py`)
  and the existing `SkosValidatorAdapter` / `Command` classes. See Phase 3.
- **OCC (`base_version`) on the mutation endpoints** — **done**: wired at
  the API level (`GET /api/version` + `base_version` on all five mutation
  bodies), not just this page — see Phase 3. The page requires a reload
  after a 409 rather than retrying against a version it never actually saw.
- **Search implementation** (Phase 2) — **done**: a linear scan
  (`build_search_results`) over the in-memory `Taxonomy`. Confirm it's still
  fast enough once tried against the real largest ontology; revisit with an
  index only if that check says otherwise.
- **`cytoscape-expand-collapse` UI** (Phase 1): vendored and loaded, not yet
  wired — using it as intended means rendering the class hierarchy as nested
  compound nodes instead of today's flat nodes + `subClassOf` arrows (VOWL
  notation). That's a visual-language change, so it needs a product decision
  before it's built, not just a code one.
- **`cosmos.gl` fallback**: a product call, not this doc's — revisit only if
  Phase 1's result is flagged as still unusable at real scale (and, per the
  note above, only after the load-test that hasn't been run yet).
- **Canvas drag-to-create relations** (Phase 4, revised): not built this
  pass — `cytoscape-edgehandles` needs a global lodash (`memoize`+`throttle`)
  and `cytoscape-edge-editing` needs `konva`, neither of which is vendored.
  The panel-based picker built instead covers the same "create/edit/delete a
  relation" need without either dependency. Revisit only if the panel UX
  proves too slow in practice — a code call at that point, not a design one.
- **Property domain/range editing** (`OwlAddPropertyClass` /
  `OwlRemovePropertyClass`, named in the original Phase 4 plan): no editor
  surface yet — it edits a property, not a link between two nodes, so it
  didn't fit this phase's shape. Would want its own property-detail view.
