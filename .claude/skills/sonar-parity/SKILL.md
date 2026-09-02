---
name: sonar-parity
description: Check code against the SonarQube rules this project's PR gate enforces (cognitive complexity S3776, invariant return S3516) before pushing. Use after writing or refactoring Python in ster/, and whenever a PR's "SonarQube Code Analysis" check fails.
---

# Sonar parity

SonarQube gates every PR here, its dashboard is unreachable from the CLI, and it
reports **one failed condition at a time** — so a guess costs a full push-and-wait
round-trip, and a wrong guess costs two. Three findings in PR #142 were each
found this way, one at a time, before the checks below existed.

Run this before pushing. It catches locally what the server would reject.

## Run it

```bash
uv run python scripts/check_complexity_ratchet.py --base origin/main --path ster
```

Already wired into `prek` (the `complexity-ratchet` hook) and therefore into
`/ci` and the pre-push hook, so normally this is not run by hand — reach for it
directly when iterating on a specific function.

It reports three things, all **diff-aware against the base branch**: a
pre-existing offender is grandfathered, but making one worse, or adding a new
one, fails. This mirrors Sonar gating *new code*, and it matters here —
`nav/logic.py::_flatten_taxonomy` scores 90 and is not this change's problem.

| Check | Threshold | Sonar rule |
|---|---|---|
| Cyclomatic complexity | 15 | — (project ratchet) |
| Cognitive complexity | 15 | S3776 |
| Invariant return | any new one | S3516 |

## What the findings mean

**Cognitive complexity** is not cyclomatic complexity. It charges for
**nesting**, so a function radon calls simple can still be over: four flat `if`s
cost 4, the same four nested cost 10. It also charges a function for anything
declared **inside** it — `_register_locate` scored 17 for the endpoint nested in
it, while its own body was one `def`.

The fix is almost never to shuffle branches around. Look for a function doing
two jobs and give each its own name — `_locate_row` was "place from coordinate
columns" and "resolve a URI through the graph", and its own docstring already
said so. Per CLAUDE.md, the touched function must end up **structurally
simpler**, not merely renumbered.

**Invariant return** (S3516) fires when every `return` hands back the same name
and that name is never rebound — building a list and returning it from two
places. It reads as two outcomes but is one. Use a single exit reached by
`break`. A rebound name (a counter) is genuinely different at each return and is
not a finding.

## When a finding is a false positive

Both checks are narrower than Sonar's, so a report here is a real match rather
than a guess. If one is genuinely wrong, say so and get agreement before
suppressing — do not add a `NOSONAR` comment to make a check pass.

## If the PR still fails after this passes

Something outside these two rules is failing — duplicated literals, a security
hotspot, a coverage condition. Do not guess: patch coverage is checkable locally
with `bash scripts/ci.sh` (not `--fast`, which skips it), and for anything else
ask for the rule message and the file/line from the dashboard.
