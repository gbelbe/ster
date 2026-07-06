# Architecture: a Presenter hierarchy for entity detail views

Status: **proposed** (design agreed, not yet implemented)
Audience: ster maintainers
Related: [module-layout.md](module-layout.md), [core-service.md](core-service.md)

## 1. Why

The Textual detail pane (right side) is built from a flat list of `DetailField`
rows, grouped into sections at separator rows (see `ster/tui/detail.py`,
`ster/tui/detail_view.py`). The **content** of those rows is produced by
`ster/nav/logic.py` (~4,000 lines), which holds one hand-written builder per
entity kind:

```
build_rdf_class_detail   build_property_detail   build_individual_detail
build_concept_detail     build_scheme_detail
build_tui_ontology_overview_fields   build_tui_taxonomy_overview_fields
```

Dispatch is a `_BUILDERS` dict (kind → function) plus two special-cased overview
sentinels. Each builder composes its own `_*_fields` / `_*_rows` helpers in its
own order. Problems:

- **Inconsistent UX.** Section vocabulary and order drift per entity — a class,
  a property and a concept each present "quality", "issues" and "metadata"
  differently (or not at all). The user can't build a stable mental model.
- **Gaps aren't actionable or even visible.** Useful signals (a property
  *missing domain/range*, an undocumented class, a concept with no definition)
  are buried in a counts row or only reachable via the lint modal.
- **Hard to maintain.** Adding a section (e.g. "Metadata coverage") means
  editing several builders by hand; `logic.py` is a god-module well over the
  complexity ceiling, so every touch fights the ratchet.

We want **one consistent, actionable, maintainable presentation layer** that
applies the same section model to *every* entity: classes in the ontology tree,
properties in the properties tree, individuals, and concepts/schemes in the
taxonomy (SKOS) tree — plus the two overviews.

## 2. Goal

A small **Presenter** class hierarchy (template method): a base class fixes a
canonical section skeleton and owns all shared rendering; one thin subclass per
entity kind supplies only entity-specific content. Consistency of **data and
UI** then holds *by construction*, and each entity's logic lives in its own
small, testable, ≤-complexity-10 unit.

Non-goals: no new runtime dependency (rendering stays text `DetailField` rows —
see §7); no change to `DetailField` / `DetailSection` / `DetailView`; no change
to the command/service mutation path.

## 3. The canonical section model

Every entity is presented as the same ordered vocabulary of sections. A section
is **omitted when empty**, so simple entities stay short while rich ones expand
predictably.

| # | Section | Meaning | Example rows |
|---|---------|---------|--------------|
| 1 | **Identity** | What this is | URI, kind, prefix, labels |
| 2 | **Health & Issues** | What needs fixing (actionable) | missing label/comment, **missing domain/range**, no definition — each a navigable issue row |
| 3 | **Completeness** | How fully populated (color-coded bars) | label/doc coverage, fill rate, SKOS/metadata coverage |
| 4 | **Relations** | How it connects | super/sub/equivalent, domain/range/inverse, broader/narrower, types, top concepts |
| 5 | **Metadata** | Descriptive annotations | generic `OntologyAnnotation` rows + "＋ Add metadata" |
| 6 | **Media** | schema.org media | image / video / url |
| 7 | **Actions** | What you can do | ＋ add subclass, promote, delete, view graph |

"Actionable" reuses the **existing** `_issue_nav_fields` machinery: an issue row
already carries a `meta` action that the TUI handles to jump to / list the
offending entities. Health rows are these nav rows, so drill-in is free.

## 4. The Presenter hierarchy

```
                    ┌────────────────────────────────────────┐
                    │            EntityPresenter (ABC)         │
                    │  render() -> list[DetailField]           │  TEMPLATE METHOD:
                    │    = identity + health + completeness    │  fixed section order,
                    │      + relations + metadata + media      │  drops empties, inserts
                    │      + actions   (each a hook)           │  separators
                    │  ── overridable hooks (default []) ──    │
                    │  identity() health() completeness()      │
                    │  relations() metadata() media() actions()│
                    │  ── shared concrete helpers ──           │
                    │  _bar()  _issue_rows()  _annotation_rows │
                    │  _media_rows()  _pct()  _sep()           │
                    └───────────────▲──────────────────────────┘
        ┌───────────────┬───────────┼───────────┬───────────────┬───────────────┐
 ClassPresenter  PropertyPresenter  IndividualP.  ConceptP.   SchemeP.   (overviews)
                                                                     OntologyOverviewPresenter
                                                                     TaxonomyOverviewPresenter
```

- **Base** (`ster/tui/presenters/base.py`) defines `render()` (the template),
  the seven hooks (default `[]`), and the shared row-builders. `metadata()` and
  `media()` have **concrete defaults** that work for any entity (every kind now
  exposes generic annotations + schema media), so most subclasses inherit them.
- **Subclasses** (one module each) override only the hooks that apply, mostly by
  calling the *existing* `_*_fields` helpers — so the migration is a re-home, not
  a rewrite.

### Registry + context

```python
# ster/tui/presenters/__init__.py
PRESENTERS: dict[str, type[EntityPresenter]] = {
    "class": ClassPresenter, "property": PropertyPresenter,
    "individual": IndividualPresenter, "concept": ConceptPresenter,
    "scheme": SchemePresenter,
}
OVERVIEW_PRESENTERS = {OVERVIEW_URI: OntologyOverviewPresenter,
                       TAXONOMY_URI: TaxonomyOverviewPresenter}
```

