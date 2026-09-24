"""Run a Textual app so that every way of stopping it gives the terminal back.

Textual restores the terminal — mouse tracking off, the main screen back, the
cursor shown — when the app ends through its own shutdown: a quit key, or
Ctrl+C / SIGINT. SIGTERM (``kill``, ``pkill``, an IDE's stop button) and SIGHUP
(a dropped SSH session) do not go through it: their default action ends the
process on the spot, and the shell underneath is left in mouse-tracking mode,
printing a report such as ``35;42;17M`` for every mouse move.

:func:`run_app` turns those two signals into Textual's normal exit, then lets
the process die of the signal exactly as it would have — a shell, ``timeout``
or a supervisor still sees it killed by SIGTERM. SIGQUIT is left alone: it asks
for a core dump, which a clean exit would take away.

Handling SIGTERM must not make a frozen ster unkillable, so a watchdog gives the
app :data:`GRACE_SECONDS` to stop; past that it resets the terminal itself and
exits.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
import threading
from functools import partial
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover - typing only
    from textual.app import App

GRACE_SECONDS: Final = 3.0

_SIGNALS: Final = tuple(
    getattr(signal, name) for name in ("SIGTERM", "SIGHUP") if hasattr(signal, name)
)

# What Textual's driver writes on the way out — mouse modes, focus events and
# bracketed paste off, the main screen back, the cursor shown — for the one
# case where it cannot run.
_RESET: Final = (
    b"\x1b[?1000l\x1b[?1003l\x1b[?1015l\x1b[?1006l\x1b[?1004l\x1b[?2004l\x1b[?1049l\x1b[?25h"
)


def run_app[ReturnType](app: App[ReturnType], **run_kwargs: Any) -> ReturnType | None:
    """Run *app* with ``app.run()``, but end it cleanly on SIGTERM and SIGHUP too.

    ``app.run()`` itself, not a loop of ster's own: Textual keeps choosing how
    its event loop is set up, and whatever stubs ``App.run`` (a test) still
    intercepts it — bypassing it once left a real app spinning inside a test.
    """
    received: list[int] = []
    tty = _saved_tty()  # before Textual switches the terminal to raw mode
    with _handling(_SIGNALS, partial(_stop, app, received, tty)):
        result = app.run(**run_kwargs)
    if received:
        _die_of(received[0])
    return result


@contextlib.contextmanager
def _handling(signals: tuple[int, ...], handler: Any):
    """Install *handler* for *signals* while the block runs, then put back what was there.

    Only the main thread may install signal handlers; anywhere else (a test
    runner's worker) the app simply runs as ``app.run()`` would.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {signum: signal.signal(signum, handler) for signum in signals}
    try:
        yield
    finally:
        for signum, old in previous.items():
            signal.signal(signum, old)


def _stop(
    app: App[Any],
    received: list[int],
    tty: tuple[int, list[Any]] | None,
    signum: int,
    _frame: object,
) -> None:
    """Ask the app to exit through Textual's shutdown, which restores the terminal.

    The handler runs on the main thread, inside the app's event loop when there
    is one. ``call_soon_threadsafe`` wakes that loop even while it waits on
    input, which a plain callback scheduled from a signal handler would not.
    """
    if received:
        return  # a second signal while stopping: the watchdog is already running
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _die_of(signum)  # no app loop (before it starts, after it ends): nothing to restore
        return
    received.append(signum)
    _start_watchdog(signum, tty)
    loop.call_soon_threadsafe(partial(app.exit, return_code=128 + signum))


def _start_watchdog(signum: int, tty: tuple[int, list[Any]] | None) -> None:
    timer = threading.Timer(GRACE_SECONDS, _force_exit, args=(signum, tty))
    timer.daemon = True
    timer.start()


def _saved_tty() -> tuple[int, list[Any]] | None:
    """The terminal's settings before the app, to put back if Textual cannot."""
    try:
        import termios  # noqa: PLC0415 - POSIX only
    except ImportError:
        return None
    try:
        fd = sys.__stdin__.fileno()  # type: ignore[union-attr]
        return fd, termios.tcgetattr(fd)
    except (termios.error, AttributeError, OSError, ValueError):
        return None  # not a terminal: nothing to put back


def _force_exit(signum: int, tty: tuple[int, list[Any]] | None) -> None:
    """The app did not stop in time — its event loop is blocked. Reset the terminal here."""
    with contextlib.suppress(AttributeError, OSError, ValueError):
        os.write(sys.__stdout__.fileno(), _RESET)  # type: ignore[union-attr]
    if tty is not None:  # a saved tty means termios imported fine in _saved_tty
        import termios  # noqa: PLC0415

        with contextlib.suppress(termios.error, OSError):
            termios.tcsetattr(tty[0], termios.TCSANOW, tty[1])
    os._exit(128 + signum)


def _die_of(signum: int) -> None:
    """End the process by *signum*'s default action, as if it had never been caught."""
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
