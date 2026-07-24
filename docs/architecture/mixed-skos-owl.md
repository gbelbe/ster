# Architecture: one navigable tree for a mixed SKOS + OWL/RDFS project

Status: **proposed** (design agreed, not yet implemented)
Audience: ster maintainers
Related: [module-layout.md](module-layout.md), [detail-presenter.md](detail-presenter.md), [core-service.md](core-service.md)

> Visual companion (glyphs, colours, lens mockups, both ster themes):
> the "One tree, two logics" mockup.

## 1. Why

ster today shows a project as **two separate trees**: an *Ontology* section
(OWL classes + individuals, walked on `rdfs:subClassOf`) and a *Taxonomy*
section (SKOS schemes + concepts, walked on `skos:broader`). For a project that
is purely one or the other, that is exactly right. For a **mixed** project — a
business-term glossary where most terms are SKOS concepts and a minority are
also OWL classes — the split forces the curator to decide *twice* where a term
lives and to navigate two half-pictures of the same thing.

We want an **integrated view**: a single navigable spine for mixed projects.
The constraint is that we must **not** degrade the clean, single-paradigm
experience for purely-OWL/RDFS or purely-SKOS projects.

The good news is that the split is only in the *presentation*. The domain model
already carries everything the integrated view needs.

> **Governing principle — paradigm-agnostic.** ster must not privilege SKOS or
> OWL/RDFS. It reads whatever the file contains and adapts; there is no "mode"
> the user selects. Pure-SKOS, pure-OWL/RDFS, and mixed are **not three products
> — they are one engine seeing three inputs.** Everything below follows from
> this: one tree builder, one context-menu system, one notation, and the "shape"
> of a project is emergent, never configured (§8).

## 2. Background: why the two hierarchies can't just be merged

The two hierarchies live at **different meta-levels**, which is why no tool
merges them for you:

- An OWL hierarchy is `rdfs:subClassOf` between `owl:Class` nodes — transitive,
  inheritable, reasoner-backed, part of the schema.
- A SKOS hierarchy is `skos:broader` between `skos:Concept` nodes — and from
  OWL's point of view every concept is merely an **individual** of the class
  `skos:Concept`.

A tool that walks `subClassOf` sees your concepts as a flat pile of instances;
a tool that walks `broader` never sees your classes at all. So any renderer has
to **pick one predicate as the spine** and demote the other to a badge/facet.
The whole design below is that deliberate choice, made once.

## 3. The strategy: the SKOS spine, with OWL laid over it

The pattern (from the *"Mixing a SKOS Taxonomy with an OWL Class Hierarchy"*
working note, 2026‑07‑13) is an **asymmetry**, not a symmetry:

- The **SKOS `broader` tree is the complete navigation spine** — the full
  inventory of terms.
- The **OWL `subClassOf` tree is a thin, selectively-promoted subset** laid
  over it. Most business terms never become classes; only a slice has genuine
  subsumption.

And one directional rule holds the whole thing together:

> **Derive `skos:broader` from `rdfs:subClassOf` — never the reverse.**

The navigation tree walks `broader` only, so it sees **everything**: grouping
edges *and* inheritance edges. The reasoner/export walks `subClassOf` only, so
it sees a **strict, sound subset**. Neither layer degrades the other.

A **promoted** term is punned: it is *both* a `skos:Concept` and an `owl:Class`
(OWL 2 DL punning). It carries an **asserted** `rdfs:subClassOf` (real
inheritance) and an **inferred** `skos:broader` (the bridge rule, below).

```
# grouping bucket — navigation only, NOT a class
ex:SalesDomain  a skos:Concept ;
    skos:prefLabel "Sales"@en ; skos:topConceptOf ex:Glossary .

# a promoted term — BOTH a concept and a class (punning)
ex:Order  a skos:Concept, owl:Class ;
    skos:prefLabel "Order"@en ;
    skos:broader ex:SalesDomain .            # asserted — pure grouping

ex:OnlineOrder  a skos:Concept, owl:Class ;
    skos:prefLabel "Online Order"@en ;
    rdfs:subClassOf ex:Order .               # asserted — real inheritance
    # skos:broader ex:Order   <- INFERRED by the bridge rule, never stored
```

### The bridge rule (view-time, not stored)

```sparql
CONSTRUCT { ?sub skos:broader ?super }
WHERE { ?sub rdfs:subClassOf ?super .
        ?sub a skos:Concept . ?super a skos:Concept .
        FILTER(?sub != ?super) }
```

