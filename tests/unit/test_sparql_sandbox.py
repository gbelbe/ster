"""The SPARQL sandbox: a query with a deadline runs in a child process that can be killed.

pyoxigraph cannot cancel a query, so these check the property that matters —
a runaway query comes back as a timeout instead of holding the caller — and
that ordinary queries answer exactly as the in-process path does.
"""

from __future__ import annotations

import time

from ster import mcp_context as mc
from ster import store
from ster.sparql_query import _sandbox, run_query_on_taxonomy

_CLASSES = "SELECT ?s WHERE { ?s a <http://www.w3.org/2002/07/owl#Class> } ORDER BY ?s"
# Four unrelated patterns over a few hundred triples: billions of combinations.
_RUNAWAY = "SELECT (COUNT(*) AS ?n) WHERE { ?a ?b ?c . ?d ?e ?f . ?g ?h ?i . ?j ?k ?l }"
_FEW = 5  # classes in a small graph
_MANY = 300  # classes in a graph big enough for _RUNAWAY to never finish
_GENEROUS_S = 30  # a deadline no ordinary query reaches
_SHORT_S = 0.5  # a deadline _RUNAWAY always reaches
_CONTROL_BACK_S = 10  # how soon the caller must get control back after _SHORT_S


def _tax(tmp_path, n: int, name: str = "t.ttl"):
    lines = ["@prefix owl: <http://www.w3.org/2002/07/owl#> ."]
    lines += [f"<https://example.org/c#C{i}> a owl:Class ." for i in range(n)]
    ttl = tmp_path / name
    ttl.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return store.load(ttl)


def _stop_worker() -> None:
    """Drop the warm worker, for a test that needs to start from none.

    The other tests do not need this: each compares worker states it created
    itself, so whatever an earlier test left running cannot change the outcome.
    """
    with _sandbox._LOCK:
        if _sandbox._worker is not None:
            _sandbox._worker.close()
        _sandbox._worker = None


def test_a_sandboxed_query_answers_like_the_in_process_one(tmp_path):
    tax = _tax(tmp_path, _FEW)

    sandboxed = run_query_on_taxonomy(tax, _CLASSES, timeout=_GENEROUS_S)
    in_process = run_query_on_taxonomy(tax, _CLASSES)

    assert sandboxed == in_process
    assert len(sandboxed.rows) == _FEW


def test_a_runaway_query_is_stopped_at_the_deadline(tmp_path):
    tax = _tax(tmp_path, _MANY)
    run_query_on_taxonomy(
        tax, _CLASSES, timeout=_GENEROUS_S
    )  # warm the worker: startup is not timed

    t0 = time.monotonic()
    result = run_query_on_taxonomy(tax, _RUNAWAY, timeout=_SHORT_S)
    elapsed = time.monotonic() - t0

    assert result.timed_out is True
    assert f"stopped after {_SHORT_S:g}s" in result.error
    assert elapsed < _CONTROL_BACK_S, "the caller must get control back, not wait for the query"


def test_the_next_query_after_a_timeout_still_answers(tmp_path):
    tax = _tax(tmp_path, _MANY)
    run_query_on_taxonomy(tax, _RUNAWAY, timeout=_SHORT_S)

    result = run_query_on_taxonomy(tax, _CLASSES, timeout=_GENEROUS_S)

    assert not result.error
    assert len(result.rows) == _MANY


def test_a_malformed_query_is_an_error_not_a_timeout(tmp_path):
    tax = _tax(tmp_path, _FEW)

    result = run_query_on_taxonomy(tax, "SELECT WHERE {", timeout=_GENEROUS_S)

    assert result.error.startswith("Query error")
    assert result.timed_out is False


def test_the_worker_is_reused_for_the_same_graph(tmp_path):
    tax = _tax(tmp_path, _FEW)
    run_query_on_taxonomy(tax, _CLASSES, timeout=_GENEROUS_S)
    first = _sandbox._worker.proc.pid

    run_query_on_taxonomy(tax, _CLASSES, timeout=_GENEROUS_S)

    assert _sandbox._worker.proc.pid == first


def test_a_changed_graph_gets_a_new_worker_that_sees_the_change(tmp_path):
    run_query_on_taxonomy(_tax(tmp_path, _FEW, "a.ttl"), _CLASSES, timeout=_GENEROUS_S)
    first = _sandbox._worker.proc.pid

    result = run_query_on_taxonomy(_tax(tmp_path, _FEW + 1, "b.ttl"), _CLASSES, timeout=_GENEROUS_S)

    assert _sandbox._worker.proc.pid != first
    assert len(result.rows) == _FEW + 1


def test_a_rebuilt_model_with_the_same_content_keeps_the_worker(tmp_path):
    run_query_on_taxonomy(_tax(tmp_path, _FEW, "a.ttl"), _CLASSES, timeout=_GENEROUS_S)
    first = _sandbox._worker.proc.pid

    run_query_on_taxonomy(_tax(tmp_path, _FEW, "b.ttl"), _CLASSES, timeout=_GENEROUS_S)

    assert _sandbox._worker.proc.pid == first


def test_run_sparql_reports_a_timeout_as_its_own_error(tmp_path):
    tax = _tax(tmp_path, _MANY)
    run_query_on_taxonomy(tax, _CLASSES, timeout=_GENEROUS_S)

    out = mc.run_sparql(tax, _RUNAWAY, timeout=_SHORT_S)

    assert out["error"] == "timeout"
    assert "LIMIT" in out["message"]


def test_the_rest_path_has_no_deadline_by_default(tmp_path):
    """sparql_payload without a timeout never starts a worker."""
    _stop_worker()

    mc.sparql_payload(_tax(tmp_path, _FEW), _CLASSES)

    assert _sandbox._worker is None
