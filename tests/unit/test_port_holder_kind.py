"""ster closes what is its to close, and leaves the rest alone.

Pressing `g` reclaims the live-server port by sending SIGTERM to whatever holds
it. The only guard was against our *own* PID, so a second ster session opened in
another terminal would kill the first one — mid-render, with mouse tracking
still on, which fills that terminal with escape sequences like `35;80;20`. The
person who lost their session is not the one who gets the message.

`_server.py` already documented that symptom, as the reason for the self-PID
guard. The guard was simply too narrow.

An unrelated process on the configured port was worse: ster would SIGTERM
someone else's server without ever asking what it was.
"""

from __future__ import annotations

import pytest

from ster.viz_vowl import EDITOR, FOREIGN, SERVER, holder_kind


@pytest.mark.parametrize(
    "command",
    [
        "uv run --project /repo ster serve onto.ttl --port 8899",
        "/repo/.venv/bin/python /repo/.venv/bin/ster serve onto.ttl",
        "ster serve a.ttl -x b.ttl",
    ],
)
def test_a_serve_is_a_view_and_may_be_replaced(command):
    assert holder_kind(command) == SERVER


@pytest.mark.parametrize(
    "command",
    ["/Users/me/.local/bin/ster", "ster onto.ttl", "/repo/.venv/bin/ster ontology/x.ttl"],
)
def test_an_interactive_session_is_someone_working(command):
    assert holder_kind(command) == EDITOR


@pytest.mark.parametrize(
    "command",
    [
        "/usr/bin/python3 -m http.server 8765",
        "node raster-tool.js",
        "/opt/homebrew/bin/postgres -D /data",
        "semanticdiff a.ttl b.ttl",
    ],
)
def test_anything_else_was_never_ours_to_kill(command):
    assert holder_kind(command) == FOREIGN


def test_a_word_merely_containing_ster_is_not_ster():
    """`raster`, `semanticdiff-ster` and friends: the match needs a path
    separator, whitespace, or the start of the line in front of it."""
    assert holder_kind("node raster-tool.js") == FOREIGN
    assert holder_kind("/usr/bin/booster --port 8765") == FOREIGN


def test_the_reclaim_only_fires_for_a_server():
    """The behavioural half: anything that is not a `ster serve` is left running,
    and the graph reports that it could not open rather than touching a process
    that was never ster's to close."""
    import inspect

    from ster.tui.app import _graph

    source = inspect.getsource(_graph._GraphMixin._reclaim_port_and_open)

    assert "if kind != viz_vowl.SERVER:" in source
    assert source.index("if kind != viz_vowl.SERVER:") < source.index("viz_vowl.free_port(pid)")
