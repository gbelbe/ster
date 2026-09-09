"""``_read_after_escape``: the escape-sequence peek shared by the raw-tty
pickers (file picker, checkbox picker, home action menu).

Regression coverage for a real bug, not just the helper's contract: a bare
Esc keypress sends a single ``\\x1b`` byte with nothing to follow, but the
code this replaced did a blocking ``stream.read(1)`` right after ESC no
matter what — which hangs on a real terminal until the *next* key arrives,
then consumes that key as if it were part of the escape sequence. That made
Esc (and, one keystroke later, whatever was typed next) appear not to work
at all, requiring several presses to get anywhere — see the checkbox-picker
and action-menu tests below for the effect this had one level up.

A ``BytesIO`` (what the rest of the raw-tty test suite already uses to stand
in for stdin) never blocks on ``read``, so it can't reproduce the hang — an
``os.pipe()`` pair is used here instead, since a pipe is a real, selectable
file descriptor without needing an actual terminal.

A second regression covered here: production reads through
``sys.stdin.buffer``, a *buffered* reader, not a raw one. Wrapping the pipe's
read end the same way (``buffering=8192`` instead of ``0``) reproduces the
exact failure a first fix introduced — servicing one byte of a 3-byte arrow
sequence pulls all three into the buffer, leaving the OS-level fd looking
empty to anything checking it with ``select()`` alone, even though the byte
this function needs is sitting right there.
"""

from __future__ import annotations

import io
import os
import time
from collections.abc import Iterator

import pytest

from ster.cli._tty_input import _read_after_escape
from ster.cli._workspace_ui import _read_checkbox_key


@pytest.fixture
def pipe() -> Iterator[tuple[io.FileIO, io.FileIO]]:
    r_fd, w_fd = os.pipe()
    reader = os.fdopen(r_fd, "rb", buffering=0)
    writer = os.fdopen(w_fd, "wb", buffering=0)
    try:
        yield reader, writer
    finally:
        reader.close()
        writer.close()


@pytest.fixture
def buffered_pipe() -> Iterator[tuple[io.BufferedReader, io.FileIO]]:
    """Same idea as ``pipe``, but the read end is a real buffered reader —
    what ``sys.stdin.buffer`` actually is in production, unlike the unbuffered
    pipes above."""
    r_fd, w_fd = os.pipe()
    reader = os.fdopen(r_fd, "rb", buffering=8192)
    writer = os.fdopen(w_fd, "wb", buffering=0)
    try:
        yield reader, writer
    finally:
        reader.close()
        writer.close()


def test_falls_back_to_a_direct_read_when_the_stream_has_no_fileno():
    """A BytesIO (no real fd) never blocks on read — nothing to peek for."""
    assert _read_after_escape(io.BytesIO(b"X")) == b"X"


def test_falls_back_to_a_direct_read_on_eof_too():
    assert _read_after_escape(io.BytesIO(b"")) == b""


def test_returns_the_byte_immediately_when_one_is_already_available(pipe):
    reader, writer = pipe
    writer.write(b"[")
    start = time.monotonic()
    assert _read_after_escape(reader) == b"["
    # Already sitting in the pipe — no reason to wait out the peek window.
    assert time.monotonic() - start < 0.03


def test_returns_empty_within_the_window_when_nothing_follows(pipe):
    """The actual bug: this used to be a plain read(1), which blocks
    indefinitely when nothing is coming — exactly the case for a lone Esc."""
    reader, _writer = pipe
    start = time.monotonic()
    result = _read_after_escape(reader)
    elapsed = time.monotonic() - start
    assert result == b""
    assert elapsed < 0.5  # bounded, not an indefinite hang


def test_a_bare_escape_does_not_swallow_the_keypress_that_follows(pipe):
    """End-to-end through _read_checkbox_key: Esc with nothing queued yet must
    resolve on its own, and the next real keypress must still be there for the
    *next* read rather than being eaten as this escape sequence's second byte.
    """
    reader, writer = pipe
    writer.write(b"\x1b")  # a lone Esc — nothing follows it
    start = time.monotonic()
    key = _read_checkbox_key(reader)
    elapsed = time.monotonic() - start
    assert key == "abort"
    assert elapsed < 0.5

    # The 'n' below was never written until *after* the Esc was resolved, so a
    # correct reader has nothing left to have consumed early.
    writer.write(b"n")
    assert _read_checkbox_key(reader) == "none"


def test_an_arrow_key_burst_already_slurped_into_the_buffer_is_still_seen(buffered_pipe):
    """The regression a first select()-only fix introduced: an arrow key
    arrives as "ESC [ A" in one burst, and reading the initial ESC through a
    *buffered* reader commonly pulls the other two bytes into its internal
    buffer along with it — select() on the raw fd then sees nothing pending,
    because there genuinely is nothing left at the OS level, even though the
    buffer is holding exactly the byte this function is being asked for.
    """
    reader, writer = buffered_pipe
    writer.write(b"\x1b[A")  # a full arrow-key sequence, sent as one burst
    first = reader.read(1)
    assert first == b"\x1b"

    start = time.monotonic()
    result = _read_after_escape(reader)
    elapsed = time.monotonic() - start

    assert result == b"["  # not b"" — the byte was already there
    assert elapsed < 0.03  # served from the buffer, no need to wait anything out
    assert _read_after_escape(reader) == b"A"
