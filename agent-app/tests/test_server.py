"""server.py end to end: a real run of fake agents against a fake ster, with all state in a temp folder."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_app import runner
from fastapi import HTTPException
from helpers import Bridge, FakeSter, agent_script

HERE = Path(__file__).parent
PRELUDE = f"import sys; sys.path.insert(0, {str(HERE)!r}); from helpers import write_trace\n"
ROWS = [["https://x.org/#a", "3"], ["https://x.org/#b", "2"]]


def custom(script, *args, output="text", **kw):
    return runner.Agent(
        label="fake",
        binary=sys.executable,
        command=[sys.executable, script, *args],
        stdin="none",
        output=output,
        **kw,
    )


class BridgeCase(unittest.TestCase):
    def setUp(self):
        self.ster = FakeSter()
        self.scripts = Path(tempfile.mkdtemp())
        self.bridges = []

    def tearDown(self):
        for b in self.bridges:
            b.close()
        self.ster.close()

    def start(self, agent=None, recipes=None):
        b = Bridge(self.ster, custom=agent, recipes=recipes)
        self.bridges.append(b)
        return b

    def seed(self, bridge, cid, turns, title="seeded"):
        (bridge.store / f"{cid}.json").write_text(
            json.dumps(
                {
                    "id": cid,
                    "title": title,
                    "created": 1.0,
                    "updated": 2.0,
                    "session_id": None,
                    "turns": turns,
                }
            )
        )

    def turn(self, tid="aaaaaaaaaaaa", status="completed", events=None, **kw):
        return {
            "id": tid,
            "prompt": "q",
            "status": status,
            "started": 1.0,
            "events": events or [],
            **kw,
        }


class TextAgent(BridgeCase):  # noqa: V102
    """Any command that prints its answer. Queries come from ster's own trace files."""

    def start_text(self):
        # the agent must write into the bridge's trace folder, which exists only once the bridge does
        placeholder = custom("-c", "pass")
        bridge = self.start(placeholder)
        script = agent_script(
            self.scripts,
            "text.py",
            PRELUDE
            + """
            write_trace(__import__('pathlib').Path(sys.argv[1]), "run-0a1b2c", "SELECT ?s ?n", ["s", "n"], [["https://x.org/#a", "3"], ["https://x.org/#b", "2"]])
            print("answer to " + sys.argv[2])
        """,
        )
        bridge.server.CUSTOM = custom(script, str(bridge.traces), "{prompt}")
        return bridge

    def test_the_answer_and_the_query_come_without_the_agent_reporting_either(self):
        bridge = self.start_text()
        status, r = bridge.ask("how many?")
        self.assertEqual(status, 200)
        ev = bridge.events(r["turn_id"])
        kinds = [e["e"] for e in ev]
        self.assertEqual(
            kinds.count("step_start"), 1
        )  # regression: the watcher once added a second one
        [call] = [e for e in ev if e["e"] == "tool_call"]
        self.assertEqual(
            (call["name"], call["id"], call["input"]["query"]),
            ("run_sparql", "run-0a1b2c", "SELECT ?s ?n"),
        )
        [trace] = [e for e in ev if e["e"] == "trace"]
        self.assertEqual(trace["steps"][0]["rows"], ROWS)
        done = ev[-2] if kinds[-1] == "ster_seen" else ev[-1]
        self.assertEqual(
            (done["e"], done["status"], done["answer"]),
            ("done", "completed", "answer to how many?"),
        )
        self.assertEqual([e["n"] for e in ev if e["e"] == "ster_seen"], [1])

    def reported(self, turn_id):
        [call] = [
            c
            for c in self.ster.log
            if c[0] == "POST" and c[1].startswith("/api/query_trace/answers/")
        ]
        self.assertEqual(call[1], f"/api/query_trace/answers/{turn_id}")
        return json.loads(call[3]), call[2]

    def test_the_answer_and_the_runs_it_rests_on_are_reported_to_ster(self):
        bridge = self.start_text()
        _, r = bridge.ask("how many?")
        bridge.events(r["turn_id"])
        body, headers = self.reported(r["turn_id"])
        self.assertEqual(
            (body["question"], body["answer"], body["status"], body["run_ids"]),
            ("how many?", "answer to how many?", "completed", ["run-0a1b2c"]),
        )
        self.assertEqual(body["conversation_id"], r["conversation_id"])
        self.assertEqual(headers["Authorization"], "Bearer test-token")

    def test_the_session_a_conversation_resumes_with_is_reported(self):
        bridge = self.start_text()
        _, r = bridge.ask("q")
        bridge.events(r["turn_id"])
        _, conv = bridge.json(f"/api/conversations/{r['conversation_id']}")
        conv["session_id"] = "sess-42"  # what the agent said to resume with
        bridge.server.save(conv)
        turn = {
            "id": "dddddddddddd",
            "prompt": "next",
            "status": "completed",
            "answer": "ok",
            "events": [],
        }
        run = bridge.server.Run(conv, turn)
        self.assertTrue(bridge.server.report_answer(run))
        body = json.loads(self.ster.log[-1][3])
        self.assertEqual(body["resume_session_id"], "sess-42")

    def test_a_ster_that_is_down_does_not_break_the_turn(self):
        bridge = self.start_text()
        with mock.patch.object(bridge.server, "STER_PORT", 9):
            turn = {"id": "eeeeeeeeeeee", "prompt": "q", "status": "completed", "events": []}
            self.assertFalse(bridge.server.report_answer(bridge.server.Run({"id": "c"}, turn)))

    def test_a_cancelled_turn_is_not_reported(self):
        bridge = self.start_text()
        turn = {"id": "ffffffffffff", "prompt": "q", "status": "cancelled", "events": []}
        self.assertFalse(bridge.server.report_answer(bridge.server.Run({"id": "c"}, turn)))

    def test_nothing_is_reported_as_not_reported_not_as_zero(self):
        bridge = self.start_text()
        _, r = bridge.ask("q")
        ev = bridge.events(r["turn_id"])
        self.assertFalse([e for e in ev if e["e"] == "usage"])
        self.assertIsNone([e for e in ev if e["e"] == "done"][0].get("cost_usd"))

    def test_the_conversation_is_saved_with_the_agent_that_answered(self):
        bridge = self.start_text()
        _, r = bridge.ask("q")
        bridge.events(r["turn_id"])
        _, conv = bridge.json(f"/api/conversations/{r['conversation_id']}")
        [t] = conv["turns"]
        self.assertEqual(
            (t["status"], t["agent"], t["answer"]), ("completed", "fake", "answer to q")
        )
        self.assertEqual(conv["title"], "q")

    def test_a_failing_agent_reports_its_error(self):
        script = agent_script(
            self.scripts, "fail.py", "sys.stderr.write('boom happened'); sys.exit(3)\n"
        )
        bridge = self.start(custom(script))
        _, r = bridge.ask("q")
        done = [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]
        self.assertEqual(done["status"], "error")
        self.assertIn("boom happened", done["error"])

    def test_an_agent_that_succeeds_silently_still_completes(self):
        bridge = self.start(custom(agent_script(self.scripts, "quiet.py", "pass\n")))
        _, r = bridge.ask("q")
        done = [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]
        self.assertEqual((done["status"], done["answer"]), ("completed", ""))

    def test_the_check_measures_the_last_run(self):
        bridge = self.start_text()
        _, r = bridge.ask("q")
        bridge.events(r["turn_id"])
        _, check = bridge.json("/api/agent-check")
        self.assertEqual(check["selected"]["label"], "fake")
        self.assertEqual(check["last_run"]["counts"]["sparql"], 1)
        self.assertEqual(
            check["last_run"]["observed"],
            {
                "stream_steps": True,
                "token_usage": False,
                "cost": False,
                "resume": False,
                "sparql_rows": True,
            },
        )
        self.assertTrue(check["ster"]["up"])


