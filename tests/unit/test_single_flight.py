"""Concurrent callers of an expensive computation share one run of it."""

import threading
import time

import pytest

from ster.single_flight import single_flight


def test_concurrent_callers_compute_once():
    store: dict[str, int] = {}
    runs: list[int] = []

    def compute() -> int:
        runs.append(1)
        time.sleep(0.2)
        store["v"] = 42
        return 42

    results: list[int] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(single_flight("k-once", lambda: store.get("v"), compute))
        )
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == [42] * 8
    assert len(runs) == 1


def test_a_cached_value_skips_the_computation():
    assert single_flight("k-hit", lambda: 7, lambda: pytest.fail("recomputed")) == 7
