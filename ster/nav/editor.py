"""Pure text-buffer editing helpers for TUI input fields.

All functions are stateless — they take (buffer, pos) and return new values,
making them straightforward to unit-test without curses.
"""

from __future__ import annotations

import curses


def _word_start_left(v: str, p: int) -> int:
    """Return the position of the start of the word to the left of *p*."""
    i = p
    while i > 0 and v[i - 1] == " ":
        i -= 1
    while i > 0 and v[i - 1] != " ":
        i -= 1
    return i


def _word_start_right(v: str, p: int) -> int:
    """Return the position just past the end of the word to the right of *p*."""
    i = p
    while i < len(v) and v[i] != " ":
        i += 1
    while i < len(v) and v[i] == " ":
        i += 1
    return i


def _apply_line_edit(buffer: str, pos: int, key: int) -> tuple[str, int]:
    """Apply one keystroke to a *(buffer, pos)* pair.

    Handles printable chars, Backspace, Del, Ctrl+A/E/K/W, arrow keys.
    Returns unchanged *(buffer, pos)* for unrecognised keys.
    """
    if key == 1:  # Ctrl+A
        return buffer, 0
    if key == 5:  # Ctrl+E
        return buffer, len(buffer)
    if key == 11:  # Ctrl+K
        return buffer[:pos], pos
    if key == 23:  # Ctrl+W — delete word backward
        i = pos
        while i > 0 and buffer[i - 1] == " ":
            i -= 1
        while i > 0 and buffer[i - 1] != " ":
            i -= 1
        return buffer[:i] + buffer[pos:], i
    if key in (curses.KEY_BACKSPACE, 127):
        if pos > 0:
            return buffer[: pos - 1] + buffer[pos:], pos - 1
        return buffer, pos
    if key == curses.KEY_DC:
        if pos < len(buffer):
            return buffer[:pos] + buffer[pos + 1 :], pos
        return buffer, pos
    if key == curses.KEY_LEFT:
        return buffer, max(0, pos - 1)
    if key == curses.KEY_RIGHT:
        return buffer, min(len(buffer), pos + 1)
    if key == curses.KEY_HOME:
        return buffer, 0
    if key == curses.KEY_END:
        return buffer, len(buffer)
    if 32 <= key < 256:
        ch = chr(key)
        return buffer[:pos] + ch + buffer[pos:], pos + 1
    return buffer, pos
