# Contributing to ster

Thank you for considering a contribution. This guide walks you through the
process from first clone to merged pull request.

---

## 1. Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11 – 3.13 | [python.org](https://www.python.org/downloads/) |
| uv | latest | `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| git | 2.x+ | system package manager |

To run all three Python versions in the test matrix you need all three
interpreters installed. `uv` can manage them for you:

```bash
uv python install 3.11 3.12 3.13
```

---

## 2. Clone and set up

```bash
git clone https://github.com/gbelbe/ster.git
cd ster

# Install all dependencies (dev + optional extras)
uv sync --extra html --extra api --extra dev

# Install the git pre-push hook (one-time, per clone)
bash scripts/install-hooks.sh
```

The pre-push hook ensures you cannot accidentally push code that has not
passed the local CI gate (see step 4).

---

## 3. Create a branch

Always work on a feature branch, never directly on `master`:

```bash
git checkout -b feat/my-feature
```

Use a short, descriptive prefix:

| Prefix | Use for |
|--------|---------|
| `feat/` | new feature |
| `fix/` | bug fix |
| `refactor/` | internal restructure with no behaviour change |
| `docs/` | documentation only |
| `chore/` | tooling, CI, dependencies |

---

## 4. Develop and test locally

### Run the full CI gate (required before pushing)

```bash
bash scripts/ci.sh
```

This mirrors the GitHub Actions pipeline exactly:

| Step | What it runs |
|------|-------------|
| Lint | `ruff check .` |
| Format | `ruff format --check .` |
| Types | `mypy ster/` |
| Security SAST | `bandit -r ster/ -c pyproject.toml` |
| CVE scan | `pip-audit --skip-editable` |
| Tests | `pytest` on Python 3.11, 3.12, and 3.13 |

On success it writes a `.ci-passed` sentinel file. The pre-push hook reads
this file and blocks `git push` if CI has not passed in the last 60 minutes.

### Faster iteration during development

```bash
bash scripts/ci.sh --fast   # current Python only, skips multi-version matrix
bash scripts/ci.sh --fix    # auto-fix ruff lint/format, then run the full gate
```

### Run a specific test file

```bash
uv run pytest tests/unit/test_my_module.py -v
```

### Auto-fix lint and format

```bash
uv run ruff check --fix .
uv run ruff format .
```

---

## 5. Commit

Write clear, focused commits. One logical change per commit.

```bash
git add path/to/changed/file.py
git commit -m "feat(module): short description of what and why"
```

Commit message conventions:

```
<type>(<scope>): <short summary>

Optional longer explanation if the why is non-obvious.
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.

---

## 6. Open a pull request

Push your branch and open a PR against `master`:

```bash
git push -u origin feat/my-feature
```

The pre-push hook will block the push if `bash scripts/ci.sh` has not been
run and passed within the last 60 minutes. If blocked, run CI first:

```bash
bash scripts/ci.sh
git push -u origin feat/my-feature
```

Then open the PR on GitHub. In the description:

- Explain **what** changed and **why**
- Reference any related issues (`Closes #123`)
- List any manual testing steps you performed

---

## 7. What happens next

- GitHub Actions runs the same CI pipeline on your branch automatically
- A maintainer reviews the code
- Address review comments with new commits (do not force-push during review)
- Once approved and CI is green, the PR is merged

---

## Coding conventions

See [CLAUDE.md](CLAUDE.md) for the full style guide used in this project,
including ruff rules, mypy patterns, and the mandatory TDD+BDD workflow for
new features.

Key points:

- Every new feature needs a Gherkin `.feature` file in `tests/features/` and
  unit tests in `tests/unit/` before any implementation code
- Do not suppress linter or type errors with `# noqa` / `# type: ignore`
  unless it is a confirmed false positive — document why on the same line
- Do not add comments that describe what the code does; only add them when
  the **why** is non-obvious

---

## Troubleshooting

**`git push` is blocked even after CI passes**

The sentinel expires after 60 minutes. Re-run `bash scripts/ci.sh`.

**Hook not installed on a fresh clone**

Run `bash scripts/install-hooks.sh` once after cloning.

**A Python version is missing from the test matrix**

```bash
uv python install 3.11   # or 3.12 / 3.13
bash scripts/ci.sh
```

**`pip-audit` reports a CVE**

Upgrade the affected package first:

```bash
uv lock --upgrade-package <package-name>
bash scripts/ci.sh
```

Only use `--ignore-vuln` for CVEs that affect pip itself (not ster's
dependencies), and only after confirming the CVE does not apply.
