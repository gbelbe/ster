# /ci — Run the full local CI gate

Runs `scripts/ci.sh`. The static checks are driven by **prek**
(`.pre-commit-config.yaml`) — the same hooks the git pre-commit hook and the
GitHub `checks` job run, so local and CI can never drift. Tests run on the
**current Python only locally** (fast feedback); GitHub Actions still runs the
**full 3.11 / 3.12 / 3.13 matrix** on every PR, so support for all three is
enforced before merge.

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
  the current Python only — the full 3.11 / 3.12 / 3.13 matrix runs on the PR,
  so check `gh pr checks` after pushing to confirm every version is green.

$ARGUMENTS
