"""Shared low-level helper for the raw-tty pickers (file picker, checkbox
picker, home action menu): resolving the escape-sequence ambiguity once
instead of three times, slightly differently, in three places.
"""

from __future__ import annotations

import os
import select
from typing import BinaryIO

# How long to give a slow link (e.g. SSH) to deliver the rest of an escape
# sequence once we already know the OS and this stream's own buffer both have
# nothing left *right now* — comfortably under human reaction time, so a lone
# Esc still feels instant.
_ESCAPE_CONTINUATION_TIMEOUT = 0.05  # seconds


def _read_after_escape(stream: BinaryIO) -> bytes:
    """One more byte, if one is already on its way — never an indefinite block.

    A terminal sends an arrow key as ESC [ X in one atomic burst; a lone Esc
    keypress sends only the ESC byte, with nothing to follow. Blocking on
    ``stream.read(1)`` here would hang until whatever key came *next* and
    silently swallow it as if it were this escape sequence's continuation —
    which is exactly what made a bare Esc take two presses to register (the
    first hung, the second both unblocked the read *and* got consumed by it
    instead of being seen as its own keypress).

    A first cut at fixing that used ``select()`` on the raw file descriptor to
    decide whether to bother reading at all — but ``stream`` here is normally
    ``sys.stdin.buffer``, a *buffered* reader, and buffering is exactly what
    breaks that check: servicing the first byte of "ESC [ A" commonly reads
    the whole 3-byte burst from the OS in one go and stashes the other two in
    the buffer, so by the time this runs, ``select()`` on the fd correctly
    reports nothing pending *at the OS level* — while the buffer is sitting on
    the very byte this function needs. That silently turned every arrow key
    into "nothing followed", i.e. treated as a bare Esc.

    So the actual check is: flip the fd non-blocking and just try
    ``stream.read(1)``. That serves an already-buffered byte immediately, no
    matter what the OS has pending (buffered data never needs a raw read at
    all); serves an OS-pending byte immediately too; and — the case that used
    to hang — returns ``None`` right away, not after however long the next
    keypress takes, when there is truly nothing anywhere yet. Only in that
    last case is there anything left to wait for, so only then does a short
    ``select()`` get a genuinely slow link (bytes of one sequence arriving a
    few ms apart) a brief window before this gives up and calls it a bare Esc.

    A stream with no real fd (a ``BytesIO`` standing in for stdin in tests, or
    anything else that can't be toggled non-blocking) skips straight to a
    direct read — the old, always-blocking behaviour those already rely on.
    """
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return stream.read(1)

    was_blocking = os.get_blocking(fd)
    os.set_blocking(fd, False)
    try:
        got = stream.read(1)
    except BlockingIOError:
        got = None
    finally:
        os.set_blocking(fd, was_blocking)
    if got:
        return got

    ready, _, _ = select.select([fd], [], [], _ESCAPE_CONTINUATION_TIMEOUT)
    return stream.read(1) if ready else b""
