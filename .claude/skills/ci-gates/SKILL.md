---
name: ci-gates
description: What the local gate and the PR checks will do before you push — read before opening or updating a PR in this repo. Covers the pre-push hook, the refactor-first and tidy ratchets on new and touched files, patch coverage (agent-app included), the known flaky tests, the CodeQL patterns seen so far, and how to recover a stacked PR after its base is squash-merged. Use before the first push of a branch and whenever a check is red and the cause is not obvious.
---

# CI gates — what to expect

`CRAFTSMANSHIP.md` (synced from craft-gate) has the general "What to expect before you push" list. This is the
ster-specific part. Every item below cost a push-fail-fix round on a real PR.

## The local gate

- `git push` runs `scripts/pre-push.sh`, which wants `bash scripts/ci.sh` (or `--fast`) to have passed **in the
  last 24 hours**. `--fast` skips mutation testing and patch coverage; it is accepted by the hook. Run it *after*
  committing and *before* pushing.
- A fresh worktree needs `uv sync --all-extras` first (xdist, type stubs). Without it, `-n auto` and mypy fail
  for reasons that have nothing to do with your change.
- `ci.sh` refuses to start if `~/.cache/prek/patches/` holds leftovers (a hook once reformatted your files).
  Look at what is in them, then remove yours.
- Stop any other `ster serve` on port 8765 before running it: `test_tui_graph_port.py` fails while one holds the
  port.
- The full gate's **mutation ratchet** compares to `origin/main`. On a branch stacked on an unmerged PR it
  reports that PR's functions as yours; the quick gate does not run it. Say so in the PR description.

## Refactor First and the tidy ratchet, on this repo

- A **new** file (a new test module, a new step-definition file, a new package) must start at 0 detectable smells;
  a **touched** file must end lower. Appending one test to an older file counts as touching it. Check with
  `uv run python scripts/check_refactor_first.py --base origin/main` **after committing** (it is silent on
  uncommitted changes) and read the real findings with `uv run python scripts/craftcov.py --format json
  --no-diff --no-cache`.
- Things this codebase calls by name look unused to vulture. Mark them on the flagged line, with a reason where it
  is not obvious: pytest functions and fixtures, pytest-bdd step functions and `unittest.TestCase` classes
  (`# noqa: V103` / `V102`), Textual `on_*` / `action_*` handlers (`V105`), FastAPI route functions inside
  `_register_*` (`V103`), `http.server` handler methods in test fakes (`V105`).
- Status codes in tests are `HTTPStatus.OK`, not `200` (PLR2004).
- Two test modules that need the same fixture import it from one place (`tests/step_defs/conftest.py` has the
  shared `api_client`); duplicated blocks are flagged in both files.
- A change that only adds code with nothing to tidy first ends with a `Tidy-Exempt: <reason>` trailer; the reason
  is read by the reviewer.
- `git commit` can fail on a reformatting hook with its output filtered, leaving no commit. Check `git log -1`.

## Patch coverage

- `pyproject.toml`'s `testpaths` is `["tests", "agent-app/tests"]`, so one `pytest --cov=.` run covers ster and the
  agent app. Do not put tests in a place that run does not collect: their code counts as 0%.
- The map and timeline pages are JavaScript inside Python strings. They are tested by asserting on the served
  source and by running the one function under `node -e` (see `tests/unit/test_map_figures.py`,
  `test_map_latlong_enrichment.py`).
- If a test fails in the coverage job, the "Patch coverage" step is **skipped**. A red `Test (Python 3.13)` caused
  by one flaky test is not a coverage failure; read the *Run tests with coverage* step first, then re-run the
  failed jobs.
- Same check locally: `COVERAGE_CORE=sysmon uv run pytest -q -n auto --cov=. --cov-report=xml` then
  `uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 90`.

## Flaky tests seen so far

Each passes alone and fails now and then under `-n auto`; re-run before investigating.
`tests/unit/test_history_screen.py::test_only_the_selected_commit_is_ever_read`,
`tests/unit/test_tui_app.py::test_renaming_a_class_follows_the_entity_regression` (`NoMatches '#detail'`),
`tests/step_defs/test_tui_class_modal.py`, `tests/unit/test_cli_first_contact.py`. See
`docs/architecture/test-flakiness.md`.

## CodeQL patterns hit so far

- User text reaching a file path: resolve with `os.path.realpath`, then require `startswith(base + os.sep)`
  (`ster/query_trace/answers.py::_inside`). A regex on the id alone is not recognised.
- A value reaching HTML: validate its shape and `html.escape` it at the response boundary, as `/timeline` does;
  coerce numbers with `int()` where they enter the markup.
- SHA-1 on an id: use SHA-256. A request URL built from page state: `encodeURIComponent` each part. A CDN script:
  an `integrity` hash and `crossorigin`.

## Stacked PRs

When the base PR is squash-merged, merging `main` into the stacked branch conflicts on every shared file. Rebase
your own commits: `git log --first-parent --no-merges --reverse <old-base>..HEAD` lists them; cherry-pick onto
`origin/main`, re-run the gate, `git push --force-with-lease`. Retarget the PR to `main` first (`gh pr edit N
--base main`).
