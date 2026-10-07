"""The page's prompt tells the agent how to shape results so a map or a timeline can be drawn from them."""

from __future__ import annotations

import unittest

from agent_app import server


class ShapingResults(unittest.TestCase):  # noqa: V102
    def test_a_count_per_place_is_asked_to_keep_the_places_iri(self):
        text = server.SYSTEM_PROMPT
        self.assertIn("IRI in its own", text)
        self.assertIn(
            "COUNT(?store) AS ?stores", text
        )  # a concrete query shape beats a description
        self.assertIn("prints the number on each", text)

    def test_a_list_is_asked_to_lead_with_the_entity_iri(self):
        self.assertIn("each entity's IRI in the first column", server.SYSTEM_PROMPT)

    def test_an_aggregate_answer_offers_the_view(self):
        text = server.SYSTEM_PROMPT
        self.assertIn("offering to show them on a map or a timeline", text)
        self.assertIn("returns the entity IRIs", text)

    def test_a_request_for_a_view_is_answered_with_its_query(self):
        self.assertIn("asks for a map or a timeline", server.SYSTEM_PROMPT)

    def test_the_prompt_stays_generic(self):
        # it is handed to every agent on every graph: no project, brand or vocabulary is named
        for word in ("adeo", "retail", "Leroy", "wgs84"):
            self.assertNotIn(word.lower(), server.SYSTEM_PROMPT.lower())

    def test_the_step_question_rule_is_still_there(self):
        self.assertIn("`question` argument", server.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
