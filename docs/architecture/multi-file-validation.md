# Architecture: validating a graph that is split across files

Status: **proposed** (analysis + design; two gaps identified, neither implemented)
Audience: ster maintainers

## 1. Why

An ontology rarely lives in one file. A realistic Adeo layout splits it by
concern — the core vocabulary in one file, 532 business-capability instances in
another, a finance overlay adding labels in a third. Each file is edited by a
different team on a different cadence.

That split creates two failure modes that look alike and are opposites:

- **Open one file and it looks broken.** `capabilities.ttl` types 532 subjects
  `ex:BusinessCapability` but never declares it — the class lives in
  `core.ttl`. Alone, the file models nothing. This is *incompleteness*.
- **Open two files and they disagree.** Both define `skos:prefLabel@en` for
  `ex:BC-1263`, with different values. Together they are *contradictory*.

Neither is detectable by RDF itself, and today ster detects neither across
files. This document says where each check belongs, how to keep the evidence
needed to report a conflict, and what ster would have to change.

## 2. The distinction that organises everything

**RDF is open-world and monotonic.** Adding triples never invalidates existing
ones. A file asserting `ex:BC-1074 ex:hasParentCapability ex:BC-900` with
neither term defined is *valid RDF*. It is incomplete, not wrong.

**Contradiction is not an RDF error either.** Two `prefLabel`s do not conflict
in the graph; the union simply holds both. Nothing at the RDF layer says a
concept may have only one — that is a SKOS *constraint* (S14), and constraints
live above RDF.

So neither question can be answered by parsing. Both need a validation layer,
and they need **different** ones:

```
                        a triple the file does not define
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
        Is the definition SOMEWHERE               Are there TWO
        in the declared scope?                    definitions?
                    │                                 │
          ┌─────────┴─────────┐             ┌─────────┴─────────┐
          ▼                   ▼             ▼                   ▼
        yes                  no           same              different
          │                   │             │                   │
     fine — merge      INCOMPLETENESS    fine — dedupe     CONTRADICTION
     and carry on      load the closure                    report + resolve
                       or report it                        by explicit policy
```

| Symptom | Class | Detected by |
|---|---|---|
| Type used, never declared | incompleteness | closure check |
| Two `prefLabel@en` | cardinality violation | SHACL / semanticlint |
| URI is both `owl:Class` and `owl:NamedIndividual` | punning — maybe intended | OWL profile check (policy switch) |
| `skos:broader` cycle only after merge | logical inconsistency | graph traversal |
| Contradictory `rdfs:domain` from two files | inconsistency | reasoner |

## 3. Where to check: the closure, not the file

The central move is to stop treating **the file** as the unit of meaning. It is
a serialization fragment. The unit is the **import closure**, declared in the
data rather than reconstructed from whatever the user happened to open:

```turtle
<https://ontology.adeo.com/business-capabilities> a owl:Ontology ;
    owl:imports <https://ontology.adeo.com/architecture-core> .
```

Three layers, each answering a different question, each with a scope that is
identical in CI and in the editor:

```
  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
  │  core.ttl    │  │capabilities  │  │  finance-    │   FILES
  │  declares    │  │   .ttl       │  │ overlay.ttl  │   fragments, not modules
  │ ex:Capability│  │532 instances │  │ extra labels │
  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
         │                 │                 │
         │   LAYER 1 — per file: DOES IT PARSE. Nothing else.
         │   A fragment is *supposed* to look incomplete.
         │                 │                 │
         ▼                 ▼                 ▼
  ┌────────────────────────────────────────────────────────┐
  │  DATASET — one named graph per file                     │
  │  every triple keeps its origin (TriG / rdflib.Dataset)  │
  └───────────────────────────┬────────────────────────────┘
                              │  owl:imports declares the scope
                              ▼
  ┌────────────────────────────────────────────────────────┐
  │  CLOSURE — the unit of meaning                          │
  │                                                         │
  │  LAYER 2 — completeness + constraints                   │
  │    · every term referenced is defined in here           │
  │    · SHACL / semanticlint over the MERGED graph         │
  └───────────────────────────┬────────────────────────────┘
                              │  all closures together
                              ▼
  ┌────────────────────────────────────────────────────────┐
  │  DATASET-WIDE                                           │
  │  LAYER 3 — cross-module coherence                       │
  │    · reasoner, only if real OWL axioms are used         │
  │      (disjointWith, cardinalities, property chains)     │
  └────────────────────────────────────────────────────────┘
```

Layer 1 must **never** judge semantics: reporting "undeclared class" for a
fragment is reporting that a fragment is a fragment.

The complement is `rdfs:isDefinedBy` on each term, pointing at its defining
ontology. That turns "where is this entity authoritative?" from tribal
knowledge into a query — *for every URI I mention but do not define, is its
`isDefinedBy` target in my closure?*

## 4. How to reconcile: keep provenance per triple

A conflict can only be **reported** if the merge kept the evidence. Flattening
files into one `Graph` destroys it: after the union there is no answer to "who
said this?".

```
  BEFORE — flatten (what ster does today)

    core.ttl ─┐
    caps.ttl ─┼──►  one Graph  ──►  "ex:BC-1263 has 2 prefLabels"
    fin.ttl  ─┘                      …asserted by whom? unanswerable

  AFTER — one named graph per file

    core.ttl ──► g:core ─┐
    caps.ttl ──► g:caps ─┼──►  Dataset  ──►  "Two prefLabels @en for ex:BC-1263
    fin.ttl  ──► g:fin  ─┘                      'Manage Treasury'      g:caps
                                                'Treasury Management'  g:fin"
```