ster runs this as a **derivation over the in-memory graph** (in
`taxonomy_to_graph` / a view builder), **not** as a triple written to the file.
The `.ttl` stays clean: `OnlineOrder subClassOf Order` is asserted; its
`broader Order` is computed on read.

## 4. What ster already has

The model is ~80% ready — the integrated view is a *projection*, not a new data
model:

- `Concept.broader` (`ster/model.py:49`) and `RDFClass.sub_class_of`
  (`ster/model.py:174`) already exist as **distinct edges**.
- `Taxonomy.node_type(uri)` (`ster/model.py:342`) already returns
  **`"promoted"`** when a URI is in *both* `concepts` and `owl_classes` — this
  is precisely the working note's "promoted term" (the pun).

  ```python
  def node_type(self, uri):
      in_concepts = uri in self.concepts
      in_classes  = uri in self.owl_classes
      if in_concepts and in_classes: return "promoted"
      if in_concepts: return "concept"
      if in_classes:  return "class"
      ...
  ```

What is missing is the **view**, the **bridge derivation**, the **promotion
action**, and the **governance checks** — all additive.

## 5. The integrated tree

In **mixed** mode, replace the two panes (`_build_main_tree`'s Ontology +
Taxonomy sections) with **one** tree that walks `broader ∪ (broader derived
from subClassOf)`. Every term appears exactly once.

```
Business Glossary                     scheme
├─ ◌ Sales                            guide term
│  ├─ ◉ Order                         concept · class
│  │  ├─ ● Online Order               class · ⊂ Order
│  │  └─ ● Store Order                class · ⊂ Order
│  └─ ○ Discount                      concept
├─ ◉ Customer                         concept · class
│  └─ ● VIP Customer                  class · ⊂ Customer
└─ ○ Region                           concept
```

Two kinds of edge share the one spine:

- an **inheritance** edge (came from `subClassOf`) — marked `⊂`, "is a kind of";
- a **grouping** edge (pure `broader`) — plain, "is grouped under".

The edge kind is a light secondary marker; the primary signal is the **node
glyph** (what the node *is*).

### Multiple roots — the disconnected case

The spine is a **forest**, not a single tree: it has one root per top-level
anchor — each `skos:ConceptScheme`, the OWL root (`owl:Thing`), and any loose
individuals. **A pun is the only thing that merges a branch across the SKOS/OWL
boundary**: its derived `broader` edge grafts a class subtree *up* under its
concept parent. So the amount of integration is exactly the amount of punning:

- **No puns** — the two hierarchies never meet; the tree shows two branches
  (the scheme(s) and `owl:Thing`). This is today's split, but as sections of
  *one* navigable tree with unified notation — honest, not a forced merge.
- **Some puns** — those branches merge; the rest stay separate.
- **Heavy punning** — mostly one spine.

```
▾ Business Glossary            skos:ConceptScheme     ← taxonomy anchor
│  ├─ ○ Region
│  └─ ◉ Order                  pun — pulls its class subtree up here
│     ├─ ● Online Order
│     └─ ● Store Order
▾ owl:Thing                    OWL classes            ← ontology anchor
   ├─ ● Vehicle
   │  └─ ● Car
   └─ ◆ alice                  individual (loose)
```

If `Order` were **not** punned, its `● Online/Store Order` classes would sit
under `owl:Thing`, not under the glossary — the two roots would be fully
separate. The integrated view therefore never *invents* a connection; it only
shows the ones that exist (via `broader`, or `subClassOf` on a pun).

## 6. Node notation

Shapes are borrowed from the notation people already read (**Protégé / VOWL**):
circle = class, diamond = individual, box = property. SKOS has no house icon, so
a concept is a *hollow* circle — a category that isn't a formal class — and the
pun is a concept with its centre *filled in* to a class. Colour is the fast
signal; the **glyph carries the same meaning** for anyone who can't rely on hue
(and ster already spends red/orange/green on lint severity).

| Node type | Glyph | Colour | Convention |
|---|:---:|---|---|
| OWL class | `●` | yellow | Protégé's class circle · `rdfs:subClassOf` |
| SKOS concept | `○` | green | hollow circle — a category, not a formal class · `skos:broader` |
| Promoted (pun) | `◉` | orange | filled-core circle — concept **and** class |
| Guide term | `◌` | grey | dotted circle — grouping only, never `a owl:Class` |
| Individual | `◆` | purple | Protégé's individual diamond |
| Property | `▪` | blue | Protégé's property box (properties pane) |
| Inheritance edge | `⊂` | — | child *is-a* parent (from `subClassOf`) |
| Scheme / root | `▾` | grey | `skos:ConceptScheme` / `owl:Thing` |

