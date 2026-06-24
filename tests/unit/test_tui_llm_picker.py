"""Tests for the inline LLM setup (mode Select → contextual model Select / form).

The ``ai.*`` calls are monkeypatched so no real model discovery / network I/O runs.
"""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Select, Static

from ster.tui.llm_group import LlmSetup


class _Host(App):
    def compose(self) -> ComposeResult:
        yield LlmSetup(id="cfg-llm")


def _run(coro_factory) -> None:  # noqa: ANN001
    asyncio.run(coro_factory())


@pytest.fixture(autouse=True)
def _unconfigured_ai(monkeypatch):
    """Default to an unconfigured AI so the mode starts at 'No model configured'."""
    monkeypatch.setattr("ster.ai.is_copypaste", lambda: False)
    monkeypatch.setattr("ster.ai.get_endpoint_config", lambda: {})
    monkeypatch.setattr("ster.ai.get_saved_model", lambda: None)
    monkeypatch.setattr("ster.ai.is_available", lambda: False)
    monkeypatch.setattr("ster.ai.detect_ollama_models", lambda: [])


def test_mode_select_offers_the_four_modes() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            select = app.query_one("#llm-mode-select", Select)
            assert [v for _label, v in select._options] == [
                "no_model",
                "copypaste",
                "local",
                "external",
            ]

    _run(scenario)


def test_defaults_to_no_model_when_unconfigured() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            setup = app.query_one(LlmSetup)
            assert setup.query_one("#llm-mode-select", Select).value == "no_model"
            assert "no ai model" in str(setup.query_one("#llm-sub Static", Static).render()).lower()

    _run(scenario)


def test_preselects_saved_mode(monkeypatch) -> None:
    monkeypatch.setattr("ster.ai.is_copypaste", lambda: True)  # configured as copy-paste

    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#llm-mode-select", Select).value == "copypaste"

    _run(scenario)


def test_copypaste_mode_saves_and_shows_hint(monkeypatch) -> None:
    saved: dict = {}
    monkeypatch.setattr("ster.ai.save_copypaste", lambda enabled: saved.update(cp=enabled))

    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            setup = app.query_one(LlmSetup)
            setup.query_one("#llm-mode-select", Select).value = "copypaste"
            await pilot.pause()
            assert saved["cp"] is True
            assert "paste" in str(setup.query_one("#llm-sub Static", Static).render()).lower()

    _run(scenario)


def test_no_model_persists_by_clearing_the_config(monkeypatch) -> None:
    cleared: dict = {}
    monkeypatch.setattr("ster.ai.clear_model", lambda: cleared.update(done=True))
    monkeypatch.setattr("ster.ai.is_copypaste", lambda: True)  # start configured, not no_model

    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            setup = app.query_one(LlmSetup)
            setup.query_one("#llm-mode-select", Select).value = "no_model"
            await pilot.pause()
            assert cleared.get("done") is True  # the choice is persisted (config cleared)

    _run(scenario)


def test_external_mode_shows_a_model_select(monkeypatch) -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            setup = app.query_one(LlmSetup)
            setup.query_one("#llm-mode-select", Select).value = "external"
            await pilot.pause()
            select = setup.query_one("#llm-ext-select", Select)
            assert "__custom__" in [v for _label, v in select._options]

    _run(scenario)


def test_local_custom_endpoint_reveals_form_and_saves(monkeypatch) -> None:
    saved: dict = {}
    monkeypatch.setattr("ster.ai.save_copypaste", lambda enabled: None)
    monkeypatch.setattr(
        "ster.ai.save_endpoint", lambda url, key, model: saved.update(url=url, model=model)
    )

    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            setup = app.query_one(LlmSetup)
            setup.query_one("#llm-mode-select", Select).value = "local"
            await pilot.pause()
            setup.query_one("#llm-local-select", Select).value = "__custom__"  # → endpoint form
            await pilot.pause()
            setup.query_one("#ep-url", Input).value = "http://localhost:1234/v1"
            setup.query_one("#ep-model", Input).value = "qwen"
            setup._save_endpoint()
            await pilot.pause()
            assert saved == {"url": "http://localhost:1234/v1", "model": "qwen"}

    _run(scenario)
