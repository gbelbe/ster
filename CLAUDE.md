# ster — Claude Code guidelines

## Code quality gate (mandatory before every commit)

Ensure the dev environment has all extras installed (mirrors CI):
```bash
uv sync --extra html --extra api --extra dev
```

Then run the full gate — every step must be clean:
```bash
uv run ruff check .          # lint
uv run ruff format --check . # format
uv run mypy ster/            # types
uv run bandit -r ster/ -c pyproject.toml   # security SAST
uv run pip-audit --ignore-vuln CVE-2026-3219 --ignore-vuln CVE-2026-6357 --skip-editable  # CVEs
uv run pytest tests/ -q --cov=ster --cov-report=term-missing  # tests + coverage
```

Run `uv run ruff check --fix . && uv run ruff format .` to auto-fix most lint/format issues before checking manually.

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

1. Write the Gherkin `.feature` file under `tests/features/`
2. List every unit test case — happy path, edge cases, error paths
3. Show which files will receive them and the function names
4. Wait for explicit user confirmation

**Only after approval:**
- Write the `pytest-bdd` step definitions under `tests/step_defs/`
- Write the unit tests under `tests/unit/`
- Write the implementation

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

1. List every test case you plan to add — happy path, edge cases, error paths
2. Show which test file(s) will receive them and the test function names
3. Wait for explicit user confirmation before writing any code

Only after the user approves the test plan should you proceed: write the tests first, then the implementation.

## Project conventions

- State machine pattern: one dataclass per viewer mode in `nav_state.py`, pure `_draw_*` / `_on_*` methods in `nav.py`
- All AI prompts live in `prompts.py` as `string.Template` objects — no prompt strings in logic files
- Use `${var}` syntax in templates when the variable name is immediately followed by a non-separator character
- AI functions in `ai.py` must go through `_call()` for copypaste/LLM dispatch
- Curses must be suspended (`curses.endwin()`) before any non-curses terminal I/O (Rich, input()), then resumed (`stdscr.refresh()`)
- All new features need tests; run the full suite before committing