The glyphs form a **progression**: a concept `○`, promoted, has its centre
filled `◉`, and becomes a full class `●` — so "concept → pun → class" reads as a
single visual story, while the individual stays an unmistakable diamond.

Design note: yellow (class) and orange (pun) are deliberately close warm hues —
a pun *is* a class — and the glyph (`●` vs `◉`) does the real separating. Push
the pun toward magenta if fully-distinct hues are preferred.

## 7. Lenses, not panes

The answer to *"should there still be a separate taxonomy tree?"* is: **as a
view, yes; as a second pane, no.** A permanent second tree is the split we are
escaping — it duplicates every shared node. Keep **one** tree and let a toolbar
switch its filter:

```
 Full        broader ∪ derived — everyone's shared artifact
 Taxonomy    broader only, all nodes shown as concepts — the curator's job
 Ontology    subClassOf only, collapses to the promoted subset — the reasoner's world
```

This directly serves the note's *two jobs, two stakeholders* (curation vs
modelling) without a parallel navigation. The **properties pane is orthogonal**
and stays as-is.

## 8. Agnostic by construction — the shape is emergent, not a mode

Per the governing principle (§1), there is **no "SKOS mode" vs "OWL mode"** to
pick. The engine is uniform, and the integrated view is not a special third mode
bolted on — it is the *general case*, of which pure-SKOS and pure-OWL are the two
endpoints. One tree builder walks the union spine (`broader ∪ derived`); one
context-menu system keys on `node_type()`; one notation renders each node by its
kind:

| The file contains… | What emerges — no mode, no config |
|---|---|
| only concepts | a scheme forest; only `○`/`◌` glyphs and concept/scheme menus appear |
| only classes | the `owl:Thing` tree; only `●`/`◆`/`▪` glyphs and class menus appear |
| both | both roots; puns merge branches where they exist (§5) |

So **"keeping pure projects clean" is not a special case to maintain — it's an
emergent property.** A pure project never *instantiates* the other paradigm's
nodes, so its glyphs and menus simply never appear. There is no
`if skos_mode: hide_owl` branch to get wrong; there is only "render each node by
its kind," which is the same code for all three inputs.

The only concession to shape is a sensible **default lens** (§7) — Full when a
project mixes, otherwise the single-paradigm view it already resolves to — and
even that is *derived* from the store counts (`owl_classes` / `concepts` /
`promoted`), never a setting the user manages.

## 9. Editing: context menus and where things get added

The "where do I add a concept scheme / class / individual?" question answers
itself once the menu is **keyed on `node_type()`** — which is exactly how ster's
`context_actions(kind)` and the section-header menus already work. Because the
tree is a forest with clear per-kind anchors (§5), every "add" has one
unambiguous home: **you add it under the node whose kind matches.**

| Right-click on… | node_type | Offers |
|---|---|---|
| the **Taxonomy anchor** (a scheme header) | scheme | **＋ Add concept scheme** · Add top concept |
| the **Ontology anchor** (`owl:Thing` header) | — | **＋ Add class** |
| a concept `○` | concept | Add narrower concept · Add related · Move · Rename · Delete |
| a class `●` | class | Add subclass · Add individual · Add class property · Rename · Delete |
| a **pun** `◉` | promoted | **both** sets — plus the branch-defining fork below |
| an individual `◆` | individual | Add type · Add property value · Convert to class · … |

This is the same machinery ster ships today — the integrated tree changes
**nothing** about it. It just renders the anchors in one tree instead of two
panes, and lets `node_type()` pick the actions. A pure-SKOS project only ever
surfaces scheme/concept menus; a pure-OWL project only class/individual menus —
agnostic, per §8.

### The pun's fork — grouping vs inheritance, made explicit

The one genuinely new decision is on a **promoted** node: adding a child means
choosing the *edge kind*, and the menu makes it explicit rather than guessing:

- **＋ Add narrower concept** → a `skos:broader` child (grouping only; the child
  is a plain concept `○`).
- **＋ Add subclass** → an `rdfs:subClassOf` child (real inheritance; the child
  is a class `●`).

This is where the invariant of §11 lives in the UI: inheritance is only ever
created by a deliberate "Add subclass" (or "Promote"), never inferred from a
grouping edge.

### Promotion / demotion

ster already ships class↔individual punning (`class_to_individual` /
`individual_to_class`). Mirror it for the concept↔class axis — the note's
"taxonomy first, then promote":

