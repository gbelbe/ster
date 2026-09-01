"""``_apply_fix`` returns *why* a Problems-modal fix did not apply.

The modal renders whatever comes back on the row itself, so every refusal needs a
sentence a user can act on — not a bare False that leaves the row looking untried.
"""

from __future__ import annotations

import pytest

from ster import store
from ster.tui.app import _READ_ONLY_MESSAGE, OntologyApp

TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://example.org/t#> .
ex:Scheme a skos:ConceptScheme .
ex:Tent a skos:Concept ; skos:prefLabel "Tent"@en ; skos:inScheme ex:Scheme .
"""

BAD = "https://example.org/t#Tent#"


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")
    application = OntologyApp(store.load(path), source="o.ttl", path=path)
    # The success path schedules a save on a worker; there is no running app here,
    # and persistence is not what these tests are about.
    monkeypatch.setattr(type(application), "_schedule_save", lambda self: None)
    return application


def test_a_fix_that_lands_reports_no_reason(app):
    assert (
        app._apply_fix({"check_id": "RDF003", "subject": BAD}, "https://example.org/t#Tent2")
        is None
    )


def test_a_choice_identical_to_the_subject_says_there_is_nothing_to_do(app):
    """Applying the prefill unchanged builds no command at all."""
    reason = app._apply_fix({"check_id": "RDF003", "subject": BAD}, BAD)

    assert reason == "Nothing to apply for this fix."


def test_a_file_backed_by_nothing_reports_it_is_read_only(app):
    app._path = None

    assert app._apply_fix({"check_id": "RDF003", "subject": BAD}, "https://example.org/t#T2") == (
        _READ_ONLY_MESSAGE
    )


def test_commands_with_no_service_report_read_only(app):
    app._service = None

    assert app._apply_fix_commands(["anything"]) == _READ_ONLY_MESSAGE


def test_a_command_that_fails_surfaces_the_services_own_message(app, monkeypatch):
    """The service's error is the useful one — "Concept not found: …" and the like."""

    class _Failed:
        ok = False
        error = "Concept not found: t#Tent#"

    monkeypatch.setattr(type(app._service), "execute", lambda *a, **k: _Failed())

    assert app._apply_fix_commands(["cmd"]) == "Concept not found: t#Tent#"


def test_a_failure_with_no_message_still_says_something(app, monkeypatch):
    class _Failed:
        ok = False
        error = ""

    monkeypatch.setattr(type(app._service), "execute", lambda *a, **k: _Failed())

    assert app._apply_fix_commands(["cmd"]) == "Fix failed."
