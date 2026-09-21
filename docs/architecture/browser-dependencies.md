# Browser dependencies — what ster loads into a page, and how it is tracked

> Implemented, except the two gaps named at the end.

## The problem this closes

ster ships three kinds of dependency and, until this change, watched one.

| Kind | Declared in | Audited by |
|---|---|---|
| Python | `pyproject.toml`, `uv.lock` | `pip-audit`, in CI and in `scripts/ci.sh` |
| Tooling (eslint) | `package.json` devDependencies | `npm audit` |
| **Browser libraries** | **nowhere** | **nothing** |

Ten JavaScript libraries are loaded into ster's pages — Cytoscape and its layout
packages for the graph, three d3 modules for the treemap, Leaflet for the map,
vis-timeline for the frieze. Every one was pinned in a Python constant and named
in no manifest at all. `pip-audit` reads Python and never saw them; `npm audit`
reads `package.json`, and they were not in it. No Dependabot or Renovate
configuration existed. A CVE in any of them would have gone unnoticed until
somebody read about it somewhere else.

## How they are loaded

Not bundled: ster has no build step for them, and deliberately so. A page is
served by ster itself, and each library is fetched **once** from a CDN into
`~/.cache/ster` and then **inlined** into the page. The second run needs no
network; the first degrades to a CDN `<script src>` tag if it cannot reach one.

```
  ster/viz_vowl/_js_assets.py     cytoscape, cytoscape-fcose, cose-base,
  ster/timeline_html.py           layout-base, cytoscape-expand-collapse,
                                  d3-hierarchy, d3-path, d3-shape,
                                  vis-timeline
        │  viz_shared.vendored(filename, url)
        ▼
  ~/.cache/ster/<file>  ──inlined──►  the page
```

## What now tracks them

**`package.json` is the manifest of record.** The ten libraries are declared as
`dependencies`, pinned exactly — no `^`, because the source pins one version and
a range would make the manifest a wish rather than a record. They are not build
inputs; declaring them is what puts them in front of `npm audit` and Dependabot.

**`.github/dependabot.yml`** watches three ecosystems: pip, npm and
github-actions. The Cytoscape family and the d3 modules are grouped, since a
Cytoscape bump usually drags its layout packages with it and six PRs for one
decision is six times the CI.

**`tests/unit/test_browser_dependencies.py`** is what makes the declaration
real. It reads the *resolved* CDN URLs out of the module constants — so an
f-string, a split literal and a plain URL are all handled alike — and asserts
that every library the code loads is declared, at the same version, exactly,
with nothing declared that no view loads. A Dependabot PR bumping `package.json`
therefore **fails CI until the Python constant moves with it**. That failure is
the feature: it is the reminder that the version lives in two places.

The suite includes a guard on the guard — a scanner that silently found nothing
would make every other assertion in the file pass.

## Two gaps left open

**Leaflet is not vendored.** `geo_map_html.py` loads it straight from unpkg with
`<link>` and `<script src>` on every map open. The map therefore needs the
network each time it is used and announces itself to unpkg on each open, while
the graph and the timeline work offline after their first run.
`viz_shared.vendored()` already does the right thing and the change is small,
but it alters how the map view loads and belongs in a PR where the map's own
tests are the proof.

**No integrity check.** `vendored()` fetches over HTTPS and caches the bytes
without verifying them. TLS protects the transport; nothing protects against a
compromised CDN or a tampered cache file. A `sha384` constant beside each version
constant, compared after download and before writing, would close it — roughly
five lines in `viz_shared`, plus one constant per library. Worth doing next,
and it gets easier now that every library has exactly one declared version to
hash.
