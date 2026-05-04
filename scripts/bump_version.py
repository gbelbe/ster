#!/usr/bin/env python3
"""Bump the project version in pyproject.toml and README.md.

Usage:
    python scripts/bump_version.py 0.3.4
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _validate(ver: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        sys.exit(f"Invalid version '{ver}' — expected MAJOR.MINOR.PATCH")


def _update_pyproject(new: str) -> str:
    path = ROOT / "pyproject.toml"
    text = path.read_text()
    updated, n = re.subn(r'(?m)^version = "\d+\.\d+\.\d+"', f'version = "{new}"', text)
    if n != 1:
        sys.exit("Could not find 'version = ...' in pyproject.toml")
    path.write_text(updated)
    return text.split("\n")[
        next(i for i, l in enumerate(text.splitlines()) if l.startswith("version = "))
    ]


def _update_readme(new: str) -> None:
    path = ROOT / "README.md"
    text = path.read_text()
    updated, n = re.subn(r"(?m)^  v\d+\.\d+\.\d+$", f"  v{new}", text)
    if n != 1:
        sys.exit("Could not find '  vX.Y.Z' version line in README.md")
    path.write_text(updated)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} <new_version>")
    new = sys.argv[1].lstrip("v")
    _validate(new)

    old_line = _update_pyproject(new)
    old = re.search(r"\d+\.\d+\.\d+", old_line)
    old_ver = old.group() if old else "?"

    _update_readme(new)

    print(f"Bumped {old_ver} → {new}")
    print("  pyproject.toml  ✓")
    print("  README.md       ✓")
    print()
    print("Don't forget to commit and tag:")
    print(f"  git commit -am 'chore: bump version to {new}'")
    print(f"  git tag v{new}")


if __name__ == "__main__":
    main()