class EventsAgent(BridgeCase):  # noqa: V102
    """An agent (or its translator) that prints the neutral protocol."""

    def start_events(self):
        bridge = self.start(
            custom("-c", "pass", output="events", resume=["--session", "{session}"])
        )
        script = agent_script(
            self.scripts,
            "events.py",
            PRELUDE
            + """
            open(os.path.join(sys.argv[1], "argv.txt"), "a").write(json.dumps(sys.argv[2:]) + "\\n")
            out = lambda **e: print(json.dumps(e), flush=True)
            out(e="session", session_id="sess-1")
            out(e="step_start", step="s1")
            out(e="usage", step="s1", input=3)
            out(e="usage", step="s1", output=5)
            out(e="tool_call", step="s1", id="c1", name="mcp__x__run_sparql", input={"query": "SELECT 1"})
            write_trace(__import__('pathlib').Path(sys.argv[1]), "run-abc123", "SELECT 1", ["n"], [["1"]])
            out(e="tool_result", id="c1", text=json.dumps({"rows": [["1"]], "trace": {"run_id": "run-abc123"}}))
            out(e="step_start", step="s2")
            out(e="text_delta", step="s2", text="one")
            out(e="done", status="completed", answer="one", cost_usd=0.5, usage={"input": 3, "output": 5})
        """,
        )
        bridge.server.CUSTOM = custom(
            script,
            str(bridge.traces),
            "{prompt}",
            output="events",
            resume=["--session", "{session}"],
        )
        return bridge

    def test_events_are_normalised_and_the_trace_is_joined_to_its_call(self):
        bridge = self.start_events()
        _, r = bridge.ask("q")
        ev = bridge.events(r["turn_id"])
        [call] = [e for e in ev if e["e"] == "tool_call"]
        self.assertEqual(call["name"], "run_sparql")  # prefix stripped
        [trace] = [e for e in ev if e["e"] == "trace"]
        self.assertEqual((trace["id"], trace["steps"][0]["rows"]), ("c1", [["1"]]))
        self.assertEqual(
            [e["n"] for e in ev if e["e"] == "ster_seen"], [1]
        )  # the same trace seen twice counts once

    def test_usage_reported_in_pieces_is_merged_per_step(self):
        bridge = self.start_events()
        _, r = bridge.ask("q")
        usage = [e for e in bridge.events(r["turn_id"]) if e["e"] == "usage" and e["step"] == "s1"]
        self.assertEqual(
            {k: v for k, v in usage[-1].items() if k in ("input", "output")},
            {"input": 3, "output": 5},
        )
        self.assertNotIn("cache_read", usage[-1])

    def test_cost_and_totals_reach_the_turn_and_the_history_list(self):
        bridge = self.start_events()
        _, r = bridge.ask("q")
        bridge.events(r["turn_id"])
        _, conv = bridge.json(f"/api/conversations/{r['conversation_id']}")
        self.assertEqual(
            (conv["turns"][0]["cost_usd"], conv["turns"][0]["usage"]),
            (0.5, {"input": 3, "output": 5}),
        )
        _, listing = bridge.json("/api/conversations")
        self.assertEqual(
            (listing[0]["cost_usd"], listing[0]["usage"]["output"], listing[0]["turns"]),
            (0.5, 5, 1),
        )

    def test_a_follow_up_resumes_the_session_the_agent_reported(self):
        bridge = self.start_events()
        _, r1 = bridge.ask("first")
        bridge.events(r1["turn_id"])
        _, r2 = bridge.ask("second", conversation_id=r1["conversation_id"])
        self.assertEqual(r2["conversation_id"], r1["conversation_id"])
        bridge.events(r2["turn_id"])
        calls = [json.loads(line) for line in (bridge.traces / "argv.txt").read_text().splitlines()]
        self.assertEqual(calls[0], ["first"])
        self.assertEqual(calls[1], ["second", "--session", "sess-1"])
        _, conv = bridge.json(f"/api/conversations/{r1['conversation_id']}")
        self.assertEqual(len(conv["turns"]), 2)

    def test_an_events_agent_that_never_finishes_the_protocol_is_reported(self):
        bridge = self.start(
            custom(
                agent_script(
                    self.scripts,
                    "partial.py",
                    "print(json.dumps({'e': 'step_start', 'step': 's'}))\n",
                ),
                output="events",
            )
        )
        _, r = bridge.ask("q")
        done = [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]
        self.assertEqual(done["status"], "error")

    def test_an_agent_with_no_final_event_answers_with_its_last_steps_text(self):
        # OpenCode, for one, never says "done": it streams steps and exits
        script = agent_script(
            self.scripts,
            "nodone.py",
            """
            out = lambda **e: print(json.dumps(e), flush=True)
            out(e="step_start", step="s1"); out(e="text_delta", step="s1", text="let me look")
            out(e="step_start", step="s2"); out(e="text_delta", step="s2", text="the answer ")
            out(e="text_delta", step="s2", text="is 18")
        """,
        )
        bridge = self.start(custom(script, output="events"))
        _, r = bridge.ask("q")
        done = [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]
        self.assertEqual((done["status"], done["answer"]), ("completed", "the answer is 18"))

    def test_an_agent_that_streams_text_and_then_fails_is_an_error_not_an_answer(self):
        script = agent_script(
            self.scripts,
            "crash.py",
            """
            print(json.dumps({"e": "step_start", "step": "s1"})); print(json.dumps({"e": "text_delta", "step": "s1", "text": "half"}), flush=True)
            sys.stderr.write("it broke"); sys.exit(2)
        """,
        )
        bridge = self.start(custom(script, output="events"))
        _, r = bridge.ask("q")
        done = [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]
        self.assertEqual(done["status"], "error")
        self.assertIn("it broke", done["error"])

    def test_a_session_repeated_on_every_line_is_said_once(self):
        script = agent_script(
            self.scripts,
            "repeat.py",
            """
            out = lambda **e: print(json.dumps(e), flush=True)
            for i in range(3):
                out(e="session", session_id="s1"); out(e="step_start", step="t%d" % i)
            out(e="done", status="completed", answer="ok")
        """,
        )
        bridge = self.start(custom(script, output="events"))
        _, r = bridge.ask("q")
        ev = bridge.events(r["turn_id"])
        self.assertEqual([e["session_id"] for e in ev if e["e"] == "session"], ["s1"])
        self.assertEqual(
            bridge.json(f"/api/conversations/{r['conversation_id']}")[1]["session_id"], "s1"
        )

    def test_garbage_lines_from_the_agent_are_skipped(self):
        script = agent_script(
            self.scripts,
            "noisy.py",
            """
            print("starting up...")
            print(json.dumps([1, 2]))
            print(json.dumps({"e": "done", "status": "completed", "answer": "fine"}))
        """,
        )
        bridge = self.start(custom(script, output="events"))
        _, r = bridge.ask("q")
        done = [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]
        self.assertEqual(done["answer"], "fine")

    def test_a_translator_turns_the_agents_own_stream_into_events(self):
        # the command prints something that is not the protocol; the recipe's translator makes it so
        translator = agent_script(
            self.scripts,
            "tr.py",
            """
            for line in sys.stdin:
                print(json.dumps({"e": "done", "status": "completed", "answer": line.strip().upper()}), flush=True)
        """,
        )
        script = agent_script(self.scripts, "raw.py", "print('hello')\n")
        bridge = self.start(custom(script, output="events", translate=[sys.executable, translator]))
        _, r = bridge.ask("q")
        done = [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]
        self.assertEqual(done["answer"], "HELLO")


