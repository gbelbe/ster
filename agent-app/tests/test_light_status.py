"""The page's every-few-seconds check of ster is one plain request that leaves no trace, not an MCP handshake."""

from __future__ import annotations

import unittest
import urllib.error
from unittest import mock

from agent_app import runner
from helpers import FakeSter
from test_server import BridgeCase  # noqa: F401  (the harness the page's end-to-end tests share)

AUTH = {"Authorization": "Bearer t"}
OVERVIEW = "/api/overview"
MCP = "/mcp"
GRAPH = "graph"


class GraphOf(unittest.TestCase):  # noqa: V102
    def test_the_graph_is_what_the_overview_says_with_its_own_stamp(self):
        graph = runner.graph_of(
            {
                "title": "T",
                "ontology_uri": "https://x/o",
                "file": "f.ttl",
                "server": {"started": "2026-01-01T10:00:00Z"},
                "graph": {"triples": 12, "fingerprint": "ab"},
            }
        )
        self.assertEqual(
            graph,
            {
                "title": "T",
                "ontology_uri": "https://x/o",
                "file": "f.ttl",
                "started": "2026-01-01T10:00:00Z",
                "triples": 12,
                "fingerprint": "ab",
            },
        )

    def test_an_overview_without_a_server_or_graph_still_has_the_fields_empty(self):
        graph = runner.graph_of({})
        self.assertEqual((graph["title"], graph["started"]), (None, None))


class Light(unittest.TestCase):  # noqa: V102
    def setUp(self):
        self.ster = FakeSter()
        self.addCleanup(self.ster.close)
        self.base = f"http://127.0.0.1:{self.ster.port}"

    def test_one_plain_request_says_it_is_up_and_what_it_serves(self):
        seen = runner.check_ster_light(self.base, AUTH)
        self.assertTrue(seen["up"])
        self.assertEqual(seen[GRAPH]["fingerprint"], self.ster.fingerprint)
        self.assertEqual([(m, p) for m, p, _h, _b in self.ster.log], [("GET", OVERVIEW)])

    def test_the_token_goes_with_the_request(self):
        runner.check_ster_light(self.base, AUTH)
        self.assertEqual(self.ster.log[0][2]["Authorization"], AUTH["Authorization"])

    def test_it_makes_no_mcp_call_so_ster_has_nothing_to_trace(self):
        runner.check_ster_light(self.base, AUTH)
        self.assertFalse([p for _m, p, _h, _b in self.ster.log if p == MCP])

    def test_a_ster_that_is_not_there_is_down_with_the_reason(self):
        dead = FakeSter()
        base = f"http://127.0.0.1:{dead.port}"
        dead.close()
        seen = runner.check_ster_light(base, AUTH, timeout=1)
        self.assertFalse(seen["up"])
        self.assertNotIn(GRAPH, seen)
        self.assertTrue(seen["error"])

    def test_a_refused_token_is_down_too(self):
        refused = urllib.error.HTTPError(self.base, 401, "Unauthorized", {}, None)  # type: ignore[arg-type]
        with mock.patch.object(runner.urllib.request, "urlopen", side_effect=refused):
            seen = runner.check_ster_light(self.base, AUTH)
        self.assertFalse(seen["up"])

    def test_something_that_answers_but_is_not_json_is_down(self):
        with mock.patch.object(runner.json, "load", side_effect=ValueError("not json")):
            self.assertFalse(runner.check_ster_light(self.base, AUTH)["up"])


class PageStatus(BridgeCase):  # noqa: V102
    def test_the_pages_status_asks_ster_with_the_light_request_and_still_reports_its_graph(self):
        bridge = self.start()
        _, status = bridge.json("/api/status")
        self.assertTrue(status["ster"])
        self.assertEqual(status[GRAPH]["fingerprint"], self.ster.fingerprint)
        asked = [(m, p) for m, p, _h, _b in self.ster.log]
        self.assertIn(("GET", OVERVIEW), asked)
        self.assertNotIn(("POST", MCP), asked)


if __name__ == "__main__":
    unittest.main()
