# Craftsmanship catalog

This is the source of truth for everything except the two catalog tables
below, which are generated from `catalog.yaml` — edit that file, not the
tables here directly (see the repo's CONTRIBUTING.md, "Adding a heuristic
or rule").
This file does not assume any particular AI tool or editor — a human
contributor, a CI script, or an agent can all read it directly. Tool-specific
wrappers (an agent guidance file, a pre-commit hook, a CI job) point back
here rather than re-stating it.

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
this is a design pass, not a commit type. Most of it (SOLID, the four rules
of simple design, Command-Query Separation) genuinely isn't mechanically
checkable the way a diff is; that part stays on the author and the
reviewer. A meaningful subset of it *is* mechanically checkable, though,
with exact numbers — see **The mechanical floor** below — and staying
inside those numbers while writing is what makes `refactor-first` and
`complexity` pass on the first push instead of a flag-then-fix cycle.
Before calling new code done, run both locally against it: `uv run
python3 scripts/craftcov.py --file <path>` and `uv run python3
scripts/check_complexity_ratchet.py --path <dir> --base origin/main`.

### Before refactoring code with no tests (legacy code)

See **Working with legacy code** below — write a characterization test
first, then tidy under its safety net.

---

## The catalog

### Structural tidyings — Kent Beck, *Tidy First?* (2023)

Small, purely structural moves: they don't change behavior, so a tidying
commit's test results must be identical before and after.

<!-- BEGIN GENERATED: tidying -->
<!-- Generated from catalog.yaml by scripts/render_catalog.py — don't
     hand-edit this table; edit catalog.yaml and run that script instead.
     See CONTRIBUTING.md. -->
| Code | id | Name | Smell / when to reach for it | What it does |
|---|---|---|---|---|
| CG001 | `guard-clauses` | Guard Clauses | Deeply nested conditionals hide the common case | Replace nested conditionals with early returns |
| CG002 | `dead-code` | Dead Code | Code nothing calls | Delete it |
| CG003 | `normalize-symmetries` | Normalize Symmetries | Equivalent code expressed in different styles, hiding which differences are real | Make the style consistent so real differences stand out |
| CG004 | `new-interface-old-implementation` | New Interface, Old Implementation | You need to change a function's calling shape | Introduce the calling shape you want, delegating to the existing implementation, before touching behavior |
| CG005 | `reading-order` | Reading Order | Declarations aren't in the order a reader needs them | Reorder for the reader, not the writer |
| CG006 | `cohesion-order` | Cohesion Order | Things that change together live far apart | Put them physically together |
| CG007 | `move-declaration-init` | Move Declaration and Initialization Together | A variable's declaration is far from its use | Relocate it next to where it's set/used |
| CG008 | `explaining-variable` | Explaining Variable | An expression's meaning isn't obvious | Extract part of it into a well-named variable |
| CG009 | `explaining-constant` | Explaining Constant | A magic literal | Replace it with a named constant |
| CG010 | `explicit-parameters` | Explicit Parameters | A function reaches into shared/ambient state | Turn the implicit dependency into an explicit parameter |
| CG011 | `chunk-statements` | Chunk Statements | An undifferentiated wall of statements | Group related statements before extracting |
| CG012 | `extract-helper` | Extract Helper | A coherent chunk of logic embedded inline | Pull it into a named function |
| CG013 | `one-pile` | One Pile | Related elements scattered with no visible shape | Temporarily collapse them to see the whole shape before re-splitting sensibly |
| CG014 | `explaining-comment` | Explaining Comment | The *why* isn't inferable from the code | Add a comment — but only for the why, never the what |
| CG015 | `delete-redundant-comment` | Delete Redundant Comment | A comment just restates the code | Remove it |
<!-- END GENERATED: tidying -->

### Smells and their fixes — Fowler (with Beck), *Refactoring*, 2nd ed. (2018)

Broader than Tidy First's structural-only scope — these describe design
problems and their standard fixes. They apply to existing code you're about
to touch *and* are worth watching for while writing new code.

<!-- BEGIN GENERATED: smell-fix -->
<!-- Generated from catalog.yaml by scripts/render_catalog.py — don't
     hand-edit this table; edit catalog.yaml and run that script instead.
     See CONTRIBUTING.md. -->
| Code | id | Name (smell) | Smell / when to reach for it | What it does |
|---|---|---|---|---|
| CG016 | `extract-class` | Large Class / God Class / Divergent Change | A class doing too much, or changing for many unrelated reasons | Split it along its actual responsibilities |
| CG017 | `move-method` | Feature Envy / Data Class | A method more interested in another object's data than its own; or a class that's all data, no behavior | Move the method to the data (or the behavior into the data class) |
| CG018 | `introduce-parameter-object` | Data Clumps | The same group of parameters travels together across call sites | Give the group its own type |
| CG019 | `replace-primitive-with-object` | Primitive Obsession | A raw string/int stands in for a real domain concept (money, a URI, a version) | Give the concept its own type |
| CG020 | `hide-delegate` | Message Chains | `a.getB().getC().getD()` reaches through several objects (Law of Demeter) | Hide the chain behind a method on the first object |
| CG021 | `replace-conditional-with-polymorphism` | Repeated Switches | The same type-based branching logic scattered across the codebase | Replace it with dispatch (polymorphism, a strategy, a registry) |
| CG022 | `collapse-hierarchy` | Speculative Generality | Abstraction or a hook built for a future that hasn't arrived | Collapse it back to what's actually used — this is YAGNI already sitting in the code |
| CG023 | `replace-inheritance-with-delegation` | Refused Bequest | A subclass uses only a fraction of what it inherits | Prefer composition over the ill-fitting inheritance |
| CG024 | `consolidate-duplicate-conditional` | Shotgun Surgery (conditional form) | One logical decision is duplicated as near-identical conditionals in several places | Consolidate into one decision point |
| CG032 | `high-cyclomatic-complexity` | High Cyclomatic Complexity | A function has too many independent linear paths through it to reason about or test exhaustively | Extract cohesive chunks into named helpers, or replace branching with dispatch (polymorphism, a strategy, a registry) |
| CG033 | `high-cognitive-complexity` | High Cognitive Complexity | A function's nesting and branching make it hard for a human to hold its logic in mind, even when cyclomatic complexity alone looks fine | Flatten nesting with guard clauses, extract nested blocks into named helpers |
| CG034 | `invariant-return` | Invariant Return | Every return in a function hands back the same never-rebound name, reading as multiple outcomes when it is really one | Collapse to a single exit point, reached by break or fall-through, instead of returning the same name from several places |
| CG035 | `duplicated-string-literal` | Duplicated String Literal | The same string literal (5+ characters) is repeated 3 or more times in one file | Extract it to a named constant so the values can't silently drift apart |
<!-- END GENERATED: smell-fix -->

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
- **Prefer 0–2 arguments; 3 is a smell, more needs restructuring.** Stricter
  than the mechanical gate below (which allows up to 5) on purpose — this is
  the *design* bar, the gate is the *floor* it won't let you fall under.
  Often `introduce-parameter-object` (above) is the fix, before the function
  is even written.
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

### The mechanical floor — the exact numbers the gates check

Everything above is design judgment; these are the literal thresholds
`refactor-first` and `complexity` enforce. Stay under them while writing
and CI passes on the first push instead of a flag-then-fix round trip —
that's the entire point of knowing them in advance rather than only
reactively, after craftCov or the complexity ratchet report something.

| Heuristic | Exact threshold | Checked by |
|---|---|---|
| `introduce-parameter-object` | > 5 parameters | ruff `PLR0913` |
| `extract-helper` | > 50 statements in one function | ruff `PLR0915` |
| `replace-conditional-with-polymorphism` | > 12 branches (`if`/`elif`/`for`/`except`/`match` combined) | ruff `PLR0912` |
| `extract-class` | > 7 instance attributes, or > 20 public methods | pylint `R0902` / `R0904` |
| `explaining-constant` | any numeric literal outside `{-1, 0, 1}` used in a comparison | ruff `PLR2004` |
| `consolidate-duplicate-conditional` | ≥ 8 consecutive lines duplicated elsewhere (exact match, comments/imports/blanks excluded) | `dupes` (calibrated against PMD CPD — see DESIGN.md) |
| `guard-clauses`, `dead-code` | pattern-based, not a count — see the catalog table above | ruff `RET505` / `F401`/`F811`/`F841` + vulture |
| High cyclomatic / cognitive complexity (CG032/CG033) | > 15 (both measures, same threshold, reported separately) | `radon` / `cognitive-complexity` |
| Invariant return (CG034) | pattern-based: every `return` in a function hands back the same never-rebound name | AST check, own logic |
| Duplicated string literal (CG035) | same literal (5+ chars) repeated > 2 times in one file | AST check, own logic |

These are ruff/pylint's **own defaults** (unless a repo's own config
overrides them — check `[tool.ruff.lint.pylint]`/`.pylintrc` before
assuming) — craft-gate didn't invent them, and doesn't second-guess them,
the same "reuse a reference implementation" principle **craftCov** and
**The complexity ratchet** already apply to the tools they wrap.

