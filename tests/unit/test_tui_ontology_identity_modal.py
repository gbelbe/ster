"""Unit tests for the ontology-identity modal (domain / path / separator / prefix)."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Input, RadioButton

from ster.tui.ontology_identity_modal import _SEP_OPTIONS, OntologyIdentityModal


class _Host(App):
    def compose(self) -> ComposeResult:
        return iter(())


def _run(coro_factory) -> None:  # noqa: ANN001
    asyncio.run(coro_factory())


def test_sep_options_are_hash_then_slash() -> None:
    assert [ch for _, ch in _SEP_OPTIONS] == ["#", "/"]


def test_returns_each_part_independently() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            result: dict = {}

            def cb(value) -> None:  # noqa: ANN001
                result["v"] = value

            app.push_screen(
                OntologyIdentityModal(domain="example.org", path="zoo", sep="/", prefix="ex"), cb
            )
            await pilot.pause()
            modal = app.screen
            modal.query_one("#oi-domain", Input).value = "garden.org"
            list(modal.query(RadioButton))[0].value = True  # switch to "#"
            await pilot.pause()
            modal._submit()
            await pilot.pause()
            # Only the domain + separator changed; path & prefix are untouched.
            assert result["v"] == {
                "domain": "garden.org",
                "path": "zoo",
                "sep": "#",
                "prefix": "ex",
            }

    _run(scenario)


def test_invalid_domain_is_rejected_and_keeps_the_modal_open() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            seen: list = []
            app.push_screen(
                OntologyIdentityModal(domain="example.org", path="zoo", sep="#", prefix=""),
                seen.append,
            )
            await pilot.pause()
            modal = app.screen
            modal.query_one("#oi-domain", Input).value = "bad/host"  # path chars in the host
            modal._submit()
            await pilot.pause()
            assert seen == []  # rejected → not dismissed

    _run(scenario)
