"""Unit tests for scripts/bump_version.py — version bump + changelog insertion."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add scripts/ to path so we can import bump_version directly
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import bump_version as bv  # noqa: E402

# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_pyproject(root: Path, version: str) -> Path:
    p = root / "pyproject.toml"
    p.write_text(f'[project]\nname = "ster"\nversion = "{version}"\n')
    return p


def _make_readme(root: Path, banner_ver: str, has_changelog: bool = True) -> Path:
    changelog = "\n## Changelog\n\n### 0.4.6\n- Old feature\n" if has_changelog else ""
    p = root / "README.md"
    p.write_text(f"# ster\n\n  v{banner_ver}\n\nSome text.{changelog}")
    return p


def _make_notes(root: Path, content: str = "- New feature X") -> Path:
    p = root / "RELEASE_NOTES.md"
    p.write_text(content)
    return p


# ── pyproject version bump ────────────────────────────────────────────────────


def test_updates_pyproject_version(tmp_path: Path) -> None:
    _make_pyproject(tmp_path, "0.4.6")
    bv._update_pyproject("0.4.7", root=tmp_path)
    assert 'version = "0.4.7"' in (tmp_path / "pyproject.toml").read_text()


def test_pyproject_does_not_alter_other_content(tmp_path: Path) -> None:
    _make_pyproject(tmp_path, "0.4.6")
    bv._update_pyproject("0.4.7", root=tmp_path)
    text = (tmp_path / "pyproject.toml").read_text()
    assert 'name = "ster"' in text


def test_pyproject_old_version_removed(tmp_path: Path) -> None:
    _make_pyproject(tmp_path, "0.4.6")
    bv._update_pyproject("0.4.7", root=tmp_path)
    assert 'version = "0.4.6"' not in (tmp_path / "pyproject.toml").read_text()


# ── README banner update ──────────────────────────────────────────────────────


def test_updates_readme_banner(tmp_path: Path) -> None:
    _make_readme(tmp_path, "0.4.6")
    bv._update_readme("0.4.7", root=tmp_path)
    assert "  v0.4.7" in (tmp_path / "README.md").read_text()


def test_readme_old_banner_removed(tmp_path: Path) -> None:
    _make_readme(tmp_path, "0.4.6")
    bv._update_readme("0.4.7", root=tmp_path)
    assert "  v0.4.6" not in (tmp_path / "README.md").read_text()


# ── changelog insertion ───────────────────────────────────────────────────────


def test_inserts_changelog_entry_at_top(tmp_path: Path) -> None:
    _make_readme(tmp_path, "0.4.6")
    notes = _make_notes(tmp_path)
    bv._update_changelog("0.4.7", notes, root=tmp_path)
    text = (tmp_path / "README.md").read_text()
    # New entry must appear before old entry
    assert text.index("### 0.4.7") < text.index("### 0.4.6")


def test_changelog_entry_has_correct_header(tmp_path: Path) -> None:
    _make_readme(tmp_path, "0.4.6")
    notes = _make_notes(tmp_path)
    bv._update_changelog("0.4.7", notes, root=tmp_path)
    assert "### 0.4.7" in (tmp_path / "README.md").read_text()


def test_changelog_entry_contains_notes_content(tmp_path: Path) -> None:
    _make_readme(tmp_path, "0.4.6")
    notes = _make_notes(tmp_path, "- My shiny new feature")
    bv._update_changelog("0.4.7", notes, root=tmp_path)
    assert "- My shiny new feature" in (tmp_path / "README.md").read_text()


def test_existing_changelog_entries_preserved(tmp_path: Path) -> None:
    _make_readme(tmp_path, "0.4.6")
    notes = _make_notes(tmp_path)
    bv._update_changelog("0.4.7", notes, root=tmp_path)
    assert "### 0.4.6" in (tmp_path / "README.md").read_text()
    assert "- Old feature" in (tmp_path / "README.md").read_text()


# ── validation ────────────────────────────────────────────────────────────────


def test_rejects_non_semver(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        bv._validate("0.4")


def test_rejects_alpha_version(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        bv._validate("abc")


def test_rejects_version_downgrade(tmp_path: Path) -> None:
    _make_pyproject(tmp_path, "0.4.6")
    with pytest.raises(SystemExit):
        bv._check_version_bump("0.4.5", root=tmp_path)


def test_rejects_same_version(tmp_path: Path) -> None:
    _make_pyproject(tmp_path, "0.4.6")
    with pytest.raises(SystemExit):
        bv._check_version_bump("0.4.6", root=tmp_path)


def test_accepts_version_bump(tmp_path: Path) -> None:
    _make_pyproject(tmp_path, "0.4.6")
    bv._check_version_bump("0.4.7", root=tmp_path)  # must not raise
