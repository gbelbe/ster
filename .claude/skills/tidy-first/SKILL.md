---
name: tidy-first
description: Before writing a feature or fix, tidy the code you're about to touch — a small, behavior-preserving structural commit, separate from the behavioral one, named for which tidying it is (Kent Beck's "Tidy First?" catalog). Use before starting any change to an existing file, class, or function; consult when the tidy ratchet (pre-push hook / CI) blocks a push for missing a tidy(<type>): commit.
---

# Tidy First

Kent Beck's discipline, from *Tidy First?*: every commit is either **structural**
(doesn't change behavior — a rename, an extraction, a reorder) or **behavioral**
(changes what the code does). Never both in one commit. When a feature is
awkward to build in the code as it stands, tidy first — make the small
structural change that makes room, as its own commit — then build the feature
on the simpler shape.

## Procedure (before writing the feature/fix)

1. Read the file(s)/function(s)/class(es) the feature is about to touch.
2. Check them against the table below. For each smell that applies, work out
   the candidate tidying and what it's actually worth here: the smell you
   found, the tidying that addresses it, and the value it brings to the
   feature that follows (e.g. "extracting `Explaining Constant` for this `3`
   means the retry-count change two lines down is a one-line diff instead of
   a guess about which `3` is which").
3. **Ask for confirmation before touching anything — don't decide silently.**
   Which tidying (if any) is worth doing is a judgment call the ratchet can't
   make, so surface it (e.g. with `AskUserQuestion`):
   - One candidate: state the smell, the tidying, and the value it brings,
     and ask for a go/no-go.
   - Several candidates: present them as options, each with its own value
     explanation, and ask which to do — "none of these" is a valid answer.
4. Once confirmed, make *only* that change, confirm the existing tests still
   pass unchanged, and commit it alone: `tidy(<type>): <what and where>`
5. Only then write the feature/fix as its own `feat(...)` / `fix(...)` commit.
6. If nothing applies, or the user declines every option, don't invent a
   tidying to satisfy the ratchet — commit the feature with a one-line
   `Tidy-Exempt: <reason>` trailer instead.
7. Never mix a `tidy(...)` commit with a behavior change in the same diff.

## The catalog

| Cluster | Tidying | What it does |
|---|---|---|
| Clarify meaning | Explaining Variable | Extract part of an expression into a well-named variable |
| Clarify meaning | Explaining Constant | Replace a magic literal with a named constant |
| Clarify meaning | Explaining Comment | Add a comment where the *why* isn't inferable from the code |
| Clarify meaning | Delete Redundant Comment | Remove a comment that just restates the code |
| Simplify control flow | Guard Clauses | Replace nested conditionals with early returns |
| Simplify control flow | Dead Code | Delete code nothing calls |
| Simplify control flow | Normalize Symmetries | Make equivalent code consistent in style, so real differences stand out |
| Reorganize for reading | Reading Order | Arrange declarations in the order a reader needs them |
| Reorganize for reading | Cohesion Order | Put things that change together, physically together |
| Reorganize for reading | Chunk Statements | Group related statements before extracting |
| Reorganize for reading | One Pile | Temporarily collapse scattered related elements to see the whole shape before re-splitting |
| Isolate behavior | Extract Helper | Pull a coherent chunk into a named function |
| Isolate behavior | Move Declaration and Initialization Together | Relocate a variable's declaration next to its use |
| Change the contract | Explicit Parameters | Turn an implicit dependency (shared/ambient state) into an explicit parameter |
| Change the contract | New Interface, Old Implementation | Introduce the calling shape you want, delegating to the existing implementation, before changing behavior |

## Smell → tidying lookup

| You notice... | Do this first |
|---|---|
| Adding a branch to code that's already deeply nested | Guard Clauses |
| The sibling of what you're changing was written in a different style | Normalize Symmetries |
| You need to change a function's signature/calling shape | New Interface, Old Implementation |
| The function you must extend does two+ unrelated things | Extract Helper |
| Declarations are scattered away from their use, and you're adding one more | Move Declaration and Initialization Together |
| The expression you must touch has a magic number or an unnamed condition | Explaining Constant / Explaining Variable |
| Dead/unreachable code sits next to where you need to add a case | Dead Code |
| The code you need is logically related to code far away in the file | Cohesion Order / Reading Order |
| The block you must extend is an undifferentiated wall of statements | Chunk Statements (often followed by Extract Helper) |
| A nearby comment is stale or just repeats the code | Delete Redundant Comment |
| The rationale for existing behavior isn't obvious and you're changing adjacent logic | Explaining Comment |
| You're passing something implicitly (global/shared object) into new code | Explicit Parameters |

## Commit convention

```
tidy(guard-clauses): flatten nested null-checks in OrderValidator#validate

Tidy-Type: guard-clauses
Tidy-Scope: OrderValidator#validate
```

The type slug matches the tidying's row above, kebab-cased (`guard-clauses`,
`dead-code`, `normalize-symmetries`, `new-interface-old-implementation`,
`reading-order`, `cohesion-order`, `move-declaration-init`,
`explaining-variable`, `explaining-constant`, `explicit-parameters`,
`chunk-statements`, `extract-helper`, `one-pile`, `explaining-comment`,
`delete-redundant-comment`).

## The ratchet

`scripts/check_tidy_ratchet.sh --base <ref>` fails if the commit range has no
`tidy(...)` commit and no `Tidy-Exempt:` trailer. It's a text check on commit
messages only — no test run, no build — so it costs milliseconds locally
(pre-push hook) and in CI (its own job, PR-only). It cannot judge *which*
tidying was right, only that the discipline (or an explicit, reviewable
exemption) was followed.

## Query your tidying history

```bash
# everything
git log --oneline --grep='^tidy('

# counts per type, per month
git log --pretty=format:'%ad %s' --date=format:'%Y-%m' --grep='^tidy(' -E \
  | sed -E 's/^([0-9-]+) tidy\(([a-z-]+)\).*/\1 \2/' \
  | sort | uniq -c | sort -rn
```

## Don't let the exemption become the rule

`Tidy-Exempt:` trusts the author's judgment, which is exactly the kind of
thing that erodes under deadline pressure. Check the ratio periodically,
don't just trust the gate exists:

```bash
git log --grep='^tidy(' --oneline | wc -l
git log --grep='^Tidy-Exempt:' --oneline | wc -l
```

If exemptions start dominating tidyings, that's a signal the discipline
slipped — the response is to look at *why*, not to remove the check.

The same caution applies to any other diff-aware skip heuristic added to this
repo (e.g. a CI job that skips a slow test tier based on changed paths): only
widen what it trusts from evidence — an actual import-graph check, a real
dependency trace — never from a hunch, and keep an unconditional full run on
a schedule independent of what any single change skipped. A heuristic that
quietly gets more permissive over time is the same failure mode as a rubber-
stamped exemption, just automated.
