"""Diff-aware cyclomatic-complexity ratchet.

Fails a change that makes complexity *worse*, while grandfathering functions
that are already over the threshold:

    A function is a violation when, in the change, its complexity exceeds
    THRESHOLD *and* it increased versus the base (a brand-new function has
    base complexity 0).

This blocks: new functions over the threshold, an already-complex function
made more complex, and a simple function pushed over the threshold. It allows:
untouched complex functions, and complex functions refactored *down*.

Usage:
    python scripts/check_complexity_ratchet.py [--base origin/main] [--path ster]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

THRESHOLD = 10

# A function above this "god-function" ceiling that you *modify* must be
# refactored DOWN as part of the change — you may not leave it flat by routing
# branches around it. Tune downward over time; never upward. See CLAUDE.md.
HARD_CEILING = 25

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def find_violations(
    base_cc: dict[str, int],
    head_cc: dict[str, int],
    threshold: int = THRESHOLD,
) -> list[str]:
    """Return human-readable violation messages for the ratchet rule."""
    violations: list[str] = []
    for name, cc in sorted(head_cc.items()):
        if cc <= threshold:
            continue
        base = base_cc.get(name, 0)
        if cc <= base:
            continue  # grandfathered (unchanged) or refactored down — allowed
        if name in base_cc:
            violations.append(
                f"{name}: complexity {base} → {cc} (> {threshold}) — "
                f"refactor to reduce complexity instead of adding to it"
            )
        else:
            violations.append(
                f"{name}: new function with complexity {cc} (> {threshold}) — "
                f"keep new functions at or below {threshold}"
            )
    return violations


def parse_changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Map ``<repo-relative path>`` → set of new-side line numbers added in a unified diff.

    Expects ``git diff --unified=0`` output. Pure deletions contribute nothing.
    """
    changed: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            current = None if p == "/dev/null" else (p[2:] if p.startswith(("a/", "b/")) else p)
            continue
        m = _HUNK_RE.match(line)
        if m and current:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            if count:
                changed.setdefault(current, set()).update(range(start, start + count))
    return changed


def touched_functions(
    changed_lines: dict[str, set[int]],
    fn_ranges: dict[str, tuple[int, int]],
    path_prefix: str,
) -> set[str]:
    """Names of functions whose ``[lineno, endline]`` overlaps a changed line in their file.

    *fn_ranges* keys are ``<relpath>::<fullname>`` with *relpath* relative to *path_prefix*.
    """
    touched: set[str] = set()
    for name, (lineno, endline) in fn_ranges.items():
        relpath = name.split("::", 1)[0]
        lines = changed_lines.get(f"{path_prefix}/{relpath}")
        if lines and any(lineno <= ln <= endline for ln in lines):
            touched.add(name)
    return touched


def touch_ceiling_violations(
    touched: set[str],
    base_cc: dict[str, int],
    head_cc: dict[str, int],
    ceiling: int = HARD_CEILING,
) -> list[str]:
    """A *touched* function above *ceiling* must be refactored down, not left flat.

    Fires when you modify a god-function (> ceiling) without reducing its
    complexity — the dodge of routing branches around it to keep the number flat.
    """
    out: list[str] = []
    for name in sorted(touched):
        cc = head_cc.get(name, 0)
        if cc > ceiling and cc >= base_cc.get(name, 0):
            out.append(
                f"{name}: complexity {cc} (> hard ceiling {ceiling}) and you modified it — "
                f"refactor it to reduce its complexity as part of this change, do not leave a "
                f"god-function flat (see CLAUDE.md 'Refactor on touch')."
            )
    return out


def _functions(blocks: object) -> list[object]:
    """Flatten radon blocks into Function blocks (functions, methods, closures)."""
    out: list[object] = []
    for block in blocks:  # type: ignore[attr-defined]
        methods = getattr(block, "methods", None)
        if methods is not None:  # a Class block
            out.extend(_functions(methods))
            out.extend(_functions(getattr(block, "inner_classes", []) or []))
        else:  # a Function block
            out.append(block)
            out.extend(_functions(getattr(block, "closures", []) or []))
    return out


def compute_functions(root: Path) -> dict[str, tuple[int, int, int]]:
    """Map ``<relpath>::<qualified function name>`` → (complexity, lineno, endline)."""
    from radon.complexity import cc_visit  # lazy: keeps find_violations import-light

    result: dict[str, tuple[int, int, int]] = {}
    for path in sorted(root.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
            blocks = cc_visit(source)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        rel = path.relative_to(root).as_posix()
        for fn in _functions(blocks):
            lineno = fn.lineno  # type: ignore[attr-defined]
            endline = getattr(fn, "endline", lineno) or lineno
            result[f"{rel}::{fn.fullname}"] = (fn.complexity, lineno, endline)  # type: ignore[attr-defined]
    return result


def compute_complexity(root: Path, threshold: int = THRESHOLD) -> dict[str, int]:
    """Map ``<relpath>::<qualified function name>`` → cyclomatic complexity for *root*."""
    return {name: cc for name, (cc, _l, _e) in compute_functions(root).items()}


def _changed_lines_from_git(base: str, path: str) -> dict[str, set[int]]:
    """New-side changed lines per file between *base* and HEAD, restricted to *path*."""
    r = subprocess.run(
        ["git", "diff", "--unified=0", f"{base}...HEAD", "--", path],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return {}
    return parse_changed_lines(r.stdout)


def _complexity_at_ref(ref: str, path: str) -> dict[str, int]:
    """Complexity map for *path* as it exists at git *ref*, via a throwaway worktree."""
    with tempfile.TemporaryDirectory() as tmp:
        worktree = Path(tmp) / "wt"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), ref],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            return compute_complexity(worktree / path)
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                capture_output=True,
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="git ref to compare against")
    parser.add_argument("--path", default="ster", help="source directory to scan")
    args = parser.parse_args(argv)

    head_funcs = compute_functions(Path(args.path))
    head = {name: cc for name, (cc, _l, _e) in head_funcs.items()}
    ranges = {name: (lineno, endline) for name, (_cc, lineno, endline) in head_funcs.items()}
    try:
        base = _complexity_at_ref(args.base, args.path)
    except subprocess.CalledProcessError as exc:
        print(f"error: could not read base ref {args.base!r}: {exc.stderr or exc}", file=sys.stderr)
        return 2

    touched = touched_functions(_changed_lines_from_git(args.base, args.path), ranges, args.path)
    violations = find_violations(base, head) + touch_ceiling_violations(touched, base, head)
    if violations:
        print(f"Complexity ratchet: {len(violations)} violation(s):\n")
        for v in violations:
            print(f"  - {v}")
        print("\nRefactor the offending function(s) — see CLAUDE.md 'Refactor on touch'.")
        return 1
    print(f"Complexity ratchet: OK (≤ {THRESHOLD}; modified god-functions reduced).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
