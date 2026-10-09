"""A question waits for a ster that is still loading instead of being sent to an agent that cannot reach it."""

from __future__ import annotations

import unittest
from unittest import mock

from agent_app import server


class WaitUntilAnswering(unittest.TestCase):
    def test_returns_the_graph_once_ster_answers(self):
        answers = iter([None, None, {"fingerprint": "abc"}])
        with (
            mock.patch.object(server, "ster_graph", lambda force=False: next(answers)),
            mock.patch.object(server.time, "sleep", lambda _s: None),
        ):
            self.assertEqual(server.wait_until_answering(timeout=60), {"fingerprint": "abc"})

    def test_gives_up_when_ster_stays_silent(self):
        with mock.patch.object(server, "ster_graph", lambda force=False: None):
            self.assertIsNone(server.wait_until_answering(timeout=0))


if __name__ == "__main__":
    unittest.main()
