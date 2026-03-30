"""Tests for the setup wizard (pure logic, no interactive prompts)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

# ── helpers ───────────────────────────────────────────────────────────────────
from ster.wizard import _KNOWN_LANGS, SetupResult, run

# ── SetupResult dataclass ─────────────────────────────────────────────────────


def test_setup_result_fields():
    r = SetupResult(
        file_path=Path("out.ttl"),
        base_uri="https://example.org/test/",
        languages=["en", "fr"],
        titles={"en": "My Taxonomy", "fr": "Ma Taxonomie"},
        descriptions={"en": "A test taxonomy."},
        creator="Alice",
        created="2026-03-25",
    )
    assert r.file_path == Path("out.ttl")
    assert r.languages == ["en", "fr"]
    assert r.titles["fr"] == "Ma Taxonomie"
    assert r.creator == "Alice"


def test_setup_result_defaults():
    r = SetupResult(
        file_path=Path("out.ttl"),
        base_uri="https://example.org/",
        languages=["en"],
    )
    assert r.titles == {}
    assert r.descriptions == {}
    assert r.creator == ""
    assert r.created == ""


# ── known languages dict ──────────────────────────────────────────────────────


def test_known_langs_has_en_fr():
    assert "en" in _KNOWN_LANGS
    assert "fr" in _KNOWN_LANGS


# ── wizard.run with mocked prompts ────────────────────────────────────────────


def _mock_prompts(answers: list[str]):
    """Return a Prompt.ask mock that pops answers sequentially."""
    it = iter(answers)

    def fake_ask(prompt, *, default="", console=None, **kw):
        try:
            return next(it)
        except StopIteration:
            return default

    return fake_ask


def test_run_happy_path(tmp_path):
    out_file = tmp_path / "new.ttl"
    answers = [
        str(out_file),  # file path
        "en,fr",  # languages
        "My Taxonomy",  # title en
        "Ma Taxonomie",  # title fr
        "A test taxonomy.",  # description en
        "",  # description fr (skip)
        "https://example.org/test/",  # base URI
        "Alice",  # creator
    ]
    with (
        patch("ster.wizard.Prompt.ask", side_effect=_mock_prompts(answers)),
        patch("ster.wizard.Confirm.ask", return_value=True),
    ):
        result = run()

    assert result is not None
    assert result.file_path == out_file
    assert result.languages == ["en", "fr"]
    assert result.titles["en"] == "My Taxonomy"
    assert result.titles["fr"] == "Ma Taxonomie"
    assert result.descriptions["en"] == "A test taxonomy."
    assert "fr" not in result.descriptions
    assert result.creator == "Alice"
    assert result.base_uri == "https://example.org/test/"


def test_run_cancelled_at_confirm(tmp_path):
    out_file = tmp_path / "new.ttl"
    answers = [str(out_file), "en", "My Taxonomy", "", "https://example.org/x/", ""]
    with (
        patch("ster.wizard.Prompt.ask", side_effect=_mock_prompts(answers)),
        patch("ster.wizard.Confirm.ask", return_value=False),
    ):
        result = run()

    assert result is None


def test_run_quit_mid_wizard(tmp_path):
    answers = ["quit"]  # user quits on first prompt
    with (
        patch("ster.wizard.Prompt.ask", side_effect=_mock_prompts(answers)),
        patch("ster.wizard.Confirm.ask", return_value=True),
    ):
        result = run()

    assert result is None


def test_run_adds_slash_to_base_uri(tmp_path):
    out_file = tmp_path / "new.ttl"
    answers = [str(out_file), "en", "Title", "", "https://example.org/myns", ""]
    with (
        patch("ster.wizard.Prompt.ask", side_effect=_mock_prompts(answers)),
        patch("ster.wizard.Confirm.ask", return_value=True),
    ):
        result = run()

    assert result is not None
    assert result.base_uri.endswith("/")


def test_run_adds_ttl_extension_if_missing(tmp_path):
    out_file = tmp_path / "notaxonomy"  # no extension
    answers = [str(out_file), "en", "Title", "", "https://example.org/x/", ""]
    with (
        patch("ster.wizard.Prompt.ask", side_effect=_mock_prompts(answers)),
        patch("ster.wizard.Confirm.ask", return_value=True),
    ):
        result = run()

    assert result is not None
    assert result.file_path.suffix == ".ttl"


def test_run_skip_optional_fields(tmp_path):
    out_file = tmp_path / "new.ttl"
    answers = [
        str(out_file),  # file
        "en",  # languages
        "Title",  # title en
        "skip",  # description — skip
        "https://example.org/x/",  # base URI
        "skip",  # creator — skip
    ]
    with (
        patch("ster.wizard.Prompt.ask", side_effect=_mock_prompts(answers)),
        patch("ster.wizard.Confirm.ask", return_value=True),
    ):
        result = run()

    assert result is not None
    assert result.descriptions == {}
    assert result.creator == ""


def test_run_sets_created_date(tmp_path):
    out_file = tmp_path / "new.ttl"
    answers = [str(out_file), "en", "Title", "", "https://example.org/x/", ""]
    with (
        patch("ster.wizard.Prompt.ask", side_effect=_mock_prompts(answers)),
        patch("ster.wizard.Confirm.ask", return_value=True),
    ):
        result = run()

    assert result is not None
    import re

    assert re.match(r"\d{4}-\d{2}-\d{2}", result.created)
