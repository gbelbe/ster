#!/usr/bin/env python3
"""Refactor First gate — see CRAFTSMANSHIP.md's "Refactor First" section for
the workflow this enforces the outcome of, not the procedure.

Fails when a touched `.py` file's total across the 8 mechanically-detectable
heuristics (craftcov.py --list-detectors) did not go down relative to where
this branch diverged from its base — unless it was already at 0, in which
case it must simply stay at 0 (a clean file can't be made dirtier and still
pass). Total-based, not per-heuristic: fixing one instance of every present
heuristic type (the workflow this gate checks the outcome of) always drops
the total by exactly the number of heuristic types that were present, so a
strict total decrease is exactly what that workflow produces.

Bypassed by a `Tidy-Exempt:` trailer anywhere in the commit range — the same
escape hatch check_tidy_ratchet.sh already uses. One exemption mechanism,
not two.

Needs its own full-corpus scan of the merge-base tree via a throwaway `git
worktree` (dupes is corpus-wide — a duplicate only means anything relative
to its other copy, so there's no way to get an accurate "before" count for
one file without scanning every file at that revision too), plus a scan of
the current tree. Both calls bypass craftcov.py's on-disk cache entirely
(this script calls its scan functions directly) since a merge-base worktree
is thrown away right after and a repeat run should never see stale numbers.

Usage:
    python3 scripts/check_refactor_first.py --base <ref> [--head <ref>]

Examples:
    python3 scripts/check_refactor_first.py --base origin/main
    python3 scripts/check_refactor_first.py --base origin/main --head HEAD
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from craftcov import (
    aggregate,
    build_detector_index,
    discover_python_files,
    load_catalog,
    merge_corpus_findings,
    scan_files,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _git(args: list[str], cwd: Path, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise SystemExit(f"✗ git {' '.join(args)} failed:\n{proc.stderr}")
    return proc.stdout


def touched_python_files(repo: Path, base_sha: str, head_ref: str) -> list[tuple[str, str]]:
    """(old_rel, new_rel) for every added/copied/modified/renamed .py file
    between base_sha and head_ref — old == new except for a real rename."""
    out = _git(
        ["diff", "--name-status", "-M", "--diff-filter=ACMR", base_sha, head_ref, "--", "*.py"],
        cwd=repo,
    )
    pairs: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R"):
            pairs.append((parts[1], parts[2]))
        else:
            pairs.append((parts[1], parts[1]))
    return pairs


def has_tidy_exempt(repo: Path, base_sha: str, head_ref: str) -> bool:
    out = _git(["log", "--format=%B", f"{base_sha}..{head_ref}"], cwd=repo, check=False)
    return any(line.startswith("Tidy-Exempt:") for line in out.splitlines())


def per_file_totals(root: Path) -> dict[str, int]:
    """Total findings across the 8 detectable heuristics, per file, for a
    full scan of `root` — bypasses craftcov.py's cache (see module docstring).

    `root` MUST be fully resolved (no symlink components) before this is
    called, matching craftcov.py's own `main()` convention: ruff/vulture
    report back absolute paths in their own resolved form, and
    `_normalize_path`'s `relative_to(root)` silently drops a finding (not
    an error — it's designed to tolerate a path outside root) if `root`
    itself wasn't resolved the same way. On macOS in particular, /tmp is a
    symlink to /private/tmp, so an unresolved tempfile-based worktree path
    reliably reproduces this and silently reports zero findings."""
    catalog = load_catalog()
    rule_maps, whole_tool, corpus_tool = build_detector_index(catalog)
    files = discover_python_files(root)
    by_file = scan_files(root, files, rule_maps, whole_tool, vulture_min_confidence=0)
    merge_corpus_findings(root, files, by_file, corpus_tool)
    return aggregate(by_file)["by_file"]  # rel -> count; a file with 0 findings is simply absent


def scan_ref(repo: Path, ref: str, scratch_parent: Path) -> dict[str, int]:
    """per_file_totals for `ref`, checked out into a throwaway worktree —
    unless `ref` is exactly what's already on disk (HEAD in the normal CI
    checkout), which is scanned in place to skip a redundant checkout."""
    if ref == "HEAD":
        return per_file_totals(repo)
    worktree = (scratch_parent / "refactor-first-ref").resolve()
    _git(["worktree", "add", "--detach", str(worktree), ref], cwd=repo)
    try:
        return per_file_totals(worktree)
    finally:
        _git(["worktree", "remove", "--force", str(worktree)], cwd=repo, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base", required=True, help="base ref this branch diverged from, e.g. origin/main"
    )
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--path", default=str(REPO_ROOT), help="repo root (default: this repo)")
    args = parser.parse_args()

    repo = Path(args.path).resolve()

    verify = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", args.base],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if verify.returncode != 0:
        print(
            f"⚠ refactor-first gate: '{args.base}' not found locally — "
            "skipping (git fetch it first)",
            file=sys.stderr,
        )
        return 0

    merge_base = _git(["merge-base", args.base, args.head], cwd=repo).strip()

    pairs = touched_python_files(repo, merge_base, args.head)
    if not pairs:
        return 0  # nothing touched, nothing to check

    if has_tidy_exempt(repo, merge_base, args.head):
        print(
            f"refactor-first gate: Tidy-Exempt: trailer found in "
            f"{merge_base[:8]}..{args.head} — skipping."
        )
        return 0

    with tempfile.TemporaryDirectory(prefix="craft-gate-refactor-first-") as tmp:
        scratch = Path(tmp)
        base_totals = scan_ref(repo, merge_base, scratch)
        head_totals = scan_ref(repo, args.head, scratch)

    failures: list[str] = []
    for old_rel, new_rel in pairs:
        before = base_totals.get(old_rel, 0)
        after = head_totals.get(new_rel, 0)
        ok = after == 0 if before == 0 else after < before
        if not ok:
            label = new_rel if old_rel == new_rel else f"{old_rel} -> {new_rel}"
            failures.append(
                f"  {label}: {before} -> {after} (needed {'0' if before == 0 else f'< {before}'})"
            )

    if failures:
        print(
            "✗ Refactor First gate: total detectable-heuristic count did not go down for:",
            file=sys.stderr,
        )
        for f in failures:
            print(f, file=sys.stderr)
        print(
            "\n  Fix one instance of every heuristic craftcov.py finds present in a touched\n"
            "  file (see CRAFTSMANSHIP.md's 'Refactor First'), bundled into one tidy(multi):\n"
            "  commit, or add a Tidy-Exempt: trailer if nothing genuinely applies.",
            file=sys.stderr,
        )
        return 1

    print(f"✓ Refactor First gate: {len(pairs)} touched file(s) OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
