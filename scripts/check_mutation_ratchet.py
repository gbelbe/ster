#!/usr/bin/env python3
"""Diff-aware mutation-testing ratchet — kill rate for touched functions only.

Covers catalog.yaml's [TODO: catalog entry] — the mechanical enforcement
CRAFTSMANSHIP.md's "Mutation ratchet" section documents. Independent of every
other gate: doesn't run mutmut itself (a prior `mutmut run` step must have
already populated `mutants/`, normally cached between CI runs the way
`node_modules` or `.venv` are), just reads its results and a git diff.

Fails when a function this change's diff actually touches has a mutation
score (killed / (killed + survived), mutmut's own definition — see
`mutmut badge`) below --threshold. Not base-vs-head like the complexity
ratchet: mutation testing is too expensive to run twice per PR (it reruns
the whole test suite once per mutant), so this checks touched functions
against a flat floor on the current tree only, not a "must have improved"
comparison. A genuinely equivalent mutant belongs behind mutmut's own
`# pragma: no mutate` (mutmut's answer to this, same idea as coverage.py's
`# pragma: no cover`) — fix the false positive at its source, not by
lowering this gate's bar.

Reaches into mutmut's internals (`mutmut.utils.format_utils.
orig_function_and_class_names_from_key`) to map a mutant key like
"pkg.mod.x_foo__mutmut_3" back to the function it mutated ("foo"), rather
than mutmut's own per-mutant line-span index (`mutants/<file>.spans`) —
verified against a real run that those spans are lines in the *generated*
mutants file, not the original source, so they can't be intersected with
a `git diff` on the original file directly. This is a real coupling to an
internal, not-obviously-public module; pin mutmut's version range and
re-verify this mapping on any major-version bump.

Usage:
    python scripts/check_mutation_ratchet.py [--base origin/main] [--path .]
        [--mutants-dir mutants] [--threshold 80]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_THRESHOLD = 80.0

# mutmut's own exit-code -> outcome mapping (mutmut.stats.status_by_exit_code,
# mirrored rather than imported: that module pulls in mutmut's full click/UI
# stack on import, for a handful of int literals this ratchet needs).
_KILLED_CODES = {1, 3, 36, -24, 24, 152, 255}  # killed, incl. timeout as a kill
_SURVIVED_CODES = {0}
_NO_TESTS_CODES = {5, 33}


def _changed_lines(base_ref: str, root: Path, rel_path: str) -> set[int]:
    """Line numbers in *rel_path*'s current working-tree content that this
    change added, modified, or deleted at, versus *base_ref* — via
    `git diff -U0`. See check_complexity_ratchet.py's identical helper for
    the full rationale (same technique, duplicated per this repo's
    standalone-scripts convention rather than a shared import).
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


def function_ranges(root: Path, rel_path: str) -> dict[str, tuple[int, int]]:
    """Map ``<rel_path>::<qualified function name>`` -> (lineno, endline)."""
    path = root / rel_path
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return {}
    ranges = {}
    for name, node in _walk_functions(tree, []):
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        ranges[f"{rel_path}::{name}"] = (node.lineno, end)
    return ranges


def touched_names(root: Path, base_ref: str, ranges: dict[str, tuple[int, int]]) -> set[str]:
    """Names from *ranges* whose line range overlaps a line this change touched."""
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


def qualified_name_from_mutant_key(key: str) -> str | None:
    """ "pkg.mod.x_foo__mutmut_3" -> "foo"; "pkg.xǁMyClassǁmethod__mutmut_1" -> "MyClass.method".

    Returns None for a key this mutmut version's naming convention doesn't
    match — treated as "not touched" by the caller (fails safe: at worst
    under-counts, never blocks a PR over a mutant it can't place).
    """
    try:
        from mutmut.utils.format_utils import orig_function_and_class_names_from_key
    except ImportError:
        return None
    try:
        func, cls = orig_function_and_class_names_from_key(key)
    except (AssertionError, ValueError):
        return None
    return f"{cls}.{func}" if cls else func


def mutant_outcome(exit_code: int | None) -> str:
    if exit_code in _KILLED_CODES:
        return "killed"
    if exit_code in _SURVIVED_CODES:
        return "survived"
    if exit_code in _NO_TESTS_CODES:
        return "no_tests"
    return "other"  # skipped / suspicious / caught-by-typecheck / segfault / not-checked


def collect_touched_results(
    root: Path, mutants_dir: Path, touched_by_file: dict[str, set[str]]
) -> dict[str, dict[str, int]]:
    """touched_by_file: {relpath: {touched qualified names}} -> per-name outcome counts."""
    results: dict[str, dict[str, int]] = {}
    for rel, names in touched_by_file.items():
        meta_path = mutants_dir / (rel + ".meta")
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            continue
        for mutant_key, exit_code in meta.get("exit_code_by_key", {}).items():
            qual = qualified_name_from_mutant_key(mutant_key)
            if qual is None or qual not in names:
                continue
            full_name = f"{rel}::{qual}"
            if full_name not in results:
                results[full_name] = {"killed": 0, "survived": 0, "no_tests": 0, "other": 0}
            results[full_name][mutant_outcome(exit_code)] += 1
    return results


def find_violations(results: dict[str, dict[str, int]], threshold: float) -> list[str]:
    violations = []
    for name, counts in sorted(results.items()):
        tested = counts["killed"] + counts["survived"]
        if tested == 0:
            if counts["no_tests"]:
                violations.append(
                    f"{name}: {counts['no_tests']} mutant(s) with no covering test — untested code"
                )
            continue
        score = 100.0 * counts["killed"] / tested
        if score < threshold:
            violations.append(
                f"{name}: mutation score {score:.0f}% ({counts['killed']}/{tested} killed, "
                f"< {threshold:.0f}%) — strengthen the test, or mark a genuinely equivalent "
                f"mutant `# pragma: no mutate`"
            )
    return violations


def has_tidy_exempt(base_ref: str) -> bool:
    """True when a `Tidy-Exempt:` trailer appears anywhere in `base_ref..HEAD`."""
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
    parser.add_argument("--mutants-dir", default="mutants", help="mutmut's output directory")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    if has_tidy_exempt(args.base):
        print(f"Mutation ratchet: Tidy-Exempt: trailer found in {args.base}..HEAD — skipping.")
        return 0

    root = Path(args.path)
    mutants_dir = root / args.mutants_dir
    if not mutants_dir.exists():
        print(f"error: {mutants_dir} not found — run `mutmut run` first.", file=sys.stderr)
        return 2

    meta_files = sorted(mutants_dir.rglob("*.meta"))
    all_ranges: dict[str, tuple[int, int]] = {}
    for meta_path in meta_files:
        rel = str(meta_path.relative_to(mutants_dir))[: -len(".meta")]
        all_ranges.update(function_ranges(root, rel))

    if not all_ranges:
        print("Mutation ratchet: no mutated files with recoverable function ranges.")
        return 0

    touched = touched_names(root, args.base, all_ranges)
    if not touched:
        print("Mutation ratchet: no touched functions with mutation data.")
        return 0

    touched_by_file: dict[str, set[str]] = {}
    for full in touched:
        rel, qual = full.split("::", 1)
        touched_by_file.setdefault(rel, set()).add(qual)

    results = collect_touched_results(root, mutants_dir, touched_by_file)
    violations = find_violations(results, args.threshold)

    if violations:
        print(f"Mutation ratchet: {len(violations)} violation(s):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    print(f"Mutation ratchet: OK (touched functions >= {args.threshold:.0f}% mutation score).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
