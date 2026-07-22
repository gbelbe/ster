"""Hover tooltip on lint-flagged (red/orange) tree nodes: a count of error/warning
issues by type. The full list lives in the detail panel (open by clicking the node)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ster import store
from ster.plugins.semanticlint.report import issue_summary
from ster.tui.app import OntologyApp

DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"


def _iss(severity: str) -> dict:
    return {"severity": severity, "check_id": "X", "message": "m", "subject": "u"}


def test_issue_summary_counts_errors_and_warnings_by_type() -> None:
    assert issue_summary([_iss("error"), _iss("error"), _iss("warning")]) == (
        "⊘ 2 errors · ⚠ 1 warning"
    )
    assert issue_summary([_iss("error")]) == "⊘ 1 error"  # singular
    assert issue_summary([_iss("warning"), _iss("warning")]) == "⚠ 2 warnings"


def test_issue_summary_ignores_info_and_empty() -> None:
    assert issue_summary([]) is None
    assert issue_summary([_iss("info")]) is None  # info is not red/orange
    assert issue_summary([_iss("error"), _iss("info")]) == "⊘ 1 error"  # info not counted


def test_hovering_a_flagged_node_shows_its_issue_counts() -> None:
    """The tree tooltip reflects the hovered node's error/warning counts; a clean node
    (no issues, not a commented property) has no tooltip."""

    async def scenario() -> None:
        from textual.widgets import Tree

        app = OntologyApp(store.load(DEMO), source="demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#ont-tree", Tree)  # Dog (a class) lives in the ontology pane
            tree.focus()
            await pilot.press("e")  # expand every node so each has a real line
            await pilot.pause()
            app._lint_issues = {ZOO + "Dog": [_iss("error"), _iss("warning")]}

            tree.hover_line = app._uri_nodes[ZOO + "Dog"].line
            await pilot.pause()
            assert tree.tooltip == "⊘ 1 error · ⚠ 1 warning"

            tree.hover_line = app._uri_nodes[ZOO + "Eagle"].line  # no issues → no lint tooltip
            await pilot.pause()
            assert tree.tooltip is None

    asyncio.run(scenario())