class ForeignFormat(BridgeCase):  # noqa: V102
    """An agent nobody has heard of, with a made-up output format: its recipe's rules are all the support it needs."""

    RULES = [
        {"when": {"kind": "hello"}, "emit": {"e": "session", "session_id": "$.sid"}},
        {
            "when": {"kind": "turn"},
            "set": {"step": "$.n"},
            "emit": {"e": "step_start", "step": "$.n"},
        },
        {
            "when": {"kind": "say"},
            "emit": {"e": "text_delta", "step": {"state": "step"}, "text": "$.t"},
        },
        {
            "when": {"kind": "bye"},
            "emit": [
                {
                    "e": "usage",
                    "step": {"state": "step"},
                    "input": "$.tokens.in",
                    "output": "$.tokens.out",
                },
                {
                    "e": "done",
                    "status": {"if": "$.failed", "then": "error", "else": "completed"},
                    "answer": "$.final",
                    "session_id": "$.sid",
                },
            ],
        },
    ]

    def agent(self, lines, **kw):
        script = agent_script(
            self.scripts,
            "foreign.py",
            f"""
            for line in {lines!r}:
                print(json.dumps(line), flush=True)
        """,
        )
        return custom(script, output="events", stream=self.RULES, **kw)

    def test_the_agent_s_own_format_becomes_a_normal_run(self):
        bridge = self.start(
            self.agent(
                [
                    {"kind": "hello", "sid": "s9"},
                    {"kind": "turn", "n": "t1"},
                    {"kind": "say", "t": "hel"},
                    {"kind": "say", "t": "lo"},
                    {"kind": "bye", "final": "hello", "sid": "s9", "tokens": {"in": 3, "out": 4}},
                ]
            )
        )
        _, r = bridge.ask("q")
        ev = bridge.events(r["turn_id"])
        self.assertEqual("".join(e["text"] for e in ev if e["e"] == "text_delta"), "hello")
        self.assertEqual([e["step"] for e in ev if e["e"] == "text_delta"], ["t1", "t1"])
        usage = [e for e in ev if e["e"] == "usage"][-1]
        self.assertEqual((usage["step"], usage["input"], usage["output"]), ("t1", 3, 4))
        done = [e for e in ev if e["e"] == "done"][0]
        self.assertEqual((done["status"], done["answer"]), ("completed", "hello"))
        _, conv = bridge.json(f"/api/conversations/{r['conversation_id']}")
        self.assertEqual(conv["session_id"], "s9")

    def test_a_failure_flag_in_its_format_becomes_an_error_status(self):
        bridge = self.start(self.agent([{"kind": "bye", "final": "nope", "failed": True}]))
        _, r = bridge.ask("q")
        self.assertEqual(
            [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]["status"], "error"
        )

    def test_lines_the_rules_do_not_know_are_ignored(self):
        bridge = self.start(
            self.agent([{"kind": "banner"}, {"surprise": 1}, {"kind": "bye", "final": "ok"}])
        )
        _, r = bridge.ask("q")
        self.assertEqual(
            [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]["answer"], "ok"
        )


