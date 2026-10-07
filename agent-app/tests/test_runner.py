"""runner.py: choosing and building the agent command, the neutral-event contract, and the ster check."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_app import runner
from helpers import FakeSter


def agent(**kw):
    base = {"label": "A", "binary": "python3", "command": ["a", "{prompt}"]}
    return runner.Agent(**{**base, **kw})


class SterToolNames(unittest.TestCase):  # noqa: V102
    def test_any_prefix_maps_to_the_ster_name(self):
        for raw in (
            "run_sparql",
            "mcp__ster__run_sparql",
            "ster_run_sparql",
            "ster.run_sparql",
            "server:run_sparql",
        ):
            self.assertEqual(runner.ster_tool(raw), "run_sparql", raw)

    def test_longest_name_wins(self):
        self.assertEqual(runner.ster_tool("x_get_current_context"), "get_current_context")

    def test_unknown_tool_is_left_alone(self):
        self.assertEqual(runner.ster_tool("other_tool"), "other_tool")

    def test_a_suffix_is_not_enough_without_a_separator(self):
        self.assertEqual(runner.ster_tool("myrun_sparql_x"), "myrun_sparql_x")


class CommandTemplate(unittest.TestCase):  # noqa: V102
    def build(self, a, **kw):
        args = {
            "prompt": "why?",
            "system_prompt": "be brief",
            "session": None,
            "model": None,
            "ster_url": "http://h/mcp",
            "ster_token": "tok",
            "recipes_dir": Path("/r"),
        }
        return a.argv(runner.Invocation(**{**args, **kw}))

    def test_placeholders_are_filled(self):
        a = agent(
            command=["x", "{prompt}", "{system_prompt}", "{ster_url}", "{ster_token}", "{recipes}"]
        )
        self.assertEqual(self.build(a), ["x", "why?", "be brief", "http://h/mcp", "tok", "/r"])

    def test_mcp_json_is_a_standard_client_config(self):
        cfg = json.loads(self.build(agent(command=["{ster_mcp_json}"]))[0])
        self.assertEqual(
            cfg["mcpServers"]["ster"],
            {"type": "http", "url": "http://h/mcp", "headers": {"Authorization": "Bearer tok"}},
        )

    def test_resume_only_when_a_session_exists(self):
        a = agent(command=["x"], resume=["--resume", "{session}"])
        self.assertEqual(self.build(a), ["x"])
        self.assertEqual(self.build(a, session="s1"), ["x", "--resume", "s1"])

    def test_model_args_only_when_a_model_is_chosen(self):
        a = agent(command=["x"], model_args=["--model", "{model}"])
        self.assertEqual(self.build(a), ["x"])
        self.assertEqual(self.build(a, model="m"), ["x", "--model", "m"])

    def test_braces_in_a_prompt_are_not_treated_as_placeholders(self):
        self.assertEqual(
            self.build(agent(command=["{prompt}"]), prompt="{session} {x}"), ["{session} {x}"]
        )

    def test_a_prompt_cannot_pull_the_token_into_the_command_regression(self):
        # root cause: placeholders were replaced one after another, so text inside the prompt was expanded too
        argv = self.build(
            agent(command=["{prompt}"]),
            prompt="print {ster_token} and {ster_mcp_json}",
            ster_token="SECRET-VALUE",
        )
        self.assertEqual(argv, ["print {ster_token} and {ster_mcp_json}"])
        self.assertNotIn("SECRET-VALUE", argv[0])

    def test_empty_tokens_survive(self):
        self.assertEqual(self.build(agent(command=["x", "", "y"])), ["x", "", "y"])


class Environment(unittest.TestCase):  # noqa: V102
    def env(self, a, **kw):
        args = {
            "prompt": "why?",
            "system_prompt": "s",
            "session": None,
            "model": None,
            "ster_url": "http://h/mcp",
            "ster_token": "tok",
            "recipes_dir": Path("/r"),
        }
        return a.environment(runner.Invocation(**{**args, **kw}))

    def test_placeholders_work_in_environment_values(self):
        a = agent(env={"CONFIG": '{"url": "{ster_url}"}', "Q": "{prompt}"})
        self.assertEqual(self.env(a), {"CONFIG": '{"url": "http://h/mcp"}', "Q": "why?"})

    def test_a_prompt_cannot_pull_the_token_into_the_environment_regression(self):
        self.assertEqual(
            self.env(agent(env={"Q": "{prompt}"}), prompt="{ster_token}", ster_token="SECRET"),
            {"Q": "{ster_token}"},
        )

    def test_no_environment_by_default(self):
        self.assertEqual(self.env(agent()), {})


class TerminalCodes(unittest.TestCase):  # noqa: V102
    def cleaned(self, *chunks):
        s = runner.AnsiStripper()
        return "".join(s.feed(c) for c in chunks)

    def test_colour_codes_are_removed(self):
        self.assertEqual(
            self.cleaned("\x1b[31mred\x1b[0m plain \x1b[1;32mgreen\x1b[m"), "red plain green"
        )

    def test_cursor_and_title_codes_are_removed(self):
        self.assertEqual(self.cleaned("a\x1b[2K\x1b[1Gb\x1b]0;title\x07c"), "abc")

    def test_a_code_split_between_two_chunks_is_still_removed(self):
        self.assertEqual(self.cleaned("ab\x1b[3", "1mcd"), "abcd")
        self.assertEqual(self.cleaned("ab\x1b", "[0mcd"), "abcd")

    def test_ordinary_text_and_non_ascii_pass_through(self):
        self.assertEqual(self.cleaned("Brico Dépôt → 18 ✓"), "Brico Dépôt → 18 ✓")

    def test_a_lone_escape_at_the_very_end_is_not_lost_forever(self):
        s = runner.AnsiStripper()
        self.assertEqual(s.feed("end\x1b"), "end")
        self.assertEqual(s.feed("x"), "\x1bx")


class Recipes(unittest.TestCase):  # noqa: V102
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def put(self, name, data):
        (self.dir / name).write_text(data if isinstance(data, str) else json.dumps(data))

    def test_a_recipe_becomes_an_agent(self):
        self.put(
            "a.json",
            {
                "label": "A",
                "binary": "python3",
                "command": ["x"],
                "translate": ["py", "{recipes}/t.py"],
                "verified": True,
                "priority": 5,
            },
        )
        [a] = runner.load_recipes(self.dir)
        self.assertEqual((a.label, a.verified, a.priority, a.source), ("A", True, 5, "a.json"))
        self.assertEqual(a.translate, ["py", f"{self.dir}/t.py"])

    def test_rules_and_environment_are_read_from_the_recipe(self):
        self.put(
            "a.json",
            {
                "label": "A",
                "binary": "b",
                "command": ["x"],
                "stream": [{"when": {"type": "t"}, "emit": {"e": "done"}}],
                "env": {"K": "{prompt}"},
            },
        )
        [a] = runner.load_recipes(self.dir)
        self.assertEqual((a.stream[0]["emit"], a.env), ({"e": "done"}, {"K": "{prompt}"}))

    def test_a_broken_recipe_is_skipped_not_fatal(self):
        self.put("bad.json", "{not json")
        self.put("missing.json", {"label": "no command"})
        self.put("ok.json", {"label": "Ok", "binary": "b", "command": ["x"]})
        self.assertEqual([a.label for a in runner.load_recipes(self.dir)], ["Ok"])

    def test_recipes_are_ordered_by_priority_then_label(self):
        self.put("1.json", {"label": "Z", "binary": "b", "command": ["x"], "priority": 1})
        self.put("2.json", {"label": "A", "binary": "b", "command": ["x"], "priority": 2})
        self.assertEqual([a.label for a in runner.load_recipes(self.dir)], ["Z", "A"])

    def test_an_empty_folder_gives_no_recipes(self):
        self.assertEqual(runner.load_recipes(self.dir), [])

    SHIPPED = Path(__file__).resolve().parent.parent / "agent_app" / "recipes"

    def shipped(self, source):
        return next(a for a in runner.load_recipes(self.SHIPPED) if a.source == source)

    def test_the_shipped_claude_recipe_is_valid(self):
        a = self.shipped("claude-code.json")
        self.assertEqual((a.binary, a.output, a.verified), ("claude", "events", True))
        self.assertTrue(a.stream)  # pure data: no script of its own
        self.assertIsNone(a.translate)

    def test_the_shipped_opencode_recipe_is_valid(self):
        a = self.shipped("opencode.json")
        self.assertEqual(
            (a.binary, a.output, a.stdin, a.verified), ("opencode", "events", "none", True)
        )
        self.assertTrue(a.stream)
        self.assertIsNone(a.translate)

    def test_every_shipped_recipe_is_pure_data(self):
        for a in runner.load_recipes(self.SHIPPED):
            self.assertTrue(a.kind == "model" or (a.stream and not a.translate), a.label)

    def test_unverified_examples_are_not_loaded_but_are_valid_recipes(self):
        loaded = {a.source for a in runner.load_recipes(self.SHIPPED)}
        self.assertNotIn("codex.json", loaded)  # an example: copied up to enable
        examples = {a.source: a for a in runner.load_recipes(self.SHIPPED / "examples")}
        self.assertFalse(examples["codex.json"].verified)  # and it says so

    def test_only_recipes_that_have_been_run_for_real_are_marked_verified(self):
        for a in runner.load_recipes(self.SHIPPED / "examples"):
            self.assertFalse(a.verified, a.label)

    def test_the_codex_example_keeps_the_token_out_of_the_command_line(self):
        a = runner.load_recipes(self.SHIPPED / "examples")[0]
        argv = a.argv(
            runner.Invocation("q", "s", None, None, "http://h/mcp", "SECRET", self.SHIPPED)
        )
        self.assertNotIn("SECRET", " ".join(argv))  # visible in a process list otherwise
        self.assertEqual(
            a.environment(
                runner.Invocation("q", "s", None, None, "http://h/mcp", "SECRET", self.SHIPPED)
            ),
            {"ASK_STER_TOKEN": "SECRET"},
        )
        self.assertIn('mcp_servers.ster.url="http://h/mcp"', argv)

    def test_the_shipped_ollama_recipe_is_a_model_server_not_a_program(self):
        a = self.shipped("ollama.json")
        self.assertEqual(
            (a.kind, a.endpoint, a.command, a.verified),
            ("model", "http://localhost:11434/v1", [], True),
        )

    def test_opencode_is_told_where_ster_is_and_may_use_nothing_else(self):
        env = self.shipped("opencode.json").environment(
            runner.Invocation("q", "s", None, None, "http://h/mcp", "TOK", self.SHIPPED)
        )
        cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual(cfg["mcp"]["ster"]["url"], "http://h/mcp")
        self.assertEqual(cfg["mcp"]["ster"]["headers"]["Authorization"], "Bearer TOK")
        rules = list(cfg["permission"].items())
        self.assertEqual(
            rules, [("*", "deny"), ("ster_*", "allow")]
        )  # order matters: the last matching rule wins

    def test_the_system_prompt_and_question_travel_as_one_message(self):
        argv = self.shipped("opencode.json").argv(
            runner.Invocation("why?", "be brief", None, None, "u", "t", self.SHIPPED)
        )
        self.assertEqual(argv[-1], "be brief\n\nQuestion: why?")
        self.assertEqual(argv[:4], ["opencode", "run", "--format", "json"])

    def test_opencode_resumes_by_session_and_takes_a_model(self):
        a = self.shipped("opencode.json")
        argv = a.argv(runner.Invocation("q", "s", "ses_1", "prov/model", "u", "t", self.SHIPPED))
        self.assertIn(["--session", "ses_1"], [argv[i : i + 2] for i in range(len(argv))])
        self.assertIn(["-m", "prov/model"], [argv[i : i + 2] for i in range(len(argv))])


class ModelServers(unittest.TestCase):  # noqa: V102
    def test_a_model_recipe_needs_an_endpoint_not_a_program(self):
        d = Path(tempfile.mkdtemp())
        (d / "m.json").write_text(
            json.dumps({"label": "M", "type": "model", "endpoint": "http://h:1/v1"})
        )
        [a] = runner.load_recipes(d)
        self.assertEqual((a.kind, a.endpoint, a.binary), ("model", "http://h:1/v1", ""))

    def test_a_model_url_in_the_environment_makes_a_model_agent(self):
        a = runner.from_env({"ASK_MODEL_URL": "http://h:1/v1"})
        self.assertEqual(
            (a.kind, a.endpoint, a.label, a.priority), ("model", "http://h:1/v1", "Model server", 0)
        )
        self.assertEqual(
            runner.from_env({"ASK_MODEL_URL": "http://h:1/v1", "ASK_AGENT_LABEL": "Local"}).label,
            "Local",
        )

    def test_a_command_in_the_environment_wins_over_a_model_url(self):
        self.assertEqual(
            runner.from_env({"ASK_AGENT_CMD": "bot", "ASK_MODEL_URL": "http://h:1/v1"}).kind,
            "command",
        )

    def test_availability_means_a_model_that_can_call_tools(self):
        from helpers import FakeModel

        runner._SERVERS.clear()
        up, plain = (
            FakeModel(models=["big"], tools_capable=("big",)),
            FakeModel(models=["plain"], tools_capable=()),
        )
        self.addCleanup(up.close)
        self.addCleanup(plain.close)

        def mk(m):
            return runner.Agent(label="M", binary="", command=[], kind="model", endpoint=m.endpoint)

        self.assertTrue(mk(up).available())
        self.assertFalse(mk(plain).available())
        self.assertEqual(
            (mk(plain).path(), mk(up).path()), (plain.endpoint, up.endpoint)
        )  # reachable, just no usable model
        self.assertFalse(
            runner.Agent(
                label="M", binary="", command=[], kind="model", endpoint="http://127.0.0.1:9/v1"
            ).available()
        )

    def test_the_reason_a_model_server_is_unusable(self):
        from helpers import FakeModel

        runner._SERVERS.clear()
        plain = FakeModel(models=["a", "b"], tools_capable=())
        self.addCleanup(plain.close)
        down = runner.Agent(
            label="M", binary="", command=[], kind="model", endpoint="http://127.0.0.1:9/v1"
        )
        self.assertEqual(runner.why_none([down], None, None)["code"], "reason.endpoint_down")
        none = runner.Agent(label="M", binary="", command=[], kind="model", endpoint=plain.endpoint)
        why = runner.why_none([none], None, None)
        self.assertEqual((why["code"], why["params"]["models"]), ("reason.no_tool_model", "a, b"))
        self.assertEqual(runner.why_none([], none, None)["code"], "reason.no_tool_model")

    def test_a_program_recipe_missing_beside_a_model_server_without_models_still_names_the_server(
        self,
    ):
        from helpers import FakeModel

        runner._SERVERS.clear()
        plain = FakeModel(models=["a"], tools_capable=())
        self.addCleanup(plain.close)
        recipes = [
            runner.Agent(label="P", binary="no-such-program-xyz", command=["x"]),
            runner.Agent(label="M", binary="", command=[], kind="model", endpoint=plain.endpoint),
        ]
        self.assertIn(
            runner.why_none(recipes, None, None)["code"],
            ("reason.none_installed", "reason.no_tool_model"),
        )


class CustomCommand(unittest.TestCase):  # noqa: V102
    def test_not_set_means_none(self):
        self.assertIsNone(runner.from_env({}))

    def test_json_list(self):
        a = runner.from_env({"ASK_AGENT_CMD": '["my agent", "--q", "{prompt}"]'})
        self.assertEqual(
            (a.binary, a.command, a.output, a.stdin),
            ("my agent", ["my agent", "--q", "{prompt}"], "text", "none"),
        )

    def test_shell_string(self):
        a = runner.from_env({"ASK_AGENT_CMD": "bot --ask '{prompt}'"})
        self.assertEqual(a.command, ["bot", "--ask", "{prompt}"])

    def test_without_a_prompt_placeholder_the_prompt_goes_to_stdin(self):
        self.assertEqual(runner.from_env({"ASK_AGENT_CMD": "bot"}).stdin, "prompt")

    def test_overrides(self):
        a = runner.from_env(
            {
                "ASK_AGENT_CMD": "bot",
                "ASK_AGENT_OUTPUT": "events",
                "ASK_AGENT_LABEL": "Bot",
                "ASK_AGENT_STDIN": "none",
            }
        )
        self.assertEqual((a.output, a.label, a.stdin), ("events", "Bot", "none"))


class Selection(unittest.TestCase):
    present = agent(label="Here", binary="python3", priority=2, source="here.json")
    other = agent(label="Also", binary="python3", priority=1, source="also.json")
    absent = agent(label="Gone", binary="no-such-program-xyz", priority=0, source="gone.json")

    def test_the_first_recipe_that_is_set_up_wins(self):
        self.assertIs(
            runner.select(
                sorted([self.present, self.other, self.absent], key=lambda a: a.priority),
                None,
                None,
            ),
            self.other,
        )

    def test_a_missing_program_is_skipped(self):
        self.assertIs(runner.select([self.absent, self.present], None, None), self.present)

    def test_the_custom_command_beats_every_recipe(self):
        custom = agent(label="Custom")
        self.assertIs(runner.select([self.present], custom, None), custom)

    def test_a_custom_command_with_a_missing_program_means_no_agent(self):
        self.assertIsNone(runner.select([self.present], agent(binary="no-such-program-xyz"), None))

    def test_a_recipe_can_be_asked_for_by_file_or_label(self):
        for wanted in ("here", "here.json", "HERE"):
            self.assertIs(
                runner.select([self.other, self.present], None, wanted), self.present, wanted
            )

    def test_asking_for_an_absent_recipe_means_no_agent(self):
        self.assertIsNone(runner.select([self.absent, self.present], None, "gone"))

    def test_nothing_set_up_means_none(self):
        self.assertIsNone(runner.select([self.absent], None, None))

    def test_the_reason_says_why(self):
        self.assertEqual(runner.why_none([], None, None)["code"], "reason.no_recipes")
        self.assertEqual(
            runner.why_none([self.absent], None, None)["code"], "reason.none_installed"
        )
        self.assertEqual(
            runner.why_none([self.absent], None, "zzz")["code"], "reason.unknown_recipe"
        )
        self.assertEqual(runner.why_none([], agent(binary="b"), None)["params"], {"binary": "b"})

    def test_every_reason_has_an_english_fallback_text(self):
        for why in (
            runner.why_none([], None, None),
            runner.why_none([self.absent], None, "z"),
            runner.why_none([], agent(), None),
        ):
            self.assertTrue(why["text"])


def ev(kind, **kw):
    return {"e": kind, "t": 0, **kw}


class Contract(unittest.TestCase):  # noqa: V102
    def full_run(self):
        return [
            ev("turn_start"),
            ev("session", session_id="s"),
            ev("step_start", step="1"),
            ev("usage", step="1", input=1),
            ev("tool_call", step="1", id="c", name="run_sparql", input={}),
            ev("tool_result", id="c", text=""),
            ev("trace", id="c"),
            ev("ster_seen", n=1),
            ev("done", status="completed", cost_usd=0.1),
        ]

    def test_a_complete_run_delivers_everything(self):
        c = runner.contract(self.full_run())
        self.assertEqual(
            c["observed"],
            {
                "stream_steps": True,
                "token_usage": True,
                "cost": True,
                "resume": True,
                "sparql_rows": True,
            },
        )
        self.assertEqual(
            (c["counts"], c["problems"]),
            ({"steps": 1, "tool_calls": 1, "sparql": 1, "traced": 1}, []),
        )

    def test_a_text_only_run_reports_what_it_lacks(self):
        c = runner.contract(
            [ev("turn_start"), ev("step_start", step="agent"), ev("done", status="completed")]
        )
        self.assertEqual(
            c["observed"],
            {
                "stream_steps": True,
                "token_usage": False,
                "cost": False,
                "resume": False,
                "sparql_rows": None,
            },
        )

    def test_no_sparql_means_rows_cannot_be_judged(self):
        events = [e for e in self.full_run() if e["e"] not in ("tool_call", "tool_result", "trace")]
        self.assertIsNone(runner.contract(events)["observed"]["sparql_rows"])

    def test_a_query_without_a_trace_is_flagged(self):
        events = [e for e in self.full_run() if e["e"] != "trace"]
        self.assertFalse(runner.contract(events)["observed"]["sparql_rows"])

    def test_queries_run_but_ster_saw_none_points_at_another_ster(self):
        events = [e for e in self.full_run() if e["e"] != "trace"]
        events = [ev("ster_seen", n=0) if e["e"] == "ster_seen" else e for e in events]
        self.assertIn(
            "prob.no_ster_traces", [p["code"] for p in runner.contract(events)["problems"]]
        )

    def test_a_missing_final_event_is_flagged(self):
        events = [e for e in self.full_run() if e["e"] != "done"]
        self.assertIn("prob.no_done", [p["code"] for p in runner.contract(events)["problems"]])

    def test_a_step_without_usage_breaks_token_reporting(self):
        events = self.full_run() + [ev("step_start", step="2")]
        self.assertFalse(runner.contract(events)["observed"]["token_usage"])

    def test_an_empty_run(self):
        c = runner.contract([])
        self.assertEqual(c["counts"]["steps"], 0)
        self.assertEqual([p["code"] for p in c["problems"]], ["prob.no_done"])


class SterCheck(unittest.TestCase):  # noqa: V102
    def test_a_healthy_ster(self):
        s = FakeSter()
        self.addCleanup(s.close)
        r = runner.check_ster(s.url, {})
        self.assertEqual(
            (r["up"], r["missing"], r["file"], r["instructions"]),
            (True, [], "/project/data.ttl", True),
        )
        self.assertEqual(len(r["tools"]), 10)

    def test_missing_required_tools_are_named(self):
        s = FakeSter(tools=["get_overview", "get_entity"])
        self.addCleanup(s.close)
        self.assertEqual(
            runner.check_ster(s.url, {})["missing"],
            ["get_vocabulary", "search_entities", "run_sparql"],
        )

    def test_nothing_listening(self):
        r = runner.check_ster("http://127.0.0.1:9/mcp", {})
        self.assertFalse(r["up"])
        self.assertIn("error", r)

    def test_headers_are_sent(self):
        s = FakeSter()
        self.addCleanup(s.close)
        runner.check_ster(s.url, {"Authorization": "Bearer abc"})
        self.assertTrue(all(h.get("Authorization") == "Bearer abc" for _, _, h, _ in s.log))


if __name__ == "__main__":
    unittest.main()
