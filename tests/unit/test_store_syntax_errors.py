"""Unit tests for store.format_parse_error — friendly syntax error formatting."""

from __future__ import annotations

from pathlib import Path

from ster.store import format_parse_error

# ── helpers ───────────────────────────────────────────────────────────────────


def _write(tmp_path: Path, name: str, lines: list[str]) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


# ── test_format_parse_error_extracts_line_number ─────────────────────────────


def test_format_parse_error_extracts_line_number(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.ttl", ["line1", "line2", "line3"])
    exc = Exception("at line 2 of <>: Bad syntax")
    result = format_parse_error(exc, path)
    assert "2" in result


# ── test_format_parse_error_shows_file_line_content ──────────────────────────


def test_format_parse_error_shows_file_line_content(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.ttl", ["first line", "THE BAD LINE", "third line"])
    exc = Exception("at line 2 of <>: Bad syntax")
    result = format_parse_error(exc, path)
    assert "THE BAD LINE" in result


# ── test_format_parse_error_no_line_number ────────────────────────────────────


def test_format_parse_error_no_line_number(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.ttl", ["something"])
    exc = Exception("some generic error with no line info")
    result = format_parse_error(exc, path)
    assert "some generic error with no line info" in result


# ── test_format_parse_error_no_crash_on_missing_file ─────────────────────────


def test_format_parse_error_no_crash_on_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.ttl"
    exc = Exception("at line 5 of <>: Bad syntax")
    result = format_parse_error(exc, path)
    # Should not raise — line content will just be absent
    assert result  # non-empty string returned


# ── test_format_parse_error_trims_long_line ───────────────────────────────────


def test_format_parse_error_trims_long_line(tmp_path: Path) -> None:
    long_line = "x" * 200
    path = _write(tmp_path, "bad.ttl", ["", long_line])
    exc = Exception("at line 2 of <>: Bad syntax")
    result = format_parse_error(exc, path)
    # The excerpt of the line shown in the message must be ≤ 120 chars
    for part in result.splitlines():
        if "x" * 10 in part:
            assert len(part) <= 120
            break


# ── test_format_parse_error_contains_syntax_word ─────────────────────────────


def test_format_parse_error_contains_syntax_word(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.ttl", ["line1", "bad line"])
    exc = Exception("at line 2 of <>: Bad syntax")
    result = format_parse_error(exc, path)
    assert "Syntax" in result or "syntax" in result


# ── test_format_parse_error_line_number_out_of_range ─────────────────────────


def test_format_parse_error_line_number_out_of_range(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.ttl", ["only one line"])
    exc = Exception("at line 99 of <>: Bad syntax")
    result = format_parse_error(exc, path)
    # Should mention line 99 but not crash even though file is shorter
    assert "99" in result
