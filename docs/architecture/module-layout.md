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
   refactored **down to ≤10 before/while they move**:

   | cc | function | layer |
   |----|----------|-------|
   | 27 | `delete_owl_class` (also > hard ceiling 25) | owl |
   | 22 | `remove_concept` | skos |
   | 19 | `rename_ontology_uri` | onto |
   | 17 | `move_concept` | skos |
   | 15 | `count_owl_uri_references` | cross |
   | 12 | `add_concept` | skos |

2. **Re-export ergonomics.** `from .domain.x import foo as foo` shims get
   exploded one-per-line by ruff unless `combine-as-imports = true` is set in
   `[tool.ruff.lint.isort]` (one-time config change).

## Sequencing — one layer per PR, smallest friction first

| Step | PR | Work |
|------|----|------|
| 1 | config | add `combine-as-imports = true` |
| 2 | onto | refactor `rename_ontology_uri` (19→≤10) + tests → move onto layer + shim |
| 3 | cross | refactor `count_owl_uri_references` (15→≤10) + tests → move cross layer + shim |
| 4 | skos | refactor `remove_concept`/`move_concept`/`add_concept` (≤10) + tests → move skos layer + shim |
| 5 | owl | refactor `delete_owl_class` (27→≤10) + tests → move owl layer + shim |
| 6 | finalize | reduce `operations.py` to a thin shim; add import-linter contracts for intra-domain boundaries |

Each step stays green (full `/ci`), the shim keeps all callers working, and tests
follow the code (rename/retarget per move; add tests for any newly extracted unit).

## The shim contract

`ster/operations.py` keeps its public surface identical by re-exporting each
moved name (`from .domain.skos import move_concept as move_concept`), so the
~37 files importing `ster.operations` are untouched. Private helpers (`_…`) move
with the layer that uses them; genuinely shared helpers go to `domain/cross.py`.
