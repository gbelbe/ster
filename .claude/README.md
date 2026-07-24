# Developing ster with Claude Code

This repo is set up for AI-pair-programming with
[**Claude Code**](https://claude.com/claude-code). Everything a new developer
needs is checked in — clone the repo, open Claude Code in it, and the setup
below is active automatically.

> First read [`../CONTRIBUTING.md`](../CONTRIBUTING.md) (setup, branches, PRs) and
> [`../CLAUDE.md`](../CLAUDE.md) (the engineering rules). This file explains the
> Claude-specific tooling that ties them together.

---

## What's in this directory

| File | Tracked? | Purpose |
|------|----------|---------|
| `commands/ci.md` | ✅ committed | the **`/ci`** slash command — run the local quality gate |
| `commands/fix-ci-gap.md` | ✅ committed | the **`/fix-ci-gap`** slash command — diagnose "local green, GitHub red" |
| `settings.local.json` | ❌ gitignored | your personal tool-permission allowlist (do not commit) |

The two `commands/*.md` files are **project slash commands**: type `/ci` or
`/fix-ci-gap` in a Claude Code session and Claude runs that workflow. They're
committed, so every contributor gets them.

---

## `CLAUDE.md` — the rules Claude follows

[`../CLAUDE.md`](../CLAUDE.md) at the repo root is **loaded into Claude's context
automatically** at the start of every session. It is the source of truth for how
we build ster, and Claude treats it as binding. The essentials it enforces:

- **Confirm before coding.** For a new feature, Claude will rephrase your
  request, ask the questions that change the design, apply **YAGNI**, then lay
  out the `.feature` file + unit-test plan and **wait for your approval** before
  writing implementation code. That pause is by design — steer the scope there.
- **Test-first (TDD + BDD).** Gherkin `.feature` under `tests/features/<domain>/`,
  step defs under `tests/step_defs/`, unit tests under `tests/unit/` — written
  before the implementation. Bug fixes start with a failing regression test.
- **Refactor on touch + the complexity ratchet.** New functions stay ≤ 10
  cyclomatic complexity; a touched function already over 10 must come *down*.
  When the ratchet triggers, Claude refactors first, then builds.
- **Dependency isolation, prompt/style conventions** — see `CLAUDE.md` for the
  full ruff/mypy tables and project conventions.

Humans should read `CLAUDE.md` too: it *is* the coding standard the PR review and
the gate check against, whether or not you used Claude to write the change.

---

## The slash commands

### `/ci` — run the quality gate
Runs `scripts/ci.sh` (the same gate the git hooks and GitHub `checks` job run)
and interprets any failures for you.

```
/ci          full gate: prek checks + eslint + pip-audit + tests + patch coverage
/ci --fast   current Python, skips the patch-coverage gate (quick iteration)
/ci --fix    let prek auto-fix ruff lint/format, then re-run to verify
```

**Never push while the gate is red.** The pre-push hook blocks any `git push`
without a fresh pass in the last 60 minutes. Static checks are driven by **prek**
(`.pre-commit-config.yaml`), so local and CI can't drift; tests run on your
current Python locally, while GitHub runs the full 3.11/3.12/3.13 matrix on the
PR — so check `gh pr checks` after pushing.

### `/fix-ci-gap` — local passed, GitHub failed
Use when local `/ci` is green but GitHub Actions fails (or you suspect it will).
It encodes the common root causes of local-vs-CI divergence and how to fix them.

---

## A typical AI-assisted change, end to end

1. **Branch** off `main` (`feat/…`, `fix/…`, `refactor/…`).
2. **Describe the change** to Claude. Expect it to ask clarifying questions and
   propose a reduced scope + a test plan — approve or adjust it.
3. Claude writes the **feature file and tests first**, then the implementation,
   refactoring anything it touches to stay under the complexity ceiling.
4. Run **`/ci`** until green (Claude will fix failures, not suppress them).
5. **Commit** (imperative subject + a *why* body) and open a PR.
6. Confirm **`gh pr checks`** is green across all three Python versions.

---

## Where to go next

- [`../CLAUDE.md`](../CLAUDE.md) — the full engineering rulebook.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — setup, branching, commits, PRs, releases.
- [`../docs/architecture/`](../docs/architecture/) — design docs: `module-layout.md`
  (the `domain/` split), `core-service.md` (commands/undo core),
  `detail-presenter.md` (entity detail views), `ontology-versioning.md` (publishing).
- Try it: open the app with `uv run ster show ster/tui/mixed-gear-demo.ttl`, then
  run `/ci` once to see the gate.