class AgentEnvironment(BridgeCase):  # noqa: V102
    def test_the_recipe_can_hand_the_agent_its_settings_through_the_environment(self):
        script = agent_script(self.scripts, "env.py", "print(os.environ['ASK_TEST_CONFIG'])\n")
        agent = custom(script, env={"ASK_TEST_CONFIG": '{"ster": "{ster_url}", "q": "{prompt}"}'})
        bridge = self.start(agent)
        _, r = bridge.ask("hello")
        done = [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]
        self.assertEqual(json.loads(done["answer"]), {"ster": self.ster.url, "q": "hello"})

    def test_terminal_colours_in_a_plain_text_answer_are_removed(self):
        script = agent_script(
            self.scripts, "colour.py", "print('\\x1b[31mred\\x1b[0m and \\x1b[1mbold\\x1b[0m')\n"
        )
        bridge = self.start(custom(script))
        _, r = bridge.ask("q")
        done = [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]
        self.assertEqual(done["answer"], "red and bold")


class Control(BridgeCase):  # noqa: V102
    def slow(self):
        return self.start(custom(agent_script(self.scripts, "slow.py", "time.sleep(30)\n")))

    def test_stop_cancels_the_run_and_ends_the_process(self):
        bridge = self.slow()
        _, r = bridge.ask("q")
        time.sleep(0.8)
        self.assertEqual(
            bridge.json(f"/api/runs/{r['turn_id']}/cancel", {}, method="POST")[1],
            {"cancelled": True},
        )
        started = time.time()
        done = [e for e in bridge.events(r["turn_id"]) if e["e"] == "done"][0]
        self.assertEqual(done["status"], "cancelled")
        self.assertLess(time.time() - started, 10)

    def test_a_conversation_answers_one_question_at_a_time(self):
        bridge = self.slow()
        _, r = bridge.ask("first")
        time.sleep(0.5)
        status, _ = bridge.ask("second", conversation_id=r["conversation_id"])
        self.assertEqual(status, 409)
        bridge.json(f"/api/runs/{r['turn_id']}/cancel", {}, method="POST")

    def test_an_empty_question_is_refused(self):
        self.assertEqual(
            self.start(custom(agent_script(self.scripts, "x.py", "pass\n"))).ask("   ")[0], 400
        )

    def test_cancelling_a_finished_or_unknown_run_does_nothing(self):
        bridge = self.start(custom(agent_script(self.scripts, "x.py", "pass\n")))
        self.assertEqual(
            bridge.json("/api/runs/nope/cancel", {}, method="POST")[1], {"cancelled": False}
        )


