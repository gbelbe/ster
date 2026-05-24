# /ci — Run the full local CI gate

Runs `scripts/ci.sh` which mirrors the GitHub Actions CI pipeline exactly
(lint, format, mypy, bandit, pip-audit, pytest on Python 3.11 / 3.12 / 3.13).

**Always run this before pushing. Fix every failure before reporting the feature done.**

## Usage

```
/ci          → full run across all three Python versions
/ci --fast   → current Python only (quick check during development)
/ci --fix    → auto-fix lint/format issues, then run the full gate
```

## What it checks (same jobs as ci.yml)

| Step | Command |
|---|---|
| Lint | `ruff check .` |
| Format | `ruff format --check .` |
| Types | `mypy ster/` |
| Security SAST | `bandit -r ster/ -c pyproject.toml` |
| CVE scan | `pip-audit --skip-editable` |
| Tests + coverage | `pytest --cov=ster` on Python 3.11, 3.12, 3.13 |

## Failure handling rules

- **Never commit or push while CI is red.**
- Fix the root cause — do not suppress errors with `# noqa`, `# nosec`, or `# type: ignore` unless the check is a confirmed false positive. Document why in a comment on the same line.
- If a new CVE appears in `pip-audit`, upgrade the affected package first. Only add `--ignore-vuln` for CVEs that affect pip itself (not ster's dependencies).
- After fixing, re-run `/ci` in full (not `--fast`) to confirm all three Python versions pass.

$ARGUMENTS
