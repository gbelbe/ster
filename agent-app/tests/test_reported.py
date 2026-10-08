"""The model an agent said it ran is what the page reports to ster with the answer."""

from __future__ import annotations

import unittest

from agent_app import reported

FIRST, SECOND, KEY = "claude-haiku-4-5", "second", "model"


def session(**fields) -> dict:
    return {"e": "session", **fields}


class ModelField(unittest.TestCase):  # noqa: V102
    def test_the_session_event_that_names_a_model_gives_it(self):
        events = [{"e": "step_start"}, session(model=FIRST)]
        self.assertEqual(reported.model_field(events), {KEY: FIRST})

    def test_the_first_event_that_names_one_wins(self):
        self.assertEqual(
            reported.model_field([session(model=FIRST), session(model=SECOND)]), {KEY: FIRST}
        )

    def test_a_session_without_a_model_and_other_events_give_nothing(self):
        self.assertEqual(reported.model_field([session(), {"e": "done", KEY: SECOND}]), {})
        self.assertEqual(reported.model_field([]), {})


if __name__ == "__main__":
    unittest.main()
