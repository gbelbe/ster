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
<!-- Generated from catalog.yaml by tools/render_catalog.py — don't
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
<!-- Generated from catalog.yaml by tools/render_catalog.py — don't
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

- **A function does one thing, and stays small** (CG025). If you're reaching for
  "and" to describe what it does, it's two functions.
- **Prefer 0–2 arguments; 3 is a smell, more needs restructuring** (CG026). Stricter
  than the mechanical gate below (which allows up to 5) on purpose — this is
  the *design* bar, the gate is the *floor* it won't let you fall under.
  Often `introduce-parameter-object` (above) is the fix, before the function
  is even written.
- **No flag arguments.** A boolean parameter that makes a function silently
  do one of two different things should be two functions.
- **Command-Query Separation** (CG027). A function either does something or answers
  something — never both. A function named `getX` that also mutates state
  will surprise every caller that doesn't read its body.
- **SOLID** (CG028; Martin, *Agile Software Development*, 2002) — most relevant day
  to day: **Dependency Inversion** (isolate an external library behind a
  thin internal adapter — the rest of the code depends on your interface,
  not the library) and **Single Responsibility** (one reason to change,
  which is exactly what `extract-class` fixes after the fact).

### The bar for new code — Kent Beck, *Extreme Programming Explained* (1999/2004)

Beck's four rules of simple design (CG029), **in priority order** — when they
conflict, an earlier rule wins:

1. Passes all the tests.
2. Reveals intention (a reader doesn't have to guess what it's for).
3. No duplication.
4. Fewest elements (no speculative generality — YAGNI, applied prospectively).

### A stricter optional reference — Sandi Metz's rules

Sandi Metz's rules (CG030) are deliberately extreme, meant to provoke a
conversation rather than be taken literally: classes ≤100 lines, methods ≤5 lines, ≤4 parameters. Useful when
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
commit) has nothing to confirm against. The characterization test (CG031)
is how you build that safety net first.

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
`scripts/craftcov.py --list-detectors` — <!-- fact:detectable -->8<!-- /fact --> of the
<!-- fact:entries -->35<!-- /fact --> entries above), the "which tidying, ask the developer"
judgment call in step 3 of the procedure becomes fully mechanical instead:

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
`.py` file's *total* across the <!-- fact:detectable -->8<!-- /fact --> detectable heuristics didn't go down
relative to where the branch diverged from its base — or, if the file was
already at 0, went up at all. It re-scans the PR's merge-base tree and its
head tree and compares per file (`dupes` needs every file scanned at each
point to find a match's other half, so there's no cheaper way to get an
accurate "before" count for one file). `Tidy-Exempt:` waives this per-file
ratchet, as it satisfies the message-pattern ratchet below, because an exempt change has
nothing to tidy. It does not waive the **new-code rule**: the gate also fails any finding
on a line the change added or rewrote (a new file must scan clean), since new code has no
legacy to grandfather.

This only covers the <!-- fact:detectable -->8<!-- /fact --> craftCov-detectable heuristics. Four more (CG032-
CG035) have their own separate mechanical gate — see "The complexity
ratchet" below. The remaining entries keep the judgment-call procedure above,
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
uv run --with-requirements scripts/gate-requirements.txt \
  python3 scripts/check_complexity_ratchet.py --base origin/main    # radon + cognitive-complexity
