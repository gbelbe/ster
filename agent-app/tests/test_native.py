"""native.py: the page's own agent loop for a model server, with a fake model, a fake ster and nothing real."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from agent_app import native, runner
from helpers import FakeModel, write_trace
from test_server import BridgeCase

INSTRUCTIONS = """ster serves one RDF file.

Before writing SPARQL, call get_vocabulary.

For every MCP tool call, include context in MCP request metadata:
  "_meta": {
    "com.example/agent-session-id": "id",
    "com.example/agent-session-question": "the question",
    "com.example/agent-question": "the subquestion"
  }

If available, include token usage for the current agent step.

This server never edits the file.

A view opens itself when it can: open_view opens a browser tab. Driving a browser is expensive.

Build graph queries with an explicit CONSTRUCT allowlist."""


def model_agent(model):
    return runner.Agent(label="Model", binary="", command=[], kind="model", endpoint=model.endpoint)


class Pieces(unittest.TestCase):  # noqa: V102
    def test_instructions_lose_only_what_is_written_for_desktop_agents(self):
        out = native.trim_instructions(INSTRUCTIONS)
        self.assertIn("call get_vocabulary", out)
        self.assertIn("never edits the file", out)
        for gone in ("_meta", "token usage", "open_view", "browser", "CONSTRUCT"):
            self.assertNotIn(gone, out)

    def test_nothing_to_trim_and_nothing_given(self):
        self.assertEqual(native.trim_instructions("plain."), "plain.")
        self.assertEqual(native.trim_instructions(""), "")
        self.assertEqual(native.trim_instructions(None), "")

    def test_the_metadata_ster_asks_for_is_filled_in_for_the_model(self):
        meta = native.meta_for(INSTRUCTIONS, "conv1", "how many?")
        self.assertEqual(
            meta,
            {
                "com.example/agent-session-id": "conv1",
                "com.example/agent-session-question": "how many?",
                "com.example/agent-question": "how many?",
            },
        )

    def test_no_metadata_when_ster_asks_for_none(self):
        self.assertEqual(native.meta_for("plain", "c", "q"), {})

    def test_only_read_tools_are_offered_with_their_own_schema(self):
        listed = [
            {
                "name": n,
                "description": "d",
                "inputSchema": {"type": "object", "properties": {"q": {}}},
            }
            for n in ("run_sparql", "open_view", "export_query_trace", "get_overview")
        ]
        listed.append({"name": "get_entity"})
        defs = native.tool_definitions(listed)
        self.assertEqual(
            sorted(d["function"]["name"] for d in defs),
            ["get_entity", "get_overview", "run_sparql"],
        )
        self.assertEqual(defs[0]["function"]["parameters"]["properties"], {"q": {}})
        self.assertEqual(
            defs[-1]["function"]["parameters"], {"type": "object", "properties": {}}
        )  # a tool with no schema

    def test_a_tool_call_written_as_text_is_recognised_only_when_it_is_clear(self):
        allowed = {"get_overview", "run_sparql"}
        self.assertEqual(
            native.spoken_call('{"name": "get_overview", "parameters": {}}', allowed)["name"],
            "get_overview",
        )
        self.assertEqual(
            native.spoken_call(
                '```json\n{"name": "run_sparql", "arguments": {"query": "x"}}\n```', allowed
            )["arguments"],
            {"query": "x"},
        )
        for text in (
            '{"name": "rm_rf", "parameters": {}}',
            "I will call get_overview",
            "[1, 2]",
            '{"name": "get_overview"',
            "",
            None,
            '{"title": "x"}',
        ):
            self.assertIsNone(native.spoken_call(text, allowed), text)

    def test_the_two_wire_formats_carry_the_same_conversation(self):
        transcript = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "run", "arguments": {"a": 1}}],
            },
            {"role": "tool", "id": "c1", "name": "run", "content": "result"},
        ]
        ollama = native.OllamaAPI("http://h/v1", "m").wire(transcript)
        self.assertEqual(
            ollama[1]["tool_calls"][0]["function"], {"name": "run", "arguments": {"a": 1}}
        )  # arguments as an object
        self.assertEqual(ollama[2], {"role": "tool", "tool_name": "run", "content": "result"})
        openai = native.OpenAIAPI("http://h/v1", "m").wire(transcript)
        self.assertEqual(
            openai[1]["tool_calls"][0],
            {"id": "c1", "type": "function", "function": {"name": "run", "arguments": '{"a": 1}'}},
        )  # as a JSON string
        self.assertEqual(openai[2], {"role": "tool", "tool_call_id": "c1", "content": "result"})

    def test_the_server_root_is_the_endpoint_without_its_version_path(self):
        for url in ("http://h:11434/v1", "http://h:11434/v1/", "http://h:11434", "http://h:11434/"):
            self.assertEqual(native._root(url), "http://h:11434")


class Discovery(unittest.TestCase):  # noqa: V102
    def setUp(self):
        runner._SERVERS.clear()
        native._capable.clear()
        self.models = []

    def tearDown(self):
        for m in self.models:
            m.close()

    def server(self, **kw):
        m = FakeModel(**kw)
        self.models.append(m)
        return m

    def test_ollama_models_that_cannot_call_tools_are_left_out(self):
        info = native.discover(
            self.server(models=["plain", "big", "other"], tools_capable=("big", "other")).endpoint
        )
        self.assertEqual(
            (info["reachable"], info["api"], info["models"], info["all"]),
            (True, "ollama", ["big", "other"], ["plain", "big", "other"]),
        )

    def test_a_server_with_no_capable_model_is_up_but_has_none(self):
        info = native.discover(self.server(models=["plain"], tools_capable=()).endpoint)
        self.assertEqual((info["reachable"], info["models"]), (True, []))

    def test_nothing_listening(self):
        self.assertEqual(native.discover("http://127.0.0.1:9/v1")["reachable"], False)

    def test_another_kind_of_server_is_taken_at_its_word(self):
        info = native.discover(self.server(ollama=False, models=["a", "b"]).endpoint)
        self.assertEqual(
            (info["reachable"], info["api"], info["models"]), (True, "openai", ["a", "b"])
        )

    def test_which_model_is_used(self):
        ollama = {
            "reachable": True,
            "api": "ollama",
            "models": ["big", "other"],
            "all": ["plain", "big", "other"],
        }
        self.assertEqual(native.choose_model(ollama, None), "big")
        self.assertEqual(native.choose_model(ollama, "other"), "other")
        self.assertIsNone(native.choose_model(ollama, "plain"))  # named, but it cannot call tools
        self.assertIsNone(native.choose_model({**ollama, "models": []}, None))
        generic = {"reachable": True, "api": "openai", "models": ["a"], "all": ["a"]}
        self.assertEqual(
            native.choose_model(generic, "anything"), "anything"
        )  # cannot be checked, so it is tried


SECOND_CALL = 2  # the model answers once, then the server goes away


class Loop(BridgeCase):  # pylint: disable=too-many-public-methods  # one test per rule of the loop  # noqa: V102
    def setUp(self):
        runner._SERVERS.clear()
        native._capable.clear()
        super().setUp()
        # the which-file check is its own MCP call; these tests count the model's calls only
        from agent_app import server as bridge_server

        patch = mock.patch.object(
            bridge_server,
            "ster_state",
            lambda force=False: {"state": "up", "graph": None},
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.ster.instructions = INSTRUCTIONS
        self.model = FakeModel()
        self.addCleanup(self.model.close)

    def ask(self, prompt="how many?", **kw):
        bridge = self.bridge
        status, r = bridge.ask(prompt, **kw)
        return r, bridge.events(r["turn_id"])

    def go(self, model=None):
        self.bridge = self.start(model_agent(model or self.model))
        return self.bridge

    def done(self, ev):
        return [e for e in ev if e["e"] == "done"][0]

    def tool_calls_seen_by_ster(self):
        return [
            json.loads(body)["params"]
            for m, p, h, body in self.ster.log
            if p == "/mcp" and b'"tools/call"' in body
        ]

    # ------------------------------------------------------------------ a normal run
    def test_the_model_asks_for_a_tool_ster_answers_and_the_model_gives_the_answer(self):
        self.ster.replies["get_overview"] = json.dumps({"title": "X"})
        self.model.script = [
            {"calls": [("get_overview", {})], "tokens": (100, 10)},
            {"content": "The title is X.", "tokens": (120, 8)},
        ]
        self.go()
        r, ev = self.ask()
        self.assertEqual(
            [e["e"] for e in ev if e["e"] != "ster_seen"],
            [
                "turn_start",
                "session",
                "step_start",
                "usage",
                "tool_call",
                "tool_result",
                "step_start",
                "usage",
                "text_delta",
                "done",
            ],
        )
        [call] = [e for e in ev if e["e"] == "tool_call"]
        self.assertEqual((call["name"], call["input"]), ("get_overview", {}))
        self.assertEqual(
            [e for e in ev if e["e"] == "tool_result"][0]["text"], json.dumps({"title": "X"})
        )
        self.assertEqual(
            [(e["step"], e["input"], e["output"]) for e in ev if e["e"] == "usage"],
            [("s1", 100, 10), ("s2", 120, 8)],
        )
        done = self.done(ev)
        self.assertEqual(
            (done["status"], done["answer"], done["usage"]),
            ("completed", "The title is X.", {"input": 220, "output": 18}),
        )
        self.assertEqual(done["session_id"], r["conversation_id"])

    def test_what_the_model_is_sent(self):
        self.model.script = [{"content": "ok"}]
        self.go()
        self.ask()
        body = self.model.requests[0]
        self.assertEqual(
            (body["model"], body["stream"], body["options"]["temperature"]), ("big", False, 0)
        )
        self.assertGreaterEqual(body["options"]["num_ctx"], 8192)
        self.assertEqual(
            sorted(t["function"]["name"] for t in body["tools"]),
            sorted(set(native.NATIVE_TOOLS) & set(__import__("helpers").TOOLS)),
        )
        system = body["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertIn("get_vocabulary", system["content"])
        for gone in ("_meta", "open_view", "browser"):
            self.assertNotIn(gone, system["content"])
        self.assertEqual(body["messages"][1], {"role": "user", "content": "how many?"})

    def test_the_tools_a_model_may_not_use_are_never_offered_or_run(self):
        self.model.script = [
            {"calls": [("open_view", {}), ("export_query_trace", {})]},
            {"content": "done"},
        ]
        self.go()
        _, ev = self.ask()
        self.assertEqual(
            {t["function"]["name"] for t in self.model.requests[0]["tools"]}
            & {"open_view", "export_query_trace"},
            set(),
        )
        self.assertEqual(self.tool_calls_seen_by_ster(), [])
        self.assertTrue(
            all(
                e["is_error"] and "Unknown tool" in e["text"] for e in ev if e["e"] == "tool_result"
            )
        )

    def test_ster_gets_the_metadata_it_asks_for_without_the_model_having_to_send_it(self):
        self.model.script = [{"calls": [("get_overview", {})]}, {"content": "ok"}]
        self.go()
        r, _ = self.ask("which brands?")
        [params] = self.tool_calls_seen_by_ster()
        self.assertEqual(
            params["_meta"],
            {
                "com.example/agent-session-id": r["conversation_id"],
                "com.example/agent-session-question": "which brands?",
                "com.example/agent-question": "which brands?",
            },
        )

    def test_a_sparql_trace_is_joined_to_its_call(self):
        self.go()

        def reply(args):
            write_trace(self.bridge.traces, "run-feed01", args.get("q", ""), ["n"], [["7"]])
            return json.dumps({"rows": [["7"]], "trace": {"run_id": "run-feed01"}})

        self.ster.replies["run_sparql"] = reply
        self.model.script = [{"calls": [("run_sparql", {"q": "SELECT 1"})]}, {"content": "7"}]
        _, ev = self.ask()
        [trace] = [e for e in ev if e["e"] == "trace"]
        self.assertEqual(trace["steps"][0]["rows"], [["7"]])
        self.assertEqual([e["n"] for e in ev if e["e"] == "ster_seen"], [1])

    def test_a_huge_result_is_cut_for_the_model_but_kept_in_the_timeline(self):
        self.ster.replies["get_vocabulary"] = "x" * 20000
        self.model.script = [{"calls": [("get_vocabulary", {})]}, {"content": "ok"}]
        self.go()
        _, ev = self.ask()
        tool_msg = self.model.requests[1]["messages"][-1]
        self.assertLess(len(tool_msg["content"]), native.TO_MODEL_CAP + 120)
        self.assertIn("more characters not shown", tool_msg["content"])
        res = [e for e in ev if e["e"] == "tool_result"][0]
        self.assertEqual((res["length"], res["truncated"]), (20000, True))

    # ------------------------------------------------------------------ the conversation
    def test_a_follow_up_continues_the_conversation_the_page_kept(self):
        self.ster.replies["get_overview"] = "overview"
        self.model.script = [
            {"calls": [("get_overview", {})]},
            {"content": "first answer"},
            {"content": "second answer"},
        ]
        self.go()
        r1, _ = self.ask("first")
        r2, ev = self.ask("second", conversation_id=r1["conversation_id"])
        roles = [m["role"] for m in self.model.requests[2]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant", "user"])
        self.assertEqual(self.model.requests[2]["messages"][-1]["content"], "second")
        self.assertTrue(ev[0]["resumed"])
        self.assertEqual(self.done(ev)["answer"], "second answer")

    def test_the_transcript_is_saved_with_the_conversation(self):
        self.model.script = [{"content": "hi"}]
        self.go()
        r, _ = self.ask()
        _, conv = self.bridge.json(f"/api/conversations/{r['conversation_id']}")
        self.assertEqual(
            [(m["role"], m["content"]) for m in conv["messages"]],
            [("user", "how many?"), ("assistant", "hi")],
        )

    # ------------------------------------------------------------------ small models and their habits
    def test_a_call_written_as_text_is_still_made(self):
        self.ster.replies["get_overview"] = "overview"
        self.model.script = [
            {"content": '{"name": "get_overview", "parameters": {}}'},
            {"content": "the answer"},
        ]
        self.go()
        _, ev = self.ask()
        self.assertEqual([e["name"] for e in ev if e["e"] == "tool_call"], ["get_overview"])
        self.assertEqual(self.done(ev)["answer"], "the answer")
        self.assertFalse(
            [e for e in ev if e["e"] == "text_delta" and "get_overview" in e["text"]]
        )  # the spoken call is not shown as an answer

    def test_an_identical_call_is_not_run_twice(self):
        self.model.script = [
            {"calls": [("get_vocabulary", {}), ("get_vocabulary", {})]},
            {"calls": [("get_vocabulary", {})]},
            {"content": "ok"},
        ]
        self.go()
        _, ev = self.ask()
        self.assertEqual(len(self.tool_calls_seen_by_ster()), 1)
        results = [e["text"] for e in ev if e["e"] == "tool_result"]
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.startswith("Not run again") for r in results[1:]))

    def test_different_arguments_are_different_calls(self):
        self.model.script = [
            {"calls": [("search_entities", {"q": "a"}), ("search_entities", {"q": "b"})]},
            {"content": "ok"},
        ]
        self.go()
        self.ask()
        self.assertEqual(len(self.tool_calls_seen_by_ster()), 2)

    def test_one_step_may_make_only_so_many_calls(self):
        self.model.script = [
            {
                "calls": [
                    ("search_entities", {"q": str(i)}) for i in range(native.MAX_CALLS_PER_STEP + 3)
                ]
            },
            {"content": "ok"},
        ]
        self.go()
        _, ev = self.ask()
        self.assertEqual(len(self.tool_calls_seen_by_ster()), native.MAX_CALLS_PER_STEP)
        results = [e for e in ev if e["e"] == "tool_result"]
        self.assertEqual(
            len(results), native.MAX_CALLS_PER_STEP + 3
        )  # every call gets an answer, so the conversation stays valid
        self.assertTrue(
            all(
                r["is_error"] and "at most" in r["text"]
                for r in results[native.MAX_CALLS_PER_STEP :]
            )
        )

    def test_a_model_that_never_answers_is_stopped(self):
        self.model.script = [{"calls": [("search_entities", {"q": str(i)})]} for i in range(10)]
        self.go()
        with mock.patch.object(native, "MAX_STEPS", 3):
            _, ev = self.ask()
        done = self.done(ev)
        self.assertEqual(done["status"], "error")
        self.assertIn("3 steps", done["error"])
        self.assertEqual(sum(e["e"] == "step_start" for e in ev), 3)

    # ------------------------------------------------------------------ things going wrong
    def test_a_model_that_cannot_call_tools_is_reported_with_the_servers_words(self):
        self.model.script = [{"error": "model does not support tools", "status": 400}]
        self.go()
        r, ev = self.ask()
        done = self.done(ev)
        self.assertEqual(done["status"], "error")
        self.assertIn("does not support tools", done["error"])
        _, conv = self.bridge.json(f"/api/conversations/{r['conversation_id']}")
        self.assertEqual(
            conv.get("messages"), []
        )  # the failed question is not left in the transcript

    def test_ster_failing_is_reported_to_the_model_which_can_carry_on(self):
        self.go()
        self.ster.tools = [t for t in self.ster.tools if t != "get_overview"]
        self.model.script = [{"calls": [("get_overview", {})]}, {"content": "could not"}]
        _, ev = self.ask()
        self.assertTrue([e for e in ev if e["e"] == "tool_result"][0]["is_error"])
        self.assertEqual(self.done(ev)["answer"], "could not")

    def test_a_model_server_that_goes_away_mid_run_is_an_error_not_a_hang(self):
        self.model.script = [{"calls": [("search_entities", {"q": "a"})]}]
        self.go()
        real_chat, calls = native.OllamaAPI.chat, []

        def chat_then_vanish(api, *a):
            calls.append(1)
            if len(calls) == SECOND_CALL:
                raise OSError("connection refused")
            return real_chat(api, *a)

        with mock.patch.object(native.OllamaAPI, "chat", chat_then_vanish):
            _, ev = self.ask()
        done = self.done(ev)
        self.assertEqual(done["status"], "error")
        self.assertIn("connection refused", done["error"])

    def test_a_question_is_refused_up_front_when_the_server_is_already_gone(self):
        self.go()
        self.model.close()
        runner._SERVERS.clear()
        self.assertEqual(self.bridge.ask("q")[0], 409)

    def test_the_run_stops_between_steps_when_cancelled(self):
        self.model.script = [{"calls": [("search_entities", {"q": str(i)})]} for i in range(10)]
        self.go()
        real_chat = native.OllamaAPI.chat

        def chat_then_cancel(api, *a):
            for run in self.bridge.server.RUNS.values():
                run.cancelled = True
            return real_chat(api, *a)

        with mock.patch.object(native.OllamaAPI, "chat", chat_then_cancel):
            _, ev = self.ask()
        self.assertLessEqual(sum(e["e"] == "step_start" for e in ev), 2)

    # ------------------------------------------------------------------ other servers
    def test_an_openai_compatible_server_works_the_same_way(self):
        model = FakeModel(ollama=False, models=["m1"])
        self.addCleanup(model.close)
        self.ster.replies["get_overview"] = "overview"
        model.script = [
            {"calls": [("get_overview", {})], "tokens": (50, 4)},
            {"content": "fine", "tokens": (60, 2)},
        ]
        self.go(model)
        _, ev = self.ask()
        self.assertEqual(self.done(ev)["answer"], "fine")
        self.assertEqual(
            [(e["input"], e["output"]) for e in ev if e["e"] == "usage"], [(50, 4), (60, 2)]
        )
        self.assertNotIn("options", model.requests[0])  # context size is Ollama's own business
        tool_msg = model.requests[1]["messages"][-1]
        self.assertEqual((tool_msg["role"], tool_msg["tool_call_id"]), ("tool", "id0"))
        assistant = model.requests[1]["messages"][-2]
        self.assertEqual(
            assistant["tool_calls"][0]["function"]["arguments"], "{}"
        )  # a JSON string, as that API wants

    def test_arguments_that_are_not_json_are_sent_back_to_the_model_to_fix(self):
        model = FakeModel(ollama=False, models=["m1"])
        self.addCleanup(model.close)
        model.script = [{"calls": [("run_sparql", "{oops")]}, {"content": "sorry"}]
        self.go(model)
        _, ev = self.ask()
        [res] = [e for e in ev if e["e"] == "tool_result"]
        self.assertTrue(res["is_error"])
        self.assertIn("not valid JSON", res["text"])
        self.assertEqual(self.tool_calls_seen_by_ster(), [])

    # ------------------------------------------------------------------ is there an agent at all?
    def test_ready_when_the_server_has_a_model_that_can_call_tools(self):
        bridge = self.go()
        agent = bridge.json("/api/status")[1]["agent"]
        self.assertEqual((agent["ready"], agent["label"]), (True, "Model"))
        listed = bridge.json("/api/agent-check")[1]["agents"][0]
        self.assertEqual(
            (
                listed["kind"],
                listed["path"],
                listed["version"],
                listed["output"],
                listed["selected"],
            ),
            ("model", self.model.endpoint, "big", "model", True),
        )

    def test_not_ready_when_the_server_does_not_answer(self):
        agent = runner.Agent(
            label="Model", binary="", command=[], kind="model", endpoint="http://127.0.0.1:9/v1"
        )
        status = self.start(agent).json("/api/status")[1]["agent"]
        self.assertEqual(
            (status["ready"], status["reason"]["code"]), (False, "reason.endpoint_down")
        )

    def test_not_ready_when_no_model_can_call_tools_and_it_says_which_it_found(self):
        model = FakeModel(models=["plain", "also-plain"], tools_capable=())
        self.addCleanup(model.close)
        status = self.start(model_agent(model)).json("/api/status")[1]["agent"]
        self.assertEqual(
            (status["ready"], status["reason"]["code"]), (False, "reason.no_tool_model")
        )
        self.assertEqual(status["reason"]["params"]["models"], "plain, also-plain")

    def test_asking_for_a_model_that_cannot_call_tools_says_so(self):
        model = FakeModel(models=["big", "plain"], tools_capable=("big",))
        self.addCleanup(model.close)
        bridge = self.go(model)
        with mock.patch.object(bridge.server, "MODEL", "plain"):
            _, ev = self.ask()
        done = self.done(ev)
        self.assertEqual(
            (done["status"], done["error_code"], done["error_params"]["model"]),
            ("error", "reason.model_not_capable", "plain"),
        )

    def test_a_chosen_model_is_the_one_used(self):
        model = FakeModel(models=["big", "other"], tools_capable=("big", "other"))
        self.addCleanup(model.close)
        model.script = [{"content": "ok"}]
        bridge = self.go(model)
        with mock.patch.object(bridge.server, "MODEL", "other"):
            self.ask()
        self.assertEqual(model.requests[0]["model"], "other")


if __name__ == "__main__":
    unittest.main()
