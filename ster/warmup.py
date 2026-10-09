"""Load a graph's expensive answers in the background, and say so while that is still going on.

A large graph takes minutes to parse and count, and the first tool call used to wait for all of it in silence, so
a client timed out and retried. The server now starts that work as soon as it has a model, and a tool that would
have to wait for it answers at once with how long it has been loading.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Final

LOADING: Final = "loading"

_lock = threading.Lock()
_current: dict[str, Any] = {}


def _warm(taxonomy: Any, done: threading.Event) -> None:
    from .mcp_context import overview, vocabulary  # noqa: PLC0415

    try:
        overview(taxonomy)
        vocabulary(taxonomy)
    except Exception:  # noqa: BLE001 — a tool call will report the same fault with its details
        pass
    finally:
        done.set()


def start(taxonomy: Any) -> None:
    """Begin warming *taxonomy* once; a model already being (or done being) warmed is left alone."""
    with _lock:
        if _current.get("taxonomy") is taxonomy:
            return
        done = threading.Event()
        # the object itself, not its id(): a collected model's id is handed to the next one
        _current.update(taxonomy=taxonomy, done=done, since=time.monotonic())
    threading.Thread(target=_warm, args=(taxonomy, done), daemon=True, name="ster-warmup").start()


def loading_seconds(taxonomy: Any) -> int | None:
    """Whole seconds *taxonomy* has been warming, or None when it is ready (or was never asked to warm)."""
    with _lock:
        if _current.get("taxonomy") is not taxonomy or _current["done"].is_set():
            return None
        return int(time.monotonic() - _current["since"])


def loading_message(seconds: int) -> str:
    return f"ster is still loading this graph ({seconds} s so far); try again in a little while."
