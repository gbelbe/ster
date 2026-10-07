"""History rebuilt from ster's traces: what the page has no copy of."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_app import history
from helpers import write_trace
from test_server import BridgeCase


def run(folder: Path, run_id: str, at: str, tool="run_sparql", args=None, **meta):
    """A run journal as ster writes it, with the metadata an agent's call carries."""
    first = {
        "event": "run_started",
        "run_id": run_id,
        "sequence": 1,
        "timestamp": at,
        "payload": {
            "tool": tool,
            "question": json.dumps({"tool": tool, "arguments": args or {}}),
            **meta,
        },
    }
    last = {
        "event": "run_completed",
        "run_id": run_id,
        "sequence": 2,
        "timestamp": at,
        "payload": {},
    }
    (folder / f"{run_id}.jsonl").write_text(json.dumps(first) + "\n" + json.dumps(last) + "\n")


def answer(folder: Path, aid: str, **fields):
    (folder / "answers").mkdir(exist_ok=True)
    body = {"id": aid, "question": "how many?", "answer": "Two.", "status": "completed", **fields}
    (folder / "answers" / f"{aid}.json").write_text(json.dumps(body))


class Rebuilding(unittest.TestCase):  # noqa: V102
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_an_answer_becomes_a_turn_of_its_conversation_with_its_runs(self):
        run(self.dir, "run-a", "2026-01-01T10:00:00Z", args={"query": "SELECT 1"})
        run(self.dir, "run-b", "2026-01-01T10:00:05Z")
        answer(
            self.dir,
            "turn1",
            conversation_id="abcdef012345",
            run_ids=["run-b", "run-a"],
            started="2026-01-01T09:59:59Z",
            resume_session_id="sess-1",
            graph_fingerprint="ff00",
            token_usage={"input": 3, "output": 4},
            cost_usd=0.5,
        )
        [conv] = history.conversations(self.dir)
        self.assertEqual(
            (conv["id"], conv["title"], conv["session_id"]), ("abcdef012345", "how many?", "sess-1")
        )
        [turn] = conv["turns"]
        self.assertEqual((turn["answer"], turn["graph"], turn["cost_usd"]), ("Two.", "ff00", 0.5))
        self.assertEqual(turn["run_ids"], ["run-a", "run-b"])  # in the order they ran

    def test_the_events_are_a_step_and_a_tool_call_per_run_then_the_answer(self):
        run(self.dir, "run-a", "2026-01-01T10:00:00Z", args={"query": "SELECT 1"})
        answer(
            self.dir,
            "turn1",
            conversation_id="abcdef012345",
            run_ids=["run-a"],
            started="2026-01-01T10:00:00Z",
        )
        [conv] = history.conversations(self.dir)
        full = history.with_events(conv, lambda rid: {"run_id": rid, "steps": []})
        kinds = [e["e"] for e in full["turns"][0]["events"]]
        self.assertEqual(kinds, ["turn_start", "step_start", "tool_call", "trace", "done"])
        call = next(e for e in full["turns"][0]["events"] if e["e"] == "tool_call")
        self.assertEqual(
            (call["id"], call["name"], call["input"]),
            ("run-a", "run_sparql", {"query": "SELECT 1"}),
        )
        self.assertEqual(full["turns"][0]["events"][-1]["answer"], "Two.")
        self.assertNotIn("_runs", full["turns"][0])

    def test_a_session_an_agent_ran_without_the_page_is_grouped_by_its_session_id(self):
        run(
            self.dir,
            "run-a",
            "2026-01-01T10:00:00Z",
            agent_session_id="ext-1",
            agent_question="Which stores?",
        )
        run(self.dir, "run-b", "2026-01-01T10:01:00Z", agent_session_id="ext-1")
        run(
            self.dir, "run-c", "2026-01-01T11:00:00Z"
        )  # no session id: not attributable, so left out
        [conv] = history.conversations(self.dir)
        self.assertEqual((conv["title"], len(conv["turns"][0]["run_ids"])), ("Which stores?", 2))
        self.assertIsNone(conv["turns"][0]["answer"])

    def test_runs_that_an_answer_rests_on_are_not_listed_again_as_a_session(self):
        run(self.dir, "run-a", "2026-01-01T10:00:00Z", agent_session_id="ext-1")
        answer(self.dir, "turn1", conversation_id="abcdef012345", run_ids=["run-a"])
        self.assertEqual(len(history.conversations(self.dir)), 1)

    def test_conversations_are_read_only_and_say_where_they_came_from(self):
        answer(self.dir, "turn1", conversation_id="abcdef012345")
        [conv] = history.conversations(self.dir)
        self.assertEqual((conv["readonly"], conv["source"]), (True, "traces"))

    def test_a_folder_with_nothing_in_it_has_no_history(self):
        self.assertEqual(history.conversations(self.dir / "missing"), [])

    def test_a_damaged_file_is_skipped(self):
        (self.dir / "run-bad.jsonl").write_text("{nope")
        answer(self.dir, "turn1", conversation_id="abcdef012345")
        (self.dir / "answers" / "bad.json").write_text("{nope")
        self.assertEqual(len(history.conversations(self.dir)), 1)


