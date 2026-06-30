# ster — Claude Code guidelines

## Code quality gate (mandatory before every commit)

Use the `/ci` skill — it runs the local gate. Static checks are driven by
**prek** (`.pre-commit-config.yaml`), the same hooks GitHub's `checks` job runs,
so local and CI can't drift.

```
/ci          # full local gate: prek checks + eslint + pip-audit + tests + diff-cover
/ci --fast   # current Python, skips the patch-coverage gate (quick iteration)
/ci --fix    # let prek auto-fix (ruff lint/format), then re-run to verify
```

Or invoke the script directly: `bash scripts/ci.sh`

**Tests run on the current Python only locally** (fast feedback). GitHub Actions
still runs the **full 3.11 / 3.12 / 3.13 matrix** on every PR — three-version
support is not dropped, just enforced on the PR rather than locally. After
pushing, check `gh pr checks` to confirm every version is green.

The git pre-push hook (prek runs `scripts/pre-push.sh`, installed via
`bash scripts/install-hooks.sh`) blocks any `git push` that does not have a
fresh local-gate pass within the last 60 minutes.

**Never push while CI is red. Fix every failure before marking a feature done.**

Run the static checks directly with prek:
```bash
uv sync --extra dev          # runtime deps are core; dev adds test/lint tools
prek run --all-files         # ruff · format · mypy · bandit · import-linter · ratchet · hygiene
uv run pip-audit --skip-editable
uv run pytest tests/ -q --cov=ster --cov-report=term-missing
```

## Ruff rules to follow in new code

| Rule | Pattern to avoid | Correct pattern |
|------|-----------------|-----------------|
| I001 | Unsorted imports | stdlib → third-party → local, blank lines between groups |
| F401 | Unused import | Remove it entirely |
| UP037 | `"quoted"` type annotation | Unquoted (file must have `from __future__ import annotations`) |
| SIM103 | `if cond: return False; return True` | `return not cond` |
| B905 | `zip(a, b)` without `strict=` | `zip(a, b, strict=False)` or `strict=True` |

## Mypy rules to follow in new code

- `str | None` passed where `str` expected → add `assert x is not None` before the call
- Variable re-defined in separate `elif` branches → add `# type: ignore[no-redef]` on the second definition
- Private attr on third-party type → add `# type: ignore[attr-defined]`
- Every new `.py` file must start with `from __future__ import annotations`

## TDD + BDD workflow (mandatory)

This project follows strict TDD with BDD for behaviour specification.

**Before writing any implementation code for a new feature, you MUST:**

1. **Clarify and challenge the request — before any spec or code:**
   - **Rephrase** the request in your own words (different phrasing, same meaning) to confirm you understood it.
   - **Ask for clarification / validation** — 3–5 focused questions on scope, user-facing behaviour, edge cases, and the success criterion.
   - **Apply YAGNI** ("You Aren't Gonna Need It"): actively challenge the use case. Question anything speculative or not strictly required to meet the goal, and propose the simplest design that satisfies it. Prefer cutting scope to adding it.
   - Proceed only once the user has validated the (possibly reduced) scope.
2. Write the Gherkin `.feature` file under `tests/features/`
3. List every unit test case — happy path, edge cases, error paths
4. Show which files will receive them and the function names
5. Wait for explicit user confirmation

**Only after approval:**
- Write the `pytest-bdd` step definitions under `tests/step_defs/`
- Write the unit tests under `tests/unit/`
- Write the implementation

## Bug fixes & regressions (mandatory)

A fix is not done until it is locked in by a test:

1. First write a **regression test that reproduces the bug** — it must *fail* against the current (broken) code, then pass once fixed.
2. Cover the **related edge cases** the bug exposes (boundary values, empty / `None`, error paths) — not just the single reported input.
3. Apply the fix; confirm the regression test **and** the full suite pass.
4. Name the test for its intent (e.g. `test_<area>_<symptom>_regression`) and note the root cause in a comment.

A bug-fix change with no new test is incomplete.

## Refactor on touch (mandatory)

When a change modifies existing code, leave it cleaner than you found it:

