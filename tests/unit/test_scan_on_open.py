"""Scan-on-open Problems modal — config flag + end-to-end app wiring.

The end-to-end test enables the semanticlint plugin (installed in the dev env),
opens a file carrying an SKO003 error, and drives the auto-fix from the modal.
"""

from __future__ import annotations

import asyncio

import pytest

from ster import store
from ster.plugins.semanticlint import config
from ster.tui.app import OntologyApp
from ster.tui.plugins.semanticlint_ui.problems_modal import ProblemRow, ProblemsModal

# A concept whose value is both prefLabel and altLabel → semanticlint SKO003 (error).
SKO003_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://ex.org/> .
ex:Scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Dog .
ex:Dog a skos:Concept ; skos:inScheme ex:Scheme ; skos:topConceptOf ex:Scheme ;
  skos:prefLabel "Dog"@en ; skos:altLabel "Dog"@en .
"""

CLEAN_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://ex.org/> .
ex:Scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Dog .
ex:Dog a skos:Concept ; skos:inScheme ex:Scheme ; skos:topConceptOf ex:Scheme ;
  skos:prefLabel "Dog"@en .
"""


# ── config flag ─────────────────────────────────────────────────────────────────


def test_check_on_open_defaults_on():
    assert config.DEFAULT_FEATURES["check_on_open"] is True


def test_check_on_open_is_a_semantic_lint_feature_toggle():
    from ster.tui.config_modal import ConfigModal

    assert ("check_on_open", "Check the file for errors when it opens") in ConfigModal._SL_FEATURES


# ── end-to-end (Textual harness) ────────────────────────────────────────────────


@pytest.fixture
def _plugin_env(tmp_path, monkeypatch):
    """Isolate prefs + quality config to tmp and enable the semanticlint plugin."""
    from ster import api_server
    from ster.nav import prefs
    from ster.plugins import state

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(prefs, "_lang_prefs_path", lambda: tmp_path / "lang.json")
    monkeypatch.setattr(prefs, "_configured_langs_path", lambda: tmp_path / "clangs.json")
    monkeypatch.setattr(api_server, "_SERVER_CONFIG_FILE", tmp_path / "server_config.json")
    monkeypatch.setattr(api_server, "_TOKEN_FILE", tmp_path / "api_token")
    monkeypatch.setattr(config, "_config_path", lambda: tmp_path / "quality.json")
    state.set_enabled("semanticlint", True)
    return tmp_path


SKO003_ISSUE = {
    "severity": "error",
    "check_id": "SKO003",
    "message": "Literal 'Dog' appears as both skos:prefLabel and skos:altLabel",
    "subject": "http://ex.org/Dog",
}


@pytest.fixture
def _scan_finds_one_error(monkeypatch):
    """Stand in for the SHACL pass, which is not what these tests are about.

    Everything below asks the same question — does the app react correctly to a
    scan *result*: open the modal, honour the feature toggle, reopen on demand.
    None of it asks whether pySHACL can spot a duplicate label; one test at the
    bottom does that, against the real engine.

    Running the real scan in all of them made them slow and, under `-n auto`,
    flaky: each one paid for a SHACL pass while competing with every other
    worker, and the 15-second settle deadline is a race nobody should have to
    win to get a true answer. The value returned here is a verbatim capture of
    what the real scan produces for SKO003_TTL, so the stand-in cannot drift
    into testing a shape the engine never emits — the integration test below
    asserts that it still matches.
    """
    monkeypatch.setattr(OntologyApp, "_blocking_errors", lambda self: [dict(SKO003_ISSUE)])


@pytest.fixture
def _scan_finds_nothing(monkeypatch):
    monkeypatch.setattr(OntologyApp, "_blocking_errors", lambda self: [])


def _open(tmp_path, ttl: str) -> OntologyApp:
    src = tmp_path / "onto.ttl"
    src.write_text(ttl, encoding="utf-8")
    return OntologyApp(store.load(src), source="onto.ttl", path=src)