**Before considering a change done**, not just before touching existing
code: `uv run python3 scripts/craftcov.py --file <path>` and
`uv run python3 scripts/check_complexity_ratchet.py --path <dir> --base
origin/main` both run cleanly against *new* code too, not only against
what Refactor First already tracked before you started. A clean local run
of both is the actual precondition for "CI will pass" — running them is
cheaper and faster than finding out from a failed push.

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

## Refactor First — a mechanically-enforced instance of the procedure above

For any heuristic craftCov can detect (see DESIGN.md's craftCov section, or
`scripts/craftcov.py --list-detectors` — 8 of the 35 entries above as of
this writing), the "which tidying, ask the developer" judgment call in step
3 of the procedure becomes fully mechanical instead:

1. Before touching file `F`, scope craftCov to it:
   `uv run python3 scripts/craftcov.py --file <F>`.
2. For each detectable heuristic present (count > 0), fix exactly **one**
   instance — the catalog's `action` field says what to do. A heuristic at
   0 for this file needs nothing.
3. Bundle every fix into **one** commit, not one per heuristic:

   ```
   tidy(multi): order_validator.py — one fix per present heuristic (4 -> 0)

   Tidy-Scope: order_validator.py
   Tidy-Fix: CG012 extract-helper (Kent Beck, Tidy First? 2023) 3->2
   Tidy-Fix: CG002 dead-code (Kent Beck, Tidy First? 2023) 5->4
   Tidy-Fix: CG009 explaining-constant (Kent Beck, Tidy First? 2023) 2->1
   ```

   `Tidy-Fix:` — repeated, one line per heuristic fixed — replaces the
   single `Tidy-Type:`/`Tidy-Source:` pair for this bundled case: a
   heuristic id, its source, and its before→after count in one line.
   `Tidy-Scope:` stays as in the general convention above.
