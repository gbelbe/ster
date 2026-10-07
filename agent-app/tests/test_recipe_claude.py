"""The Claude recipe's stream rules turn a recorded Claude Code stream into neutral events. The fixture is a real run, scrubbed."""

from __future__ import annotations

import functools
import json
import unittest
from pathlib import Path

from agent_app import runner
from helpers import WEB, translate_recorded

RECIPE = next(a for a in runner.load_recipes(WEB / "recipes") if a.source == "claude-code.json")
FIXTURE = Path(__file__).parent / "fixtures" / "claude_stream.jsonl"


translate = functools.partial(translate_recorded, RECIPE)


class RecordedRun(unittest.TestCase):  # noqa: V102
    @classmethod
    def setUpClass(cls):
        cls.events = translate(FIXTURE.read_text())

    def kinds(self, kind):
        return [e for e in self.events if e["e"] == kind]

    def test_the_session_comes_first_and_enables_follow_ups(self):
        self.assertEqual(self.events[0]["e"], "session")
        self.assertTrue(self.events[0]["session_id"])

    def test_each_model_call_is_a_step_with_reported_usage(self):
        steps = [e["step"] for e in self.kinds("step_start")]
        self.assertEqual(len(steps), 2)
        used = {e["step"] for e in self.kinds("usage")}
        self.assertEqual(used, set(steps))

    def test_usage_carries_only_numbers_the_stream_gave(self):
        for u in self.kinds("usage"):
            self.assertTrue(set(u) <= {"e", "step", "input", "output", "cache_read", "cache_write"})
            self.assertTrue(all(isinstance(v, int) for k, v in u.items() if k not in ("e", "step")))

    def test_the_tool_call_has_its_arguments_assembled_from_fragments(self):
        [call] = self.kinds("tool_call")
        self.assertEqual(runner.ster_tool(call["name"]), "get_overview")
        self.assertIsInstance(call["input"], dict)

    def test_every_tool_call_gets_its_result_with_ster_text_unmodified(self):
        [call], [res] = self.kinds("tool_call"), self.kinds("tool_result")
        self.assertEqual(res["id"], call["id"])
        self.assertIn("ontology_uri", res["text"])
        self.assertFalse(res["is_error"])

    def test_the_final_event_has_answer_cost_and_totals(self):
        [done] = self.kinds("done")
        self.assertEqual(done["status"], "completed")
        self.assertTrue(done["answer"])
        self.assertGreater(done["cost_usd"], 0)
        self.assertEqual(set(done["usage"]), {"input", "output", "cache_read", "cache_write"})

    def test_streamed_text_adds_up_to_the_answer(self):
        self.assertEqual(
            "".join(e["text"] for e in self.kinds("text_delta")).strip(),
            self.kinds("done")[0]["answer"].strip(),
        )

    def test_the_whole_run_satisfies_the_bridge_contract(self):
        events = [{"t": 0, **e} for e in self.events]
        for e in events:
            if e["e"] == "tool_call":
                e["name"] = runner.ster_tool(e["name"])
        c = runner.contract(events)
        self.assertTrue(
            c["observed"]["stream_steps"]
            and c["observed"]["token_usage"]
            and c["observed"]["cost"]
            and c["observed"]["resume"]
        )


class Robustness(unittest.TestCase):  # noqa: V102
    def test_garbage_and_unknown_lines_are_ignored(self):
        self.assertEqual(
            translate("not json\n{}\n" + json.dumps({"type": "something_new"}) + "\n"), []
        )

    def test_an_error_result_is_reported_as_an_error(self):
        [done] = translate(
            json.dumps(
                {
                    "type": "result",
                    "is_error": True,
                    "result": "boom",
                    "usage": {"output_tokens": 3},
                }
            )
        )
        self.assertEqual(
            (done["status"], done["answer"], done["usage"]), ("error", "boom", {"output": 3})
        )

    def test_tool_arguments_that_are_not_json_are_kept_raw(self):
        lines = [
            {"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m"}}},
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "tool_use", "id": "c", "name": "t"},
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": "{oops"},
                },
            },
            {"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}},
        ]
        call = next(
            e for e in translate("\n".join(map(json.dumps, lines))) if e["e"] == "tool_call"
        )
        self.assertEqual(call["input"], {"raw": "{oops"})

    def test_a_list_tool_result_is_flattened_to_text(self):
        line = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "c",
                        "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
                    }
                ]
            },
        }
        [res] = translate(json.dumps(line))
        self.assertEqual((res["id"], res["text"]), ("c", "ab"))

    def test_a_count_the_stream_omits_is_left_out_not_zeroed(self):
        line = {
            "type": "stream_event",
            "event": {"type": "message_delta", "usage": {"output_tokens": 7}},
        }
        [u] = translate(json.dumps(line))
        self.assertEqual({k: v for k, v in u.items() if k != "step"}, {"e": "usage", "output": 7})


if __name__ == "__main__":
    unittest.main()
