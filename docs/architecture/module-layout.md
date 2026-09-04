# Module layout — splitting `operations.py` into a `domain/` package

> Plan-of-record for the domain split. Behaviour-neutral refactor: it relocates
> existing domain logic, it does **not** change what any function does.

## Why

After the `TaxonomyService` refactor, the call flow is
`viewer → core/commands/* → TaxonomyService → operations.*`. The **commands** are
already a package split by ontology layer
(`core/commands/{skos,owl,onto,cross}.py`), but the **domain logic** they delegate
to is still a single 1,165-line, 51-function module (`ster/operations.py`) mixing
SKOS, OWL, ontology-metadata, and cross-cutting rename concerns.

Splitting the domain layer to mirror the command layer gives:

- **Symmetry** — `domain/skos.py` ↔ `commands/skos.py`, etc.
- **Smaller files** — ~200–300 lines each instead of one 1,165-line module.
- **Clear ownership** and easier per-layer testing.
- **Enforceable boundaries** — import-linter can forbid `domain.skos` from
  reaching into `domain.owl` (and vice-versa).

## Target structure

```
ster/domain/
  __init__.py
  skos.py      # concept ops:  add/remove/move_concept, add_broader_link,
               #               set/remove_{label,definition,scope_note},
               #               add/remove_related, create_scheme
  owl.py       # class/property ops: add/delete/clear_owl_property,
               #               delete_owl_class, add_subclass_of,
               #               _owl_subclass_tree, rename_owl_uri (+ _rename_owl_*)
  onto.py      # ontology metadata: rename_ontology_uri, ontology_domain/prefix,
               #               rename_ontology_domain/prefix, validate_*, count_*
  cross.py     # cross-layer: rename_entity_uri, count_uri_references,
               #               rename_uri, resolve, expand_uri,
               #               shared helpers (_is_ancestor, _subtree_uris, …)
ster/operations.py   # thin re-export shim → ~37 caller files keep importing `ster.operations`
```

## Constraints discovered (why this is refactor-*then*-move)

1. **The complexity ratchet treats a relocated function as new.** A moved
   function isn't in the `origin/main` baseline, so the ratchet sees "new
   function, complexity > 10 → fail". These exceed 10 today and must be
   refactored **down to ≤15 before/while they move**:

   | cc | function | layer |
   |----|----------|-------|
   | 27 | `delete_owl_class` | owl |
   | 22 | `remove_concept` | skos |
   | 19 | `rename_ontology_uri` | onto |
   | 17 | `move_concept` | skos |
   | 12 | `add_concept` | skos |

2. **Re-export ergonomics.** `from .domain.x import foo as foo` shims get
   exploded one-per-line by ruff unless `combine-as-imports = true` is set in
   `[tool.ruff.lint.isort]` (one-time config change).

## Sequencing — one layer per PR, smallest friction first

| Step | PR | Work |
|------|----|------|
| 1 | config | add `combine-as-imports = true` |
| 2 | onto | refactor `rename_ontology_uri` (19→≤15) + tests → move onto layer + shim |
| 3 | cross | refactor `count_owl_uri_references` (already 15) + tests → move cross layer + shim |
| 4 | skos | refactor `remove_concept`/`move_concept`/`add_concept` (≤15) + tests → move skos layer + shim |
| 5 | owl | refactor `delete_owl_class` (27→≤15) + tests → move owl layer + shim |
| 6 | finalize | reduce `operations.py` to a thin shim; add import-linter contracts for intra-domain boundaries |

Each step stays green (full `/ci`), the shim keeps all callers working, and tests
follow the code (rename/retarget per move; add tests for any newly extracted unit).

## The shim contract

`ster/operations.py` keeps its public surface identical by re-exporting each
moved name (`from .domain.skos import move_concept as move_concept`), so the
~37 files importing `ster.operations` are untouched. Private helpers (`_…`) move
with the layer that uses them; genuinely shared helpers go to `domain/cross.py`.

## Other package splits (same shim contract)

The same shim contract — a package of submodules behind a re-export surface
that keeps every existing import working — was used for eight more
oversized files, all in the `refactor/complexity-and-file-size-20260904` PR
that made "clean" (tested, lint-clean, complexity-clean) the standing bar for
this project from that point on. `ster.git.manager` (last on the list below)
was the last of the originally-identified oversized files, closing out that
project-wide pass — every file flagged at the start of that PR now lives in a
package split behind this same shim contract:

- **`ster.cli`** (was `ster/cli.py`, 2,697 lines) → `ster/cli/` — 13
  submodules by concern (bootstrap in `_app.py`, file picker, workspace UI,
  edit commands, export, publish, serve, home screen, …) plus `__init__.py`
  (the shim) and `__main__.py`. Flat module-level functions, so the shim is
  a plain re-export list.
