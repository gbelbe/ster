"""Unit tests for TUI input helpers in ster.nav.editor.

Covers keystroke reading (UTF-8 / accent handling) and the stateless
line-edit buffer operations.
"""

from __future__ import annotations

import curses

from ster.nav.editor import _apply_line_edit, read_keycode


class _FakeWin:
    """Minimal stand-in for a curses window exposing get_wch()."""

    def __init__(self, result):
        self._result = result

    def get_wch(self):
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


# ── read_keycode: UTF-8 / accent handling ─────────────────────────────────────


def test_read_keycode_returns_codepoint_for_ascii():
    assert read_keycode(_FakeWin("a")) == ord("a")


def test_read_keycode_assembles_accented_char_regression():
    # Regression: byte-wise getch() split "é" (0xC3 0xA9) into two garbage
    # chars. get_wch() assembles the multibyte sequence into one character,
    # so we get the real codepoint (233), not 195 followed by 169.
    assert read_keycode(_FakeWin("é")) == 0x00E9  # 233


def test_read_keycode_assembles_symbol_above_latin1():
    assert read_keycode(_FakeWin("€")) == 0x20AC  # 8364


def test_read_keycode_passes_special_key_int_unchanged():
    # Arrows / function keys come back from get_wch() as ints, untouched.
    assert read_keycode(_FakeWin(curses.KEY_UP)) == curses.KEY_UP


def test_read_keycode_timeout_returns_minus_one():
    # get_wch() raises curses.error when no input is available (with timeout).
    assert read_keycode(_FakeWin(curses.error())) == -1


# ── _apply_line_edit: accented characters insert correctly ────────────────────


def test_line_edit_inserts_accented_char():
    # Latin-1 accents (128–255) insert unchanged once the codepoint is read.
    assert _apply_line_edit("", 0, 0x00E9) == ("é", 1)


def test_line_edit_inserts_accent_mid_buffer():
    assert _apply_line_edit("cafe", 4, 0x00E9) == ("cafeé", 5)
