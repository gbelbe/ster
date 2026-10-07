"""Claiming the live-server port before a view opens.

One decision for the TUI, the CLI and ``ster serve``: reuse a server already
showing this file at this build, replace a stale ``ster serve``, and never touch
an interactive ster session or a process that is not ster.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import _version
from ster.viz_vowl import _claim, _server
from ster.viz_vowl._claim import BLOCKED, FREE, REUSE, claim_port

TAX = Path("/project/tax.ttl")


@pytest.fixture
def wire(monkeypatch):
    """Stub the world claim_port reads; returns the list of pids it tried to close."""
    freed: list[int] = []

    def _wire(
        *,
        command: str | None,
        served: str | None = None,
        build: str | None = _version.__version__,
        frees: bool = True,
    ) -> list[int]:
        monkeypatch.setattr(
            _server, "port_holder", lambda host=None, port=None: (321, command) if command else None
        )
        monkeypatch.setattr(
            _claim, "server_overview", lambda *a, **k: {"file": served} if served else None
        )
        monkeypatch.setattr(_claim, "server_build", lambda *a, **k: build)
        monkeypatch.setattr("ster.api_server.load_token", lambda: "tok")
        monkeypatch.setattr(_server, "free_port", lambda pid, *a, **k: freed.append(pid) or frees)
        return freed

    return _wire


def test_claim_port_free_port_needs_nothing(wire):
    freed = wire(command=None)

    assert claim_port(TAX).outcome == FREE
    assert freed == []


def test_claim_port_same_file_same_build_reuses(wire):
    freed = wire(command="ster serve tax.ttl", served=str(TAX.resolve()))

    claim = claim_port(TAX, confirm=lambda _q: pytest.fail("must not ask to reuse"))

    assert claim.outcome == REUSE
    assert claim.url.endswith(":8765") or claim.url.count(":") == 2
    assert freed == []


def test_claim_port_same_file_other_build_offers_replace(wire):
    freed = wire(command="ster serve tax.ttl", served=str(TAX.resolve()), build="0.0.1")
    questions: list[str] = []

    claim = claim_port(TAX, confirm=lambda q: questions.append(q) or True)

    assert claim.outcome == FREE
    assert freed == [321]
    assert "0.0.1" in questions[0]  # says why it is not reusable


def test_claim_port_other_file_asks_before_replacing(wire):
    freed = wire(command="ster serve other.ttl", served="/project/other.ttl")
    questions: list[str] = []

    claim = claim_port(TAX, confirm=lambda q: questions.append(q) or True)

    assert claim.outcome == FREE
    assert freed == [321]
    assert "other.ttl" in questions[0]


def test_claim_port_declined_replace_leaves_the_server_running(wire):
    freed = wire(command="ster serve other.ttl", served="/project/other.ttl")

    claim = claim_port(TAX, confirm=lambda _q: False)

    assert claim.outcome == BLOCKED
    assert "left running" in claim.message
    assert freed == []


def test_claim_port_without_confirm_replaces_silently(wire):
    """The TUI passes no confirm: a blocking prompt there once froze the UI."""
    freed = wire(command="ster serve other.ttl", served="/project/other.ttl")

    assert claim_port(TAX).outcome == FREE
    assert freed == [321]


def test_claim_port_failed_close_is_reported(wire):
    wire(command="ster serve other.ttl", served="/project/other.ttl", frees=False)

    claim = claim_port(TAX)

    assert claim.outcome == BLOCKED
    assert "couldn't stop" in claim.message


def test_claim_port_editor_holder_warns_and_never_kills(wire):
    freed = wire(command="/venv/bin/ster edit tax.ttl", served=str(TAX.resolve()))

    claim = claim_port(TAX, confirm=lambda _q: True)

    assert claim.outcome == BLOCKED
    assert "another ster session is open" in claim.message
    assert "close it first to release the port" in claim.message
    assert freed == []


def test_claim_port_foreign_holder_never_killed(wire):
    freed = wire(command="postgres -D /data")

    claim = claim_port(TAX, confirm=lambda _q: True)

    assert claim.outcome == BLOCKED
    assert "not ster" in claim.message
    assert freed == []


def test_claim_port_server_that_does_not_answer_is_left_alone(wire):
    """A `ster serve` command line whose server gives no session: do not guess."""
    freed = wire(command="ster serve tax.ttl", served=None)

    claim = claim_port(TAX)

    assert claim.outcome == BLOCKED
    assert freed == []


def test_claim_port_without_a_file_never_reuses(wire):
    """No file to compare against means no server can be said to show it."""
    wire(command="ster serve tax.ttl", served=str(TAX.resolve()))

    assert claim_port(None, confirm=lambda _q: True).outcome == FREE


# ── the probes ─────────────────────────────────────────────────────────────────


def test_server_build_reads_the_ster_version(monkeypatch):
    monkeypatch.setattr(_claim, "_get_json", lambda *a, **k: {"ster": "9.9", "version": 3})

    assert _claim.server_build("http://x", "t") == "9.9"


@pytest.mark.parametrize("body", [None, [], {"ster": 3}, {}])
def test_server_build_is_none_for_anything_else(monkeypatch, body):
    monkeypatch.setattr(_claim, "_get_json", lambda *a, **k: body)

    assert _claim.server_build("http://x", "t") is None


# ── holder_message: one next step per kind of holder ───────────────────────────


@pytest.mark.parametrize(
    ("command", "fragment"),
    [
        ("/venv/bin/ster edit tax.ttl", "Please close it first to release the port"),
        ("ster serve tax.ttl", "Close that process and reopen the file"),
        ("nginx: master", "not ster"),
    ],
)
def test_holder_message_names_the_next_step_for_each_kind(command, fragment):
    message = _server.holder_message(99, command, 8765)

    assert fragment in message
    assert "99" in message
    assert "8765" in message
