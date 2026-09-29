"""Diff-aware complexity ratchet — cyclomatic and cognitive.

Covers catalog.yaml's high-cyclomatic-complexity, high-cognitive-complexity,
invariant-return, and duplicated-string-literal entries (CG032-CG035) — the
mechanical enforcement CRAFTSMANSHIP.md's "The complexity ratchet" section
documents. These four aren't part of craftCov's own scan (craftcov.py
--list-detectors won't show them) — they're diff-aware ratchets like
Refactor First, not a whole-repo report, so they live in their own script
and their own catalog entries have no `detectors` field.

Fails a change that leaves complexity *at or above where it started*, while
grandfathering functions the change never reaches at all:

    A function already over THRESHOLD that the diff actually touches (via
    `git diff -U0`, matched against the function's line range) must come
    out *lower* than it went in — unchanged is not enough, only a genuine
    decrease passes. A function the diff never reaches is grandfathered
    regardless of its complexity. A brand-new function (base complexity 0)
    over THRESHOLD always fails.

This blocks: new functions over the threshold, an already-complex function
made more complex *or left exactly as complex as before* once touched, and a
simple function pushed over the threshold. It allows: untouched complex
functions (touched only elsewhere in the same file), and complex functions
refactored *down* — even if the result is still over THRESHOLD, since paying
down debt is a ratchet, not a one-shot requirement.

Two further checks mirror SonarQube rules many teams already gate on, so
they fail here rather than after a push:

    Cognitive complexity (S3776), same ratchet, same threshold. It is a
    different measure from cyclomatic — it charges for *nesting*, so a function
    radon calls simple can still be over. Both of the ratchet's own metrics are
    reported separately because a refactor can improve one and not the other.

    Invariant return (S3516): every return in a function hands back the same
    never-rebound name. Mutating a list and returning it from two places reads
    as two outcomes but is one, and the rule is asking for a single exit.

    Duplicated string literal (S1192), same ratchet, scoped per file: the same
    literal (5+ characters) repeated 3+ times in one file should be a named
    constant instead.

A file move counts as a change to everything it carries — there is no
rename-awareness here. A function or literal that only moved to a new file
is evaluated exactly like new code and must meet the threshold on its own,
not compared against an identically-named entry that happened to live
somewhere else in the base ref.

Needs the `complexity` extra (`radon`, `cognitive-complexity`) — see the
README's Install section for the exact versions this release expects.

Usage:
    python scripts/check_complexity_ratchet.py [--base origin/main] [--path .]
"""

from __future__ import annotations

import argparse
import ast
import re
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
    touched: set[str] | None = None,
) -> list[str]:
    """Return human-readable violation messages for the ratchet rule.

    Without *touched* (the default): the original rule — a violation only
    when *cc* increased versus *base* (a brand-new function has base 0).
    Unchanged-and-already-over-threshold is silently allowed, because
    without diff information there is no way to tell "genuinely untouched"
    from "touched but numerically unchanged" apart, and the former must
    never be flagged.

    With *touched* (a set of names this change's diff actually reaches —
    see `_touched_names`): a name in *touched* whose *cc* is still over
    *threshold* must have strictly *decreased*, not just avoided
    increasing — matching every consuming repo's own written policy
    ("if your change touches an over-threshold function, bring its
    complexity down"). A name *not* in *touched* falls back to the
    original unchanged-is-fine rule, since by construction an untouched
    name's *cc* never differs from *base* anyway.
    """
    violations: list[str] = []
    for name, cc in sorted(head_cc.items()):
        if cc <= threshold:
            continue
        base = base_cc.get(name, 0)
        if name not in base_cc:
            violations.append(
                f"{name}: new function with {metric} {cc} (> {threshold}) — "
                f"keep new functions at or below {threshold}"
            )
        elif touched is not None and name in touched:
            if cc < base:
                continue  # touched and genuinely improved — allowed
            verb = "unchanged at" if cc == base else f"{base} →"
            violations.append(
                f"{name}: {metric} {verb} {cc} (> {threshold}) — this function was "
                f"touched and is still over {threshold}; reduce {metric}, don't just "
                f"avoid increasing it"
            )
        elif cc > base:
            violations.append(
                f"{name}: {metric} {base} → {cc} (> {threshold}) — "
                f"refactor to reduce {metric} instead of adding to it"
            )
        # else: cc <= base, not known to be touched — grandfathered, allowed
    return violations


