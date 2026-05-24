# /ci — Run the full local CI gate

Runs `scripts/ci.sh` which mirrors the GitHub Actions CI pipeline exactly
(lint, format, mypy, bandit, pip-audit, pytest on Python 3.11 / 3.12 / 3.13).

**This MUST be run and pass before every `git push`.** The git pre-push hook
(`scripts/pre-push.sh`) blocks any push automatically if CI has not passed
in the last 60 minutes. Install the hook once with: `bash scripts/install-hooks.sh`

## Usage

```
/ci          → full run across all three Python versions (required before push)
/ci --fast   → current Python only (quick check during development)
/ci --fix    → auto-fix lint/format issues, then run the full gate
```

Invoke directly as: `bash scripts/ci.sh [--fast|--fix]`

## What it checks (mirrors ci.yml exactly)

| Step | Command |
|---|---|
| Lint | `ruff check .` |
| Format | `ruff format --check .` |
| Types | `mypy ster/` |
| Security SAST | `bandit -r ster/ -c pyproject.toml` |
| CVE scan | `pip-audit --skip-editable` |
| Tests + coverage | `pytest --cov=ster` on Python 3.11, 3.12, 3.13 |

On success, writes `.ci-passed` (gitignored sentinel, expires 60 min).
The git pre-push hook reads this file and blocks any `git push` that
would bypass the gate — this works for all developers, not just Claude.

## Failure handling rules

- **Never commit or push while CI is red.**
- Fix the root cause — do not suppress errors with `# noqa`, `# nosec`, or
  `# type: ignore` unless the check is a confirmed false positive. Document
  why in a comment on the same line.
- If a new CVE appears in `pip-audit`, upgrade the package first. Only add
  `--ignore-vuln` for CVEs that affect pip itself, not ster's dependencies.
- After fixing, re-run `/ci` in full (not `--fast`) to confirm all three
  Python versions pass before pushing.

$ARGUMENTS
