"""Unit tests for the publish-menu key mapping (arrow-navigation logic)."""

from __future__ import annotations

import io


def _act(first: bytes, rest: bytes = b"") -> str:
    from ster.cli import _menu_action_for_key

    return _menu_action_for_key(first, io.BytesIO(rest))


def test_enter_selects():
    assert _act(b"\r") == "select"
    assert _act(b"\n") == "select"


def test_ctrl_c_quits():
    assert _act(b"\x03") == "quit"


def test_plain_escape_quits():
    # ESC with no following "[" is a bare Escape → back/quit.
    assert _act(b"\x1b", b"") == "quit"


def test_arrow_up_and_down():
    assert _act(b"\x1b", b"[A") == "up"
    assert _act(b"\x1b", b"[B") == "down"


def test_unknown_escape_sequence_is_none():
    assert _act(b"\x1b", b"[C") == "none"  # right arrow — unused


def test_ordinary_key_is_none():
    assert _act(b"x") == "none"
