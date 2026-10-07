"""``ensure_live_server``: start the server, and only if that fails settle the port.

The common case — nothing on the port — must cost nothing extra; the claim is
the fallback for a start that failed, and every outcome of it is either a usable
server or an error that says why.
"""

from __future__ import annotations

import pytest

from ster.viz_vowl import _claim, _render, _server
from ster.viz_vowl._claim import BLOCKED, FREE, REUSE, Claim


@pytest.fixture
def starts(monkeypatch):
    """Record start attempts; the list of results is consumed one per attempt."""
    attempts: list[bool] = []
    results: list[bool] = []

    def _start(_tax, _path, _cb=None):
        attempts.append(True)
        return results.pop(0)

    monkeypatch.setattr(_server, "_start_api_server", _start)
    return attempts, results


def test_ensure_live_server_starts_without_claiming_when_the_port_is_free(monkeypatch, starts):
    attempts, results = starts
    results.append(True)
    monkeypatch.setattr(_claim, "claim_port", lambda *a, **k: pytest.fail("no claim needed"))

    _render.ensure_live_server(object(), None)

    assert len(attempts) == 1


def test_ensure_live_server_reuses_a_server_already_showing_the_file(monkeypatch, starts):
    attempts, results = starts
    results.append(False)
    monkeypatch.setattr(_claim, "claim_port", lambda *a, **k: Claim(REUSE, url="http://x:1"))

    _render.ensure_live_server(object(), None)

    assert len(attempts) == 1  # did not try to bind a second server


def test_ensure_live_server_starts_again_once_the_port_is_freed(monkeypatch, starts):
    attempts, results = starts
    results.extend([False, True])
    monkeypatch.setattr(_claim, "claim_port", lambda *a, **k: Claim(FREE))

    _render.ensure_live_server(object(), None)

    assert len(attempts) == 2


def test_ensure_live_server_raises_the_claims_reason_when_blocked(monkeypatch, starts):
    _, results = starts
    results.append(False)
    monkeypatch.setattr(
        _claim,
        "claim_port",
        lambda *a, **k: Claim(BLOCKED, "another ster session is open (x)."),
    )

    with pytest.raises(RuntimeError, match="another ster session is open"):
        _render.ensure_live_server(object(), None)


def test_ensure_live_server_falls_back_to_the_generic_reason_when_free_but_unstartable(
    monkeypatch, starts
):
    """A free port that still will not start is not a port problem (broken install)."""
    _, results = starts
    results.extend([False, False])
    monkeypatch.setattr(_claim, "claim_port", lambda *a, **k: Claim(FREE))
    monkeypatch.setattr(
        _server, "unavailable_reason", lambda *a, **k: "the ster server isn't running."
    )

    with pytest.raises(RuntimeError, match="isn't running"):
        _render.ensure_live_server(object(), None)
