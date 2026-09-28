# Craftsmanship catalog

This is the source of truth. It does not assume any particular AI tool or
editor — a human contributor, a CI script, or an agent can all read this file
directly. Tool-specific wrappers (a Claude Code skill, a pre-commit hook, a
CI job) point back here rather than re-stating it.

Two separate concerns, on purpose:

1. **Writing new code well the first time** — a checklist, not a commit
   ritual. Nothing to "tidy" in code that doesn't exist yet.
2. **Changing existing code safely** — Kent Beck's *Tidy First?* discipline:
   every commit is either structural (doesn't change behavior) or behavioral
   (changes what the code does), never both. When existing code is untested
   ("legacy," per Feathers' definition below), tidying needs a safety net
   first.

Every entry below is attributed. When you act on one — proposing it to the
developer, or citing it in a commit — **name the smell and its source**, the
same way you'd cite a source in any other claim. "This function does two
unrelated things (Feature Envy, Fowler)" is a specific, checkable claim.
"This could be cleaner" is not.

## Procedure

### Before writing a feature or fix on existing code

1. Read the file(s)/function(s)/class(es) the change is about to touch.
2. Check them against the catalog below. For each smell that applies, work
   out what it's actually worth here: the smell you found, its source, the
   tidying/refactoring that addresses it, and the concrete value it brings to
   the change that follows.
3. **Ask the developer to confirm before touching anything — don't decide
   silently.** Which tidying (if any) is worth doing is a judgment call the
   automation can't make:
   - One candidate: state the smell (with its source), the fix, and the
     value it brings; ask for a go/no-go.
   - Several candidates: present them as options, each with its own value
     explanation and source; ask which to do — "none of these" is valid.
4. Once confirmed, make *only* that change, confirm existing tests are
   unchanged, and commit it alone (see **Commit convention** below).
5. Only then commit the feature/fix itself, as its own commit.
6. If nothing applies, or the developer declines every option, don't invent
   one — commit the feature with a `Tidy-Exempt:` trailer instead (see
   below).
7. Never mix a tidying commit with a behavior change in the same diff.

### Before writing new code

Run it past the **new-code checklist** below *before* declaring it done —
this is a design pass, not a commit type. There's no ratchet for it because
"is this well-designed" isn't mechanically checkable the way a diff is; it's
on the author and the reviewer.

### Before refactoring code with no tests (legacy code)

See **Working with legacy code** below — write a characterization test
first, then tidy under its safety net.

---

## The catalog

### Structural tidyings — Kent Beck, *Tidy First?* (2023)

Small, purely structural moves: they don't change behavior, so a tidying
commit's test results must be identical before and after.

| id | Name | Smell / when to reach for it | What it does |
|---|---|---|---|
| `guard-clauses` | Guard Clauses | Deeply nested conditionals hide the common case | Replace nested conditionals with early returns |
| `dead-code` | Dead Code | Code nothing calls | Delete it |
| `normalize-symmetries` | Normalize Symmetries | Equivalent code expressed in different styles, hiding which differences are real | Make the style consistent so real differences stand out |
| `new-interface-old-implementation` | New Interface, Old Implementation | You need to change a function's calling shape | Introduce the calling shape you want, delegating to the existing implementation, before touching behavior |
| `reading-order` | Reading Order | Declarations aren't in the order a reader needs them | Reorder for the reader, not the writer |
| `cohesion-order` | Cohesion Order | Things that change together live far apart | Put them physically together |
| `move-declaration-init` | Move Declaration and Initialization Together | A variable's declaration is far from its use | Relocate it next to where it's set/used |
| `explaining-variable` | Explaining Variable | An expression's meaning isn't obvious | Extract part of it into a well-named variable |
| `explaining-constant` | Explaining Constant | A magic literal | Replace it with a named constant |
| `explicit-parameters` | Explicit Parameters | A function reaches into shared/ambient state | Turn the implicit dependency into an explicit parameter |
| `chunk-statements` | Chunk Statements | An undifferentiated wall of statements | Group related statements before extracting |
| `extract-helper` | Extract Helper | A coherent chunk of logic embedded inline | Pull it into a named function |
| `one-pile` | One Pile | Related elements scattered with no visible shape | Temporarily collapse them to see the whole shape before re-splitting sensibly |
| `explaining-comment` | Explaining Comment | The *why* isn't inferable from the code | Add a comment — but only for the why, never the what |
| `delete-redundant-comment` | Delete Redundant Comment | A comment just restates the code | Remove it |

### Smells and their fixes — Fowler (with Beck), *Refactoring*, 2nd ed. (2018)

Broader than Tidy First's structural-only scope — these describe design
problems and their standard fixes. They apply to existing code you're about
to touch *and* are worth watching for while writing new code.

| id | Name (smell) | Smell / when to reach for it | What it does |
|---|---|---|---|
| `extract-class` | Large Class / God Class / Divergent Change | A class doing too much, or changing for many unrelated reasons | Split it along its actual responsibilities |
| `move-method` | Feature Envy / Data Class | A method more interested in another object's data than its own; or a class that's all data, no behavior | Move the method to the data (or the behavior into the data class) |
| `introduce-parameter-object` | Data Clumps | The same group of parameters travels together across call sites | Give the group its own type |
| `replace-primitive-with-object` | Primitive Obsession | A raw string/int stands in for a real domain concept (money, a URI, a version) | Give the concept its own type |
| `hide-delegate` | Message Chains | `a.getB().getC().getD()` reaches through several objects (Law of Demeter) | Hide the chain behind a method on the first object |
| `replace-conditional-with-polymorphism` | Repeated Switches | The same type-based branching logic scattered across the codebase | Replace it with dispatch (polymorphism, a strategy, a registry) |
| `collapse-hierarchy` | Speculative Generality | Abstraction or a hook built for a future that hasn't arrived | Collapse it back to what's actually used — this is YAGNI already sitting in the code |
| `replace-inheritance-with-delegation` | Refused Bequest | A subclass uses only a fraction of what it inherits | Prefer composition over the ill-fitting inheritance |
| `consolidate-duplicate-conditional` | Shotgun Surgery (conditional form) | One logical decision is duplicated as near-identical conditionals in several places | Consolidate into one decision point |

*Comments as a smell* (Fowler, and independently Martin below): a comment
explaining *what* a block does is a signal the block wants a name, not a
comment — that's `extract-helper`/`explaining-variable`, not
`explaining-comment`. Reach for `explaining-comment` only for *why*, never
*what*.

*Alternative Classes with Different Interfaces*: usually the same situation
as `normalize-symmetries` one level up — two things that do the same job
should look like it.

### New-code principles — Robert C. Martin, *Clean Code* (2008)

Design checklist, not a commit ritual — apply while writing, not after.

- **A function does one thing, and stays small.** If you're reaching for
  "and" to describe what it does, it's two functions.
- **Prefer 0–2 arguments; 3 is a smell, more needs restructuring** — often
  `introduce-parameter-object` (above) is the fix, before the function is
  even written.
- **No flag arguments.** A boolean parameter that makes a function silently
  do one of two different things should be two functions.
- **Command-Query Separation.** A function either does something or answers
  something — never both. A function named `getX` that also mutates state
  will surprise every caller that doesn't read its body.
- **SOLID** (Martin, *Agile Software Development*, 2002) — most relevant day
  to day: **Dependency Inversion** (isolate an external library behind a
  thin internal adapter — the rest of the code depends on your interface,
  not the library) and **Single Responsibility** (one reason to change,
  which is exactly what `extract-class` fixes after the fact).

### The bar for new code — Kent Beck, *Extreme Programming Explained* (1999/2004)

Beck's four rules of simple design, **in priority order** — when they
conflict, an earlier rule wins:

1. Passes all the tests.
2. Reveals intention (a reader doesn't have to guess what it's for).
3. No duplication.
4. Fewest elements (no speculative generality — YAGNI, applied prospectively).

### A stricter optional reference — Sandi Metz's rules

Deliberately extreme, meant to provoke a conversation rather than be taken
literally: classes ≤100 lines, methods ≤5 lines, ≤4 parameters. Useful when
a project's own complexity ceiling feels too permissive and the team wants a
sharper target to aim for — not a gate.

---

## Working with legacy code — Michael Feathers, *Working Effectively with Legacy Code* (2004)

Feathers' definition: **legacy code is code without tests** — age is
irrelevant. Untested code can't be tidied safely the normal way, because
"confirm the existing tests are unchanged" (the whole point of a structural
commit) has nothing to confirm against.

The procedure, step by step:

1. **Find a seam** — a place you can observe or change behavior without
   editing the code at that exact spot (a constructor argument, a factory,
   an injected dependency).
2. **Write a characterization test** — a test that documents what the code
   *actually does right now*, including its bugs. It isn't asserting the
   code is correct, only that you've pinned its current behavior down before
   touching it. Commit it on its own:
   ```
   test(characterize): pin OrderValidator.validate's current null-handling

   Tidy-Source: Michael Feathers, Working Effectively with Legacy Code (2004)
   ```
3. **Now tidy or refactor under that safety net**, same procedure as above —
   the characterization test is what "confirm existing tests are unchanged"
   means for code that had no tests at all a moment ago.
4. Once real (intent-driven, not just characterizing) tests exist, the code
   graduates out of "legacy" — the characterization test can be extended or
   replaced by tests that assert *intended* behavior rather than merely
   *current* behavior.

A `test(characterize):` commit satisfies the tidy-ratchet the same way a
`tidy(<type>):` commit does (see **The ratchet**) — it's the prerequisite
move for legacy code, not an exemption from the discipline.

---

## Commit convention

```
tidy(extract-class): split OrderValidator's audit-log concern into its own class

Tidy-Type: extract-class
Tidy-Source: Martin Fowler (with Kent Beck), Refactoring, 2nd ed. (2018)
Tidy-Scope: OrderValidator
```

- **Subject**: `tidy(<id>): <what and where>`, `<id>` from the catalog's
  `id` column.
- **`Tidy-Type:`** — same id, machine-queryable.
- **`Tidy-Source:`** — the author/book the smell or tidying comes from. If
  it's a locally-invented tidying not in this catalog, say so plainly
  (`Tidy-Source: project convention, see docs/...`) rather than omit it —
  the point is traceability, not gatekeeping which sources count.
- **`Tidy-Scope:`** — the function/class/module touched.

If nothing applied and none was invented:

```
Tidy-Exempt: <one-line reason>
```

Legacy-code prerequisite work uses `test(characterize):` (see above) instead
of `tidy(...)`.

## The ratchet

A commit-message check (`scripts/check_tidy_ratchet.sh`) fails a push/PR
whose commit range has no `tidy(<type>):` commit, no `test(characterize):`
commit, and no `Tidy-Exempt:` trailer. Text-only, no test run — costs
milliseconds. It cannot judge whether the right tidying was picked, only
that the discipline (or an explicit, reviewable exemption) was followed.

## Don't let the exemption become the rule

`Tidy-Exempt:` trusts the author's judgment, which erodes under deadline
pressure like any such gate. Check the ratio periodically, don't just trust
the gate exists:

```bash
git log --grep='^tidy(' --oneline | wc -l
git log --grep='^Tidy-Exempt:' --oneline | wc -l

# which sources actually get cited
git log --grep='^Tidy-Source:' -E --pretty=format:'%b' \
  | grep '^Tidy-Source:' | sort | uniq -c | sort -rn
```

If exemptions start dominating tidyings, that's a signal the discipline
slipped — the response is to look at *why*, not to remove the check.

The same caution applies to any other diff-aware skip heuristic a project
adds on top of this (e.g. a CI job that skips a slow test tier based on
changed paths): only widen what it trusts from evidence — an actual
import-graph check, a real dependency trace — never from a hunch, and keep
an unconditional full run on a schedule independent of what any single
change skipped. A heuristic that quietly gets more permissive over time is
the same failure mode as a rubber-stamped exemption, just automated.

## Query your history

```bash
# everything
git log --oneline --grep='^tidy(\|^test(characterize):'

# counts per type, per month
git log --pretty=format:'%ad %s' --date=format:'%Y-%m' --grep='^tidy(' \
  | sed -E 's/^([0-9-]+) tidy\(([a-z-]+)\).*/\1 \2/' \
  | sort | uniq -c | sort -rn
```