```

Wired into CI as the `complexity` job, PR-only, alongside `tidy` and
`refactor-first`. `Tidy-Exempt:` waives the debt rules (a touched over-threshold function must come out
lower; a literal count must not grow) but not the new-code rules: a function, invariant
return or duplicated literal that did not exist at the base still fails.

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
T="--with-requirements scripts/gate-requirements.txt"            # mutmut is pinned there
uv run $T mutmut run                                           # generates + runs mutants
uv run $T python3 scripts/check_mutation_ratchet.py --base origin/main --threshold 80
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

**Runs are diff-scoped, not whole-campaign.** `scripts/mutation_plan.py run` drops only the cached
verdicts the diff can have staled — the functions a changed test, fixture, data file or unmutated
helper reaches — then runs `mutmut run`, which re-tests exactly those and any function whose source
changed. A full campaign happens on the first initialisation of a repo and on cache-wide causes
only. Test files you add are measured on a first pass and their functions re-tested on a second.
A test change that *lowers* the score of a function it covers fails the ratchet, even though the
function itself was not touched. DESIGN.md's "Diff-scoped mutation runs" has the details and limits.

**A genuinely equivalent mutant** (code where no test *could* tell the
difference because the behavior really is identical) gets mutmut's own
`# pragma: no mutate` — the same idea as coverage.py's `# pragma: no
cover`. This fixes the false positive at its source; don't reach for
`Tidy-Exempt:` for a single surviving mutant, save it for skipping the
gate entirely on a PR where that's the right call.

**Test-quality rule.** A new or changed behavioral test should be designed to
kill a meaningful mutation: assert the observable result, cover the relevant
boundary/error branch, and avoid merely executing the line. Mutation selection
is diff-scoped and per function. A changed function passes at the threshold
(80% by default), or, below it, only when it already has a recorded score in
`.mutation-baseline.json` and improves on it by at least 20% — never asked for
more than the threshold itself, so a function at 78% that reaches the threshold
passes. A function with no recorded score — new, or never measured — must reach
the threshold outright; there is no "first run records the baseline" grace.
Design its tests for the threshold before the first push (see `templates/tdd-bdd-yagni.snippet.md`, "Design the tests before
the code").

## Configuration: craft-gate.toml

Every number and rule a gate uses is a value in one file, `craft-gate.toml`, at the repo root
(or the same sections under `[tool.craft-gate.<section>]` in `pyproject.toml`; when both exist the
standalone file wins). `templates/craft-gate.toml` lists every value with its default and a
comment; copying it unchanged changes nothing, because each value there is the default.

| Section | Values |
|---|---|
| `[patch-coverage]`, `[mutation]`, `[bdd]` | `enabled` and `reason`, `threshold` (and `improvement` for mutation), `source`, `paths`, `exclude` |
| `[complexity]` | `cyclomatic`, `cognitive`, `duplicated-literal-occurrences`, `duplicated-literal-min-length` |
| `[refactor-first]` | `per-file`: `must-decrease` or `must-not-increase` |
| `[design-review]` | `max-parameters`, `max-lines` |
| `[exemptions]` | `legacy-debt` (default true) and `new-code` (default false): what a `Tidy-Exempt:` trailer may waive |

Rules the file follows:

- **Strict.** An unknown section or key, or a value out of range, is an error that names it; it is
  never silently ignored, so a typo cannot leave a gate at its default while looking configured.
- **Every value is proven.** `tests/features/config_effects.feature` moves each value and shows
  the verdict move with it, and a test fails if a value in the schema has no scenario. A value
  that did nothing would be decoration.
- **Loosening is a decision.** Raising a limit or lowering a threshold fails no check, so the PR
  comment lists every value a change makes weaker (`scripts/config_loosening.py`, "Thresholds
  loosened"), and `templates/CODEOWNERS.snippet` puts the file under review. Never edit a value to
  make a gate pass; fix the code.
- **New code stays strict by default.** `exemptions.new-code = true` reopens the loophole that
  `Tidy-Exempt:` used to be; leave it false.

## Test gates: on unless declared off — patch coverage, mutation, behaviour coverage

Three gates ask whether a change is *tested*, not whether it is well structured:
patch coverage (changed lines are covered), the mutation ratchet (the tests would
notice if a touched function's behaviour changed) and behaviour coverage (changed
lines are covered by Gherkin scenarios, not only by unit tests). All three run by
default. Before running, each asks `scripts/gate_config.py` what to do:

| The repo... | The gate... |
|---|---|
| has what it needs | runs |
| switched it off in `pyproject.toml`, with a reason | is skipped; the reason is in the job summary and the PR comment |
| has not switched it off but lacks what it needs | **fails**, saying what to add or how to opt out |

The last row is the point: a gate never passes because it found nothing to check.
What each one needs: patch coverage a pytest suite; mutation a `[tool.mutmut]`
section; behaviour coverage `.feature` files under its `paths`. Mutation and
behaviour coverage measure the same suite patch coverage does, so they are skipped,
with that as the reason, when patch coverage is off.

```toml
# craft-gate.toml (or the same tables under [tool.craft-gate.*] in pyproject.toml)
[patch-coverage]
threshold = 90            # default; also: source = "your_package"

