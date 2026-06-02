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
import subprocess
import sys
import tempfile
from pathlib import Path

THRESHOLD = 10


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


def compute_complexity(root: Path, threshold: int = THRESHOLD) -> dict[str, int]:
    """Map ``<relpath>::<qualified function name>`` → cyclomatic complexity for *root*."""
    from radon.complexity import cc_visit  # lazy: keeps find_violations import-light

    result: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
            blocks = cc_visit(source)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        rel = path.relative_to(root).as_posix()
        for fn in _functions(blocks):
            result[f"{rel}::{fn.fullname}"] = fn.complexity  # type: ignore[attr-defined]
    return result


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

    head = compute_complexity(Path(args.path))
    try:
        base = _complexity_at_ref(args.base, args.path)
    except subprocess.CalledProcessError as exc:
        print(f"error: could not read base ref {args.base!r}: {exc.stderr or exc}", file=sys.stderr)
        return 2

    violations = find_violations(base, head)
    if violations:
        print(f"Complexity ratchet: {len(violations)} violation(s) (threshold {THRESHOLD}):\n")
        for v in violations:
            print(f"  - {v}")
        print("\nRefactor the offending function(s) — see CLAUDE.md 'Refactor on touch'.")
        return 1
    print(f"Complexity ratchet: OK (no function pushed over {THRESHOLD}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
