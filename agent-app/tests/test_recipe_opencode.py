"""The OpenCode recipe's rules turn a recorded OpenCode run (`opencode run --format json`) into neutral events.
The fixture is a real run against a local model with ster as its only tool, scrubbed."""

from __future__ import annotations

import functools
import json
import unittest
from pathlib import Path

from agent_app import runner
from helpers import WEB, translate_recorded

RECIPE = next(a for a in runner.load_recipes(WEB / "recipes") if a.source == "opencode.json")
FIXTURE = Path(__file__).parent / "fixtures" / "opencode_stream.jsonl"


translate = functools.partial(translate_recorded, RECIPE)


class RecordedRun(unittest.TestCase):  # noqa: V102
    @classmethod
    def setUpClass(cls):
        cls.events = translate(FIXTURE.read_text())

    def kinds(self, kind):
        return [e for e in self.events if e["e"] == kind]

    def test_every_line_says_which_session_it_belongs_to(self):
        sessions = {e["session_id"] for e in self.kinds("session")}
        self.assertEqual(len(sessions), 1)
        self.assertTrue(next(iter(sessions)).startswith("ses_"))

    def test_each_model_call_is_a_step_with_its_own_usage(self):
        steps = [e["step"] for e in self.kinds("step_start")]
        self.assertEqual(len(steps), 2)
        self.assertEqual([e["step"] for e in self.kinds("usage")], steps)

    def test_usage_is_in_the_neutral_names(self):
        for u in self.kinds("usage"):
            self.assertEqual(set(u), {"e", "step", "input", "output", "cache_read", "cache_write"})
            self.assertTrue(all(isinstance(v, int) for k, v in u.items() if k not in ("e", "step")))

    def test_a_tool_use_line_is_both_the_call_and_its_result(self):
        [call], [res] = self.kinds("tool_call"), self.kinds("tool_result")
        self.assertEqual(res["id"], call["id"])
        self.assertEqual(
            runner.ster_tool(call["name"]), "get_overview"
        )  # "ster_" prefix is this agent's way of naming it
        self.assertIn("ontology_uri", res["text"])  # ster's reply, unmodified
        self.assertFalse(res["is_error"])

    def test_the_calls_belong_to_the_step_that_made_them(self):
        [call] = self.kinds("tool_call")
        self.assertEqual(call["step"], self.kinds("step_start")[0]["step"])

    def test_the_final_text_belongs_to_the_last_step(self):
        [text] = self.kinds("text_delta")
        self.assertEqual(text["step"], self.kinds("step_start")[-1]["step"])
        self.assertIn("Adeo retail geography", text["text"])

    def test_this_agent_has_no_final_event_and_costs_are_not_reported(self):
        self.assertEqual(self.kinds("done"), [])
        self.assertFalse(any("cost_usd" in e for e in self.events))


class Robustness(unittest.TestCase):  # noqa: V102
    def test_a_failed_tool_call_is_an_error_result(self):
        line = {
            "type": "tool_use",
            "part": {
                "callID": "c",
                "tool": "ster_run_sparql",
                "state": {"status": "error", "input": {"query": "x"}, "error": "bad query"},
            },
        }
        res = [e for e in translate(json.dumps(line)) if e["e"] == "tool_result"][0]
        self.assertEqual((res["text"], res["is_error"]), ("bad query", True))

    def test_lines_of_a_kind_it_does_not_know_are_ignored(self):
        self.assertEqual(
            translate(json.dumps({"type": "something_new", "part": {}}) + "\nnot json"), []
        )


if __name__ == "__main__":
    unittest.main()
