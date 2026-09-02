"""Diff-aware complexity ratchet — cyclomatic and cognitive.

Fails a change that makes complexity *worse*, while grandfathering functions
that are already over the threshold:

    A function is a violation when, in the change, its complexity exceeds
    THRESHOLD *and* it increased versus the base (a brand-new function has
    base complexity 0).

This blocks: new functions over the threshold, an already-complex function
made more complex, and a simple function pushed over the threshold. It allows:
untouched complex functions, and complex functions refactored *down*.

Two further checks mirror the SonarQube rules that this project keeps tripping
over, so they fail here rather than after a push:

    Cognitive complexity (S3776), same ratchet, same threshold. It is a
    different measure from cyclomatic — it charges for *nesting*, so a function
    radon calls simple can still be over. Both of the ratchet's own metrics are
    reported separately because a refactor can improve one and not the other.

    Invariant return (S3516): every return in a function hands back the same
    never-rebound name. Mutating a list and returning it from two places reads
    as two outcomes but is one, and the rule is asking for a single exit.

Usage:
    python scripts/check_complexity_ratchet.py [--base origin/main] [--path ster]
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import tempfile
from pathlib import Path

THRESHOLD = 15


def find_violations(
    base_cc: dict[str, int],
    head_cc: dict[str, int],
    threshold: int = THRESHOLD,
    metric: str = "complexity",
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
                f"{name}: {metric} {base} → {cc} (> {threshold}) — "
                f"refactor to reduce {metric} instead of adding to it"
            )
        else:
            violations.append(
                f"{name}: new function with {metric} {cc} (> {threshold}) — "
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


# ── Cognitive complexity (SonarQube S3776) ───────────────────────────────────
# A different measure from cyclomatic: it charges for nesting, so a flat chain
# of conditions stays cheap while the same branches nested three deep do not.
# The reference implementation is used rather than a re-derivation, because the
# point is to agree with the server — checked against two functions Sonar
# actually rejected, which it scored 17 and 17.


def _qualified(stack: list[str], name: str) -> str:
    return ".".join([*stack, name])


def _walk_functions(node: ast.AST, stack: list[str]):
    """Every function in *node*, with the qualified name it should be reported under."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _walk_functions(child, [*stack, child.name])
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield _qualified(stack, child.name), child
            yield from _walk_functions(child, [*stack, child.name])
        else:
            yield from _walk_functions(child, stack)


def compute_cognitive(root: Path) -> dict[str, int]:
    """Map ``<relpath>::<qualified function name>`` → cognitive complexity."""
    from cognitive_complexity.api import get_cognitive_complexity  # lazy, as above

    result: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        rel = path.relative_to(root).as_posix()
        for name, node in _walk_functions(tree, []):
            result[f"{rel}::{name}"] = get_cognitive_complexity(node)
    return result


# ── Invariant return (SonarQube S3516) ───────────────────────────────────────


def _returns_one_never_rebound_name(node: ast.AST) -> str | None:
    """The name every return hands back, when it is bound exactly once.

    Two returns of the same mutated list read as two outcomes but are one, which
    is what the rule objects to. A name that is *rebound* between the returns —
    a counter, say — really does yield different values, so it is not a finding.
    """
    returns = [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Return) and _encloses(node, child)
    ]
    if len(returns) < 2 or not all(isinstance(r.value, ast.Name) for r in returns):
        return None
    names = {r.value.id for r in returns}  # type: ignore[union-attr]
    if len(names) != 1:
        return None
    name = names.pop()
    bindings = sum(
        1
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store) and child.id == name
    )
    return name if bindings == 1 else None


def _encloses(func: ast.AST, stmt: ast.AST) -> bool:
    """True when *stmt* belongs to *func* itself, not to a function nested in it."""
    for child in ast.iter_child_nodes(func):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            node is stmt for node in ast.walk(child)
        ):
            return False
    return True


def compute_invariant_returns(root: Path) -> dict[str, str]:
    """Map ``<relpath>::<qualified function name>`` → the invariantly returned name."""
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        rel = path.relative_to(root).as_posix()
        for name, node in _walk_functions(tree, []):
            returned = _returns_one_never_rebound_name(node)
            if returned is not None:
                result[f"{rel}::{name}"] = returned
    return result


def _measure_at_ref(ref: str, path: str) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
    """Every metric for *path* as it exists at git *ref*, via a throwaway worktree.

    One worktree for all three: checking out the base ref is the slow part, and
    doing it once per metric would triple the cost of every commit.
    """
    with tempfile.TemporaryDirectory() as tmp:
        worktree = Path(tmp) / "wt"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), ref],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            root = worktree / path
            return (
                compute_complexity(root),
                compute_cognitive(root),
                compute_invariant_returns(root),
            )
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                capture_output=True,
            )


def _complexity_at_ref(ref: str, path: str) -> dict[str, int]:
    """Cyclomatic complexity for *path* at git *ref*."""
    return _measure_at_ref(ref, path)[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="git ref to compare against")
    parser.add_argument("--path", default="ster", help="source directory to scan")
    args = parser.parse_args(argv)

    root = Path(args.path)
    head_funcs = compute_functions(root)
    head = {name: cc for name, (cc, _l, _e) in head_funcs.items()}
    head_cog = compute_cognitive(root)
    head_inv = compute_invariant_returns(root)
    try:
        base, base_cog, base_inv = _measure_at_ref(args.base, args.path)
    except subprocess.CalledProcessError as exc:
        print(f"error: could not read base ref {args.base!r}: {exc.stderr or exc}", file=sys.stderr)
        return 2

    violations = find_violations(base, head, metric="cyclomatic complexity")
    violations += find_violations(base_cog, head_cog, metric="cognitive complexity")
    # Grandfathered like the ratchet: an invariant return that was already there
    # is not this change's problem, but a new one is.
    violations += [
        f"{name}: every return hands back the same never-rebound {returned!r} "
        f"(SonarQube S3516) — use one exit, reached by break"
        for name, returned in sorted(head_inv.items())
        if name not in base_inv
    ]

    print(f"Complexity ratchet: OK (cyclomatic and cognitive ≤ {THRESHOLD}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
