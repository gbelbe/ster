"""A turn that failed is reported to ster with its error as the answer, so the history shows what went wrong."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from agent_app import server

BOOM = "ValueError: bad value(s) in fds_to_keep"
CREATED = 201
ANSWER, ERROR, STATUS, FAILED, DONE = "answer", "error", "status", "error", "completed"


def reported(turn: dict) -> dict:
    """The body the page sends to ster for *turn*."""
    sent: list[dict] = []

    def fetch(_method, _path, body, _headers):
        sent.append(json.loads(body))
        return CREATED, b"", "application/json"

    with (
        mock.patch.object(server, "ster_fetch", fetch),
        mock.patch.object(server, "ster_token", lambda: "token"),
    ):
        server.report_answer(
            server.Run({"id": "conv"}, {"id": "turn", "prompt": "q", "events": [], **turn})
        )
    return sent[0]


class ErrorAnswer(unittest.TestCase):  # noqa: V102
    def test_a_turn_that_failed_has_its_error_as_the_answer(self):
        body = reported({STATUS: FAILED, ERROR: BOOM})
        self.assertEqual((body[ANSWER], body[ERROR], body[STATUS]), (BOOM, BOOM, FAILED))

    def test_a_real_answer_is_kept_even_when_there_was_an_error_on_the_way(self):
        body = reported({STATUS: DONE, ANSWER: "42", ERROR: BOOM})
        self.assertEqual((body[ANSWER], body[ERROR]), ("42", BOOM))

    def test_a_turn_without_either_reports_neither(self):
        body = reported({STATUS: DONE})
        self.assertNotIn(ANSWER, body)
        self.assertNotIn(ERROR, body)


if __name__ == "__main__":
    unittest.main()
