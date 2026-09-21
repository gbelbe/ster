"""Opening the timeline on a selection, and on a query result.

`t` opens the frieze of the whole file, or of what the selected entity stands
over. The focus travels as an entity IRI rather than as a query, for the reason
the map gives: a procedure reaches its events, its deadlines and its provenance,
and those IRIs belong in the page rather than in a link nobody can send.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import rdflib
from textual.app import App
from textual.widgets import TextArea

from ster.api import _focused_timeline_query
from ster.model import Label, RDFClass, Taxonomy
from ster.timeline_html import DEFAULT_TIMELINE_QUERY
from ster.tui import query
from ster.tui.query_screen import QueryScreen

NS = "https://ex.org/t#"

TURTLE = """
@prefix ex:   <https://ex.org/t#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

ex:procedure rdfs:label "Procedure" .
ex:deposit   ex:of ex:procedure ; rdfs:label "Deposit" ; ex:on "2026-08-18"^^xsd:date .
ex:decision  ex:of ex:procedure ; rdfs:label "Decision" ; ex:on "2026-09-18"^^xsd:date .
ex:colour    rdfs:label "colour" .
"""


def _query_for(uri: str, turtle: str = TURTLE) -> str:
    """The query the server would prime the page with, for a focus of *uri*."""
    import ster.api as api

    graph = rdflib.Graph().parse(data=turtle, format="turtle")
    original = api._graph_for_locate
    api._graph_for_locate = lambda _tax: graph  # type: ignore[assignment]
    try:
        return _focused_timeline_query(None, uri)
    finally:
        api._graph_for_locate = original  # type: ignore[assignment]


# ── the query the focus becomes ───────────────────────────────────────────────


def test_a_procedure_becomes_a_query_over_its_events() -> None:
    """The case the inward walk exists for: the procedure carries no date."""
    sparql = _query_for(NS + "procedure")
    assert NS + "deposit" in sparql
    assert NS + "decision" in sparql
    assert "VALUES ?thing" in sparql


def test_a_dated_entity_reaches_at_least_itself() -> None:
    assert NS + "deposit" in _query_for(NS + "deposit")


def test_an_entity_reaching_nothing_dated_yields_no_query() -> None:
    """Empty, so the caller opens the whole file rather than a blank frieze."""
    assert _query_for(NS + "colour") == ""


# ── the URL the TUI opens ─────────────────────────────────────────────────────


def _pin_server(monkeypatch) -> None:  # noqa: ANN001
    import ster.api_server as api_server

    monkeypatch.setattr(api_server, "load_server_config", lambda: ("http://127.0.0.1", 8765))


def test_timeline_url_carries_the_query(monkeypatch) -> None:  # noqa: ANN001
    _pin_server(monkeypatch)
    url = query.timeline_url("SELECT ?s WHERE { ?s ?p ?o }")
    assert url.startswith("http://127.0.0.1:8765/timeline?q=")
    assert "SELECT" in url


def test_timeline_url_carries_the_focus_when_given(monkeypatch) -> None:  # noqa: ANN001
    _pin_server(monkeypatch)
    assert "focus=" in query.timeline_url("", NS + "procedure")


def test_timeline_url_omits_the_focus_when_absent(monkeypatch) -> None:  # noqa: ANN001
    _pin_server(monkeypatch)
    assert "focus=" not in query.timeline_url("SELECT ?s WHERE { ?s ?p ?o }")


# ── the count the query screen reports ────────────────────────────────────────


@dataclass
class _Result:
    columns: list[str]
    rows: list[list[str]]
    error: str = ""
    query_type: str = "SELECT"
    extra: dict = field(default_factory=dict)


def test_dated_count_counts_rows_that_can_be_placed() -> None:
    graph = rdflib.Graph().parse(data=TURTLE, format="turtle")
    result = _Result(columns=["thing"], rows=[[NS + "deposit"], [NS + "colour"]])
    assert query.dated_count(graph, result) == 1


# ── the query screen ──────────────────────────────────────────────────────────


class _Host(App):
    pass


def _tax() -> Taxonomy:
    base = "https://example.org/onto/"
    t = Taxonomy()
    t.ontology_uri = base.rstrip("/")
    t.owl_classes[base + "Person"] = RDFClass(uri=base + "Person", labels=[Label("en", "Person")])
    return t


def test_the_hint_names_the_timeline_only_when_something_can_be_dated() -> None:
    screen = QueryScreen(_tax())
    screen._graph = rdflib.Graph().parse(data=TURTLE, format="turtle")

    dated = screen._time_hint(_Result(columns=["thing"], rows=[[NS + "deposit"]]))
    assert "ctrl+t" in dated and "1 datable" in dated

    assert screen._time_hint(_Result(columns=["thing"], rows=[[NS + "colour"]])) == ""


def test_the_shortcut_says_so_rather_than_opening_an_empty_frieze() -> None:
    notices: list[str] = []
    opened: list[str] = []

    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            screen = QueryScreen(_tax())
            app.push_screen(screen)
            await pilot.pause()
            screen.notify = lambda msg, **kw: notices.append(str(msg))  # type: ignore[method-assign]
            # The screen binds both seams in __init__, which is what makes them
            # injectable: patching the module here would come too late.
            screen._server_ok = lambda: True
            screen._open = lambda url: bool(opened.append(url) or True)

            screen.action_timeline()  # nothing has been run yet
            assert opened == []
            assert "temporal" in notices[-1].lower()

            screen._graph = rdflib.Graph().parse(data=TURTLE, format="turtle")
            screen._last_result = _Result(columns=["thing"], rows=[[NS + "deposit"]])
            screen._dated = 1
            screen.query_one("#query-editor", TextArea).text = DEFAULT_TIMELINE_QUERY
            screen.action_timeline()
            await pilot.pause()
            assert opened and "/timeline" in opened[0]

    asyncio.run(scenario())


def test_the_shortcut_reports_a_server_that_is_not_running() -> None:
    notices: list[str] = []

    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            screen = QueryScreen(_tax())
            app.push_screen(screen)
            await pilot.pause()
            screen.notify = lambda msg, **kw: notices.append(str(msg))  # type: ignore[method-assign]
            screen._server_ok = lambda: False
            screen._last_result = _Result(columns=["thing"], rows=[[NS + "deposit"]])
            screen._dated = 1
            screen.action_timeline()
            await pilot.pause()

    asyncio.run(scenario())
    assert notices and "server" in notices[-1].lower()


# ── the focus target, when the reader has selected something ──────────────────


def test_a_selection_that_reaches_dates_becomes_the_focus() -> None:
    from ster.time_shapes import dated_from
    from ster.tui.app import OntologyApp

    graph = rdflib.Graph().parse(data=TURTLE, format="turtle")
    app = OntologyApp(_tax(), source="demo.ttl")
    app._detail_uri = NS + "procedure"
    assert app._timeline_focus_target(graph, dated_from) == NS + "procedure"


def test_a_selection_that_reaches_nothing_says_so_and_shows_everything() -> None:
    from ster.time_shapes import dated_from
    from ster.tui.app import OntologyApp

    notices: list[str] = []
    graph = rdflib.Graph().parse(data=TURTLE, format="turtle")
    app = OntologyApp(_tax(), source="demo.ttl")
    app.notify = lambda msg, **kw: notices.append(str(msg))  # type: ignore[method-assign]
    app._detail_uri = NS + "colour"

    assert app._timeline_focus_target(graph, dated_from) is None
    assert notices and "whole file" in notices[-1]


def test_no_selection_means_no_focus() -> None:
    from ster.time_shapes import dated_from
    from ster.tui.app import OntologyApp

    app = OntologyApp(_tax(), source="demo.ttl")
    app._detail_uri = ""
    assert app._timeline_focus_target(rdflib.Graph(), dated_from) is None
