"""rules.py: the little language a recipe uses to turn an agent's own lines into neutral events."""

from __future__ import annotations

import unittest

from agent_app import rules
from agent_app.rules import Rules
from helpers import WEB  # noqa: F401  (puts agent-app/ on the path)


def run(rule_list, *lines):
    engine, out = Rules(rule_list), []
    for line in lines:
        out += engine.apply(line)
    return out


class Paths(unittest.TestCase):  # noqa: V102
    DOC = {"a": {"b": [{"c": 1}, {"c": 2}], "s": "x"}, "n": 0, "f": False, "none": None}

    def test_fields_and_indexes(self):
        self.assertEqual(rules.get(self.DOC, "$.a.s"), "x")
        self.assertEqual(rules.get(self.DOC, "$.a.b[1].c"), 2)

    def test_the_root(self):
        self.assertIs(rules.get(self.DOC, "$"), self.DOC)

    def test_a_wildcard_projects_over_every_item(self):
        self.assertEqual(rules.get(self.DOC, "$.a.b[*].c"), [1, 2])

    def test_missing_steps_are_missing_not_errors(self):
        for path in ("$.nope", "$.a.nope", "$.a.b[5].c", "$.a.s.deeper", "$.a.s[0]", "$.n.x"):
            self.assertIs(rules.get(self.DOC, path), rules._MISSING, path)

    def test_falsy_values_are_still_values(self):
        self.assertEqual((rules.get(self.DOC, "$.n"), rules.get(self.DOC, "$.f")), (0, False))

    def test_a_non_path_is_missing(self):
        self.assertIs(rules.get(self.DOC, "a.b"), rules._MISSING)


class Matching(unittest.TestCase):  # noqa: V102
    def test_every_listed_path_must_match(self):
        r = [{"when": {"type": "x", "event.kind": "y"}, "emit": {"e": "hit"}}]
        self.assertEqual(len(run(r, {"type": "x", "event": {"kind": "y"}})), 1)
        self.assertEqual(run(r, {"type": "x", "event": {"kind": "z"}}), [])
        self.assertEqual(run(r, {"type": "other", "event": {"kind": "y"}}), [])

    def test_a_list_means_any_of(self):
        r = [{"when": {"type": ["a", "b"]}, "emit": {"e": "hit"}}]
        self.assertEqual([len(run(r, {"type": t})) for t in ("a", "b", "c")], [1, 1, 0])

    def test_exists(self):
        has = [{"when": {"x": {"exists": True}}, "emit": {"e": "hit"}}]
        lacks = [{"when": {"x": {"exists": False}}, "emit": {"e": "hit"}}]
        self.assertEqual(
            (
                len(run(has, {"x": 1})),
                len(run(has, {})),
                len(run(lacks, {})),
                len(run(lacks, {"x": 1})),
            ),
            (1, 0, 1, 0),
        )

    def test_a_missing_path_never_matches_a_value(self):
        self.assertEqual(run([{"when": {"a.b": None}, "emit": {"e": "hit"}}], {"a": {}}), [])

    def test_no_when_matches_everything(self):
        self.assertEqual(len(run([{"emit": {"e": "hit"}}], {}, {"x": 1})), 2)

    def test_every_matching_rule_fires_in_order(self):
        r = [
            {"when": {"t": 1}, "emit": {"e": "first"}},
            {"when": {"t": 1}, "emit": {"e": "second"}},
            {"when": {"t": 2}, "emit": {"e": "never"}},
        ]
        self.assertEqual([e["e"] for e in run(r, {"t": 1})], ["first", "second"])

    def test_a_line_that_is_not_an_object_matches_nothing(self):
        self.assertEqual(run([{"when": {"t": 1}, "emit": {"e": "x"}}], [1, 2], "text", 5, None), [])