class NoAgent(BridgeCase):  # noqa: V102
    def test_the_page_is_told_why_and_cannot_ask(self):
        bridge = self.start(agent=None, recipes=[])
        _, status = bridge.json("/api/status")
        self.assertEqual(
            (status["agent"]["ready"], status["agent"]["label"], status["agent"]["reason"]["code"]),
            (False, None, "reason.no_recipes"),
        )
        code, body = bridge.ask("q")
        self.assertEqual(code, 409)
        self.assertEqual(body["detail"], status["agent"]["reason"]["text"])

    def test_history_stays_readable(self):
        bridge = self.start(agent=None, recipes=[])
        self.seed(
            bridge,
            "abcdef012345",
            [
                self.turn(
                    events=[
                        {
                            "e": "done",
                            "t": 1,
                            "status": "completed",
                            "answer": "old",
                            "cost_usd": 0.25,
                        }
                    ],
                    usage={"input": 1, "output": 2, "cache_read": 3, "cache_write": 4},
                )
            ],
        )
        _, listing = bridge.json("/api/conversations")
        self.assertEqual((listing[0]["title"], listing[0]["usage"]["cache_write"]), ("seeded", 4))
        self.assertEqual(bridge.json("/api/conversations/abcdef012345")[0], 200)

    def test_the_check_says_there_is_no_agent_without_failing(self):
        bridge = self.start(agent=None, recipes=[])
        _, check = bridge.json("/api/agent-check")
        self.assertEqual(
            (check["selected"], check["agents"], check["reason"]["code"]),
            (None, [], "reason.no_recipes"),
        )

    def test_an_agent_installed_later_is_picked_up_without_a_restart(self):
        bridge = self.start(agent=None, recipes=[])
        self.assertFalse(bridge.json("/api/status")[1]["agent"]["ready"])
        bridge.server.CUSTOM = custom(agent_script(self.scripts, "x.py", "print('hi')\n"))
        self.assertTrue(bridge.json("/api/status")[1]["agent"]["ready"])

    def test_a_recipe_whose_program_is_missing_is_not_an_agent(self):
        ghost = runner.Agent(
            label="Ghost", binary="no-such-program-xyz", command=["x"], source="ghost.json"
        )
        bridge = self.start(agent=None, recipes=[ghost])
        agent = bridge.json("/api/status")[1]["agent"]
        self.assertEqual(
            (agent["ready"], agent["reason"]["code"]), (False, "reason.none_installed")
        )
        listed = bridge.json("/api/agent-check")[1]["agents"]
        self.assertEqual(
            (listed[0]["label"], listed[0]["path"], listed[0]["selected"]), ("Ghost", None, False)
        )


class History(BridgeCase):  # noqa: V102
    def test_delete_removes_the_conversation(self):
        bridge = self.start()
        self.seed(bridge, "abcdef012345", [self.turn()])
        self.assertEqual(bridge.json("/api/conversations/abcdef012345", method="DELETE")[0], 200)
        self.assertEqual(bridge.json("/api/conversations/abcdef012345")[0], 404)

    def test_a_turn_left_running_by_a_dead_server_is_shown_as_interrupted(self):
        bridge = self.start()
        self.seed(bridge, "abcdef012345", [self.turn(status="running")])
        self.assertEqual(
            bridge.json("/api/conversations/abcdef012345")[1]["turns"][0]["status"], "interrupted"
        )

    def test_conversation_ids_that_are_not_ours_are_refused(self):
        bridge = self.start()
        for bad in ("../../etc/passwd", "ABCDEF012345", "short", "abcdef01234g"):
            self.assertEqual(bridge.json(f"/api/conversations/{bad}")[0], 404, bad)

    def test_a_conversation_id_can_never_name_a_file_outside_the_store(self):
        # the router already refuses slashes; this is the second lock, on the function that builds the path
        bridge = self.start()
        for bad in (
            "../x",
            "..",
            "a/b",
            "abcdef01234",
            "abcdef0123456",
            "ABCDEF012345",
            "abcdef01234g",
            "",
            "/etc/passwd",
        ):
            with self.assertRaises(HTTPException, msg=bad):
                bridge.server.conv_path(bad)
        path = bridge.server.conv_path("abcdef012345")
        self.assertEqual((path.parent, path.name), (bridge.store, "abcdef012345.json"))

    def test_the_list_is_newest_first_and_sums_cost_from_older_events(self):
        bridge = self.start()
        old = self.turn(
            events=[{"e": "done", "t": 1, "status": "completed", "cost_usd": 0.5}]
        )  # saved before costs were stored
        new = self.turn(tid="bbbbbbbbbbbb", cost_usd=0.25)
        self.seed(bridge, "aaaaaaaaaaa1", [old], title="older")
        self.seed(bridge, "aaaaaaaaaaa2", [new], title="newer")
        data = json.loads((bridge.store / "aaaaaaaaaaa2.json").read_text())
        data["updated"] = 99.0
        (bridge.store / "aaaaaaaaaaa2.json").write_text(json.dumps(data))
        _, listing = bridge.json("/api/conversations")
        self.assertEqual(
            [(c["title"], c["cost_usd"]) for c in listing], [("newer", 0.25), ("older", 0.5)]
        )

    def test_the_interface_languages_on_offer_come_from_the_catalog_folder(self):
        _, langs = self.start().json("/api/locales")
        self.assertEqual({l["code"]: l["name"] for l in langs}, {"en": "English", "fr": "Français"})


