"""A run's journal folded into the steps the page draws: a failed step says why instead of showing nothing."""

from __future__ import annotations

import json
import unittest

from agent_app import trace_steps

RUN, FILE, STEP = "run-1", ".ster/query-traces/run-1.jsonl", "raw-sparql"
QUERY = "SELECT * WHERE { ?s ?p ?o }"
STATUS, DONE, FAILED, STEPS, MESSAGE, CODE = (
    "status",
    "completed",
    "failed",
    "steps",
    "error_message",
    "error_code",
)
STEP_FAILED, QUERY_FAILED, FAILURE, GENERATED = (
    "step_failed",
    "query_generated",
    "failure",
    "query_generated",
)
BOOM = "ValueError: boom"


def line(event: str, **payload) -> str:
    entry = {"event": event, "payload": payload}
    if event.startswith("step") or event == GENERATED:
        entry["step_id"] = STEP
    return json.dumps(entry)


def fold(*lines: str) -> dict:
    return trace_steps.fold(list(lines), RUN, FILE)


def only_step(*lines: str) -> dict:
    [step] = fold(*lines)[STEPS]
    return step


class Completed(unittest.TestCase):  # noqa: V102
    def test_a_completed_step_has_its_query_rows_and_timing(self):
        info = fold(
            line("run_started", query_type="raw_sparql", agent_question="how many?"),
            line("step_planned", step_kind="raw_sparql_execution", natural_language="Run it"),
            line(GENERATED, query=QUERY),
            line(
                "step_completed",
                status=DONE,
                columns=["n"],
                result_rows=[["3"]],
                row_count=1,
                duration_ms=2.5,
            ),
        )
        [step] = info[STEPS]
        self.assertEqual((info["run_id"], info["file"]), (RUN, FILE))
        self.assertEqual((info["query_type"], info["agent_question"]), ("raw_sparql", "how many?"))
        self.assertEqual(
            (step["query"], step["columns"], step["rows"], step["row_count"]),
            (QUERY, ["n"], [["3"]], 1),
        )
        self.assertEqual(
            (step[STATUS], step["duration_ms"], step["kind"], step["goal"]),
            (DONE, 2.5, "raw_sparql_execution", "Run it"),
        )

    def test_the_rows_kept_for_the_page_are_capped(self):
        rows = [[str(n)] for n in range(trace_steps.MAX_ROWS + 20)]
        step = only_step(
            line(
                "step_completed", status=DONE, columns=["n"], result_rows=rows, row_count=len(rows)
            )
        )
        self.assertEqual(len(step["rows"]), trace_steps.MAX_ROWS)
        self.assertEqual(step["row_count"], trace_steps.MAX_ROWS + 20)


class Failed(unittest.TestCase):  # noqa: V102
    def test_a_failed_step_keeps_why_it_failed_and_what_was_asked(self):
        step = only_step(
            line(GENERATED, query=QUERY),
            line(
                STEP_FAILED,
                status=FAILED,
                error_code="query_failed",
                error_message=BOOM,
                error_type="ValueError",
                traceback="Traceback…",
                duration_ms=1.5,
            ),
        )
        self.assertEqual(step["query"], QUERY)
        self.assertEqual((step[STATUS], step[CODE], step[MESSAGE]), (FAILED, "query_failed", BOOM))
        self.assertEqual(
            (step["error_type"], step["traceback"], step["duration_ms"]),
            ("ValueError", "Traceback…", 1.5),
        )

    def test_an_older_failure_that_only_said_error_is_still_read(self):
        self.assertEqual(
            only_step(line(STEP_FAILED, status=FAILED, error="the old field"))[MESSAGE],
            "the old field",
        )

    def test_a_failed_step_without_a_status_is_failed(self):
        self.assertEqual(only_step(line(STEP_FAILED, error_code="read_only"))[STATUS], FAILED)

    def test_a_failed_run_says_why_on_the_run_too(self):
        info = fold(
            line(
                "run_failed",
                status=FAILED,
                error_code="timeout",
                error_message="Query stopped after 10s.",
            )
        )
        self.assertEqual(
            (info[FAILURE][CODE], info[FAILURE][MESSAGE]), ("timeout", "Query stopped after 10s.")
        )

    def test_a_run_that_worked_has_no_failure(self):
        self.assertNotIn(FAILURE, fold(line("run_completed", status=DONE)))

    def test_a_run_nothing_was_recorded_for_has_no_steps(self):
        self.assertEqual(fold()[STEPS], [])


if __name__ == "__main__":
    unittest.main()