ster has half a step toward this already: `Taxonomy.context_source` records
provenance **per entity** — enough to say "this one is read-only, it came from
`places.ttl`", not enough to say "these two files disagree about this field".
Per-triple provenance is what conflict reporting needs.

Then make the precedence policy **explicit and visible**. Any of
last-wins / editable-wins / refuse-and-ask is defensible. *Silent* first-wins is
not, because the file being edited may not be the one whose value is displayed.

## 5. What ster does today

```
  ster show caps.ttl -x core.ttl

    caps.ttl ──┐
               ├─► store.load()  ──►  Taxonomy  ──►  TUI
    core.ttl ──┘        │                 │
                        │                 └──►  lint runs on self._path
                        │                       ── caps.ttl ONLY ──┐
                        │                                          │ GAP 2
                        └──► _merge_context(): URI already         │
                             present → skip, silently ─┐           │
                                                       │ GAP 1     │
                                                       ▼           ▼
                                          conflicts invisible   union-only
                                          (evidence dropped)    violations
                                                                invisible
```

**Gap 1 — collisions are swallowed.**
[`ster/store/_load_save.py:117`](../../ster/store/_load_save.py) — `_merge_context`
skips a URI already present. Keeping the editable definition is the right
*resolution*; the problem is that nothing records or reports that a second
definition existed.

**Gap 2 — lint never sees the union.**
[`ster/tui/app/_lint.py:29`](../../ster/tui/app/_lint.py) — `_compute_lint`
passes a single path. Violations that exist only in the merged graph are
invisible precisely when the user has told ster about the other files.
`store.source_files(taxonomy)` already returns the right list.

**What already works.** The unreadable-file guard
([`ster/store/_diagnosis.py`](../../ster/store/_diagnosis.py), PR #185) is
Layer 1 done correctly: it reports incompleteness *at the point of opening a
file*, names the undeclared type, and offers to declare it. Loading the
defining file with `-x` is the other half of the same answer.

## 6. Proposed changes

Smallest first; each stands alone.

| # | Change | Layer | Effort |
|---|---|---|---|
| 1 | `_merge_context` collects collisions into `Taxonomy.conflicts` instead of dropping them; Problems modal renders them | 2 | small |
| 2 | `_compute_lint` runs over `source_files(taxonomy)`, not `self._path` | 2 | small |
| 3 | Suggest `-x <file>` from the unreadable-file modal when a sibling file declares the missing type | 1 | small |
| 4 | Honour `owl:imports` as the closure, so scope stops depending on `-x` | 2 | medium |
| 5 | Per-triple provenance (named graphs) so conflicts name both files and lines | 2 | medium |
| 6 | Reasoner pass for real OWL axioms | 3 | large — only if needed |

Items 1 and 2 remove the two gaps above and reuse machinery that already
exists. Item 6 is likely unnecessary while the data is mostly SKOS plus light
OWL — a graph traversal covers `broader` cycles without a reasoner.

## 7. Open questions

- Is punning (a URI as both class and individual) intended in the Adeo
  ontology? It is deliberate in the SKOS+OWL work, so the check must be a
  policy switch rather than a hard error. See
  [`mixed-skos-owl.md`](mixed-skos-owl.md).
- Should a closure violation **block** editing, as an unreadable file now does,
  or only warn? Blocking is right for "this file alone means nothing"; warning
  is probably right for "these two files disagree", since the user may be
  mid-reconciliation.
- Do the closure and the git repository boundary coincide? If a closure spans
  repositories, CI needs to fetch the imports before it can validate anything
  beyond Layer 1.

## 8. Changing which file is writable, mid-session

A session loads one writable file plus read-only context (`store.load`'s
*context* argument; §5). Until now that choice was fixed when the session
opened, so editing an entity the tree already showed meant quitting and
reopening — the editor said as much, in a notification that named the file and
then offered nothing.

`ster.working_file.switch` swaps the roles instead. It is deliberately a small
pure-ish function taking its side effects as arguments, because every way this
operation fails is an **ordering** mistake rather than a logic one:

1. validate — a refused switch must leave the session untouched;
2. no-op when the chosen file is already writable — re-parsing on a menu
   reopen is a freeze with nothing to show for it;
3. **flush before the roles move** — a pending edit belongs to the file that is
   writable *now*;
4. load, then apply — a parse failure leaves the previous model in place.

Step 3 is the one that bites. The editor saves on a debounced background worker
that reads `self.tax` and `self._path` **as a pair**; flushing after the swap
writes one ontology into another ontology's file. `_install_working_file` holds
`_save_lock` across the swap for the same reason.

The API serving the same session caches the same answer in three places, all
repointed by `api_server.publish_working_file`: the published `taxonomy` (whose
`context_source` drives the read-only guard), `file_path` (the save target —
read from live state, never closed over), and the lazily built
`_mutation_backend` tuple, which is dropped so the next write rebuilds it
against the new roles.

**Known limitation.** `publish_dir` is derived once as
`file_path.parent / "ontology"` and mounted as StaticFiles at app startup, and
a mount cannot be repointed afterwards. Switching to a working file in a
*different directory* and then publishing still targets the original session's
`ontology/`. Files in one directory — the normal layout — are unaffected.
