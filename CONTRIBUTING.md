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

# Install all dependencies (runtime deps are core; dev adds the test/lint tools)
uv sync --extra dev

# Install the git pre-push hook (one-time, per clone)
bash scripts/install-hooks.sh
```

The pre-push hook ensures you cannot accidentally push code that has not
passed the local CI gate (see step 4).

---

## 3. Create a branch

Always work on a feature branch, never directly on `main`:

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

The static checks are driven by **prek** (`.pre-commit-config.yaml`) — the *same
hooks* the git pre-commit hook and the GitHub `checks` job run, so local and CI
can't drift:

| Step | Driven by |
|------|-----------|
| Lint · format · types · SAST · imports · complexity ratchet · hygiene | `prek run --all-files` — ruff (incl. its `S`/flake8-bandit SAST rules, which replaced standalone bandit) · ruff-format · mypy · import-linter · `scripts/check_complexity_ratchet.py` |
| JS lint + syntax | `eslint .` + `node --check` |
| CVE scan | `pip-audit --skip-editable` |
| Tests + coverage | `pytest --cov=ster` — **current Python only, locally** (fast feedback) |
| Patch coverage (≥ 90%) | `diff-cover` vs `origin/main` |

Tests run on your current interpreter locally; **GitHub Actions runs the full
3.11 / 3.12 / 3.13 matrix on every PR** — so support for all three is enforced on
the PR, not locally. After pushing, check `gh pr checks` to confirm every version
is green.

On success `scripts/ci.sh` writes a `.ci-passed` sentinel. The pre-push hook reads
it and blocks `git push` if the gate has not passed in the last 60 minutes.

### Faster iteration during development

```bash
bash scripts/ci.sh --fast   # current Python, skips the patch-coverage gate
bash scripts/ci.sh --fix    # let prek auto-fix ruff lint/format, then re-run the gate
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

Write clear, focused commits. One logical change per commit. Sign off every
commit under the **Developer Certificate of Origin** (DCO) with `-s`:

```bash
git add path/to/changed/file.py
git commit -s -m "feat(module): short description of what and why"
```

`-s` appends a `Signed-off-by: Your Name <you@example.com>` line, certifying you
have the right to submit the change under the project's [LICENSE](LICENSE) (see
<https://developercertificate.org/>). The **DCO** check rejects any PR whose
commits are not signed off — fix an existing branch with `git rebase --signoff main`.
Commits should also be **GPG-signed** (`-S`).

Commit message conventions:

```
<type>(<scope>): <short summary>

Optional longer explanation if the why is non-obvious.
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.

---

## 6. Open a pull request

Push your branch and open a PR against `main`:

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

### Development rules (mandatory)

These apply to everyone. Most are enforced automatically by CI (and surfaced by
the pull-request checklist); see [CLAUDE.md](CLAUDE.md) for the full version.

1. **Clarify & simplify first** — restate the request, ask the questions that
   change the design, and apply **YAGNI** to cut scope to the simplest thing
   that works.
2. **Test-first / BDD** — write the Gherkin `.feature` (`tests/features/`) and
   unit tests (`tests/unit/`) before the implementation. Changed lines must be
   ≥ 90% covered *(enforced by `diff-cover`)*, and every `.feature` must be
   bound to a test *(enforced)*.
3. **Bug fixes** — add a regression test that fails before the fix, plus the
   related edge cases. A fix with no test is incomplete.
4. **Refactor on touch** — when a change would add complexity, refactor instead
   of piling on branches. New functions stay ≤ 10 cyclomatic complexity, and a
   touched function already over 10 must come *down*, never up *(enforced by the
   complexity ratchet)*. Update the affected tests.
5. **External dependencies** — keep them minimal (YAGNI), constrain versions,
   commit `uv.lock`, and import each heavy library from a single adapter module
   only *(enforced by `import-linter`: `pylode`→`html_export`, `llm`→`ai`,
   `fastapi`→`api`)*.
6. **Hygiene** — don't suppress linter/type errors with `# noqa` / `# type:
   ignore` unless it's a confirmed false positive (say why inline); comments
   explain the **why**, not the **what**.

All of the above run via `bash scripts/ci.sh` and GitHub Actions; commits must be
**GPG-signed**.

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

---

## Internal docs (maintainers)

`ster` is developed in a private repository and mirrored to this public one, so
**anything tracked on `main` becomes public**. Keep internal-only material out of
the tracked tree — put it in `docs/internal/` (gitignored) or on a private-only
branch that is never pushed to the public remote. The **Leak scan** workflow
(`scripts/check_no_internal_docs.sh`) fails the build if a tracked file lives
under `docs/internal/` / `*.internal.md`, or carries the `STER-INTERNAL-ONLY`
marker. External contributions are integrated *through* the private repo via
`bash scripts/ster-pr.sh <PR-number>`.

---

## Releasing a new version (maintainers)

The release pipeline is fully automated. Human input is limited to writing
the changelog entry.

### Step 1 — Write release notes

Create `RELEASE_NOTES.md` (gitignored) with bullet points describing what
changed. Plain markdown, one bullet per notable change:

```markdown
- **New subclass creation**: click "↓ New subclass" in a class detail panel to create and link a new child class inline
- **Pre-push hook**: `scripts/install-hooks.sh` blocks git push without a passing CI run
```

### Step 2 — Run CI

```bash
bash scripts/ci.sh
```

The release script checks the CI sentinel and will refuse to run if it is
absent or older than 60 minutes.

### Step 3 — Release

```bash
bash scripts/release.sh 0.4.7
```

The script will:

| Action | What happens |
|--------|-------------|
| Validate | semver format, new > current, CI green, notes non-empty |
| Bump | `pyproject.toml` version + README ASCII banner |
| Changelog | Prepend `### 0.4.7` entry (from `RELEASE_NOTES.md`) to `## Changelog` in README |
| Commit | `chore(release): v0.4.7` |
| Tag | `v0.4.7` |
| Push | branch + tag to GitHub |
| Build | `uv build` → `dist/ster-0.4.7*` |
| Publish | `twine upload` to PyPI |
| Clean | removes `RELEASE_NOTES.md` |

### What you never need to do manually

- Edit `pyproject.toml`
- Edit the README banner or changelog section
- Run `git tag`, `git push`, `uv build`, or `twine upload`
- Ask Claude to do any of the above
