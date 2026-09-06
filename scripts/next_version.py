#!/usr/bin/env python3
"""Print the version the commits since the last tag have earned, or nothing.

Releases should not depend on someone remembering to edit a number. Conventional
Commits already record what each change was, so the version follows from the log:
a breaking change moves the major, a feature the minor, a fix the patch, and
housekeeping moves nothing — a docs-only merge cuts no tag.

While the major is still 0 a breaking change moves the *minor* instead, which is
what semantic-release does, so no stray ``feat!:`` declares the project 1.0.

Prints ``v<version>`` on stdout when a release is due and stays silent when it is
not, so a workflow can act on whether there was any output at all.
"""

from __future__ import annotations

import re
import subprocess
import sys

# type(scope)!: description — the scope and the bang are both optional
_SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]*\))?(?P<bang>!)?:\s")
_BREAKING = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)

# What each Conventional Commit type is worth. Anything absent releases nothing:
# docs, style, test, chore and ci change no behaviour a user could observe.
_LEVEL_OF = {
    "feat": "minor",
    "fix": "patch",
    "perf": "patch",
    "refactor": "patch",
    "build": "patch",
    "revert": "patch",
}
_RANK = {"patch": 1, "minor": 2, "major": 3}


def bump_level(messages: list[str]) -> str | None:
    """The highest release level *messages* justify, or None for housekeeping."""
    best: str | None = None
    for message in messages:
        subject = message.strip().splitlines()[0] if message.strip() else ""
        match = _SUBJECT.match(subject)
        if match is None:
            continue  # not a Conventional Commit: it says nothing about level
        if match.group("bang") or _BREAKING.search(message):
            level: str | None = "major"
        else:
            level = _LEVEL_OF.get(match.group("type"))
        if level and (best is None or _RANK[level] > _RANK[best]):
            best = level
    return best


def next_version(current: str | None, level: str) -> str:
    """Apply *level* to *current*, which may carry a leading v or be absent."""
    if current is None:
        return "0.1.0"
    major, minor, patch = (int(p) for p in current.lstrip("v").split(".")[:3])
    if level == "major":
        # 0.x may break without becoming 1.0 — that call is deliberate, not automatic.
        return f"0.{minor + 1}.0" if major == 0 else f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _git(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def last_tag() -> str | None:
    """The most recent v-tag reachable from HEAD, or None in a fresh repository."""
    return _git("describe", "--tags", "--abbrev=0", "--match", "v*") or None


def commits_since(tag: str | None) -> list[str]:
    """Every commit message after *tag*, or all of them when there is no tag."""
    span = f"{tag}..HEAD" if tag else "HEAD"
    raw = _git("log", "--no-merges", "--format=%B%x00", span)
    return [m for m in raw.split("\0") if m.strip()]


def main() -> int:
    tag = last_tag()
    level = bump_level(commits_since(tag))
    if level is None:
        return 0  # nothing releasable: silence tells the workflow not to tag
    print(f"v{next_version(tag, level)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
