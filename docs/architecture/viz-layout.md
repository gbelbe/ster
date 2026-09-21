# Visualisation layout — a shared layer, and the two files that should be split

> Proposal. Step 1 is implemented on `feat/timeline-view`; steps 2 and 3 are
> plans of record, behaviour-neutral, each following the shim contract that
> `module-layout.md` established for the eight earlier package splits.

## Where things stand

ster now has three views. They were built one at a time, and it shows.

| View | Shapes (what an entity resolves to) | Results (SPARQL → rows) | Page |
|---|---|---|---|
| Graph | — | `viz_vowl/_query_result.py` | `viz_vowl/` (package) |
| Map | `geo_shapes.py` — **1248** | `geo_results.py` — 261 | `geo_map_html.py` — **1482** |
| Timeline | `time_shapes.py` — 307 | `time_results.py` — 174 | `timeline_html.py` — 155 |

Plus `viz.py` (247), label formatting shared by the graph renderers, and
`viz_shared.py` (165), added by step 1 below.

The naming is already symmetric — `<domain>_shapes` / `<domain>_results` /
`<domain>_*_html` — and the timeline was written into that shape deliberately
rather than inventing a fourth convention. Two things remain out of line: a
shared layer that did not exist, and two files well over the size bar this
project set for itself.

## Step 1 — `viz_shared.py` (done)

Writing the timeline surfaced four helpers that every view needs and that each
view had been answering for itself:

- `label_of` — SKOS prefLabel, then rdfs:label, then the URI's tail;
- `image_of` — the first picture, whatever vocabulary named it;
- `most_specific_types` — declared classes minus those a sibling implies
  (`geo_shapes._facet_classes` is the same twenty lines);
- `reachable_inward` — the closure `located_from` walks, parameterised by what
  the caller is looking for, so `dated_from` is one line rather than thirty;
- `vendored(filename, url)` — download a library once into `~/.cache/ster` and
  return its text, the rule `viz_vowl._js_assets` applies to Cytoscape and
  `timeline_html` now applies to vis-timeline.

Nothing in `viz_shared` knows what a map or a frieze is. A view imports from it;
it imports from no view — the layering `geo_results` already keeps over
`geo_shapes`, applied one level up so that a **fourth** view costs no third copy.

The timeline uses it today. The map does not yet, deliberately: adopting it
there is a behaviour-neutral change that belongs in its own commit, where the
diff is readable and the existing map tests are the proof.

**Follow-up (step 1b):** point `geo_shapes` and `geo_results` at
`viz_shared`, keeping `geo_results.label_of` and `geo_shapes.image_of` as
re-exports so the ~10 call sites and their tests are untouched. Net effect:
roughly 60 duplicated lines deleted and one definition of each rule.

## Step 2 — split `geo_shapes.py` and `geo_map_html.py`

Both are over 1000 lines, which is the line this project drew for itself: every
file flagged in the `refactor/complexity-and-file-size-20260904` pass now lives
in a package behind a re-export shim. These two arrived after that pass and were
never folded into it.

`geo_shapes.py` (1248) holds five distinct concerns that barely reference one
another:

```
ster/geo_shapes/
  __init__.py      # shim: re-export the current public surface unchanged
  _wkt.py          # _split_crs, _parse_coords, wkt_to_geojson, _collection, _centroid_of
  _geometry.py     # Geometry, coordinates_of, geometry_of, is_located, anything_located
  _reach.py        # REACH_DEPTH, located_from (→ viz_shared.reachable_inward)
  _hierarchy.py    # _declared_containment, attachment_predicates, place_parent/level/type,
                   # place_ancestors, numeric_literals
  _facets.py       # facets_of, facet_catalogue, badges_of, image_of
  _layers.py       # STER_MAP, map_layers, _layer_record, placeholders, legends
```

`geo_map_html.py` (1482) is one Python string holding a whole front end, and
splits the way `timeline_html.py` is already arranged — library / app / data:

```
ster/geo_map_html/
  __init__.py      # shim: render_map_html
  _page.py         # the HTML skeleton
  _style.py        # the CSS block
  _vendor.py       # Leaflet script/style tags (→ viz_shared.vendored)
ster/assets/map_app.js   # the ~900 lines of JS, moved out of the string
```

Moving the JS to `assets/` is the larger win of the two: it is the change that
puts the map's front end under `eslint` and `node --check` the way
`graph_app.js` and `timeline_app.js` already are. `test_map_page_syntax.py`
exists precisely because that code is invisible to every tool — it documents a
bug that shipped because a stray `*/` was unreadable to ruff, mypy and the
tests alike. Extracting the file makes that test a belt to the assets' braces
rather than the only line of defence.

Sequencing, one PR each, same as the earlier splits: `_wkt` (pure functions, no
callers outside the module), `_layers`, `_facets`, `_hierarchy`, `_geometry` +
`_reach`, then the page. Each step stays green; the shim keeps all callers
working.

## Step 3 — a `ster/viz/` package (optional)

Regrouping the eleven files as `ster/viz/{shared,vowl,geo,time}/` would make the
view boundary an enforceable one: import-linter could then forbid `viz.geo` from
reaching into `viz.time`, which today is a convention held up by review alone.

It is also the largest churn of the three and buys the least on its own. Worth
doing **after** step 2, if at all — and only together with the import-linter
contracts, since without them it is a rename that improves nothing a reader can
see.

## Naming asymmetry left in place

`geo_map_html` against `timeline_html` reads oddly: one names its view, the
other names its domain. `geo_map_html` → `geo_html` would fix it and is a
two-line shim. Not done here because renaming a module in the same branch that
adds a feature makes the diff harder to read than the inconsistency is to live
with.
