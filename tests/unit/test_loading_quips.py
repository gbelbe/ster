"""The loading screen keeps a line of commentary under the spinner: one per step, rolling on while the step lasts."""

from __future__ import annotations

import asyncio

import pytest
from textual.widgets import Static

from ster.model import Taxonomy
from ster.tui.app import OntologyApp
from ster.tui.app._loading_quips import _BY_STEP, _ELSEWHERE, QUIP_EVERY, quip_for

# every message the loaders send, with the counters of the context files left out
STEPS = (
    "Starting",
    "Parsing RDF",
    "Building model",
    "Assigning handles",
    "Updating cache",
    "Loaded from cache",
    "Ready",
    "Reading the editable file's schema",
    "Reading context 3/19: Component.ttl",
    "Merging context 3/19: Component.ttl",
    "Building navigation index",
    "Indexing individuals",
    "Configuring browser",
    "Building properties",
    "Building browser",
    "Building browser tree",
    "Building ontology tree",
    "Finalizing browser",
)
MERGING = "Merging context 2/3: b.ttl"
PHASE = "Loading"
PERCENT = 40
LONGEST = 90  # characters: a sentence that fits an 80-column terminal beside the spinner without wrapping twice


@pytest.mark.parametrize("message", STEPS)
def test_every_step_has_sentences_of_its_own(message):
    assert quip_for(message, 0) not in _ELSEWHERE


@pytest.mark.parametrize("message", STEPS)
def test_a_step_that_lasts_gets_more_than_one_sentence(message):
    assert len({quip_for(message, tick) for tick in range(len(_BY_STEP) * 4)}) >= 2  # noqa: PLR2004


def test_the_sentence_rolls_on_with_the_tick_and_comes_back_round():
    sentences = [quip_for("Reading context 1/2: a.ttl", tick) for tick in range(8)]
    assert sentences[0] != sentences[1]
    assert sentences[:4] == sentences[4:]


def test_a_longer_message_is_not_taken_for_the_shorter_one_it_starts_with():
    assert quip_for("Building browser tree", 0) not in {
        quip_for("Building browser", t) for t in range(2)
    }


def test_an_unknown_step_still_gets_a_sentence():
    assert quip_for("Something new", 0) in _ELSEWHERE


def test_no_sentence_is_repeated_or_too_long_for_the_screen():
    every = [sentence for _, group in _BY_STEP for sentence in group] + list(_ELSEWHERE)
    assert len(every) == len(set(every))
    assert max(map(len, every)) <= LONGEST


def _app() -> OntologyApp:
    """An app that is showing its loader and has nothing else going on that would repaint it."""
    app = OntologyApp(Taxonomy(), source="slow.ttl", progressive_startup=True)
    app._initialize_browser = lambda: None  # type: ignore[method-assign]
    return app


def _shown(app) -> list[str]:
    return str(app.query_one("#loading", Static).render()).split("\n")


def test_the_loading_text_has_the_step_and_then_a_sentence_about_it():
    app = _app()

    async def scenario():
        async with app.run_test(size=(100, 20)):
            app._set_loading_progress(PHASE, PERCENT, MERGING)
            return _shown(app)

    first, second, third = asyncio.run(scenario())
    assert first.endswith(f"{PHASE} {PERCENT}%")
    assert second == MERGING
    assert third == quip_for(second, 0)


def test_the_sentence_rolls_on_while_the_spinner_turns_and_the_step_stays():
    app = _app()

    async def scenario():
        async with app.run_test(size=(100, 20)):
            app._set_loading_progress(PHASE, PERCENT, MERGING)
            before = _shown(app)
            for _ in range(QUIP_EVERY):
                app._advance_loading_spinner()
            return before, _shown(app)

    before, after = asyncio.run(scenario())
    assert after[1] == before[1]
    assert after[2] != before[2]


def test_a_plain_message_is_left_alone_by_the_spinner():
    app = _app()

    async def scenario():
        async with app.run_test(size=(100, 20)):
            app._set_loading_progress(PHASE, PERCENT, MERGING)
            app._set_loading_message("Unable to load")
            app._advance_loading_spinner()
            return _shown(app)

    assert asyncio.run(scenario()) == ["Unable to load"]