- **`ster.nav.logic`** (was `ster/nav/logic.py`) → `ster/nav/logic/` — split
  by the entity kind each function's logic concerns (`_concept.py`,
  `_individual.py`, `_property_.py`, `_rdf_class.py`, `_tree.py`,
  `_mixed_tree.py`, `_overview.py`, `_fields.py`, `_global_.py`).
- **`ster.viz_vowl`** (was `ster/viz_vowl.py`) → `ster/viz_vowl/` — split by
  concern (`_graph_builders.py`, `_relations.py`, `_query_result.py`,
  `_detail.py`, `_html_template.py`, `_js_assets.py`, `_server.py`).
- **`ster.tui.app`** (was `ster/tui/app.py`, 3,625 lines, ~200 methods on one
  `OntologyApp(App)` class) → `ster/tui/app/`. A single stateful class
  doesn't split into free functions the way the other three did, so this one
  uses **mixin classes** instead, one per business domain (lifecycle, config,
  tree building, panels, detail rendering, lint, rebuild, busy/save,
  problems, row actions, context menu, editing modals, ontology identity,
  tree events, misc actions, graph view, SHACL), composed in `__init__.py`:

  ```python
  class OntologyApp(_LifecycleMixin, _ConfigMixin, ..., _ShaclMixin, App):
      CSS = ...
      BINDINGS = ...
      COMMANDS = ...
  ```

  This is safe and Textual-native: `Widget.__init_subclass__` /
  `DOMNode.__init_subclass__` walk `cls.__mro__` to collect `reactive()`
  descriptors and merge `BINDINGS`/`CSS` from every base, so anything a mixin
  declares is picked up automatically. Each mixin is a plain class (not
  itself inheriting from `App`), and `self.foo()` resolves across mixins
  through the normal MRO with no extra qualification — the one addition this
  split needed that the function-based splits didn't is `_state.py`: a
  typing-only `_AppState` class (real at type-check time, an empty no-op base
  at runtime) declaring every attribute/method a mixin may borrow from a
  sibling, so mypy can check cross-mixin `self.foo()` calls without each
  mixin re-declaring ~200 signatures it doesn't own. Module-level helpers
  (`_start_context_server`, `_nav_hint`, sentinel-codec functions, …) and
  small support classes (`OntologyTree`, `_StorePersistence`,
  `EntitySearch`) that don't belong to any one mixin live in their own
  `_constants.py`/`_helpers.py`/`_tree_widget.py`/`_persistence.py`/
  `_entity_search.py` support modules, imported by whichever mixins need
  them.
- **`ster.store`** (was `ster/store.py`, 1,273 lines, ~73 flat functions, no
  classes) → `ster/store/` — split by RDF-persistence concern, in dependency
  order (each layer only imports the ones before it):
  - `_constants.py` — shared namespaces/constants (`VOID`, `SCHEMA`, `VANN`,
    `NOTE_PROPERTY_URI`, `_RDFLIB_DEFAULT_PREFIXES`) needed by more than one
    other submodule.
  - `_format.py` — serialisation-format detection: extension mapping,
    content sniffing, mismatch/parse-error reporting.
  - `_graph_io.py` — low-level graph parsing/indexing: the fast native
    pyoxigraph path (`_native_index`) and the generic rdflib-graph walk
    (`_graph_index`) that both build the same `_Index` type; `_parse_graph`
    for callers that need a plain rdflib `Graph`.
  - `_convert.py` — format conversion (`convert`, `convert_to_ttl`), used by
    the RDF/XML→TTL working-copy flow.
  - `_cache.py` — the binary (pickled) Taxonomy cache: schema-fingerprinted,
    owner-only, pruned of stale entries when the model shape changes.
  - `_from_graph.py` — Graph → Taxonomy: builds each entity kind (classes,
    properties, concepts, schemes, individuals, the ontology node) from an
    indexed graph; ends in `graph_to_taxonomy`.
  - `_to_graph.py` — Taxonomy → Graph: the inverse serializer, one function
    per entity kind, ending in `taxonomy_to_graph`.
  - `_normalize.py` — post-load hierarchy normalisation (symmetric
    broader/narrower, top-concept bookkeeping) and the namespace/prefix
    helpers serialisation uses (`_bind_namespace`, `_concept_scheme_uri`).
  - `_load_save.py` — the public `load`/`save`/`is_editable` entry points:
    cache orchestration, read-only context-file merging, and the atomic
    (temp-file + `os.replace`) write.

  Flat module-level functions, so the shim is a plain re-export list, same as
  `ster.cli` and `ster.nav.logic`. Two tests patched functions at the
  package-attribute level (`patch("ster.store.taxonomy_to_graph", ...)`,
  `monkeypatch.setattr(store, "_bin_cache_dir", ...)`) expecting an *internal*
  call within the package (`save()` calling `taxonomy_to_graph()`, or
  `_get_bin_cache_path()` calling `_bin_cache_dir()`) to observe the patch —
  which a package-level re-export cannot do, since the callee is a separate
  name binding in a sibling submodule's own namespace. Those were retargeted
  to the submodule-qualified path (`ster.store._to_graph.taxonomy_to_graph`,
  `store._cache._bin_cache_dir`), matching the convention `ster.cli`'s tests
  already use for same-package internal patches.