def project(root: Path, files=("data.ttl",), context=None):
    (root / ".ster").mkdir(parents=True, exist_ok=True)
    (root / ".ster" / "project.json").write_text(
        json.dumps({"files": list(files), "context": context or {}})
    )
    return root


class Settings(unittest.TestCase):  # noqa: V102
    def cfg(self, env=None, cwd=None):
        from agent_app import server

        return server.settings(env or {}, cwd or Path("/nowhere"))

    def test_the_named_project_wins(self):
        root = Path(tempfile.mkdtemp())
        self.assertEqual(
            self.cfg({"ASK_PROJECT": str(root)}, cwd=project(Path(tempfile.mkdtemp())))["root"],
            root.resolve(),
        )

    def test_otherwise_the_folder_the_server_is_run_from(self):
        here = Path(tempfile.mkdtemp())
        self.assertEqual(self.cfg(cwd=here)["root"], here)

    def test_a_home_relative_project_is_expanded(self):
        self.assertEqual(self.cfg({"ASK_PROJECT": "~"})["root"], Path.home().resolve())

    def test_where_ster_listens_can_be_chosen(self):
        self.assertEqual((self.cfg()["host"], self.cfg()["port"]), ("127.0.0.1", 8765))
        c = self.cfg({"ASK_STER_HOST": "10.0.0.5", "ASK_STER_PORT": "9000"})
        self.assertEqual((c["host"], c["port"]), ("10.0.0.5", 9000))


class StateFolder(unittest.TestCase):  # noqa: V102
    """Saved conversations moved from .ster/webapp to .ster/agent-app: they are carried over, never lost."""

    def setUp(self):
        from agent_app import server

        self.migrate = server.migrate_state
        self.ster = Path(tempfile.mkdtemp())

    def test_the_old_folder_is_moved_with_its_conversations(self):
        (self.ster / "webapp" / "conversations").mkdir(parents=True)
        (self.ster / "webapp" / "conversations" / "abcdef012345.json").write_text("{}")
        self.migrate(self.ster)
        self.assertFalse((self.ster / "webapp").exists())
        self.assertEqual(
            (self.ster / "agent-app" / "conversations" / "abcdef012345.json").read_text(), "{}"
        )

    def test_an_existing_new_folder_is_never_overwritten(self):
        (self.ster / "webapp").mkdir()
        (self.ster / "webapp" / "old.txt").write_text("old")
        (self.ster / "agent-app").mkdir()
        (self.ster / "agent-app" / "new.txt").write_text("new")
        self.migrate(self.ster)
        self.assertTrue(
            (self.ster / "webapp" / "old.txt").exists()
        )  # left for the user to sort out
        self.assertEqual((self.ster / "agent-app" / "new.txt").read_text(), "new")
        self.assertFalse((self.ster / "agent-app" / "old.txt").exists())

    def test_nothing_to_move_is_fine(self):
        self.migrate(self.ster)
        self.assertEqual(list(self.ster.iterdir()), [])

    def test_running_it_twice_changes_nothing(self):
        (self.ster / "webapp").mkdir()
        self.migrate(self.ster)
        self.migrate(self.ster)
        self.assertTrue((self.ster / "agent-app").is_dir())


