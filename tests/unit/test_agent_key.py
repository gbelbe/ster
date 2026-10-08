"""The 'a' key answers at once and does its waiting off the UI thread, so a TUI that is still starting is not frozen."""

from __future__ import annotations

import pytest

from ster import store
from ster.plugins import talk_to_graph
from ster.tui import query
from ster.tui.app import OntologyApp

pytestmark = pytest.mark.mutation  # noqa: V107  # pytest reads it to select the mutation tests

ADDRESS = "http://127.0.0.1:8781"
OPENING = "Opening the agent page…"
STILL = "Still opening the agent page — one moment."
SECONDS = 20.0
TWICE = 2
RUNNING, WAIT = "server_is_running", "wait_for_server"


@pytest.fixture
def app(tmp_path, monkeypatch):
    src = tmp_path / "o.ttl"
    src.write_text("@prefix : <https://example.org/o#> .\n", encoding="utf-8")
    opened = OntologyApp(store.load(src), source="o.ttl", path=src)
    opened.said = []  # type: ignore[attr-defined]
    opened.notify = lambda message, severity=None, **_k: opened.said.append((message, severity))  # type: ignore[method-assign,attr-defined]
    started: list[dict] = []
    opened.run_worker = lambda fn, **kw: started.append({"fn": fn, **kw})  # type: ignore[method-assign]
    opened.started = started  # type: ignore[attr-defined]
    monkeypatch.setattr(query, WAIT, lambda _s: True)
    monkeypatch.setattr(query, "open_browser", lambda _u: True)
    monkeypatch.setattr(talk_to_graph, "page_url", lambda *_a: (ADDRESS, None))
    monkeypatch.setattr("ster.api_server.load_server_config", lambda: ("http://127.0.0.1", 8765))
    return opened


def test_the_key_answers_at_once_and_hands_the_waiting_to_a_worker(app):
    app.action_open_agent()
    assert app.said == [(OPENING, None)]
    [worker] = app.started
    assert worker["thread"] is True
    assert worker["fn"] == app._open_agent_worker


def test_pressing_it_again_meanwhile_does_not_start_a_second_page(app):
    app.action_open_agent()
    app.action_open_agent()
    app.action_open_agent()
    assert len(app.started) == 1
    assert [m for m, _ in app.said] == [OPENING, STILL, STILL]


def test_when_the_worker_is_done_the_key_works_again_and_the_outcome_is_said(app):
    app.action_open_agent()
    app._agent_page_done("Agent page opened", None)
    assert app._opening_agent is False
    assert app.said[-1] == ("Agent page opened", None)
    app.action_open_agent()
    assert len(app.started) == TWICE


def test_the_worker_reports_the_outcome_back_on_the_ui_thread(app):
    reported: list[tuple] = []
    app.call_from_thread = lambda fn, *args: reported.append((fn, args))  # type: ignore[method-assign]
    app._open_agent_worker()
    assert reported == [
        (app._agent_page_done, (f"Agent page opened in your browser — {ADDRESS}", None))
    ]


def test_a_failure_in_the_worker_is_reported_not_swallowed(app, monkeypatch):
    def broken(*_a):
        raise OSError("no sockets")

    monkeypatch.setattr(talk_to_graph, "page_url", broken)
    reported: list[tuple] = []
    app.call_from_thread = lambda fn, *args: reported.append(args)  # type: ignore[method-assign]
    app._open_agent_worker()
    assert reported == [("Couldn't open the agent page: no sockets", "warning")]


def test_it_waits_for_the_server_that_starts_beside_the_browser(app, monkeypatch):
    waited: list[float] = []
    monkeypatch.setattr(query, WAIT, lambda seconds: waited.append(seconds) or True)
    app._open_agent_page()
    assert waited == [SECONDS]


def test_a_server_that_never_comes_up_is_named_for_the_agent_page_not_the_map(app, monkeypatch):
    monkeypatch.setattr(query, WAIT, lambda _s: False)
    monkeypatch.setattr(
        query, "server_unavailable_reason", lambda what="the map": f"Couldn't open {what}: down"
    )
    assert app._open_agent_page() == ("Couldn't open the agent page: down", "warning")


# ── waiting for the server ────────────────────────────────────────────────────


def test_the_wait_ends_as_soon_as_the_server_is_up(monkeypatch):
    answers = iter([False, False, True])
    monkeypatch.setattr(query, RUNNING, lambda: next(answers))
    assert query.wait_for_server(5, every=0.001) is True


def test_the_wait_gives_up_after_its_time(monkeypatch):
    monkeypatch.setattr(query, RUNNING, lambda: False)
    assert query.wait_for_server(0.02, every=0.005) is False


def test_a_server_that_is_already_up_costs_no_wait(monkeypatch):
    monkeypatch.setattr(query, RUNNING, lambda: True)
    assert query.wait_for_server(0, every=10) is True


def test_the_unavailable_reason_names_what_could_not_be_opened(monkeypatch):
    monkeypatch.setattr("ster.api_server.load_server_config", lambda: ("http://127.0.0.1", 8765))
    monkeypatch.setattr("ster.viz_vowl.port_holder", lambda port: None)
    assert (
        query.server_unavailable_reason("the agent page")
        == "Couldn't open the agent page: the ster server isn't running."
    )
    assert query.server_unavailable_reason().startswith("Couldn't open the map:")