[mutation]
enabled = false
reason = "suite takes 40 minutes; revisit when it is split"

[bdd]
paths = ["tests/features"]  # default
threshold = 80              # default
```

Both coverage gates leave test files out of the measurement (`exclude`, default
`tests/*`, `test_*.py`, `conftest.py`, and so on): a test's own lines always run, so counting
them would pad the percentage. A repo that checked this found its behaviour gate passing at
90% while scenarios covered 71% of the production lines.

A switched-off gate needs a non-empty `reason`; a typo in a section or key is an
error, not silently ignored. There is no `Tidy-Exempt:` bypass for these gates: the
way out is the declared opt-out, which stays visible.

**Behaviour coverage.** The gate runs only the behaviour tests (`pytest tests/features
--cov`) and applies `diff-cover` to that report, so every line the diff changed must
be exercised by a scenario. A line can be fully covered by unit tests while no
scenario describes the behaviour it serves; this catches that. A scenario step with
no definition fails when the behaviour tests run, so orphaned steps surface here too.
What it cannot see is whether a scenario was written *before* the code. See
`docs/design/behaviour-coverage.md`.

## What to expect before you push — a checklist from real PRs

The gates are mechanical, and a few of their behaviours surprise whoever meets them for the first time —
a person or a coding agent. Know these in advance and the first push is the last one.

**Refactor First (`scripts/check_refactor_first.py`)**

- It compares the *committed* range (`origin/main...HEAD`). With uncommitted changes it can print
  nothing at all, which looks like a pass. Commit first, then run it.
- A **new file** has no "before", so it must be at **0** detectable smells — all eight, in tests and
  helpers as much as in source. A touched **existing** file must end **lower** than it began, even if
  your edit added nothing: touching it is what triggers the duty to fix one instance of each heuristic
  present. Plan for this when you append a test to a file with older smells.
- The smells that show up most in new code, and the fix:
  - *unused function / class / method* (vulture, CG002): code that a framework calls by name or
    registration — pytest and pytest-bdd tests and steps, `unittest.TestCase` classes, Textual
    `on_*`/`action_*` handlers, FastAPI route functions, `http.server` `do_GET` — looks unused.
    Say so on the flagged line with vulture's own code: `# noqa: V103` (function), `V105` (method),
    `V102` (class), `V101` (attribute), `V107` (variable), with a reason if it is not obvious.
    Vulture is run over the **whole corpus**, as craftCov does: run `craftcov.py --format json
    --no-diff --no-cache` for the real findings, not `vulture <one file>`, which reports things another
    file uses.
  - *magic number* (PLR2004, CG009): a named constant; for HTTP status codes `http.HTTPStatus.OK`.
  - *too many arguments* (PLR0913, CG018, more than 5): a small frozen dataclass as parameter object.
  - *too many statements / branches* (PLR0915 / PLR0912): split into named helpers.
  - *too many attributes / methods* (R0902 / R0904): split the class, or, for a plain record or a test
    suite, `# pylint: disable=too-many-instance-attributes  # <why>` on the class line.
  - *duplicate code* (CG024) counts across files: the same list in a source file and a test, or the
    same fixture in two test modules, is flagged in both. Import one copy.
- Fixing a whole new package to 0 is real work. If it is not worth it, `Tidy-Exempt:` is the documented
  escape — with an honest reason, since a reviewer reads it.

**Tidy First ratchet (`scripts/check_tidy_ratchet.sh`)**

- It reads the commit messages in `origin/main..HEAD`. After a rebase onto a base that squash-merged
  your earlier work, the `tidy(...)` commit that satisfied it may no longer be in the range: check.
- A pre-commit hook that reformats files makes `git commit` fail; if its output is filtered, no commit
  is made and nothing says so. Check `git log -1` after committing.

**Complexity ratchet**

- A touched function over 15 must end **lower**, not just no worse: moving the route handlers out of an
  over-15 `register_*` function was what made a one-parameter change pass.
- In touched code, a string literal repeated more than twice (S1192) fails; name it once.

**Patch coverage**

- Only code that the *one* coverage run executes counts. Tests run in another step, another directory
  outside `testpaths`, or a separate job leave their code at 0%: put them in the same run.
- Code inside a string (JavaScript or HTML embedded in a Python module) is not measured at all.
- If any test in the coverage job fails, the patch-coverage step is **skipped**, not failed. A red job
  whose failure is one flaky test therefore says nothing about coverage: read the *tests* step first.

**Stacked pull requests**

- When the base PR is **squash-merged**, merging `main` into the stacked branch conflicts on every file
  both touched (add/add). Rebase your own commits instead: `git log --first-parent --no-merges
  <old-base>..HEAD` lists them; cherry-pick them onto `origin/main` and push with `--force-with-lease`.
- A gate that compares to `main` counts the base PR's code as yours until it merges (for example a
  mutation ratchet): say so in the PR description so the reviewer does not read it as your regression.

**Local gate and hooks**

- Prek stashes unstaged changes into a user-global directory (`~/.cache/prek/patches/`) when a hook
  rewrites files; leftovers make a later full run refuse to start. They are replayed into your tree, so
  look at what they hold before deleting them.
- GitHub sometimes answers a push with `Internal Server Error`. Retry after a minute or two before
  suspecting the branch.

## SonarQube — what it rejects that the other gates do not

SonarQube judges **new code** only, runs on the server, and reports **one failed condition at a time**, so
a finding you could have avoided costs a push and a wait each. Nothing local reproduces it (the complexity
ratchet covers S3776, S3516 and S1192; the rest is below). Everything here was learned from findings Sonar
raised on real pull requests — read it before writing the code, not after the check fails. When a PR's
"SonarQube Code Analysis" check is red, the list of issues is at
`<server>/project/issues?id=<project>&pullRequest=<n>&resolved=false`; fix **all** of them in one push.

**1. A suppression comment has its reason after a second `#` (S7632).** Sonar parses `# noqa: CODE` and
treats whatever follows on the same comment as part of the syntax. A dash, an em dash or a colon before the
reason is a finding on its own:

```python
except Exception:  # noqa: BLE001 - an unreadable file falls back     # flagged
except Exception:  # noqa: BLE001  # an unreadable file falls back     # accepted
```

The same goes for every code (`PLR0913`, `V103`, `PLC0415`, `ARG001` …) and for `# NOSONAR - reason`, which
is how a finding Sonar raises but that does not apply gets dismissed (a parameter an interface imposes, an
RDF namespace that is an identifier, not an address). A suppression must say *why*; one without a reason
is a reviewer's first question.

**2. A regular expression must not backtrack (S5852, S5869, S5843).**
- Adjacent quantified groups that can match the same characters (`\s*=?\s*["']?\s*`) can split a long run
  of them in many ways: polynomial time on input an attacker or a served page controls. Make the
  quantifiers possessive (`\s*+`, `=?+`, Python 3.11+) when nothing after a run can match what the run
  matched, or merge the runs (`[\s=]*`), or stop using a regular expression for it.
- A repeated range under `re.IGNORECASE` (`[A-Za-z]`) is a finding: `[a-z]` already covers both.
- A single expression over about 20 in Sonar's regex complexity (several alternations of strings, IRIs and
  comments) is a finding: build it from named pieces and join them.
- Write a regression test that feeds a long run of the repeating character (50 000 spaces) and asserts it
  finishes within a budget. Without the fix it does not finish.

**3. Sonar types `dataclasses.replace()` as a bare `DataclassInstance` (S5655).** mypy is satisfied, Sonar
then reports the caller as passing, returning or receiving "a different type" — four findings from one
line. Give the copy its type once: build it with its constructor, or put `replace` behind one helper whose
return annotation names the class (`def _changed(source: Src, **changes: Any) -> Src: return cast(Src,
replace(source, **changes))`) and use the helper everywhere. A `cast` repeated at each call site works but
spreads the workaround.

**4. A parameter an interface imposes is not "unused" (S1172) — say so.** A method that implements a
`Protocol`, a callback signature or a framework hook keeps parameters it does not read; Sonar cannot see the
interface. Mark the `def` line `# NOSONAR - the <Interface> passes it`. Do not make the class inherit from a
`Protocol` to silence it when the class is a dataclass: the protocol's properties become read-only
attributes and construction fails. Do not delete the parameter either: the caller passes it.

**5. Parameter count: ruff, craftCov and Sonar use three limits (S107).** craftCov's CG018 flags more than 5
(it runs `ruff check --select PLR0913` with the *project's* ruff configuration); Sonar's limit here is 13.
`# noqa: PLR0913` silences ruff, not Sonar, so a function over 13 needs both comments. Do **not** set
`[tool.ruff.lint.pylint] max-args = 13` to "match" Sonar: craftCov reads that setting, so the stricter
gate would silently drop to 13. Any new function over 5 already fails Refactor First long before Sonar's
13, so the Sonar finding only appears on a legacy function you touch. A parameter object removes the
finding for an internal helper (`_pick(state)` instead of seven arguments); for a command whose signature
*is* the option list, `# NOSONAR - every CLI option is a parameter` on the `def` line.

**Ruff rules that mirror Sonar and cost nothing to turn on:** `PGH004` (a bare `# noqa`) and `B014` (a
handler naming the same exception twice). `ARG` (unused arguments, S1172) and `RUF100` (unused `noqa`) would
help too but ruff cannot limit them to new code: enable them only in a repo with few existing violations.
No ruff rule reproduces S7632 (the `# noqa` reason syntax), S5852 (backtracking) or S5655 (types): those
stay a reading of the diff.

**6. Do not list an exception beside its base (S5713).** `except (OSError, URLError)`, `except
(HTTPError, OSError)`, `except (FileNotFoundError, OSError)`: the subclass is already caught. Name the base
once; a test pins that the subclass is still handled.

**7. No clear-text `http://` in a literal (S5332).** In tests, build an unreachable or local address from a
scheme variable in the shared helper rather than writing `http://127.0.0.1:1/`. For an RDF namespace the
advice is *wrong* (`http://…` and `https://…` are different IRIs): take it from `rdflib.namespace` where it
exists, or mark the line `# NOSONAR - RDF namespace IRI`, never switch it to `https`.

**8. Repeated string literal (S1192), cognitive complexity (S3776), invariant return (S3516)** are checked
locally by `scripts/check_complexity_ratchet.py`; user-interface labels, menu texts and selectors repeated
in a view module are the usual source — name each once at the top of the module.

**9. Browser JavaScript has its own rules.** What Sonar asked of `graph_app.js`: `globalThis`, not `window`;
`for…of`, not an index loop or `forEach` with a side effect; `Math.trunc` and `codePointAt`; an optional
catch binding (`catch {` , not `catch(_){}`) and never an empty `catch` — log at `console.debug` or say why
it is ignored; a plural built with a ternary inside a string is a nested-ternary finding, use a helper.

**Process traps**
- **A comment is a changed line.** Sonar counts a line you only touched as new code, but so do diff-cover and
  the mutation ratchet: rewriting a suppression comment on an `except` branch no test runs, or on a line
  inside a function with no mutation baseline, fails *those* gates (a sweep of four such comments failed
  on coverage and on a 29 % mutation score, and was closed). Fix the syntax **in the lines your change
  adds**; leave older lines alone unless you are testing them.
- **Test code is code.** Every rule above applies to `tests/` too (S5332 and S5852 were raised on test
  helpers and test files).
- **Cheap local check before pushing:** `grep -nE "noqa: [A-Z]+[0-9]+ +[-—:]" $(git diff --name-only
  origin/main...HEAD)` finds the first trap; for the others, read the list above against the diff.

### Close the loop: a Sonar finding, once fixed, becomes a lint rule

*Only for a repository that gates on SonarQube (a `sonar-project.properties`, or a SonarQube check on its
PRs). A repository without Sonar needs none of this and nothing in craft-gate depends on it: no gate,
script or `craft-gate.toml` value here refers to Sonar.*

A Sonar finding costs a push and a wait, so each kind should cost it **once**. After fixing a finding the
server raised, and before the PR is considered done, a coding agent does the following, in this order,
and puts it in the same PR as the fix (a `chore(lint):` commit of its own is fine):

1. **Is there a ruff rule for it?** (`ruff rule --all`, or the rule list's name for the Sonar rule.) If yes,
   add its code to `select` in the project's ruff configuration, run `ruff check` on the whole repo, and
   keep it only if it adds **no** new violation (ruff cannot limit a rule to new code). If it would
   flag old code, do not turn it on: use step 2.
2. **Otherwise add a diff-aware check** to the project's own parity script (`scripts/check_sonar_parity.py`
   in the repository that has one; create it from the same shape — judge only the lines the change added,
   one small function per trap, a unit test per trap that fails without the fix). Wire it where the
   complexity ratchet is wired (the local gate script, the CI job, a manual pre-commit hook).
3. **Never loosen a shared setting to make Sonar and a linter agree.** Check who else reads the setting:
   `craftcov` runs `ruff check --select PLR0913` with the project's configuration, so raising
   `max-args` to Sonar's limit would silently weaken the stricter gate.
4. **Write the trap down** in the section above if it is a new kind; the next agent reads that, not the
   history.

If a finding is a false positive for this project (an RDF namespace read as a clear-text URL, a
parameter an interface imposes), the fix is the documented suppression with its reason, and **no** lint
rule is added: the point is to prevent real recurrences, not to encode Sonar's mistakes.

## Reporting — visible, not just enforced

Two default, non-blocking mechanisms make craftCov's findings visible
without gating anything: a sticky PR comment showing what changed in this
PR (`scripts/craftcov_pr_comment.py`), and a GitHub code-scanning SARIF
export showing the repo's current state overall
(`craftcov.py --format sarif`). Neither is a ratchet — nothing here fails
a build. See DESIGN.md's **Reporting** section for the full detail and
the CI wiring.

The same comment carries two more non-blocking sections: **Gates switched off in
this repo** (any test gate opted out, with its reason), and **Design review
(advisory)**. The second covers the rules in "New-code principles" that no gate can
decide from a diff. `scripts/design_review.py` flags, in the Python functions a change
touched, the smells that usually point at them: a flag argument (a `bool` parameter) for
*one thing*, more than two parameters, "and" in a name, a `get_`/`is_`/`find_` function
that changes state (command-query separation), and a function over about 20 lines. They
are prompts for the reviewer, not findings; nothing fails. The judgement calls with no
smell to flag (naming, responsibility, whether tests state the behaviour, YAGNI) are on
the PR checklist, `templates/PULL_REQUEST_TEMPLATE.md`.

**An independent reviewer.** For the same rules, a model can judge what a smell cannot. The
`craft-reviewer` subagent (`agents/craft-reviewer.md`, run through the `craft-review` skill)
reviews a branch as a lead developer with no knowledge of how it was written, graded against
the "New-code principles" above. Every finding must quote the code and cite a catalog code, or
it is dropped. It is advisory and read-only; it is not a gate, because a model's verdict is not
repeatable. See `docs/design/reviewer.md`.

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