class SterLauncher(BridgeCase):  # noqa: V102
    """When ster is not running the page starts it for its project, with tracing on and its trace folder named."""

    def setUp(self):
        super().setUp()
        self.root = project(
            Path(tempfile.mkdtemp()),
            files=["main.ttl"],
            context={"main.ttl": ["ctx a.ttl", "ctx-b.ttl"]},
        )
        self.bridge = self.start()
        from agent_app import server

        self.server = server
        self.patches = [
            mock.patch.object(server, "ROOT", self.root),
            mock.patch.object(server, "STER_DIR", self.root / ".ster"),
            mock.patch.object(server, "TRACES", self.root / ".ster" / "query-traces"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_it_starts_ster_for_the_project_with_tracing_on(self):
        up = iter([False, True])
        with (
            mock.patch.object(self.server, "ster_up", lambda: next(up)),
            mock.patch.object(self.server.subprocess, "Popen") as popen,
        ):
            self.assertTrue(self.server.ensure_ster())
        [call] = popen.call_args_list
        cmd, kw = call.args[0], call.kwargs
        self.assertEqual(cmd[1:3], ["serve", "main.ttl"])
        self.assertEqual(
            [cmd[i + 1] for i, a in enumerate(cmd) if a == "-x"],
            ["ctx a.ttl", "ctx-b.ttl"],
        )  # the project's other files, read-only
        self.assertEqual(kw["cwd"], self.root)  # relative paths resolve inside the project
        self.assertEqual(
            (kw["env"]["STER_QUERY_TRACE"], kw["env"]["STER_QUERY_TRACE_DIR"]),
            ("1", str(self.root / ".ster" / "query-traces")),
        )
        self.assertTrue(kw["start_new_session"])  # outlives this server

    def test_a_running_ster_is_left_alone(self):
        with (
            mock.patch.object(self.server, "ster_up", lambda: True),
            mock.patch.object(self.server.subprocess, "Popen") as popen,
        ):
            self.assertTrue(self.server.ensure_ster())
        popen.assert_not_called()

    def test_the_log_goes_inside_the_project(self):
        with mock.patch.object(self.server, "ster_up", lambda: True):
            pass
        up = iter([False, True])
        with (
            mock.patch.object(self.server, "ster_up", lambda: next(up)),
            mock.patch.object(self.server.subprocess, "Popen"),
        ):
            self.server.ensure_ster()
        self.assertTrue((self.root / ".ster" / "agent-app").is_dir())


class FollowingSter(BridgeCase):  # noqa: V102
    """The page is connected to the graph its ster serves, whatever that is."""

    def status(self, bridge):
        with mock.patch.dict(bridge.server._served, {"at": 0.0}):
            return bridge.json("/api/status")[1]

    def test_it_reports_the_graph_ster_serves_now(self):
        self.ster = FakeSter(file="/anywhere/a.ttl", title="Retail")
        st = self.status(self.start())
        self.assertEqual(
            (st["ster"], st["ster_state"], st["ster_port"]), (True, "up", self.ster.port)
        )
        self.assertEqual(
            (st["graph"]["title"], st["graph"]["triples"], st["graph"]["fingerprint"]),
            ("Retail", 12, "00aa11bb22cc33dd"),
        )

    def test_a_ster_that_is_down_is_down_with_no_graph(self):
        bridge = self.start()
        with (
            mock.patch.object(bridge.server, "STER_PORT", 9),
            mock.patch.dict(bridge.server._served, {"at": 0.0}),
        ):
            st = bridge.json("/api/status")[1]
        self.assertEqual((st["ster"], st["ster_state"], st["graph"]), (False, "down", None))

    def test_a_change_of_graph_is_seen_within_seconds(self):
        self.assertLessEqual(self.start().server.SERVED_TTL, 5)
        self.ster = FakeSter()
        bridge = self.start()
        first = self.status(bridge)["graph"]["fingerprint"]
        self.ster.fingerprint = "ffffffffffffffff"
        self.assertNotEqual(self.status(bridge)["graph"]["fingerprint"], first)

    def test_a_question_is_never_refused_for_the_graph_ster_serves(self):
        self.ster = FakeSter(file="/some/other/graph.ttl")
        bridge = self.start(custom("-c", "pass"))
        self.assertEqual(bridge.call("/api/ask", {"prompt": "how many?"})[0], 200)

    def test_each_answer_records_the_graph_it_was_given_on(self):
        self.ster = FakeSter()
        bridge = self.start(custom("-c", "pass"))
        _, body = bridge.call("/api/ask", {"prompt": "q"})
        ids = json.loads(body)
        bridge.events(ids["turn_id"])
        saved = bridge.json(f"/api/conversations/{ids['conversation_id']}")[1]
        self.assertEqual(saved["turns"][0]["graph"], "00aa11bb22cc33dd")
        [call] = [c for c in self.ster.log if c[1].startswith("/api/query_trace/answers/")]
        self.assertEqual(json.loads(call[3])["graph_fingerprint"], "00aa11bb22cc33dd")

    def test_the_status_says_when_this_ster_process_started(self):
        self.ster = FakeSter()
        self.assertEqual(self.status(self.start())["graph"]["started"], "2026-01-01T10:00:00Z")

    def test_each_answer_records_which_ster_process_it_was_asked_of(self):
        self.ster = FakeSter()
        bridge = self.start(custom("-c", "pass"))
        ids = json.loads(bridge.call("/api/ask", {"prompt": "q"})[1])
        bridge.events(ids["turn_id"])
        saved = bridge.json(f"/api/conversations/{ids['conversation_id']}")[1]
        self.assertEqual(saved["turns"][0]["ster_started"], "2026-01-01T10:00:00Z")

    def test_ster_is_started_from_the_project_when_it_is_down(self):
        bridge = self.start()
        root = Path(tempfile.mkdtemp())
        project(root, files=["a.ttl"], context={"a.ttl": ["b.ttl"]})
        up = iter([False, True])
        with (
            mock.patch.object(bridge.server, "ROOT", root),
            mock.patch.object(bridge.server, "STER_DIR", root / ".ster"),
            mock.patch.object(bridge.server, "ster_up", lambda: next(up)),
            mock.patch.object(bridge.server.subprocess, "Popen") as popen,
        ):
            bridge.server.ensure_ster()
        cmd = popen.call_args.args[0]
        self.assertEqual((cmd[2], cmd[cmd.index("-x") + 1]), ("a.ttl", "b.ttl"))


class Guards(BridgeCase):  # noqa: V102
    def test_a_foreign_host_is_refused(self):
        self.assertEqual(self.start().call("/api/status", headers={"Host": "evil.example"})[0], 403)

    def test_a_foreign_origin_is_refused(self):
        bridge = self.start()
        self.assertEqual(
            bridge.call("/api/ask", {"prompt": "x"}, headers={"Origin": "http://evil.example"})[0],
            403,
        )

    def test_localhost_origins_are_accepted(self):
        bridge = self.start()
        for origin in ("http://localhost:1234", "http://127.0.0.1:9"):
            self.assertEqual(bridge.call("/api/status", headers={"Origin": origin})[0], 200, origin)

    def test_only_the_maps_read_calls_reach_ster(self):
        bridge = self.start()
        for method, path in (
            ("POST", "/api/locate"),
            ("POST", "/api/timeline"),
            ("POST", "/api/sparql_query"),
            ("GET", "/api/node-detail?uri=u"),
        ):
            code, _ = bridge.call(path, {} if method == "POST" else None, method=method)
            self.assertEqual(code, 200, path)
        for method, path in (
            ("POST", "/api/individuals"),
            ("POST", "/api/relation/remove"),
            ("GET", "/api/locate"),
            ("POST", "/api/node-detail"),
            ("GET", "/api/version"),
        ):
            code, _ = bridge.call(path, {} if method == "POST" else None, method=method)
            self.assertEqual(code, 404, f"{method} {path}")

    def test_the_bridge_supplies_the_token_when_the_page_has_none(self):
        bridge = self.start()
        bridge.call("/api/locate", {"uris": []})
        self.assertEqual(self.ster.log[-1][2].get("Authorization"), "Bearer test-token")

    def test_a_token_the_caller_brings_is_kept(self):
        bridge = self.start()
        bridge.call("/api/locate", {"uris": []}, headers={"Authorization": "Bearer mine"})
        self.assertEqual(self.ster.log[-1][2].get("Authorization"), "Bearer mine")

    def test_the_query_string_is_forwarded(self):
        bridge = self.start()
        bridge.call("/api/node-detail?uri=http%3A%2F%2Fx")
        self.assertEqual(self.ster.log[-1][1], "/api/node-detail?uri=http%3A%2F%2Fx")


class EmbeddedMap(BridgeCase):  # noqa: V102
    def seed_query(self, bridge, query):
        self.seed(
            bridge,
            "abcdef012345",
            [
                self.turn(
                    events=[
                        {
                            "e": "tool_call",
                            "t": 1,
                            "id": "t1",
                            "name": "run_sparql",
                            "input": {"query": query},
                        }
                    ]
                )
            ],
        )

    def get(self, bridge, tool="t1", conv="abcdef012345", turn="aaaaaaaaaaaa", extra=""):
        return bridge.redirect_of(f"/ster-map?conv={conv}&turn={turn}&tool={tool}{extra}")

    def test_the_frame_is_sent_to_sters_own_embedded_map_with_the_agents_query(self):
        bridge = self.start()
        self.seed_query(bridge, "SELECT ?a WHERE { ?a <p> 'x' }")
        code, location = self.get(bridge)
        self.assertEqual(code, 302)
        self.assertTrue(location.startswith(f"http://127.0.0.1:{self.ster.port}/map?q="), location)
        self.assertIn("SELECT%20%3Fa%20WHERE", location)
        self.assertTrue(location.endswith("&embed=1"))

    def test_the_full_page_link_is_the_same_page_without_embed(self):
        bridge = self.start()
        self.seed_query(bridge, "SELECT 1")
        location = self.get(bridge, extra="&full=1")[1]
        self.assertNotIn("embed", location)

    def test_the_timeline_has_the_same_frame_and_full_page_links(self):
        bridge = self.start()
        self.seed_query(bridge, "SELECT ?a WHERE { ?a <p> 'x' }")
        url = "/ster-timeline?conv=abcdef012345&turn=aaaaaaaaaaaa&tool=t1"
        code, location = bridge.redirect_of(url)
        self.assertEqual(code, 302)
        self.assertTrue(
            location.startswith(f"http://127.0.0.1:{self.ster.port}/timeline?q="), location
        )
        self.assertTrue(location.endswith("&embed=1"))
        self.assertNotIn("embed", bridge.redirect_of(url + "&full=1")[1])

    def test_a_timeline_for_an_unknown_call_is_a_404(self):
        bridge = self.start()
        self.seed_query(bridge, "SELECT 1")
        self.assertEqual(
            bridge.redirect_of("/ster-timeline?conv=abcdef012345&turn=aaaaaaaaaaaa&tool=nope")[0],
            404,
        )

    def test_markup_in_a_query_is_escaped_in_the_address(self):
        bridge = self.start()
        self.seed_query(bridge, "</textarea><script>alert(1)</script>")
        location = self.get(bridge)[1]
        self.assertNotIn("<", location)

    def test_an_unknown_tool_conversation_or_turn_is_a_404(self):
        bridge = self.start()
        self.seed_query(bridge, "SELECT 1")
        for kw in ({"tool": "nope"}, {"conv": "bbbbbbbbbbbb"}, {"turn": "cccccccccccc"}):
            self.assertEqual(self.get(bridge, **kw)[0], 404, kw)

    def test_a_tool_call_without_a_query_is_a_404(self):
        bridge = self.start()
        self.seed(
            bridge,
            "abcdef012345",
            [
                self.turn(
                    events=[
                        {"e": "tool_call", "t": 1, "id": "t1", "name": "get_overview", "input": {}}
                    ]
                )
            ],
        )
        self.assertEqual(self.get(bridge)[0], 404)


if __name__ == "__main__":
    unittest.main()
