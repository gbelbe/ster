"""A conversation that outlives its graph: the follow-up starts a fresh agent session and is told the graph changed."""

from __future__ import annotations

import unittest

from agent_app import graph_switch
from helpers import agent_script
from test_server import (  # noqa: F401  (the harness the page's end-to-end tests share)
    BridgeCase,
    custom,
)

OLD, NEW = "2438f633db5379a2", "23d53a064b74cace"
SHOP = {"title": "Retail", "triples": 26670, "fingerprint": NEW}
ECHO = "import sys; print('asked: ' + sys.argv[1])"
ASKED = "asked: "
GRAPH, QUESTION, PROMPT = "graph", "how many?", "prompt"
SHOP_NAME, FOLLOW_UP, ANSWER, FILE, FRESH = (
    "Retail (26670 triples)",
    "and per class?",
    "answer",
    "f.ttl",
    "fresh_session",
)


def turn(graph=None, **kw) -> dict:
    return {PROMPT: QUESTION, **({GRAPH: graph} if graph else {}), **kw}


class Changed(unittest.TestCase):  # noqa: V102
    def test_a_different_graph_than_the_last_answered_turns_is_a_change(self):
        self.assertTrue(graph_switch.changed([turn(OLD)], NEW))

    def test_the_same_graph_is_not(self):
        self.assertFalse(graph_switch.changed([turn(NEW)], NEW))

    def test_only_the_last_turn_that_knew_its_graph_counts(self):
        self.assertTrue(graph_switch.changed([turn(NEW), turn(OLD), turn()], NEW))
        self.assertFalse(graph_switch.changed([turn(OLD), turn(NEW), turn()], NEW))

    def test_nothing_to_compare_is_no_change(self):
        self.assertFalse(graph_switch.changed([], NEW))
        self.assertFalse(graph_switch.changed([turn()], NEW))
        self.assertFalse(graph_switch.changed([turn(OLD)], None))


class Naming(unittest.TestCase):  # noqa: V102
    def test_the_title_comes_first_then_the_ontology_then_the_file(self):
        self.assertEqual(graph_switch.name_of(SHOP), SHOP_NAME)
        self.assertEqual(
            graph_switch.name_of({"ontology_uri": "https://x/o", "file": FILE}), "https://x/o"
        )
        self.assertEqual(graph_switch.name_of({"file": FILE}), FILE)

    def test_a_graph_nothing_is_known_about_still_has_a_name(self):
        self.assertEqual(graph_switch.name_of(None), "a different graph")

    def test_the_note_says_not_to_reuse_and_to_look_again(self):
        note = graph_switch.note_for(SHOP)
        self.assertIn(SHOP_NAME, note)
        self.assertIn("do not reuse", note)
        self.assertIn("get_overview", note)


class Afresh(unittest.TestCase):  # noqa: V102
    def test_starting_afresh_forgets_the_old_session_and_transcript_and_adds_the_note(self):
        conv = {"session_id": "old-session", "messages": [{"role": "user", "content": "x"}]}
        current = turn()
        graph_switch.start_afresh(conv, current, SHOP)
        self.assertEqual((conv["session_id"], conv["messages"]), (None, []))
        self.assertTrue(graph_switch.prompt_of(current).startswith("[Note from the page"))
        self.assertTrue(graph_switch.prompt_of(current).endswith(QUESTION))
        self.assertEqual(current[PROMPT], QUESTION)  # what the person wrote is kept as it was
        self.assertEqual(current[FRESH], {GRAPH: NEW, "name": SHOP_NAME})

    def test_without_a_fresh_start_the_agent_is_asked_what_was_written(self):
        self.assertEqual(graph_switch.prompt_of(turn()), QUESTION)


class Flow(BridgeCase):  # noqa: V102
    """The page end to end: the second question, asked after ster began serving another graph."""

    def start_echo(self):
        script = agent_script(self.scripts, "echo.py", ECHO)
        bridge = self.start(custom(script, "{prompt}"))
        return bridge

    def ask_twice(self, bridge, change_graph):
        _, first = bridge.ask(QUESTION)
        bridge.events(first["turn_id"])
        if change_graph:
            self.ster.fingerprint = "ffffffffffffffff"
        _, second = bridge.ask(FOLLOW_UP, first["conversation_id"])
        bridge.events(second["turn_id"])
        _, conv = bridge.json(f"/api/conversations/{first['conversation_id']}")
        return conv["turns"]

    def test_a_follow_up_after_a_graph_change_starts_afresh_and_is_told(self):
        first, second = self.ask_twice(self.start_echo(), change_graph=True)
        self.assertNotIn(FRESH, first)
        self.assertEqual(second[FRESH][GRAPH], "ffffffffffffffff")
        self.assertIn("Note from the page", second[ANSWER])
        self.assertTrue(second[ANSWER].endswith(FOLLOW_UP))
        self.assertEqual(second[PROMPT], FOLLOW_UP)

    def test_a_follow_up_on_the_same_graph_is_asked_as_written(self):
        _, second = self.ask_twice(self.start_echo(), change_graph=False)
        self.assertNotIn(FRESH, second)
        self.assertEqual(second[ANSWER], ASKED + FOLLOW_UP)


if __name__ == "__main__":
    unittest.main()
