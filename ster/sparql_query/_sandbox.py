"""Run a SPARQL query in a child process that a deadline can stop.

pyoxigraph cannot cancel a query: a runaway join keeps a core busy until it
finishes, however long that takes, and a thread cannot be interrupted either.
Agents write such queries by accident (an unbound triple pattern, a stray
cartesian product), so the MCP path runs them here, where a timeout ends the
process instead of the server waiting on it.

One worker is kept warm and reused while the graph stays the same: starting a
process and loading the graph cost far more than a typical query (a few ms),
so they are paid once per graph version, not once per query. A worker that
times out is killed; the next query starts a fresh one.
"""

from __future__ import annotations

import hashlib
import multiprocessing as mp
import sys
import threading
from multiprocessing import resource_tracker
from typing import Any, Final

from ._caching import _trace
from ._types import QueryResult

# spawn, not fork: forking a threaded server can copy a lock held by another
# thread into a child that will never release it, and macOS defaults to spawn.
_CTX: Final = mp.get_context("spawn")
# Loading the graph is not the query's fault, so it gets its own, generous limit.
_STARTUP_TIMEOUT_S: Final = 60.0
_READY: Final = "ready"


def _serve(conn: Any, data: bytes) -> None:  # pragma: no cover - runs in the child
    """Child process: load the graph once, then answer queries until the pipe closes."""
    import io  # noqa: PLC0415

    import pyoxigraph as ox  # noqa: PLC0415

    from ._execute import _detect_query_type, _oxigraph_result  # noqa: PLC0415

    store = ox.Store()
    store.bulk_load(io.BytesIO(data), format=ox.RdfFormat.N_QUADS)
    conn.send(_READY)
    while True:
        try:
            query = conn.recv()
        except EOFError:
            return
        try:
            result = _oxigraph_result(store.query(query), _detect_query_type(query))
        # A malformed query is the caller's, not a worker fault: it comes back as
        # a QueryResult carrying the message, exactly as the in-process path does.
        except Exception as exc:  # noqa: BLE001
            result = QueryResult(columns=[], rows=[], error=f"Query error: {exc}")
        conn.send(result)


def _has_descriptor(stream: Any) -> bool:
    """Whether *stream* stands on a real file descriptor."""
    try:
        return bool(stream.fileno() >= 0)
    except (AttributeError, OSError, ValueError):
        return False


def _start_resource_tracker() -> None:
    """Make sure multiprocessing's resource tracker is running, whatever ``sys.stderr`` is.

    Starting the tracker hands ``sys.stderr``'s file descriptor to it. A terminal UI (Textual) replaces ``sys.stderr``
    with a capture object whose ``fileno()`` is -1, and the spawn then fails with "bad value(s) in fds_to_keep":
    every query with a deadline failed with it for as long as the server lived inside the TUI. The process's own
    stderr stands in for the moment it takes; once the tracker runs it is not started again, so this happens once.
    """
    shown = sys.stderr
    own = sys.__stderr__
    if not _has_descriptor(shown) and _has_descriptor(own):
        sys.stderr = own
    try:
        resource_tracker.ensure_running()
    finally:
        sys.stderr = shown


class _Worker:
    """One child process holding one version of the graph."""

    def __init__(self, store: Any, data: bytes, digest: str) -> None:
        _start_resource_tracker()
        self.store = store  # held, so its identity cannot be reused by another graph
        self.digest = digest
        self.conn, child = _CTX.Pipe()
        self.proc = _CTX.Process(target=_serve, args=(child, data), daemon=True)
        self.proc.start()
        child.close()
        if not self.conn.poll(_STARTUP_TIMEOUT_S) or self.conn.recv() != _READY:
            self.close()
            raise RuntimeError("SPARQL worker did not start")

    def ask(self, sparql: str, timeout: float) -> QueryResult | None:
        """The answer, or None when *timeout* seconds passed first (worker then dead)."""
        self.conn.send(sparql)
        if self.conn.poll(timeout):
            answer: QueryResult = self.conn.recv()
            return answer
        self.close()
        return None

    def alive(self) -> bool:
        return self.proc.is_alive()

    def close(self) -> None:
        self.proc.kill()
        self.proc.join(timeout=5)
        self.conn.close()


_LOCK: Final = threading.Lock()
_worker: _Worker | None = None


def _dump(store: Any) -> bytes:
    import pyoxigraph as ox  # noqa: PLC0415

    data: bytes = store.dump(format=ox.RdfFormat.N_QUADS)
    return data


def _worker_for(store: Any) -> _Worker:
    """The warm worker when it already holds this graph, else a new one."""
    # One process-wide worker, guarded by _LOCK.
    global _worker  # noqa: PLW0603
    worker = _worker
    if worker is None or not worker.alive() or worker.store is not store:
        data = _dump(store)
        digest = hashlib.sha256(data).hexdigest()
        # A rebuilt model with the same content (a reload, an edit undone) keeps it.
        if worker is not None and worker.alive() and worker.digest == digest:
            worker.store = store
        else:
            if worker is not None:
                worker.close()
            _trace(f"sparql sandbox: starting a worker ({len(data)} bytes of N-Quads)")
            worker = _Worker(store, data, digest)
            _worker = worker
    return worker


def timeout_message(timeout: float) -> str:
    return (
        f"Query stopped after {timeout:g}s. Narrow it: bind subjects or predicates, "
        "add FILTERs or a LIMIT, and avoid joining unrelated patterns (a cartesian "
        "product) or unbounded property paths (*, +) over the whole graph."
    )


def run_with_timeout(store: Any, sparql: str, timeout: float) -> QueryResult:
    """Answer *sparql* against *store* in the worker, giving up after *timeout* seconds."""
    # Same process-wide worker as _worker_for.
    global _worker  # noqa: PLW0603
    with _LOCK:
        worker = _worker_for(store)
        result = worker.ask(sparql, timeout)
        if result is None:
            _worker = None
            return QueryResult(columns=[], rows=[], error=timeout_message(timeout), timed_out=True)
        return result