`ster/tui/detail.py::_fields_for` becomes a one-liner lookup:
`presenter_for(tax, uri, ctx).render()`.

Cross-cutting inputs (today threaded as ever-growing positional args:
`activity`, `lint`, `configured_langs`, metadata coverage, the annotation
catalogs) collapse into one frozen `PresenterContext` dataclass passed to the
constructor — no more signature churn when a new input appears.

```python
@dataclass(frozen=True)
class PresenterContext:
    tax: Taxonomy
    lang: str = "en"
    configured_langs: tuple[str, ...] = ()
    activity: dict | None = None      # git edit activity (overview)
    lint: dict | None = None          # semanticlint counts (overview)
    metadata: dict | None = None      # metadata-coverage %s (overview)
    metadata_props: tuple = ()        # ontology-metadata catalog
    entity_metadata_props: tuple = () # entity-metadata catalog
```

## 5. Per-kind responsibilities

| Presenter | Health (actionable) | Completeness | Relations |
|-----------|---------------------|--------------|-----------|
| `ClassPresenter` | missing label/comment; subtree issues; no individuals | subtree label/doc, property-fill | super/sub/equivalent/disjoint, applicable properties |
| `PropertyPresenter` | **missing domain/range**, missing label | fill rate | domain/range/inverse/sub-property |
| `IndividualPresenter` | missing label/type | — | types, property assertions |
| `ConceptPresenter` | missing prefLabel/definition, mapping gaps | SKOS completion % | broader/narrower/related, mappings |
| `SchemePresenter` | scheme issues | scheme completion | top concepts |
| `OntologyOverviewPresenter` | errors + warnings **+ structural gaps** | label/doc + ontology/entity metadata + languages | structure counts (classes/properties/individuals) |
| `TaxonomyOverviewPresenter` | SKOS aggregate issues | SKOS aggregate coverage | scheme/concept counts |

The reorganized **ontology overview** (the trigger for this work) is just
`OntologyOverviewPresenter` filling the canonical hooks:

```
zoo · https://example.org/zoo/ · prefix: zoo            health 72/100

Health & Issues                         Completeness
  2 errors                       →         Labels        ████████░░ 80%
  13 warnings                    →         Documentation ████░░░░░░ 42%
  3 properties missing domain/range →      Ontology meta ██░░░░░░░░ 17%
  4 classes undocumented            →      Entity meta   ░░░░░░░░░░  0%
  5 classes with no individuals     →      en 100% · fr 25%
Structure                               Activity
  Classes 7 · Properties 2 · Inds 3       edited 2026-06-28 · 41 commits
```

## 6. Dependency on the generic-annotations work

`metadata()`/`health()` are uniform only because classes and properties now
retain **generic annotations** (the `RDFClass.annotations` / `OWLProperty.annotations`
buckets + round-trip) and `ster/metadata_coverage` exists. Those land in the
metadata-quality change (PR #40). This refactor builds on top of them.

## 7. Rendering decision: text rows, no new deps

Textual ships `DataTable`, `Sparkline`, `ProgressBar`, `Digits` and `Collapsible`,
and `textual-plotext` would add real charts. For now we **stay with text
`DetailField` rows** (color-coded block bars, navigable issue rows): it reuses
the whole existing render/focus/action pipeline, adds nothing to the dependency
list (CLAUDE.md: keep deps minimal), and the Presenter base makes a later swap to
richer widgets a one-place change (replace `render()`'s row emission) without
touching any subclass. Charts via `textual-plotext` are a deferred, opt-in
follow-up (e.g. a class-depth histogram in `StructurePresenter`).

## 8. Migration plan (incremental, each step green)

- **P0 — scaffold.** Add `presenters/base.py`, the registry, and `PresenterContext`,
  with a `LegacyPresenter` that wraps today's `build_*` functions. `detail.py`
  dispatches through the registry. **Zero behaviour change**; full suite green.
- **P1 — ontology overview.** Implement `OntologyOverviewPresenter` with the new
  Health / Completeness / Structure / Activity layout (§5). Delivers the
  user-visible reorganization first. Snapshot + field tests updated.
- **P2…P6 — per entity.** Migrate `class → property → individual → concept → scheme`
  one presenter per step: move the existing `_*_fields` bodies into hooks,
  normalize to the canonical section order, retire the old `build_*` function and
  its `LegacyPresenter` shim. Each step shrinks `logic.py` and is independently
  shippable.
- **P7 — taxonomy overview** + delete the last shims.

## 9. Testing strategy

- **Base** (pure, no Textual): a fake presenter proves `render()` emits hooks in
  canonical order, drops empty sections, and inserts separators.
- **Per subclass** (pure): given a small `Taxonomy`, assert the section set,
  ordering, the actionable Health rows (correct `meta` action), and the
  Completeness percentages — reusing the existing `test_tui_overview` /
  `test_tui_detail` style (`build_* → DetailField` assertions).
- **Integration**: the existing `DetailView` / snapshot tests stay green through
  P0 (LegacyPresenter), then are updated per entity as it migrates.
- **Ratchet**: each presenter hook stays ≤ 10; the template `render()` is a flat
  concat (≤ 5). The refactor *reduces* `logic.py`'s god-functions.

## 10. Risks & mitigations

- *Behaviour drift during migration* → P0 wraps the existing builders verbatim
  (byte-identical output), so the redesign only changes a kind once its
  dedicated test is in place.
- *Over-abstraction* → only seven hooks, all optional; subclasses mostly delegate
  to existing helpers. No section is invented that no entity uses.
- *Signature churn* → `PresenterContext` absorbs future inputs in one place.
