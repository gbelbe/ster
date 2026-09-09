"""Ticking the context files, driven through a fake terminal.

The picker is raw-tty code, so it is exercised the way the file picker beside it
already is: a BytesIO standing in for stdin, and termios/tty patched out. That
keeps the key handling — which is the part with the logic in it — under test
rather than excluded.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ster.cli import _context_checkbox_picker, _read_checkbox_key


def _run(options: list[Path], keys: bytes) -> list[Path]:
    fake_stdin = MagicMock()
    fake_stdin.isatty.return_value = True
    fake_stdin.fileno.return_value = 0
    fake_stdin.buffer = io.BytesIO(keys)

    with (
        patch("sys.stdin", fake_stdin),
        patch("sys.stdout.write", return_value=None),
        patch("sys.stdout.flush", return_value=None),
        patch("tty.setraw", return_value=None),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr", return_value=None),
        patch("termios.tcflush", return_value=None),
    ):
        return _context_checkbox_picker(options)


@pytest.fixture
def three(tmp_path: Path) -> list[Path]:
    return [tmp_path / "places.ttl", tmp_path / "products.ttl", tmp_path / "people.ttl"]


DOWN, UP, ENTER, SPACE, ESC = b"\x1b[B", b"\x1b[A", b"\r", b" ", b"\x1b\x1b"


def test_enter_with_nothing_ticked_loads_nothing(three) -> None:
    """The default is none: context is opt-in, so silence means no."""
    assert _run(three, ENTER) == []


def test_space_ticks_the_row_under_the_cursor(three) -> None:
    assert _run(three, SPACE + ENTER) == [three[0]]


def test_space_twice_unticks_it_again(three) -> None:
    """A checkbox that cannot be cleared is a trap."""
    assert _run(three, SPACE + SPACE + ENTER) == []


def test_the_cursor_moves_before_it_ticks(three) -> None:
    assert _run(three, DOWN + SPACE + ENTER) == [three[1]]


def test_several_files_can_be_ticked(three) -> None:
    """The whole reason for checkboxes over a typed list."""
    assert _run(three, SPACE + DOWN + DOWN + SPACE + ENTER) == [three[0], three[2]]


def test_a_ticks_everything(three) -> None:
    assert _run(three, b"a" + ENTER) == three


def test_n_clears_everything(three) -> None:
    """Trailing Enter is never reached — 'n' confirms on its own, see below."""
    assert _run(three, b"a" + b"n" + ENTER) == []


def test_n_confirms_immediately_without_waiting_for_enter(three) -> None:
    """The whole point of 'n': one guaranteed, unambiguous key to leave with
    nothing loaded — unlike Esc, which has to tell a bare keypress apart from
    the start of an arrow-key sequence and isn't airtight on every terminal.
    """
    assert _run(three, SPACE + b"n") == []


def test_n_overrides_ticks_from_earlier_in_the_session(three) -> None:
    assert _run(three, SPACE + DOWN + SPACE + b"n") == []


def test_the_cursor_wraps_at_the_top(three) -> None:
    """Up from the first row reaches the last, as in the file picker."""
    assert _run(three, UP + SPACE + ENTER) == [three[2]]


def test_escape_skips_the_step(three) -> None:
    """Esc means "I did not want to answer this", not "load what I ticked"."""
    assert _run(three, SPACE + ESC) == []


def test_ctrl_c_leaves_with_nothing_rather_than_raising(three) -> None:
    """Interrupting an optional prompt must not take the whole session down."""
    assert _run(three, SPACE + b"\x03") == []


def test_a_key_that_means_nothing_is_ignored(three) -> None:
    """A stray keypress must not tick, move, or leave — it just redraws.

    Reading a key and deciding what it means are separate now, and "nothing" is
    a real answer the loop has to handle rather than an absent else-branch.
    """
    assert _run(three, b"x" + SPACE + ENTER) == [three[0]]


def test_an_unknown_escape_sequence_is_ignored_rather_than_leaving(three) -> None:
    """Esc-[ followed by something that is not an arrow is not an abort."""
    assert _run(three, b"\x1b[Z" + SPACE + ENTER) == [three[0]]


class _ExhaustedStdin:
    """A stdin that has run out, and complains if asked again too many times.

    Without this the regression it guards would *hang* the suite rather than
    fail it: a picker that keeps reading past end of input loops forever. Turning
    the hang into an AssertionError is what makes the test safe to run.
    """

    def __init__(self, limit: int = 50) -> None:
        self.calls = 0
        self.limit = limit

    def read(self, _n: int) -> bytes:
        self.calls += 1
        if self.calls > self.limit:
            raise AssertionError("the picker kept reading after stdin ended")
        return b""


def test_a_closed_stdin_reads_as_leaving() -> None:
    """EOF is not a keypress, and there is no next one coming."""
    assert _read_checkbox_key(io.BytesIO(b"")) == "abort"


def test_the_picker_leaves_when_stdin_ends_instead_of_spinning(three) -> None:
    """A pipe that ends, or a terminal that goes away, must not loop forever.

    Every branch of the key reader had a byte to match on, so an empty read fell
    through to "unrecognised" and the loop redrew and asked again — forever.
    """
    fake_stdin = MagicMock()
    fake_stdin.isatty.return_value = True
    fake_stdin.fileno.return_value = 0
    fake_stdin.buffer = _ExhaustedStdin()

    with (
        patch("sys.stdin", fake_stdin),
        patch("sys.stdout.write", return_value=None),
        patch("sys.stdout.flush", return_value=None),
        patch("tty.setraw", return_value=None),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr", return_value=None),
        patch("termios.tcflush", return_value=None),
    ):
        assert _context_checkbox_picker(three) == []

    assert fake_stdin.buffer.calls == 1, "it should stop at the first empty read"


def test_the_returned_order_follows_the_list_not_the_clicks(three) -> None:
    """Stable output: the same ticks give the same list however they were made."""
    assert _run(three, DOWN + DOWN + SPACE + UP + UP + SPACE + ENTER) == [three[0], three[2]]
