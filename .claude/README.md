# Developing ster with Claude Code

This repo is set up for AI-pair-programming with
[**Claude Code**](https://claude.com/claude-code). Everything a new developer
needs is checked in — clone the repo, open Claude Code in it, and the setup
below is active automatically.

> First read [`../CONTRIBUTING.md`](../CONTRIBUTING.md) (setup, branches, PRs) and
> [`../AGENTS.md`](../AGENTS.md) (the engineering rules). This file explains the
> Claude-specific tooling that ties them together.

---

## What's in this directory

| File | Tracked? | Purpose |
|------|----------|---------|
| `commands/ci.md` | ✅ committed | the **`/ci`** slash command — run the local quality gate |
| `commands/fix-ci-gap.md` | ✅ committed | the **`/fix-ci-gap`** slash command — diagnose "local green, GitHub red" |
| `agents/ci-fixer.md` | ✅ committed | a **Sonnet subagent** that fixes mechanical CI failures (ruff, mypy, eslint, prek) |
| `skills/sonar-parity/` | ✅ committed | the Sonar rules the PR gate enforces, and how to fix each finding |
| `settings.local.json` | ❌ gitignored | your personal tool-permission allowlist (do not commit) |

The two `commands/*.md` files are **project slash commands**: type `/ci` or
`/fix-ci-gap` in a Claude Code session and Claude runs that workflow. They're
committed, so every contributor gets them.

---

## `AGENTS.md` — the rules Claude follows

[`../AGENTS.md`](../AGENTS.md) at the repo root is **loaded into Claude's context
automatically** at the start of every session (`CLAUDE.md` is a symlink to it,
for Claude Code's own file-lookup). It is the source of truth for how we build
ster, and Claude treats it as binding. The essentials it enforces:

- **Confirm before coding.** For a new feature, Claude will rephrase your
  request, ask the questions that change the design, apply **YAGNI**, then lay
  out the `.feature` file + unit-test plan and **wait for your approval** before
  writing implementation code. That pause is by design — steer the scope there.
- **Test-first (TDD + BDD).** Gherkin `.feature` under `tests/features/<domain>/`,
  step defs under `tests/step_defs/`, unit tests under `tests/unit/` — written
  before the implementation. Bug fixes start with a failing regression test.
- **Refactor on touch + the complexity ratchet.** New functions stay ≤ 15
  cyclomatic complexity; changes must not increase complexity above 15.
  When the ratchet triggers, Claude refactors first, then builds.
- **Dependency isolation, prompt/style conventions** — see `AGENTS.md` for the
  full ruff/mypy tables and project conventions.

Humans should read `AGENTS.md` too: it *is* the coding standard the PR review and
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
current Python locally, while GitHub runs the full 3.12/3.13 matrix on the
PR — so check `gh pr checks` after pushing.

`/ci` runs as a **Sonnet subagent**, so the gate's long output never enters
your conversation. It replies with a short PASS/FAIL report that sorts each
failure into *mechanical* (hand to `ci-fixer`) or *needs judgment*.

### Which model does what

Most work here has two phases: plan (clarify, apply YAGNI, write the test plan),
then implement the approved plan. Only the first needs the strongest model.

| Work | Model |
|---|---|
| Planning, root-causing flaky tests, complexity-driven refactors, architecture docs | Opus (main session) |
| `/ci` runs, mechanical CI fixes (`ci-fixer`) | Sonnet (subagents) |

To get that split in your own sessions, set `"model": "opusplan"` in your user
settings: it uses Opus in plan mode (Shift+Tab) and Sonnet once you approve the
plan.

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

- [`../AGENTS.md`](../AGENTS.md) — the full engineering rulebook.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — setup, branching, commits, PRs, releases.
- [`../docs/architecture/`](../docs/architecture/) — design docs: `module-layout.md`
  (the package/shim-contract pattern used for every oversized-file split —
  `domain/`, `cli/`, `nav/logic/`, `viz_vowl/`, `tui/app/`, `store/`,
  `sparql_query/`, `tui/config_modal/`, `git/manager/`), `core-service.md`
  (commands/undo core), `detail-presenter.md` (entity detail views),
  `ontology-versioning.md` (publishing).
- Try it: open the app with `uv run ster show ster/tui/mixed-gear-demo.ttl`, then
  run `/ci` once to see the gate.