4. Only then commit the feature/fix itself, as usual.

**Bounded effort, not exhaustive.** This fixes one instance of every present
heuristic type per touch, not the whole file — a heavily-smelly legacy file
doesn't need to be perfect before a feature can land in it, just measurably
better. Counts trend to zero over repeated touches, the same incremental
spirit as the rest of this catalog.

**Enforced, not just documented.** `scripts/check_refactor_first.py` (wired
into CI as the `refactor-first` job, PR-only) fails a PR when a touched
`.py` file's *total* across the 8 detectable heuristics didn't go down
relative to where the branch diverged from its base — or, if the file was
already at 0, went up at all. It re-scans the PR's merge-base tree and its
head tree and compares per file (`dupes` needs every file scanned at each
point to find a match's other half, so there's no cheaper way to get an
accurate "before" count for one file). `Tidy-Exempt:` bypasses it the same
way it bypasses the message-pattern ratchet below — one exemption
mechanism, not two.

This only covers the 8 craftCov-detectable heuristics. Four more (CG032-
CG035) have their own separate mechanical gate — see "The complexity
ratchet" below. The remaining 23 keep the judgment-call procedure above,
backed only by the message-pattern ratchet below, not a count-based gate.

## The complexity ratchet — cyclomatic, cognitive, invariant return, duplicated literal

A second diff-aware gate, independent of craftCov and Refactor First above
(different tools, different catalog entries — CG032-CG035 — no `detectors`
field, since that key specifically means "craftcov.py's own scan covers
this," and these don't). `scripts/check_complexity_ratchet.py`:

- **High Cyclomatic Complexity** (McCabe) and **High Cognitive Complexity**
  (SonarQube S3776 — a different measure: it charges for *nesting*, so a
  function radon calls simple can still be over) — same threshold (15),
  same ratchet rule as below, reported separately since a refactor can fix
  one without the other.
- **Invariant Return** (S3516) — every `return` in a function hands back
  the same never-rebound name, reading as several outcomes when it's
  really one.
- **Duplicated String Literal** (S1192) — the same literal (5+ characters)
  repeated 3+ times in one file, scoped per file rather than per function.

**The ratchet rule**: a brand-new function over threshold is always a
violation (base complexity 0). An *existing* function/literal already over
threshold that this change's diff actually reaches (matched by line range
against `git diff`) must come out **lower** than it went in — left
unchanged is not enough, only a genuine decrease passes. One the diff
never reaches at all is grandfathered regardless of its number. This is
stricter than "never worse": touching a bad function obligates you to
improve it, at least a little — it doesn't have to reach the threshold in
one PR, just move the right direction. Not retroactive, though: nothing
here forces anyone to go looking for complexity to fix in code nobody's
touching.

```bash
uv sync --extra complexity                                    # radon + cognitive-complexity
uv run python3 scripts/check_complexity_ratchet.py --base origin/main
```

