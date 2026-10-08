"""The page's full check of ster says it is a health check, in the namespace ster's own instructions use."""

from __future__ import annotations

import json
import unittest

from agent_app import runner
from helpers import FakeSter

AUTH = {"Authorization": "Bearer t"}
WITH_KEYS = 'Put "com.example/agent-question" in _meta.'
NAMESPACE = "com.example"


class Namespace(unittest.TestCase):  # noqa: V102
    def test_it_is_the_part_before_the_agent_keys(self):
        self.assertEqual(runner.meta_namespace(WITH_KEYS), NAMESPACE)
        self.assertEqual(runner.meta_namespace('"org.x/agent-session-id" and more'), "org.x")

    def test_instructions_without_such_keys_have_none(self):
        self.assertIsNone(runner.meta_namespace("plain instructions"))
        self.assertIsNone(runner.meta_namespace(""))
        self.assertIsNone(runner.meta_namespace(None))


class Check(unittest.TestCase):  # noqa: V102
    def overview_call(self, instructions):
        ster = FakeSter(instructions=instructions)
        self.addCleanup(ster.close)
        runner.check_ster(ster.url, AUTH)
        bodies = [json.loads(b) for m, p, _h, b in ster.log if m == "POST" and p == "/mcp"]
        return next(b for b in bodies if b["method"] == "tools/call")["params"]

    def test_the_check_marks_its_overview_call_untraced(self):
        self.assertEqual(self.overview_call(WITH_KEYS)["_meta"], {f"{NAMESPACE}/untraced": True})

    def test_a_ster_that_names_no_namespace_gets_no_mark(self):
        self.assertEqual(self.overview_call("plain instructions")["_meta"], {})


if __name__ == "__main__":
    unittest.main()
