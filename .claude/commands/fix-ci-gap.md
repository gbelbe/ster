# /fix-ci-gap — Investigate local-vs-GitHub CI divergence

Use this skill whenever local CI passes but GitHub Actions fails (or is
suspected to). It encodes the two most common root causes and how to fix them.

## When to invoke

- GitHub CI fails on a commit that passed local `/ci`
- A colleague says "it was green for me" but CI is red
- After a large refactor with multiple file deletions or renames

## Root causes (in order of likelihood)

### 1. Stale mypy incremental cache

**Symptom**: GitHub fails with `Module "ster.X" has no attribute "Y"` or
similar mypy errors that don't appear locally.

**Why**: mypy's incremental cache (`.mypy_cache/`) stores type information from
previous runs. A file modified locally but never committed — or a file deleted
from disk while its stale cache entry remains — can mask real type errors
locally. GitHub always runs cold (no cache).

**Fix**:
```bash
rm -rf .mypy_cache
uv run mypy ster/ --no-incremental
```

The local `scripts/ci.sh` already passes `--no-incremental` to prevent this.
If you see it recur, confirm the flag is still present.

---

### 2. Ghost deletions — tracked files deleted locally but not staged

**Symptom**: GitHub CI fails at test collection with `ImportError` or
`ModuleNotFoundError` for a symbol that no longer exists locally.

**Why**: When you delete a file with `rm` (not `git rm`) and never stage the
deletion, the file still exists in git. GitHub clones from git and sees it.
pytest on GitHub tries to import it and crashes. Local pytest never sees the
missing file.

**Detect**:
```bash
git ls-files --deleted
```
Any output here is a ghost. The local `scripts/ci.sh` pre-flight step catches
this and exits before running tests.

**Fix**:
```bash
git add -u          # stages all deletions (and modifications)
# or for specific files:
git rm path/to/file
```

---

## Runbook

1. **Clear mypy cache and re-run types**
   ```bash
   rm -rf .mypy_cache
   uv run mypy ster/ --no-incremental
   ```

2. **Check for ghost deletions**
   ```bash
   git ls-files --deleted
   ```
   If non-empty: `git add -u` and re-check.

3. **Check for uncommitted modifications that imports depend on**
   ```bash
   git diff --name-only          # unstaged
   git diff --cached --name-only # staged but not committed
   ```
   If `ster/` files are modified but not committed, GitHub sees the old version.
   Any symbol added locally but not committed will cause GitHub mypy/pytest to fail.

4. **Run local CI in cold mode (mirrors GitHub)**
   ```bash
   rm -rf .mypy_cache
   bash scripts/ci.sh
   ```
   The pre-flight ghost check + `--no-incremental` mypy make this equivalent to
   a GitHub cold run.

5. **If still diverging**: read the full GitHub Actions log — look for the
   exact error line and the Python version. Sometimes it's a version-specific
   issue (3.11 vs 3.13) that only shows up in the matrix run.

## Hardening rule

Each time a new divergence pattern is found:
- Add a detection step to `scripts/ci.sh`
- Document it in this file under a new "Root causes" section
- Adjust `--no-incremental` / pre-flight as needed so local CI catches it next time