- **Promote to class** (on a `concept`): add `a owl:Class`, and offer to assert
  `rdfs:subClassOf` to its current `broader` parent → the grouping edge becomes
  a real inheritance edge. The node becomes `promoted`.
- **Demote to guide term** (on a `promoted`): drop `owl:Class` + `subClassOf`;
  it falls back to grouping-only.

Both are ordinary `TaxonomyService` commands, reusing the context-menu +
detail-view plumbing that already exists.

## 10. Governance — semanticlint checks

The note's rules are exactly the "fails silently" cases ster's quality pass
exists for. They become semanticlint / SHACL checks (which ster already
generates and enforces):

1. **`subClassOf ⊆ broader`** — every asserted class edge must have a
   (derivable) broader edge; never promote a grouping edge just because the tree
   "looks like" a hierarchy.
2. **Guide terms are never `a owl:Class`** — this is what keeps a "Sales Domain"
   bucket out of your reasoning.
3. **Puns declare both types explicitly** — OWL 2 DL permits punning, but strict
   profile validators want `skos:Concept` *and* `owl:Class` spelled out.
4. **Do not materialise `skos:broaderTransitive`** — it is correct across
   inheritance edges and *wrong* across grouping ones (`broader` is deliberately
   non-transitive). No navigation UI needs it.

## 11. The invariant to build around

> **Never write a `subClassOf` edge *from* a `broader` edge.**

The tree may *display* a broader edge derived from `subClassOf` (the `⊂`
marker), but turning a grouping edge into a class edge — promotion — is always a
deliberate, reviewed action, never automatic.

### 11.1 Why the bridge is one-way

The two relations are not two flavours of the same thing — one is a strong
logical axiom, the other a weak navigation hint. The rule is just "you may
weaken a strong claim, never strengthen a weak one."

- **`rdfs:subClassOf` is a universally-quantified, reasoner-consumed axiom.**
  `A subClassOf B` asserts *every instance of A is necessarily a B*, A inherits
  all of B's constraints (domain/range/restrictions/disjointness), and it is
  **transitive** — a reasoner propagates it and uses it in consistency checking.
  Getting it wrong doesn't mislabel a node; it silently generates false
  entailments everywhere downstream.
- **`skos:broader` is a deliberately non-logical grouping.** SKOS makes it
  **non-transitive** on purpose (hence the separate `broaderTransitive`) and it
  carries **zero** entailment about instances or inheritance. It means "a
  curator would file X under Y." Its cost of being wrong is a click.

The asymmetry that follows:

- **`subClassOf` → `broader` (always safe).** If `OnlineOrder subClassOf Order`,
  then "Order is broader than OnlineOrder" is also true, informally. Every real
  inheritance edge is legitimately a grouping edge too — deriving it **discards**
  logical force, never adds a claim. Weakening is sound, so the nav spine can
  safely be derived from every class edge.
- **`broader` → `subClassOf` (fabricates truth).** File `Order broader
  SalesDomain` because "Sales" is a bucket to organise the glossary; derive
  `subClassOf` from it and you've asserted *"every Order is necessarily a
  SalesDomain and inherits its constraints"* — a false universal claim invented
  from a filing decision. "Sales Domain," never meant to be a class, becomes an
  `owl:Class` with instances; constraints propagate through a bucket; the
  reasoner entails nonsense. The note calls this "an ontology polluted with
  buckets."

Three framings of the same point:

- **Soundness** — `subClassOf ⊨` a grouping; `broader ⊭` inheritance. The reverse
  derivation is literally an *unsound inference rule*.
- **Meta-levels** — `subClassOf` is schema-level (between classes); `broader` is
  instance-level (concepts are individuals of `skos:Concept`). Strong→weak
  projects a schema fact down to navigation (harmless); weak→strong **promotes a
  filing annotation up into a schema axiom** — manufacturing schema from a hint.
