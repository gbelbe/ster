"""Compute an expensive answer once, however many callers ask for it at the same time.

An agent that gets no reply retries, and the page polls on top of that, so the same costly computation (parsing the
graph, hashing every triple) used to start again for each caller and all of them fought over the one interpreter.
Callers with the same key now queue behind the first and take its result.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable

_registry_lock = threading.Lock()
_locks: dict[Hashable, threading.Lock] = {}


def single_flight[T](key: Hashable, lookup: Callable[[], T | None], compute: Callable[[], T]) -> T:
    """The value *lookup* finds, or the one *compute* makes — by exactly one caller per *key* at a time.

    *lookup* is asked before taking the lock and again after, so a caller that waited finds what the first one stored.
    """
    found = lookup()
    if found is not None:
        return found
    with _registry_lock:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        found = lookup()
        if found is not None:
            return found
        return compute()
