---
description: Run the full local CI gate and report what failed
argument-hint: "[--fast|--fix]"
context: fork
model: sonnet
---

# /ci — Run the full local CI gate

**Your task: run `bash scripts/ci.sh $ARGUMENTS` now, then reply with the
report described under "What to report back" at the end of this page.** The
rest of the page is reference for reading the result.

This runs as a **Sonnet subagent** (`context: fork`): the gate's output is long,
and keeping it out of the main conversation stops every later turn from
re-reading it. The subagent runs the gate and hands back a short report; the
main session (or the `ci-fixer` agent) does the fixing.

Runs `scripts/ci.sh`. The static checks are driven by **prek**
(`.pre-commit-config.yaml`) — the same hooks the git pre-commit hook and the
GitHub `checks` job run, so local and CI can never drift. Tests run on the
**current Python only locally** (fast feedback); GitHub Actions runs the
**3.12 / 3.13 matrix** on every PR, so support for both is enforced before
merge.

**This MUST be run and pass before every `git push`.** The git pre-push hook
(installed via prek) runs `scripts/pre-push.sh`, which blocks any push unless
this gate passed in the last 60 minutes. Install the hooks once with:
`bash scripts/install-hooks.sh` (installs prek's pre-commit + pre-push hooks).

## Usage

```
/ci          → full local gate: prek checks + eslint + pip-audit + tests + diff-cover
/ci --fast   → current Python, skips the patch-coverage gate (quick dev check)
/ci --fix    → let prek's hooks auto-fix (ruff lint/format), then re-run to verify
```

Invoke directly as: `bash scripts/ci.sh [--fast|--fix]`

## What it checks

| Step | Driven by |
|---|---|
| Lint · format · types · SAST · imports · ratchet · hygiene | `prek run --all-files` |
| JS lint + syntax | `eslint .` + `node --check` |
| CVE scan | `pip-audit --skip-editable` |
| Tests + coverage | `pytest --cov=ster` (current Python) |
| Patch coverage | `diff-cover` vs `origin/main` (full mode) |

On success, writes `.ci-passed` (gitignored sentinel, expires 60 min).
The prek pre-push hook reads this file and blocks any `git push` that
would bypass the gate — this works for all developers, not just Claude.

## Failure handling rules

- **Never commit or push while CI is red.**
- Fix the root cause — do not suppress errors with `# noqa`, `# nosec`, or
  `# type: ignore` unless the check is a confirmed false positive. Document
  why in a comment on the same line.
- If a new CVE appears in `pip-audit`, upgrade the package first. Only add
  `--ignore-vuln` for CVEs that affect pip itself, not ster's dependencies.
- After fixing, re-run `/ci` in full (not `--fast`) before pushing. Local runs
  the current Python only — the 3.12 / 3.13 matrix runs on the PR, so check
  `gh pr checks` after pushing to confirm every version is green.

## What to report back

Do not edit source files — `--fix`'s own
prek auto-fixes are the only changes this command makes. Then reply with only:

1. **PASS** or **FAIL**, and the mode that ran (full / `--fast` / `--fix`).
2. On failure, one line per failure: `check · file:line · message` (the exact
   error text, trimmed; for a failing test, its node id and the assertion).
   Group repeats of one error as `N× …` rather than listing each.
3. For each failure, whether it is **mechanical** (ruff, format, mypy, eslint,
   prek hygiene — hand to the `ci-fixer` agent) or **needs judgment** (a failing
   or flaky test, the complexity ratchet, pip-audit, patch coverage).

No log dumps and no advice beyond that — the reader has the repo in front of
them.