- **Economics** (§1's opening: cost of a wrong answer) — taxonomy work is cheap,
  done with business people; ontology work is expensive because it propagates
  through reasoning. One-way guarantees the **cheap activity can never silently
  commit you to the expensive one.**

### 11.2 Enforcement — defence in depth

The UI alone can't enforce it (files get hand-edited and imported), so guard it
at three layers:

1. **Structural — the command set is asymmetric by construction (strongest).**
   The bridge (`broader` ← `subClassOf`) is a **view-time derivation** in
   `taxonomy_to_graph`, **never persisted**; there is a CONSTRUCT for
   `broader←subClassOf` and *none* for the reverse. **No command turns a
   `broader` edge into a `subClassOf` edge**, and none is ever added — the only
   producer of "inheritance from a concept" is the explicit `promote_to_class` /
   "Add subclass" a human invokes (§9). Tests lock it: "add narrower concept"
   yields only a `broader` edge; a round-trip never writes a derived `broader`;
   no reverse mutation exists in the command registry.

2. **Quality / CI — semanticlint catches the *symptoms* in any input.** The four
   checks of §10 as SHACL/SPARQL, run in ster's lint pass and in CI: a grouping
   bucket that became `owl:Class`; a `subClassOf` on a marked guide term
   (**error**); a persisted `broader` that mirrors a `subClassOf` (redundant —
   derive on read instead); puns missing a type; a materialised
   `broaderTransitive`.

3. **Import boundary — never synthesise on the way in.** When importing an
   external ontology/taxonomy (`ontology_imports.py`, the ext-ontologies
   screen), import `broader` as `broader` and `subClassOf` as `subClassOf`;
   **do not auto-generate `subClassOf` from `broader`.** Run the layer-2 checks
   on the import and surface violations before the file lands.

Net effect: the tree may *show* a `broader` edge that came from `subClassOf`
(the `⊂` marker), but the only path from grouping to inheritance is a deliberate,
reviewed promotion — the human-in-the-loop the rule exists to protect.

## 12. Where it touches the code

| Concern | Location | Change |
|---|---|---|
| Bridge derivation | `taxonomy_to_graph` / new view builder | CONSTRUCT `broader` from `subClassOf` at read time (not stored) |
| Shape detection | `ster/tui/data.py`, `ster/tui/app.py` on mount | count `owl_classes` / `concepts` / `promoted` → pick mode |
| Integrated tree build | `ster/tui/app.py::_build_main_tree` | mixed mode: one spine walking `broader ∪ derived`; per-node glyph from `node_type()` |
| Lens filter | `ster/tui/app.py` (toolbar action) | Full / Taxonomy / Ontology filter over the one tree |
| Node notation | tree label rendering | glyph + colour per `node_type`; `⊂` edge marker |
| Promoted detail | presenter hierarchy (`detail-presenter.md`) | a `promoted` presenter composing the class + concept facets |
| Promotion commands | `ster/core/commands/…` + context menu | `promote_to_class` / `demote_to_guide_term` |
| Governance | `ster/plugins/semanticlint/…` | the four checks in §10 |

## 13. Prior art

**Grouping buckets.** The **Getty AAT** is the strongest precedent — *guide
terms* (e.g. `<furniture by function>`) that exist purely to organise the tree
and are explicitly marked not-real-concepts. **MeSH** keeps its navigational
tree numbers formally separate from its semantic relationships. Both are decades
of production practice for "grouping with no inheritance".

**The mixing.** **VocBench 3** is the most faithful tool — OWL and SKOS in one
project, separate Class and Concept tabs, SKOS integrity validation.
**TopBraid EDG** includes an Ontology asset collection *into* a Taxonomy
collection with SHACL-driven forms and a configurable tree predicate.
**Collibra** maps cleanly — guide terms + `broader` become a "groups / is
grouped by" relation, `subClassOf` a separate "is a kind of" relation, both in
one browse tree (the closest analogue to §6's two edge kinds). **FIBO** makes
everything an `owl:Class` and borrows SKOS only as annotation — one tree, but it
can't express loose grouping without inventing fake superclasses, so it fails
this requirement. **AGROVOC** and the **EU Publications Office** go the other
way: SKOS as the published artifact, OWL kept separate.

ster's position: adopt the **union-spine + promotion** pattern (VocBench /
Collibra family), keep the file clean by **deriving** the bridge, and lean on
its existing semanticlint layer for the governance the pattern requires.

## 14. Open questions / phasing

- **Phase 1** (smallest useful slice): shape detection + the union-spine tree in
  mixed mode + the `broader`-from-`subClassOf` bridge, behind a flag. Pure
  projects unchanged.
- **Phase 2**: the lens filter (Full / Taxonomy / Ontology) and the `promoted`
  detail presenter.
- **Phase 3**: promotion / demotion commands.
- **Phase 4**: the four governance checks in semanticlint.
- Open: do guide terms need an explicit marker (a `skos:Collection`, or an
  annotation à la Getty) so §10.2 can be enforced, or is "concept without
  `owl:Class` and with children that are classes" a good-enough heuristic?
- Open: should the lens choice persist per-file (like the language pref)?
