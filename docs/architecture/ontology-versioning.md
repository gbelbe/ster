# Ontology versioning & publishing

> How ster turns a working `*.ttl` source file into versioned, published
> artifacts. Stable versions are **driven by git tags**; the source file on disk
> is never mutated during publish — version triples are patched in memory only.
> Code lives in [`ster/publish.py`](../../ster/publish.py) and
> [`ster/git/manager.py`](../../ster/git/manager.py).

## The publish tree

ster publishes into an `ontology/` directory beside the source file, organised
into three kinds of channel:

```
<repo>/
  kai-internal-knowledge.ttl        ← the working source (edited in the TUI)
  ontology/
    dev/                            ← rolling; mirrors the latest commit
      index.html
      kai-internal-knowledge.ttl
    latest/                         ← always identical to the newest stable release
      index.html
      kai-internal-knowledge.ttl
    v0.1.1/                         ← immutable snapshot, one per stable release
      index.html
      kai-internal-knowledge.ttl
    v0.1.2/
      index.html
      kai-internal-knowledge.ttl
```

Every channel directory holds the **same two artifacts**, produced by two
serializers (`publish.py`):

| File | Serializer | Notes |
|------|-----------|-------|
| `<stem>.ttl` | `TurtleSerializer` | version-patched Turtle |
| `index.html` | `HtmlSerializer` | pyLODE docs; silently skipped if pyLODE is missing |

"Copying the HTML and TTL" is really **re-serializing the in-memory graph** into
a destination directory — the files are regenerated, not file-copied.

## The version string

```
0.1.2 + 20260604 . abc1234
└─┬─┘   └──┬───┘   └──┬──┘
 base     date      git short-sha
(from tag) (today)  (rev-parse --short HEAD)
```

- **base** — semver, derived from the latest git tag (see below).
- **+date.sha** — build metadata, stamped at publish time.

Built by `build_version_string(base, date, sha)`. The base is stamped into the
ontology's OWL triples (`owl:versionInfo`, `owl:versionIRI`, `dcterms:modified`)
by `patch_version_triples` / `_patch_version_in_graph`.

## Stable release — git-tag driven

There is **no version number stored in a config file**. The source of truth is
the set of git tags. Each ontology's tags are namespaced by the file stem:

```
kai-internal-knowledge/v0.1.2
└──────── stem ───────┘ └─ semver ─┘
```

The `<stem>/` prefix (`ontology_tag`) keeps ontology tags out of the bare
`vX.Y.Z` namespace used for the PyPI package release, and lets several
ontologies coexist in one repo. Only tags matching `<stem>/v` + strict semver
count toward the current version.

`perform_stable_release(taxonomy_file, publish_dir, bump, git)` runs the flow:

```
                  ┌─────────────────────────────────────────────┐
   "Publish a     │ 1. list git tags  ──► latest_ontology_version │
    new Stable     │ 2. bump major/minor/patch  (seed 0.1.0 if none)
    version"   ──► │ 3. patch_version_triples(file)  ← stamps OWL
   (TUI menu)      │ 4. write artifacts ─► v{base}/  AND  latest/
                  │ 5. git commit  "release(<stem>): v{base}"
                  │ 6. git tag  <stem>/v{base}  (annotated)
                  │ 7. git push  HEAD:main  +  the tag  (no-op w/o remote)
                  └─────────────────────────────────────────────┘
```

Key points:

- Step 4 writes the **same artifacts to two directories**: `v{base}/` (the
  immutable snapshot) and `latest/`. That is why `latest/` and the newest
  `vX.Y.Z/` are byte-identical.
- The next release re-reads the tags, so the highest `<stem>/vX.Y.Z` tag always
  defines "current". Bumping is `max(tagged versions)` then major/minor/patch.
- `push_release` pushes HEAD to the configured `main_branch` (default `main`),
  not whatever branch is checked out — releases always land on main.

Returns a `ReleaseResult(version, version_str, tag, artifacts, pushed)`.

## Dev channel — follows commits, no tags

`dev/` is a rolling mirror of the latest committed state. It is refreshed
automatically **after an ordinary commit/push** (not a release):
`GitManager._refresh_dev_artifacts` → `regenerate_dev_artifacts`.

```
   ordinary commit/push (GitManager)
            │
            ▼
   _refresh_dev_artifacts   ← best-effort, never raises
            │
            ▼
   regenerate_dev_artifacts(source_file)
            │  • read base version from file's owl:versionInfo (fallback 0.1.0)
            │  • stamp fresh  base+today+sha
            ▼
   write artifacts ─► ontology/dev/   (dev only — no v{}/ or latest/)
```

No new tag, no separate commit of the dev artifacts: the refresh writes them
into the working tree, and they ride along on the next commit. Because it is
best-effort, a failed dev rebuild prints a dim warning and never blocks the
commit/push flow.

## When each artifact is written

| Trigger | Dirs written | New tag? | Commits artifacts? |
|---------|--------------|----------|--------------------|
| Stable release (`perform_stable_release`) | `v{base}/` + `latest/` | yes — `<stem>/v{base}` | yes, then pushes HEAD:main + tag |
| Ordinary commit via `GitManager` | `dev/` | no | no (rides the next commit) |

## Source-file safety

The working `*.ttl` is **not** modified during a *dev* rebuild — patching
happens on an in-memory `rdflib.Graph` (`_build_context`). During a *stable*
release, `patch_version_triples` does write the new version triples back into
the source file (so the committed source records its released version), then the
artifacts are generated from that graph.

## Quick reference — key functions

| Function | Role |
|----------|------|
| `build_version_string` | assemble `base+date.sha` |
| `bump_version` / `next_ontology_version` | semver bump (seeds `0.1.0`) |
| `ontology_tag` / `parse_ontology_tag` | `<stem>/vX.Y.Z` tag naming |
| `latest_ontology_version` | highest semver among this ontology's tags |
| `patch_version_triples` | stamp OWL version triples into the source file |
| `write_stable_artifacts` | write to `v{base}/` + `latest/` |
| `write_dev_artifacts` / `regenerate_dev_artifacts` | write to `dev/` |
| `perform_stable_release` | full git-tag-driven release |
| `discover_published_pages` / `build_publish_menu` | list channels in the TUI |
