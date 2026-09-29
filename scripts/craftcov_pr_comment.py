#!/usr/bin/env python3
"""Posts (or updates) a sticky PR comment summarizing craftCov's findings —
the repo-wide total and its by-heuristic breakdown, diffed against where
the branch diverged from its base. Same "what changed" question
check_refactor_first.py answers per touched file, answered here at the
whole-repo level and surfaced where a developer is already looking (the
PR itself), not just in a CI log.

Sticky, not one-comment-per-push: every run looks for an existing comment
starting with MARKER and PATCHes it in place via the GitHub API, rather
than posting a new comment each time and burying the PR in duplicates.

Needs its own full-corpus scan of the merge-base tree via a throwaway
`git worktree`, same reasoning and same technique as
check_refactor_first.py (dupes needs every file scanned at each point to
find a match's other half) — this script does its own scan rather than
importing check_refactor_first.py's, since that one returns per-file
totals only, not the by-heuristic aggregate this needs.

Requires the `gh` CLI, authenticated (GitHub Actions runners have this by
default via `GH_TOKEN: ${{ github.token }}` — see templates/ci-job.yml).

Usage:
    python scripts/craftcov_pr_comment.py --base origin/main --repo OWNER/NAME --pr 123
    python scripts/craftcov_pr_comment.py --base origin/main --dry-run   # print, don't post
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from craftcov import (  # noqa: E402
    aggregate,
    build_detector_index,
    diff_by_heuristic,
    discover_python_files,
    load_catalog,
    merge_corpus_findings,
    scan_files,
)

MARKER = "<!-- craftcov-pr-report -->"


def _git(args: list[str], cwd: Path, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise SystemExit(f"✗ git {' '.join(args)} failed:\n{proc.stderr}")
    return proc.stdout


def full_scan(root: Path) -> dict:
    """The full craftCov aggregate for `root`. `root` must be fully
    resolved — see check_refactor_first.py's per_file_totals for why."""
    catalog = load_catalog()
    rule_maps, whole_tool, corpus_tool = build_detector_index(catalog)
    files = discover_python_files(root)
    by_file = scan_files(root, files, rule_maps, whole_tool, vulture_min_confidence=0)
    merge_corpus_findings(root, files, by_file, corpus_tool)
    return aggregate(by_file)


def scan_ref(repo: Path, ref: str, scratch_parent: Path) -> dict:
    """full_scan's aggregate for `ref`, via a throwaway worktree — unless
    `ref` is "HEAD", scanned in place to skip a redundant checkout."""
    if ref == "HEAD":
        return full_scan(repo)
    worktree = (scratch_parent / "pr-comment-ref").resolve()
    _git(["worktree", "add", "--detach", str(worktree), ref], cwd=repo)
    try:
        return full_scan(worktree)
    finally:
        _git(["worktree", "remove", "--force", str(worktree)], cwd=repo, check=False)


def _format_row(hid: str, old: int, new: int, catalog_by_id: dict[str, dict]) -> str:
    code = catalog_by_id.get(hid, {}).get("code", "")
    delta = new - old
    dsign = "+" if delta > 0 else ""
    tag = " 🆕" if old == 0 else (" ✅" if new == 0 else "")
    return f"| {code} | `{hid}` | {old} | {new} | {dsign}{delta}{tag} |"


def _doc_link(repo_slug: str | None, head_sha: str) -> str:
    # Pinned to this exact commit's blob, not a branch name — every repo
    # this runs in has its own CRAFTSMANSHIP.md at the same path, and the
    # default branch isn't always "main" (semanticlint's is "master").
    if not repo_slug:
        return "CRAFTSMANSHIP.md"
    return f"[CRAFTSMANSHIP.md](https://github.com/{repo_slug}/blob/{head_sha}/CRAFTSMANSHIP.md)"


def render_markdown(
    base_agg: dict,
    head_agg: dict,
    catalog_by_id: dict[str, dict],
    repo_slug: str | None,
    head_sha: str,
) -> str:
    base_total, head_total = base_agg["total"], head_agg["total"]
    changed = diff_by_heuristic(base_agg["by_heuristic"], head_agg["by_heuristic"])
    total_delta = head_total - base_total
    sign = "+" if total_delta > 0 else ""

    lines = [MARKER, "## craftCov report", ""]
    lines.append(f"**Repo-wide total: {base_total} → {head_total} ({sign}{total_delta})**")
    lines.append("")

    if not changed:
        lines.append("No change in any heuristic's count.")
    else:
        lines.append("| Code | Heuristic | Before | After | Δ |")
        lines.append("|---|---|---|---|---|")
        lines.extend(_format_row(hid, old, new, catalog_by_id) for hid, old, new in changed)

    lines.append("")
    doc_ref = _doc_link(repo_slug, head_sha)
    lines.append(
        f"<sub>Updated automatically on each push — see {doc_ref} "
        "for what these mean. 🆕 = newly present, ✅ = fully resolved.</sub>"
    )
    return "\n".join(lines)


def _issues_api(repo_slug: str, suffix: str) -> str:
    return f"repos/{repo_slug}/issues/{suffix}"


def find_existing_comment(repo_slug: str, pr: int) -> int | None:
    out = subprocess.run(
        ["gh", "api", _issues_api(repo_slug, f"{pr}/comments"), "--paginate"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    try:
        comments = json.loads(out or "[]")
    except json.JSONDecodeError:
        return None
    for c in comments:
        if c.get("body", "").startswith(MARKER):
            return c["id"]
    return None


def post_or_update_comment(repo_slug: str, pr: int, body: str) -> None:
    existing = find_existing_comment(repo_slug, pr)
    if existing is not None:
        subprocess.run(
            [
                "gh",
                "api",
                _issues_api(repo_slug, f"comments/{existing}"),
                "-X",
                "PATCH",
                "-f",
                f"body={body}",
            ],
            check=True,
        )
    else:
        subprocess.run(
            [
                "gh",
                "api",
                _issues_api(repo_slug, f"{pr}/comments"),
                "-X",
                "POST",
                "-f",
                f"body={body}",
            ],
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base", required=True, help="base ref this branch diverged from, e.g. origin/main"
    )
    parser.add_argument("--path", default=".", help="repo root (default: current directory)")
    parser.add_argument("--repo", help="OWNER/NAME, required unless --dry-run")
    parser.add_argument("--pr", type=int, help="PR number, required unless --dry-run")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the comment body, don't post it"
    )
    args = parser.parse_args()

    if not args.dry_run and (not args.repo or not args.pr):
        parser.error("--repo and --pr are required unless --dry-run")

    repo = Path(args.path).resolve()
    merge_base = _git(["merge-base", args.base, "HEAD"], cwd=repo).strip()
    head_sha = _git(["rev-parse", "HEAD"], cwd=repo).strip()

    catalog_by_id = {e["id"]: e for e in load_catalog()}

    with tempfile.TemporaryDirectory(prefix="craft-gate-pr-comment-") as tmp:
        scratch = Path(tmp)
        base_agg = scan_ref(repo, merge_base, scratch)
        head_agg = scan_ref(repo, "HEAD", scratch)

    body = render_markdown(base_agg, head_agg, catalog_by_id, args.repo, head_sha)

    if args.dry_run:
        print(body)
        return 0

    post_or_update_comment(args.repo, args.pr, body)
    print(f"✓ craftCov PR comment posted/updated on {args.repo}#{args.pr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