- **`ster.sparql_query`** (was `ster/sparql_query.py`, 1,187 lines, ~37
  members, no classes but two dataclasses) → `ster/sparql_query/` — split
  by SPARQL-engine concern, in dependency order:
  - `_types.py` — shared value types: `QueryResult`, `PresetQuery`, and the
    `UriIndex` type alias every other submodule builds on.
  - `_presets.py` — `_PREFIXES`, `SPARQL_KEYWORDS` (editor autocomplete
    seed list), and the `PRESET_QUERIES` registry.
  - `_uri_index.py` — builds the prefix → qname completion index from a
    loaded `Taxonomy`: `build_qname_index` (flat) and `build_uri_index`
    (richer, with class hierarchy and individuals-by-class) plus their
    bucket/hierarchy-assembly helpers.
  - `_caching.py` — the parsed-graph cache and URI-index cache
    (`load_graph`, `load_graph_cached`, `build_uri_index_cached`,
    `warm_graph_caches`), keyed by file path + mtime, plus `_SPARQL_LOCK`
    (rdflib's SPARQL parser is a process-wide global and not thread-safe —
    see `tests/unit/test_sparql_thread_safety.py`).
  - `_execute.py` — `run_query` / `run_query_on_graph`, the shared
    entry-points every caller (TUI, CLI, MCP) uses to execute a SPARQL
    string against a taxonomy, plus result-shaping helpers
    (`find_uri_column`, `compute_col_widths`).
  - `_autocomplete.py` — editor smart-completion: cursor-position context
    detection, qname/prefix candidate filtering, and buffer scanning
    (`extract_query_variables`, `extract_result_uris`).

  Flat module-level functions, so the shim is a plain re-export list, same
  as `ster.cli`, `ster.nav.logic`, and `ster.store`. One test
  (`test_warm_preload_skipped_when_no_graph_in_cache`, and its `step_defs`
  mirror) hit the same internal-call hazard as the `store.py` split:
  `patch.object(_sq, "build_uri_index_cached", ...)` patched the top-level
  re-export, but `warm_graph_caches` calls `build_uri_index_cached`
  unqualified from within the same `_caching.py` submodule, so the patch
  never took effect. Retargeted to
  `patch.object(_sq_caching, "build_uri_index_cached", ...)` against
  `ster.sparql_query._caching`, the submodule where the callee actually
  lives.

- **`ster.tui.config_modal`** (was `ster/tui/config_modal.py`, 1,129 lines) →
  `ster/tui/config_modal/` — a different shape from the five splits above:
  the file already held several small standalone Textual widget/message
  classes ahead of one larger stateful class (`ConfigModal(ModalBase[None])`,
  ~600 of the 1,129 lines). Each small class got its own home, grouped by
  what it supports rather than one-class-per-file:
  - `_messages.py` — `DeclareAnnotationProperty`, `EnforceShaclRequested`,
    the messages the metadata catalog posts for the app to act on.
  - `_labels.py` — `suggest_label` and the namespace-prefix table it uses.
  - `_percent.py` — `_pct_display`/`_pct_parse`, the Semantic Lint tab's
    percent-string ↔ 0.0–1.0 threshold helpers.
  - `_metadata_widgets.py` — one catalog row's widgets: `_MetaCheckbox`,
    `_EnforceButton`, `_MetaRow`.
  - `_metadata_catalog.py` — `_MetaCatalog`, the catalog editor itself
    (checklist + add row + its own arrow-key roving), substantial enough
    (~300 lines) for its own file.
  - `_general_widgets.py` — `_SecretInput`, `_ServerGroup`, `_LangGroup`,
    the small General-tab support widgets.

  `ConfigModal` itself, once those neighbours were pulled out, still read as
  doing several genuinely distinct things (one per tab, plus cross-tab
  navigation, plus result-gathering) — the same shape of problem
  `ster.tui.app`'s `OntologyApp` had, just at a tenth of the size — so it
  uses the same mixin-classes-for-one-stateful-class pattern, six mixins
  this time (`_GeneralMixin`, `_PropsMixin`, `_PluginsMixin`,
  `_SemanticLintMixin`, `_NavigationMixin`, `_StateMixin`), composed in
  `__init__.py` alongside `DEFAULT_CSS`/`BINDINGS`/`__init__`/`compose` (kept
  there rather than a mixin of their own — assembly, not a business concern).
  A `_state.py` typing-only `_ModalState` plays the same role as
  `ster.tui.app`'s `_AppState`, declaring every attribute/method a mixin may
  borrow from a sibling.

  One extra hazard this split surfaced that the flat-function splits didn't:
  several handlers used the `@on(...)` decorator, which only registers via a
  metaclass hook (`_MessagePumpMeta.__new__`) that runs when *that exact
  class* is defined — a plain mixin (not itself a `Widget`/`MessagePump`
  subclass until composed into `ConfigModal`) never goes through that
  metaclass, so a decorated handler defined on a mixin is silently never
  dispatched once split out (`ster.tui.app`'s mixins avoid this the same
  way, and already used no `@on(...)` at all). Fixed by converting every
  such handler to Textual's naming-convention dispatch (`on_checkbox_changed`,
  `on_input_changed`, `on_button_pressed`, `on__meta_catalog_changed`, …),
  filtering by widget id/class inside the method body where the decorator
  used to carry a CSS selector — this dispatches correctly across mixins
  because Textual walks the whole MRO and calls each class's own handler,
  not just the first one found.

