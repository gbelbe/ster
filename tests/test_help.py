"""Tests for ster/help.py — welcome_lines and readme_section."""

from __future__ import annotations

from ster.help import AUTHOR, SECTIONS, VERSION, readme_section, welcome_lines

# ── SECTIONS structure ────────────────────────────────────────────────────────


def test_sections_is_list():
    assert isinstance(SECTIONS, list)
    assert len(SECTIONS) > 0


def test_sections_each_entry_has_title_and_entries():
    for title, entries in SECTIONS:
        assert isinstance(title, str)
        assert isinstance(entries, list)


def test_sections_entries_are_two_tuples():
    for _, entries in SECTIONS:
        for entry in entries:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            keys, desc = entry
            assert isinstance(keys, str)
            assert isinstance(desc, str)


def test_sections_contains_navigation():
    titles = [t for t, _ in SECTIONS]
    assert any("NAVIGATION" in t for t in titles)


def test_sections_contains_general():
    titles = [t for t, _ in SECTIONS]
    assert any("GENERAL" in t for t in titles)


# ── welcome_lines ─────────────────────────────────────────────────────────────


def test_welcome_lines_returns_list():
    lines = welcome_lines()
    assert isinstance(lines, list)
    assert all(isinstance(l, str) for l in lines)


def test_welcome_lines_ends_with_press_any_key():
    lines = welcome_lines()
    assert lines[-1].strip() == "Press any key to continue …"


def test_welcome_lines_with_title_includes_title():
    lines = welcome_lines(title="My Taxonomy", n_concepts=42, lang="fr")
    joined = "\n".join(lines)
    assert "My Taxonomy" in joined
    assert "42" in joined
    assert "fr" in joined


def test_welcome_lines_without_title_skips_header():
    lines = welcome_lines()
    # No title lines — first line should be a section header
    first_non_empty = next(l for l in lines if l.strip())
    # Should be a section name, not a title
    assert any(section_title in first_non_empty for section_title, _ in SECTIONS)


def test_welcome_lines_concept_singular():
    lines = welcome_lines(title="T", n_concepts=1, lang="en")
    joined = "\n".join(lines)
    assert "1 concept " in joined or "1 concept·" in joined or "1 concept" in joined
    assert "concepts" not in joined


def test_welcome_lines_concept_plural():
    lines = welcome_lines(title="T", n_concepts=5, lang="en")
    joined = "\n".join(lines)
    assert "5 concepts" in joined


def test_welcome_lines_includes_all_section_titles():
    lines = welcome_lines()
    joined = "\n".join(lines)
    for section_title, _ in SECTIONS:
        assert section_title in joined


def test_welcome_lines_includes_key_shortcuts():
    lines = welcome_lines()
    joined = "\n".join(lines)
    # At minimum the quit shortcut must appear
    assert "q" in joined


# ── readme_section ────────────────────────────────────────────────────────────


def test_readme_section_returns_string():
    md = readme_section()
    assert isinstance(md, str)


def test_readme_section_has_markdown_header():
    md = readme_section()
    assert "## Keyboard shortcuts" in md


def test_readme_section_has_table_headers():
    md = readme_section()
    assert "| Keys | Action |" in md
    assert "|------|--------|" in md


def test_readme_section_includes_all_sections():
    md = readme_section()
    for section_title, _ in SECTIONS:
        assert section_title in md


def test_readme_section_wraps_keys_in_backticks():
    md = readme_section()
    # Every key description should appear in a backtick-delimited cell
    assert "`" in md


def test_version_and_author_are_strings():
    assert isinstance(VERSION, str)
    assert len(VERSION) > 0
    assert isinstance(AUTHOR, str)
    assert len(AUTHOR) > 0