def _changed_lines(base_ref: str, root: Path, rel_path: str) -> set[int]:
    """Line numbers in *rel_path*'s current working-tree content that this
    change added, modified, or deleted at, versus *base_ref* — via
    `git diff -U0`.

    Zero context means every hunk's "+" side is exactly the lines that
    changed, nothing surrounding. A pure-deletion hunk reports a new-side
    count of 0; its anchor line (the insertion point) is still counted as
    touched, since deleting the last statement in a function is a change
    *to* that function even though nothing was added.
    """
    out = subprocess.run(
        ["git", "diff", "--no-color", "-U0", base_ref, "--", rel_path],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    lines: set[int] = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", out, re.MULTILINE):
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        lines.update(range(start, start + count)) if count else lines.add(start)
    return lines


def _touched_names(root: Path, base_ref: str, ranges: dict[str, tuple[int, int]]) -> set[str]:
    """Names from *ranges* (``<relpath>::<qualified name>`` → (lineno, endline))
    whose line range overlaps a line this change touched in that file.

    One `git diff` per file, not per function — cheap enough, and a file
    with no diff at all (nothing in *ranges* here was touched) skips
    straight past without running git at all.
    """
    by_file: dict[str, list[str]] = {}
    for name in ranges:
        by_file.setdefault(name.split("::", 1)[0], []).append(name)

    touched: set[str] = set()
    for file_rel, names in by_file.items():
        changed = _changed_lines(base_ref, root, file_rel)
        if not changed:
            continue
        for name in names:
            start, end = ranges[name]
            if any(start <= line <= end for line in changed):
                touched.add(name)
    return touched


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


def _discover_python_files(root: Path) -> list[Path]:
    """Every *.py file under root git doesn't ignore, sorted — tracked or
    not, since this is a "head" scan of the current working tree and a
    brand-new function in a file you haven't `git add`ed yet is exactly
    the case this ratchet needs to catch, not skip.

    Not `root.rglob("*.py")`: with `--path` defaulting to `.` (the whole
    repo, not a pre-scoped source subdirectory the way kai-ster's own
    `--path ster` happened to be), an unfiltered rglob walks straight into
    `.venv/`/`node_modules/`/caches and reports hundreds of violations in
    vendored code that was never this repo's to fix.

    Not plain `git ls-files` either (tracked-only, unlike craftcov.py's own
    `discover_python_files`, which scans a committed cache/snapshot flow
    where that's the right call): `--others --exclude-standard` adds every
    untracked file git *wouldn't* ignore, so a new file still fails the
    ratchet before its first `git add`. Falls back to a plain rglob outside
    a git repo.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return sorted(root / line for line in out.splitlines() if line)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return sorted(root.rglob("*.py"))


def compute_functions(root: Path) -> dict[str, tuple[int, int, int]]:
    """Map ``<relpath>::<qualified function name>`` → (complexity, lineno, endline)."""
    from radon.complexity import cc_visit  # lazy: keeps find_violations import-light

    result: dict[str, tuple[int, int, int]] = {}
    for path in _discover_python_files(root):
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


def compute_cognitive_ranges(root: Path) -> dict[str, tuple[int, int, int]]:
    """Map ``<relpath>::<qualified function name>`` → (cognitive complexity, lineno, endline)."""
    from cognitive_complexity.api import get_cognitive_complexity  # lazy, as above

    result: dict[str, tuple[int, int, int]] = {}
    for path in _discover_python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        rel = path.relative_to(root).as_posix()
        for name, node in _walk_functions(tree, []):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            result[f"{rel}::{name}"] = (get_cognitive_complexity(node), node.lineno, end)
    return result


def compute_cognitive(root: Path) -> dict[str, int]:
    """Map ``<relpath>::<qualified function name>`` → cognitive complexity."""
    return {name: cc for name, (cc, _l, _e) in compute_cognitive_ranges(root).items()}


# ── Invariant return (SonarQube S3516) ───────────────────────────────────────

MIN_RETURNS_TO_COMPARE = 2  # a single return can't be "invariant" against itself


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
    if len(returns) < MIN_RETURNS_TO_COMPARE or not all(
        isinstance(r.value, ast.Name) for r in returns
    ):
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
    for path in _discover_python_files(root):
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


# ── Duplicated string literals (SonarQube S1192) ─────────────────────────────
# Scoped per file (not per-function, unlike the metrics above) — that is the
# rule's own granularity: it flags a literal repeated across a file, not
# within one function. Defaults approximate SonarQube's own Python defaults.

DUPLICATE_LITERAL_THRESHOLD = 3
DUPLICATE_LITERAL_MIN_LENGTH = 5
MIN_OCCURRENCES_TO_REPORT = 2  # a literal seen once isn't "duplicated" yet


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    """id() of every bare string Expr that is a docstring, to exclude it.

    A docstring is the first statement of a Module/ClassDef/FunctionDef/
    AsyncFunctionDef body when that statement is itself a bare string
    constant — the same exclusion SonarQube applies, since a repeated
    docstring is not the accidental duplication S1192 is looking for.
    """
    ids: set[int] = set()
    candidates: list[ast.AST] = [tree]
    candidates.extend(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for node in candidates:
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def compute_duplicate_literals(
    root: Path, min_length: int = DUPLICATE_LITERAL_MIN_LENGTH
) -> dict[str, int]:
    """Map ``<relpath>::<repr of literal>`` → occurrence count, for literals repeated ≥2×.

    Counted per file (S1192's own granularity), excluding docstrings and any
    literal shorter than *min_length*. A literal that appears only once is
    left out entirely — the ratchet only ever cares about repeats.
    """
    result: dict[str, int] = {}
    for path in _discover_python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        docstring_ids = _docstring_node_ids(tree)
        counts: dict[str, int] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in docstring_ids or len(node.value) < min_length:
                continue
            literal = repr(node.value)
            counts[literal] = counts.get(literal, 0) + 1
        rel = path.relative_to(root).as_posix()
        for literal, count in counts.items():
            if count >= MIN_OCCURRENCES_TO_REPORT:
                result[f"{rel}::{literal}"] = count
    return result


def _measure_at_ref(
    ref: str, path: str
) -> tuple[dict[str, int], dict[str, int], dict[str, str], dict[str, int]]:
    """Every metric for *path* as it exists at git *ref*, via a throwaway worktree.

    One worktree for all four: checking out the base ref is the slow part, and
    doing it once per metric would multiply the cost of every commit.

    *path* is resolved relative to the repo root before joining it onto the
    worktree — ``Path(worktree) / path`` alone silently discards ``worktree``
    whenever *path* is absolute (a documented ``pathlib`` behaviour: joining an
    absolute path onto anything replaces the left side entirely), which would
    make this read the real working tree instead of the checked-out base ref.
    """
    repo_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    rel_path = Path(path).resolve().relative_to(repo_root)
    with tempfile.TemporaryDirectory() as tmp:
        worktree = Path(tmp) / "wt"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), ref],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            root = worktree / rel_path
            return (
                compute_complexity(root),
                compute_cognitive(root),
                compute_invariant_returns(root),
                compute_duplicate_literals(root),
            )
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                capture_output=True,
            )


def has_tidy_exempt(base_ref: str) -> bool:
    """True when a `Tidy-Exempt:` trailer appears anywhere in `base_ref..HEAD`.

    Same bypass, same trailer, as check_tidy_ratchet.sh and
    check_refactor_first.py — one exemption mechanism for every gate this
    project ships, not a separate one per script.
    """
    out = subprocess.run(
        ["git", "log", "--format=%B", f"{base_ref}..HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return any(line.startswith("Tidy-Exempt:") for line in out.splitlines())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="git ref to compare against")
    parser.add_argument("--path", default=".", help="source directory to scan")
    args = parser.parse_args(argv)

    if has_tidy_exempt(args.base):
        print(f"Complexity ratchet: Tidy-Exempt: trailer found in {args.base}..HEAD — skipping.")
        return 0

    root = Path(args.path)
    head_funcs = compute_functions(root)
    head = {name: cc for name, (cc, _l, _e) in head_funcs.items()}
    head_cog_ranges = compute_cognitive_ranges(root)
    head_cog = {name: cc for name, (cc, _l, _e) in head_cog_ranges.items()}
    head_inv = compute_invariant_returns(root)
    head_dup = compute_duplicate_literals(root)
    try:
        base, base_cog, base_inv, base_dup = _measure_at_ref(args.base, args.path)
    except subprocess.CalledProcessError as exc:
        print(f"error: could not read base ref {args.base!r}: {exc.stderr or exc}", file=sys.stderr)
        return 2

    # A name this change's diff actually reaches — vs. numerically unchanged
    # because it merely happens to sit in a file with unrelated edits.
    # Touched-and-still-over-threshold must decrease, not just not increase.
    cc_ranges = {n: (v[1], v[2]) for n, v in head_funcs.items()}
    cog_ranges = {n: (v[1], v[2]) for n, v in head_cog_ranges.items()}
    touched_cc = _touched_names(root, args.base, cc_ranges)
    touched_cog = _touched_names(root, args.base, cog_ranges)

    violations = find_violations(base, head, metric="cyclomatic complexity", touched=touched_cc)
    violations += find_violations(
        base_cog, head_cog, metric="cognitive complexity", touched=touched_cog
    )
    # Grandfathered like the ratchet: an invariant return that was already there
    # is not this change's problem, but a new one is.
    violations += [
        f"{name}: every return hands back the same never-rebound {returned!r} "
        f"(SonarQube S3516) — use one exit, reached by break"
        for name, returned in sorted(head_inv.items())
        if name not in base_inv
    ]
    violations += find_violations(
        base_dup,
        head_dup,
        threshold=DUPLICATE_LITERAL_THRESHOLD - 1,
        metric="duplicated string literal",
    )

    if violations:
        print(f"Complexity ratchet: {len(violations)} violation(s):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    print(f"Complexity ratchet: OK (cyclomatic, cognitive ≤ {THRESHOLD}; no S1192 duplication).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
