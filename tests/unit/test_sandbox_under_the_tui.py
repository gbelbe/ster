"""The query sandbox starts its child process even when sys.stderr has no file descriptor, as in the TUI.

Textual replaces sys.stderr with a capture object whose fileno() is -1. multiprocessing hands sys.stderr's descriptor to
its resource tracker when it starts one, and the spawn failed with "bad value(s) in fds_to_keep": every MCP query with
a deadline failed for as long as the server lived inside the TUI.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from ster.sparql_query import _execute, _sandbox
from ster.sparql_query._types import QueryResult

BROKEN = -1
CHILD = textwrap.dedent(
    """
    import sys

    class Capture:  # what Textual puts in place of sys.stderr
        def fileno(self):
            return -1
        def write(self, text):
            return len(text)
        def flush(self):
            pass

    if __name__ == "__main__":
        sys.stderr = Capture()
        from ster.sparql_query import _sandbox
        _sandbox._start_resource_tracker()
        worker = _sandbox._Worker(object(), b"", "digest")
        print("started", worker.alive(), file=sys.__stdout__)
        worker.close()
    """
)


class _Stream:
    def __init__(self, fileno):
        self._fileno = fileno

    def fileno(self):
        if isinstance(self._fileno, Exception):
            raise self._fileno
        return self._fileno


def test_a_real_stream_has_a_descriptor():
    assert _sandbox._has_descriptor(sys.__stderr__) is True


@pytest.mark.parametrize(
    "stream",
    [_Stream(BROKEN), _Stream(OSError("closed")), _Stream(ValueError("detached")), object(), None],
)
def test_a_stream_without_a_usable_descriptor_has_none(stream):
    assert _sandbox._has_descriptor(stream) is False


def _tracker_sees(monkeypatch, shown):
    """What sys.stderr is while the tracker is being started."""
    seen = []
    monkeypatch.setattr(sys, "stderr", shown)
    monkeypatch.setattr(
        _sandbox.resource_tracker, "ensure_running", lambda: seen.append(sys.stderr)
    )
    _sandbox._start_resource_tracker()
    return seen[0]


def test_the_tracker_is_started_with_the_processs_own_stderr_when_the_shown_one_is_unusable(
    monkeypatch,
):
    assert _tracker_sees(monkeypatch, _Stream(BROKEN)) is sys.__stderr__


def test_a_stderr_that_works_is_left_in_place_for_the_tracker(monkeypatch):
    shown = _Stream(2)
    assert _tracker_sees(monkeypatch, shown) is shown


def test_the_shown_stderr_is_put_back_afterwards(monkeypatch):
    shown = _Stream(BROKEN)
    _tracker_sees(monkeypatch, shown)
    assert sys.stderr is shown


def test_the_shown_stderr_is_put_back_even_when_the_tracker_fails(monkeypatch):
    shown = _Stream(BROKEN)
    monkeypatch.setattr(sys, "stderr", shown)

    def broken():
        raise OSError("no tracker")

    monkeypatch.setattr(_sandbox.resource_tracker, "ensure_running", broken)
    with pytest.raises(OSError, match="no tracker"):
        _sandbox._start_resource_tracker()
    assert sys.stderr is shown


def test_a_worker_starts_in_a_process_whose_stderr_is_the_tuis_capture():
    """The real thing, in a process of its own so that no tracker is running yet."""
    pytest.importorskip("pyoxigraph")
    done = subprocess.run(
        [sys.executable, "-c", CHILD], capture_output=True, text=True, timeout=120, check=False
    )
    assert "bad value" not in done.stderr
    assert done.stdout.strip() == "started True", done.stderr[-800:]


def test_a_spawn_the_platform_refuses_is_answered_without_a_deadline(monkeypatch, tmp_path):
    from ster import store

    source = tmp_path / "o.ttl"
    source.write_text('@prefix : <https://example.org/o#> .\n:a :p "x" .\n', encoding="utf-8")
    taxonomy = store.load(source)

    def refused(*_a):
        raise ValueError("bad value(s) in fds_to_keep")

    monkeypatch.setattr(_sandbox, "run_with_timeout", refused)
    result = _execute.run_query_on_taxonomy(taxonomy, "ASK { ?s ?p ?o }", timeout=5)
    assert isinstance(result, QueryResult)
    assert not result.error