def test_scan_on_open_shows_the_problems_modal_for_an_error(
    _plugin_env, settle, _scan_finds_one_error
):
    app = _open(_plugin_env, SKO003_TTL)

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            # The predicate names the rows, not just the modal: Textual swaps the
            # screen first and mounts its children on a later turn, so a wait that
            # stops at `isinstance(..., ProblemsModal)` returns with the modal open
            # and empty. Under -n auto that gap is wide enough to lose, which is
            # how this test failed in CI while passing in isolation.
            shown = await settle(
                pilot,
                lambda: (
                    isinstance(app.screen, ProblemsModal) and len(app.screen.query(ProblemRow)) == 1
                ),
            )
            assert shown, "Problems modal did not open with its one row"

    asyncio.run(scenario())


def test_clean_file_opens_silently(_plugin_env, _scan_finds_nothing):
    app = _open(_plugin_env, CLEAN_TTL)

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(30):
                await pilot.pause()
            assert not isinstance(app.screen, ProblemsModal)

    asyncio.run(scenario())


def test_auto_fix_removes_the_duplicate_label_and_closes(_plugin_env, settle):
    from textual.widgets import Button

    from ster.model import LabelType

    app = _open(_plugin_env, SKO003_TTL)

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            # Wait for the button, not for the screen. The modal becomes the
            # active screen before its rows have mounted, so a predicate on the
            # screen alone returns while the thing the next line uses does not
            # exist yet — which is how this failed in CI as
            # `NoMatches: '.problem-fix' on ProblemsModal()`: the modal was
            # open, and empty. Waiting on the screen was a proxy for waiting on
            # the scan, and a proxy is exactly what this fixture exists to avoid.
            ready = await settle(pilot, lambda: bool(app.screen.query(".problem-fix")))
            assert ready, "the problems modal never rendered a fix control"
            app.screen.query_one(".problem-fix", Button).press()
            # The auto-fix drops the last row → the modal dismisses itself.
            closed = await settle(pilot, lambda: not isinstance(app.screen, ProblemsModal))
            assert closed
            dog = app.tax.concepts["http://ex.org/Dog"]
            alts = [lbl.value for lbl in dog.labels if lbl.type == LabelType.ALT]
            assert "Dog" not in alts  # the redundant altLabel is gone
            prefs_ = [lbl.value for lbl in dog.labels if lbl.type == LabelType.PREF]
            assert prefs_ == ["Dog"]  # prefLabel kept

    asyncio.run(scenario())


def test_scan_skipped_when_check_on_open_is_off(_plugin_env, _scan_finds_one_error):
    config.set_feature("check_on_open", False)
    app = _open(_plugin_env, SKO003_TTL)

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(30):
                await pilot.pause()
            assert not isinstance(app.screen, ProblemsModal)

    asyncio.run(scenario())


def test_problems_action_reopens_after_dismissal(_plugin_env, settle, _scan_finds_one_error):
    config.set_feature("check_on_open", False)  # no auto-open; test the '!' action
    app = _open(_plugin_env, SKO003_TTL)

    async def scenario():
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(20):
                await pilot.pause()
            assert not isinstance(app.screen, ProblemsModal)
            app.action_problems()
            shown = await settle(pilot, lambda: isinstance(app.screen, ProblemsModal))
            assert shown

    asyncio.run(scenario())


# ── the real scanner, once ──────────────────────────────────────────────────


def test_the_real_scan_reports_the_duplicate_label(_plugin_env):
    """The engine itself, with no stand-in — and the contract the fixture above
    depends on. If pySHACL ever reports this differently, this fails and the
    stand-in above is shown to be stale, rather than quietly testing fiction."""
    app = _open(_plugin_env, SKO003_TTL)

    errors = app._blocking_errors()

    assert [e["check_id"] for e in errors] == ["SKO003"]
    assert errors[0]["severity"] == SKO003_ISSUE["severity"]
    assert errors[0]["subject"] == SKO003_ISSUE["subject"]