- **`ster.git.manager`** (was `ster/git/manager.py`, 1,031 lines, one
  `GitManager` class plus a handful of module-level helpers) → `ster/git/manager/`
  — the same shape of problem as `ster.tui.config_modal`'s `ConfigModal`, just
  without any Textual concerns: `GitManager` is a plain Python class, so its
  mixins carry no `@on(...)`/reactive/BINDINGS hazards at all. Split into
  seven mixins by business concern, composed in `__init__.py`:

  ```python
  class GitManager(
      _ConfigMixin, _SetupMixin, _SyncMixin, _StagingMixin,
      _CommitMixin, _PushMixin, _ReleaseMixin,
  ):
      ...
  ```

  - `_config.py` — instance construction and the config accessors
    (`is_enabled`, `is_configured`, `_persist`, `_repo`) every other mixin
    reads/writes through.
  - `_setup.py` — interactive first-time setup: detect/init/clone/link a
    repo, the branch-strategy prompt, and everything `setup()` delegates to.
  - `_sync.py` — fetch/pull-behind checks (`fetch_remote`, `check_and_pull`,
    `pre_edit_check`, `record_head`).
  - `_staging.py` — `stage_file`/`stage_path`/`has_staged_changes`.
  - `_commit.py` — the commit/push flow: staged-changes gate, semanticlint
    quality gate, commit-message prompt, push-strategy choice.
  - `_push.py` — direct push and PR creation (`gh` CLI, falling back to the
    GitHub REST API).
  - `_release.py` — git-tag-driven semver release tagging.

  Plus three small support modules the mixins share, and `_state.py` (the
  same typing-only cross-mixin surface as `ster.tui.app`/`ster.tui.config_modal`,
  minus the Textual base class):
  - `_subprocess.py` — the `_git`/`_git_available` subprocess wrapper.
  - `_config_store.py` — the global `~/.config/ster/git_repos.json`
    load/save pair and its `CONFIG_DIR`/`CONFIG_FILE` constants.
  - `_console.py` — the stdout/stderr Rich consoles every mixin prints
    through.

  Two more module-level helpers unrelated to `GitManager` itself got their
  own homes: `_activity.py` (`file_activity`) and `_diff.py` (`render_diff`).

  This split hit the internal-call hazard hardest of all eight: `_git`,
  `_git_available`, `console`, `err`, `CONFIG_FILE`, and `CONFIG_DIR` were
  each called unqualified from **every** mixin (~90 call sites for `_git`
  alone), and around 90 pre-existing tests patched them at the flat module's
  top level (`patch("ster.git.manager._git", ...)`,
  `monkeypatch.setattr(gm, "console", ...)`, etc.). A package-level re-export
  can't make those patches reach an internal caller, so the fix here went
  further than prior splits: every mixin reaches these primitives through a
  **module-qualified** attribute access (`_subprocess._git(...)`, not a bare
  `_git(...)` imported via `from ._subprocess import _git`) so the lookup
  happens at call time against the submodule's own namespace — the same
  namespace a patch targets. The three support modules
  (`_subprocess.py`/`_config_store.py`/`_console.py`) exist specifically to
  give each primitive one canonical, patchable home. All ~90 affected test
  patches were mechanically retargeted to the matching submodule-qualified
  path (`ster.git.manager._subprocess.*`, `ster.git.manager._console.*`,
  `ster.git.manager._config_store.*`).
