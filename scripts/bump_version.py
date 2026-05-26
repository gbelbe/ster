#!/usr/bin/env python3
"""Bump the project version in pyproject.toml and README.md.

Usage:
    python scripts/bump_version.py 0.3.4
    python scripts/bump_version.py 0.3.4 --notes RELEASE_NOTES.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _validate(ver: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        sys.exit(f"Invalid version '{ver}' — expected MAJOR.MINOR.PATCH")


def _version_tuple(v: str) -> tuple[int, int, int]:
    a, b, c = v.split(".")
    return int(a), int(b), int(c)


def _current_version(root: Path = ROOT) -> str:
    text = (root / "pyproject.toml").read_text()
    m = re.search(r'(?m)^version = "(\d+\.\d+\.\d+)"', text)
    if not m:
        sys.exit("Could not find version in pyproject.toml")
    return m.group(1)


def _check_version_bump(new: str, root: Path = ROOT) -> None:
    current = _current_version(root)
    if _version_tuple(new) <= _version_tuple(current):
        sys.exit(f"New version {new} must be greater than current {current}")


def _update_pyproject(new: str, root: Path = ROOT) -> str:
    path = root / "pyproject.toml"
    text = path.read_text()
    updated, n = re.subn(r'(?m)^version = "\d+\.\d+\.\d+"', f'version = "{new}"', text)
    if n != 1:
        sys.exit("Could not find 'version = ...' in pyproject.toml")
    path.write_text(updated)
    return text.split("\n")[
        next(i for i, l in enumerate(text.splitlines()) if l.startswith("version = "))
    ]


def _update_readme(new: str, root: Path = ROOT) -> None:
    path = root / "README.md"
    text = path.read_text()
    updated, n = re.subn(r"(?m)^  v\d+\.\d+\.\d+$", f"  v{new}", text)
    if n != 1:
        sys.exit("Could not find '  vX.Y.Z' version line in README.md")
    path.write_text(updated)


def _update_changelog(new: str, notes_path: Path, root: Path = ROOT) -> None:
    notes = notes_path.read_text().strip()
    if not notes:
        sys.exit(f"{notes_path.name} is empty — add release notes before publishing")
    path = root / "README.md"
    text = path.read_text()
    replacement = f"## Changelog\n\n### {new}\n{notes}\n"
    updated, n = re.subn(r"(?m)^## Changelog\n", replacement, text, count=1)
    if n != 1:
        sys.exit("Could not find '## Changelog' section in README.md")
    path.write_text(updated)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Bump ster version")
    parser.add_argument("version", help="New version, e.g. 0.4.7")
    parser.add_argument("--notes", metavar="FILE", help="Path to RELEASE_NOTES.md")
    args = parser.parse_args()

    new = args.version.lstrip("v")
    _validate(new)
    _check_version_bump(new)

    old_line = _update_pyproject(new)
    old = re.search(r"\d+\.\d+\.\d+", old_line)
    old_ver = old.group() if old else "?"

    _update_readme(new)

    if args.notes:
        _update_changelog(new, Path(args.notes))
        print("  README.md changelog ✓")

    print(f"Bumped {old_ver} → {new}")
    print("  pyproject.toml  ✓")
    print("  README.md       ✓")


if __name__ == "__main__":
    main()