class Emitting(unittest.TestCase):  # noqa: V102
    def test_paths_are_filled_and_literals_kept(self):
        r = [{"emit": {"e": "tool", "name": "$.fn.name", "fixed": 7, "flag": True}}]
        self.assertEqual(
            run(r, {"fn": {"name": "run"}}),
            [{"e": "tool", "name": "run", "fixed": 7, "flag": True}],
        )

    def test_an_absent_field_is_left_out_never_written_as_null(self):
        self.assertEqual(
            run([{"emit": {"e": "u", "a": "$.a", "b": "$.b"}}], {"a": 1}), [{"e": "u", "a": 1}]
        )

    def test_an_explicit_null_in_the_line_is_left_out_too(self):
        self.assertEqual(run([{"emit": {"e": "u", "a": "$.a"}}], {"a": None}), [{"e": "u"}])

    def test_zero_and_false_are_kept(self):
        self.assertEqual(
            run([{"emit": {"e": "u", "n": "$.n", "f": "$.f"}}], {"n": 0, "f": False}),
            [{"e": "u", "n": 0, "f": False}],
        )

    def test_nested_objects_are_filled_recursively(self):
        r = [{"emit": {"e": "done", "usage": {"in": "$.u.i", "out": "$.u.o"}}}]
        self.assertEqual(run(r, {"u": {"i": 3}}), [{"e": "done", "usage": {"in": 3}}])

    def test_a_list_of_templates_prints_in_order(self):
        r = [{"emit": [{"e": "one"}, {"e": "two", "v": "$.v"}]}]
        self.assertEqual(run(r, {"v": 9}), [{"e": "one"}, {"e": "two", "v": 9}])

    def test_a_dollar_inside_a_literal_string_is_not_special_unless_it_starts_it(self):
        self.assertEqual(
            run([{"emit": {"e": "x", "t": "costs $5"}}], {}), [{"e": "x", "t": "costs $5"}]
        )


class Expressions(unittest.TestCase):  # noqa: V102
    def test_any_takes_the_first_present_value(self):
        r = [{"emit": {"e": "x", "v": {"any": ["$.a", "$.b", "fallback"]}}}]
        self.assertEqual(run(r, {"b": 2})[0]["v"], 2)
        self.assertEqual(run(r, {})[0]["v"], "fallback")
        self.assertEqual(run(r, {"a": 0, "b": 2})[0]["v"], 0)  # zero is a value

    def test_join_makes_text_of_a_list_or_keeps_a_string(self):
        r = [{"emit": {"e": "x", "t": {"join": "$.content[*].text"}}}]
        self.assertEqual(
            run(r, {"content": [{"text": "a"}, {"text": "b"}, {"other": 1}]})[0]["t"], "ab"
        )
        r2 = [{"emit": {"e": "x", "t": {"join": "$.content"}}}]
        self.assertEqual(run(r2, {"content": "plain"})[0]["t"], "plain")
        self.assertEqual(run(r2, {}), [{"e": "x"}])

    def test_if_chooses_on_presence_and_truth(self):
        r = [{"emit": {"e": "x", "s": {"if": "$.err", "then": "error", "else": "ok"}}}]
        for line, want in (
            ({"err": True}, "error"),
            ({"err": "yes"}, "error"),
            ({"err": False}, "ok"),
            ({"err": ""}, "ok"),
            ({"err": 0}, "ok"),
            ({"err": None}, "ok"),
            ({}, "ok"),
        ):
            self.assertEqual(run(r, line)[0]["s"], want, line)

    def test_if_without_else_leaves_the_field_out(self):
        self.assertEqual(
            run([{"emit": {"e": "x", "s": {"if": "$.err", "then": "error"}}}], {}), [{"e": "x"}]
        )

    def test_if_can_produce_booleans(self):
        r = [{"emit": {"e": "x", "flag": {"if": "$.err", "then": True, "else": False}}}]
        self.assertEqual((run(r, {"err": 1})[0]["flag"], run(r, {})[0]["flag"]), (True, False))


class Memory(unittest.TestCase):  # noqa: V102
    RULES = [
        {
            "when": {"t": "start"},
            "set": {"step": "$.id"},
            "emit": {"e": "step_start", "step": "$.id"},
        },
        {
            "when": {"t": "text"},
            "emit": {"e": "text_delta", "step": {"state": "step"}, "text": "$.x"},
        },
    ]

    def test_a_remembered_value_is_available_to_later_lines(self):
        out = run(
            self.RULES,
            {"t": "start", "id": "s1"},
            {"t": "text", "x": "a"},
            {"t": "start", "id": "s2"},
            {"t": "text", "x": "b"},
        )
        self.assertEqual([e.get("step") for e in out if e["e"] == "text_delta"], ["s1", "s2"])

    def test_before_anything_is_remembered_the_field_is_left_out(self):
        self.assertEqual(
            run(self.RULES, {"t": "text", "x": "a"}), [{"e": "text_delta", "text": "a"}]
        )

    def test_each_run_has_its_own_memory(self):
        run(self.RULES, {"t": "start", "id": "s1"})
        self.assertEqual(
            run(self.RULES, {"t": "text", "x": "a"}), [{"e": "text_delta", "text": "a"}]
        )