class TheQuestionOfACall(BridgeCase):  # noqa: V102
    def test_the_plain_language_question_ster_recorded_comes_with_the_trace(self):
        bridge = self.start()
        run(bridge.traces, "run-q", "2026-01-01T10:00:00Z", agent_question="How many open epics?")
        self.assertEqual(
            bridge.server.read_trace("run-q")["agent_question"], "How many open epics?"
        )

    def test_a_trace_without_one_says_none(self):
        bridge = self.start()
        run(bridge.traces, "run-n", "2026-01-01T10:00:00Z")
        self.assertIsNone(bridge.server.read_trace("run-n")["agent_question"])


class InThePage(BridgeCase):  # noqa: V102
    def start_with_traces(self):
        bridge = self.start()
        run(bridge.traces, "run-a", "2026-01-01T10:00:00Z", args={"query": "SELECT 1"})
        write_trace(bridge.traces, "run-a", "SELECT 1", ["n"], [["2"]])  # ster's own rows for it
        answer(
            bridge.traces,
            "turn1",
            conversation_id="abcdef012345",
            run_ids=["run-a"],
            started="2026-01-01T10:00:00Z",
        )
        return bridge

    def test_the_list_shows_what_only_the_traces_remember(self):
        rows = self.start_with_traces().json("/api/conversations")[1]
        self.assertEqual(
            [(r["id"], r["readonly"], r["prompts"]) for r in rows],
            [("abcdef012345", True, ["how many?"])],
        )

    def test_the_pages_own_copy_wins(self):
        bridge = self.start_with_traces()
        self.seed(bridge, "abcdef012345", [self.turn()], title="mine")
        [row] = bridge.json("/api/conversations")[1]
        self.assertEqual((row["title"], row["readonly"]), ("mine", False))

    def test_opening_one_gives_its_events_with_ster_s_rows(self):
        conv = self.start_with_traces().json("/api/conversations/abcdef012345")[1]
        events = conv["turns"][0]["events"]
        trace = next(e for e in events if e["e"] == "trace")
        self.assertEqual(trace["steps"][0]["rows"], [["2"]])
        self.assertTrue(conv["readonly"])

    def test_an_unknown_one_is_a_404(self):
        self.assertEqual(self.start().call("/api/conversations/aaaaaaaaaaaa")[0], 404)

    def test_a_conversation_kept_by_ster_cannot_be_deleted_from_here(self):
        bridge = self.start_with_traces()
        self.assertEqual(bridge.call("/api/conversations/abcdef012345", method="DELETE")[0], 409)


if __name__ == "__main__":
    unittest.main()