- Before editing, look for a clean-code refactor of the code you're touching. When a feature would **add complexity** to existing code (yet another `if/elif/else` branch, a growing function, copy-pasted logic), **propose a refactor that factors it out** — dispatch table / polymorphism / strategy, an extracted helper, or a small dataclass — so the code stays easy to maintain and to test, *instead of* piling on branches.
- **Complexity ratchet (cyclomatic complexity 10):** new functions must stay at or below complexity 10. A modification must **never increase** the complexity of a function that is already above 10 — if your change touches such a function, **refactor it to bring the complexity down** (toward ≤ 10) instead of adding another branch. Raising the limit is not an option.
- **Refactor first, then build — when the ratchet triggers, treat it as the trigger to refactor, not an obstacle to route around.** If a feature would push a function over the limit, or you must modify a function already well over it (a "god-function" such as a 100+-complexity dispatch loop), **STOP and refactor that function first**: pause, surface a small behaviour-preserving refactor plan to the user, make the suite green on that refactor, *then* build the feature on the simpler structure. The goal is that the codebase is genuinely **better after** the change.
- **Do not dodge the ratchet to keep the number flat.** Widening an `isinstance` tuple, relocating branches into a helper dispatcher, splitting one action into many rows, or otherwise shuffling complexity around so the count stays the same is **not** a refactor — the touched function must end up **structurally simpler**. Prefer generic dispatch (dispatch tables / registries / polymorphism / strategy) over long `if/elif` chains. This is enforced: `scripts/check_complexity_ratchet.py` has a **hard ceiling** (`HARD_CEILING`, currently 25) — modifying a function above it without reducing its complexity is a CI failure.
- Surface the refactor proposal (with its trade-off) to the user before implementing. YAGNI still applies — prefer the simplest structure; don't over-abstract.
- After refactoring, **update the unit tests to match** the new structure: rename/move/retarget existing tests and add tests for any newly extracted unit. Tests must track the refactor, never lag it.

## BDD conventions

- Feature files live in `tests/features/<domain>/` (e.g. `ci/`, `model/`)
- Step definitions live in `tests/step_defs/test_<domain>.py`
- Unit tests live in `tests/unit/test_<module>.py`
- One `.feature` file per feature domain
- Scenario names must be human-readable business descriptions
- Use `@pytest.fixture` for shared setup (avoid duplication across step files)
- Shared `@given` / `@then` steps go in `tests/step_defs/conftest.py`

## Feature development workflow (mandatory)

Before writing any implementation code for a new feature, you MUST:

1. Rephrase the request, ask for clarification/validation, and apply **YAGNI** to challenge and simplify the use case before committing to scope
2. List every test case you plan to add — happy path, edge cases, error paths
3. Show which test file(s) will receive them and the test function names
4. Wait for explicit user confirmation before writing any code

Only after the user approves the simplified scope and test plan should you proceed: write the tests first, then the implementation.

## Project conventions

- State machine pattern: one dataclass per viewer mode in `nav_state.py`, pure `_draw_*` / `_on_*` methods in `nav.py`
- All AI prompts live in `prompts.py` as `string.Template` objects — no prompt strings in logic files
- Use `${var}` syntax in templates when the variable name is immediately followed by a non-separator character
- AI functions in `ai.py` must go through `_call()` for copypaste/LLM dispatch
- Curses must be suspended (`curses.endwin()`) before any non-curses terminal I/O (Rich, input()), then resumed (`stdscr.refresh()`)
- All new features need tests; run the full suite before committing

## External dependencies (mandatory)

Third-party libraries must stay easy to upgrade without breaking changes:

- **Isolate every external library behind a thin internal adapter** — the rest of the code imports our module, never the library directly. Follow the existing pattern: `llm` is reached only through `ai.py::_call()`, pyLODE only through `html_export.py`. A library swap or major upgrade should touch one file, not the whole tree.
- **Keep the dependency list minimal** — apply YAGNI to dependencies too. Don't add a library for what the stdlib or an existing dependency already does; justify each new dependency in the PR.
- **Constrain versions deliberately** in `pyproject.toml` (a lower bound on the features you actually use) and commit the resolved `uv.lock` so installs are reproducible.
- **On every upgrade**: read the library's changelog for breaking changes, bump `uv.lock`, then run the full gate (`/ci`) plus `pip-audit` before committing. Pin away from a release only with a comment explaining why.
- Prefer well-maintained, widely-used libraries with stable APIs; treat a hard-to-pin or fast-churning dependency as a risk to flag.
