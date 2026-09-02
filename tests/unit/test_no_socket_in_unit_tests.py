"""The TUI must not open a socket when a unit test opens a file.

Opening a file makes OntologyApp start the MCP context server, which binds the
configured port — 8765 by default. Under ``-n auto`` that is a race between
workers: the loser gets "address already in use", its app never reaches ready,
and the failure surfaces somewhere unrelated as a missing widget. A tree that
was byte-identical to a green one went red in CI on exactly this.

Asserted by identity rather than by probing the port. A probe cannot fail
reliably — uvicorn comes up on a daemon thread, so the socket may not be open
yet when the probe runs — and a timing-dependent test guarding a fix for
timing-dependent failures would be worth less than nothing.
"""

from __future__ import annotations

from ster import api_server


def test_the_background_server_is_stubbed_out_by_default() -> None:
    """The autouse guard in tests/conftest.py, asserted rather than assumed.

    Identity, not behaviour: calling it and seeing False proves nothing, because
    the real function also returns False when it cannot bind — which is exactly
    what happens in the race this guards against.
    """
    assert api_server.start_background.__module__ != "ster.api_server"


def test_the_servers_own_tests_still_get_the_real_thing() -> None:
    """The guard must not quietly gut the tests whose subject is the server."""
    from tests.conftest import _SERVER_OWN_TESTS

    assert "tests.unit.test_server_startup" in _SERVER_OWN_TESTS
