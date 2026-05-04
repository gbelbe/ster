# ster — Claude Code guidelines

## Code quality gate (mandatory before every commit)

```bash
uv run ruff check .          # lint — must be clean
uv run ruff format --check . # format — must be clean
uv run mypy ster/            # types — must be clean
uv run pytest tests/ -q      # tests — all must pass
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