class Fragments(unittest.TestCase):  # noqa: V102
    RULES = [
        {
            "when": {"t": "open"},
            "begin": {"key": "$.i", "fields": {"id": "$.id", "name": "$.name"}},
        },
        {"when": {"t": "piece"}, "append": {"key": "$.i", "text": "$.part"}},
        {
            "when": {"t": "close"},
            "flush": {
                "key": "$.i",
                "emit": {
                    "e": "tool_call",
                    "id": "@id",
                    "name": "@name",
                    "input": {"json": "buffer"},
                },
            },
        },
    ]

    def test_pieces_are_assembled_and_parsed(self):
        out = run(
            self.RULES,
            {"t": "open", "i": 0, "id": "c1", "name": "run"},
            {"t": "piece", "i": 0, "part": '{"q": "SEL'},
            {"t": "piece", "i": 0, "part": 'ECT 1"}'},
            {"t": "close", "i": 0},
        )
        self.assertEqual(
            out, [{"e": "tool_call", "id": "c1", "name": "run", "input": {"q": "SELECT 1"}}]
        )

    def test_two_blocks_in_flight_do_not_mix(self):
        out = run(
            self.RULES,
            {"t": "open", "i": 0, "id": "a", "name": "n"},
            {"t": "open", "i": 1, "id": "b", "name": "m"},
            {"t": "piece", "i": 1, "part": '{"y": 2}'},
            {"t": "piece", "i": 0, "part": '{"x": 1}'},
            {"t": "close", "i": 0},
            {"t": "close", "i": 1},
        )
        self.assertEqual([(e["id"], e["input"]) for e in out], [("a", {"x": 1}), ("b", {"y": 2})])

    def test_arguments_that_are_not_json_are_kept_raw(self):
        out = run(
            self.RULES,
            {"t": "open", "i": 0, "id": "c", "name": "n"},
            {"t": "piece", "i": 0, "part": "{oops"},
            {"t": "close", "i": 0},
        )
        self.assertEqual(out[0]["input"], {"raw": "{oops"})

    def test_no_pieces_means_empty_arguments(self):
        out = run(self.RULES, {"t": "open", "i": 0, "id": "c", "name": "n"}, {"t": "close", "i": 0})
        self.assertEqual(out[0]["input"], {})

    def test_closing_something_never_opened_prints_nothing(self):
        self.assertEqual(run(self.RULES, {"t": "close", "i": 7}), [])

    def test_a_piece_for_something_never_opened_is_ignored(self):
        self.assertEqual(
            run(self.RULES, {"t": "piece", "i": 3, "part": "x"}, {"t": "close", "i": 3}), []
        )

    def test_a_block_is_forgotten_once_flushed(self):
        out = run(
            self.RULES,
            {"t": "open", "i": 0, "id": "c", "name": "n"},
            {"t": "close", "i": 0},
            {"t": "close", "i": 0},
        )
        self.assertEqual(len(out), 1)


class Lists(unittest.TestCase):  # noqa: V102
    RULES = [
        {
            "when": {"type": "user"},
            "each": "$.content",
            "where": {"type": "result"},
            "emit": {"e": "tool_result", "id": "$.for", "text": {"join": "$.parts[*].t"}},
        }
    ]

    def test_one_event_per_matching_item(self):
        line = {
            "type": "user",
            "content": [
                {"type": "result", "for": "a", "parts": [{"t": "1"}, {"t": "2"}]},
                {"type": "text"},
                {"type": "result", "for": "b", "parts": []},
            ],
        }
        self.assertEqual(
            run(self.RULES, line),
            [
                {"e": "tool_result", "id": "a", "text": "12"},
                {"e": "tool_result", "id": "b", "text": ""},
            ],
        )

    def test_a_missing_or_non_list_is_ignored(self):
        self.assertEqual(
            run(
                self.RULES,
                {"type": "user"},
                {"type": "user", "content": "text"},
                {"type": "user", "content": {"a": 1}},
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