Wired into CI as the `complexity` job, PR-only, alongside `tidy` and
`refactor-first`. `Tidy-Exempt:` bypasses it the same way it bypasses the
other two — one exemption mechanism for all three gates.

## Patch coverage — new code must be tested, not just committed

A fourth gate, orthogonal to everything above: none of the other three
check whether a change has *tests* at all, only whether its structure is
sound. [`diff-cover`](https://github.com/Bachmann1234/diff_cover)
(third-party, not a craft-gate script) reads a coverage report and a git
diff together, and fails when the lines the diff actually *changed* are
under-covered — untouched parts of the repo don't count, so this isn't a
whole-repo coverage floor (which a well-tested old codebase can clear while
a brand-new untested file quietly drags the average down only slightly).

```bash
uv run pytest --cov=<your_package> --cov-report=xml
uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 90
```

Wired into CI as the `patch-coverage` job, PR-only. **No `Tidy-Exempt:`
bypass** — deliberately, unlike the three gates above: this ports the exact
mechanism an existing, well-tested project (kai-ster) already runs
unconditionally, and diff-cover itself has no concept of a commit-trailer
exemption to hook into. If a real exception is needed (a generated file,
a vendored import), exclude it from coverage measurement itself
(`--cov=<your_package>` / a `[tool.coverage.run] omit` entry), not from
this gate.

**90% is kai-ster's own number, not a mandated one** — CRAFTSMANSHIP.md
ships the pattern; the threshold is yours to set per repo.

**Embed it in an existing coverage-producing job when you have one — don't
duplicate the test run.** `templates/ci-job.yml`'s `patch-coverage` job is
a full standalone job because it has to assume nothing else exists; but if
your repo already has a job running `pytest --cov ... --cov-report=xml`
(a lint-and-test job, a version-matrix job), add the diff-cover step to
*that* job instead. A separate job means a second full test run just to
get a second `coverage.xml` — real CI time for no new information. Every
consumer this gate has actually been wired into so far needed this: two
had an existing coverage-producing job (the step went there, no second
job), one had none (the standalone job was the right shape as-is).

Patch coverage answers "did a test run this line?" A test with no
assertion, or one asserting the wrong thing, still counts as covering the
line — coverage can't tell tested from merely-executed apart. Mutation
testing can: [`mutmut`](https://github.com/boxed/mutmut) changes one small
thing about your code (a `>` to a `>=`, a `+` to a `-`) and reruns your
tests — if they all still pass, that mutant *survived*, meaning nothing
actually checks the behavior that changed. `scripts/check_mutation_ratchet.py`
fails when a function **this change's diff touches** has a mutation score
(killed / (killed + survived), mutmut's own metric) below `--threshold`.

```bash
uv sync --extra mutation                                      # mutmut
uv run mutmut run                                              # generates + runs mutants
uv run python3 scripts/check_mutation_ratchet.py --base origin/main --threshold 80
```

**One of the five default gates (`templates/ci-job.yml`).** Mutation testing
reruns a focused behavioral test suite once per mutant. Configure
`[tool.mutmut]` with `source_paths` and
`pytest_add_cli_args_test_selection` listing the unit-test files marked
`@pytest.mark.mutation`; the normal test job still runs the complete suite.
The focused selection prevents mutmut from collecting unrelated integration,
TUI, and helper modules that make mutation runs needlessly slow or fragile.
The local runner and CI reuse the `mutants/` cache. See DESIGN.md's
"Mutation ratchet" for the full rationale, including why this
checks a flat floor on the current tree rather than a base-vs-head
comparison like the complexity ratchet.

**A genuinely equivalent mutant** (code where no test *could* tell the
difference because the behavior really is identical) gets mutmut's own
`# pragma: no mutate` — the same idea as coverage.py's `# pragma: no
cover`. This fixes the false positive at its source; don't reach for
`Tidy-Exempt:` for a single surviving mutant, save it for skipping the
gate entirely on a PR where that's the right call.

**Test-quality rule.** A new or changed behavioral test should be designed to
kill a meaningful mutation: assert the observable result, cover the relevant
boundary/error branch, and avoid merely executing the line. Mutation selection
is diff-scoped and per function. A changed function passes at 80% mutation
score, or, below 80%, only when it improves at least 20% over its first recorded
per-function score in `.mutation-baseline.json`.

## Reporting — visible, not just enforced

Two default, non-blocking mechanisms make craftCov's findings visible
without gating anything: a sticky PR comment showing what changed in this
PR (`scripts/craftcov_pr_comment.py`), and a GitHub code-scanning SARIF
export showing the repo's current state overall
(`craftcov.py --format sarif`). Neither is a ratchet — nothing here fails
a build. See DESIGN.md's **Reporting** section for the full detail and
the CI wiring.

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
