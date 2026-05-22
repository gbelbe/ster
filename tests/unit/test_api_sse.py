"""Async unit test for the SSEBroadcaster."""

from __future__ import annotations

import asyncio

from ster.api import SSEBroadcaster


async def test_broadcaster_emits_updated_event() -> None:
    bc = SSEBroadcaster()
    received: list[str] = []

    async def collect() -> None:
        async for chunk in bc.subscribe():
            received.append(chunk)
            return  # stop after first event

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.01)  # let subscribe() register its queue
    await bc._broadcast()
    await asyncio.wait_for(task, timeout=2.0)

    assert len(received) == 1
    assert '"updated"' in received[0]


async def test_broadcaster_keepalive_on_timeout() -> None:
    """subscribe() yields a keepalive comment when the wait times out."""
    import unittest.mock as mock

    bc = SSEBroadcaster()
    received: list[str] = []

    # Patch wait_for inside ster.api so only the internal call times out,
    # not the outer await used by the test harness.
    original_wait = asyncio.wait_for
    call_count = 0

    async def _patched_wait_for(coro, timeout=None):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError
        return await original_wait(coro, timeout=timeout)

    with mock.patch("ster.api.asyncio.wait_for", side_effect=_patched_wait_for):
        async for chunk in bc.subscribe():
            received.append(chunk)
            break  # stop after first yield

    assert len(received) == 1
    assert "keepalive" in received[0]


async def test_broadcaster_multiple_listeners() -> None:
    bc = SSEBroadcaster()
    results: list[list[str]] = [[], []]

    async def collect(idx: int) -> None:
        async for chunk in bc.subscribe():
            results[idx].append(chunk)
            return

    t1 = asyncio.create_task(collect(0))
    t2 = asyncio.create_task(collect(1))
    await asyncio.sleep(0.01)
    await bc._broadcast()
    await asyncio.gather(
        asyncio.wait_for(t1, timeout=2.0),
        asyncio.wait_for(t2, timeout=2.0),
    )

    assert '"updated"' in results[0][0]
    assert '"updated"' in results[1][0]
