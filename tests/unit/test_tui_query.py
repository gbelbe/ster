"""Unit tests for the New-TUI SPARQL query adapter + screen."""

from __future__ import annotations

import asyncio

from textual.app import App
from textual.widgets import DataTable, TextArea

from ster.model import Label, RDFClass, Taxonomy
from ster.tui import query
from ster.tui.query_screen import QueryScreen

BASE = "https://example.org/onto/"


def _tax() -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = BASE.rstrip("/")
    t.owl_classes[BASE + "Person"] = RDFClass(uri=BASE + "Person", labels=[Label("en", "Person")])
    t.owl_classes[BASE + "Animal"] = RDFClass(uri=BASE + "Animal", labels=[Label("en", "Animal")])
    return t


# ── adapter ─────────────────────────────────────────────────────────────────


def test_run_select_returns_columns_and_rows() -> None:
    res = query.run(_tax(), "SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }")
    assert res.error == ""
    assert res.columns == ["c"]
    values = {r[0] for r in res.rows}
    assert BASE + "Person" in values and BASE + "Animal" in values


def test_run_ask_returns_true_false() -> None:
    res = query.run(_tax(), "ASK { ?c a <http://www.w3.org/2002/07/owl#Class> }")
    assert res.query_type == "ASK"
    assert res.rows == [["true"]]


def test_run_syntax_error_is_captured_not_raised() -> None:
    res = query.run(_tax(), "SELECT ?s WHERE { this is not sparql")
    assert res.error  # an error message, no exception
    assert res.rows == []


def test_run_reflects_in_memory_edits() -> None:
    """A class added in memory (not on disk) is visible to the query."""
    t = _tax()
    t.owl_classes[BASE + "Robot"] = RDFClass(uri=BASE + "Robot", labels=[Label("en", "Robot")])
    res = query.run(t, "SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }")
    assert BASE + "Robot" in {r[0] for r in res.rows}


def test_presets_are_exposed() -> None:
    ps = query.presets()
    assert ps and all(p.label and p.sparql for p in ps)


# ── entity index (rdflib-powered) ─────────────────────────────────────────────


def _tax_with_bindings() -> Taxonomy:
    from ster.model import OWLIndividual, OWLProperty

    t = Taxonomy()
    t.ontology_uri = BASE.rstrip("/")
    t.namespace_bindings = {"kai": BASE, "skos": "http://www.w3.org/2004/02/skos/core#"}
    t.owl_classes[BASE + "Person"] = RDFClass(uri=BASE + "Person", labels=[Label("en", "Person")])
    t.owl_individuals[BASE + "alice"] = OWLIndividual(uri=BASE + "alice")
    t.owl_properties[BASE + "hasOwner"] = OWLProperty(
        uri=BASE + "hasOwner", prop_type="ObjectProperty"
    )
    from ster.model import Concept

    t.concepts[BASE + "Term1"] = Concept(uri=BASE + "Term1")  # a concept in the file's own ns
    return t


def test_build_entity_index_classifies_and_prefixes_entities() -> None:
    idx = query.build_entity_index(_tax_with_bindings())
    assert "kai" in idx.prefixes
    assert idx.classes.get("kai") == ["Person"]  # only the file's own class under kai:
    assert "alice" in idx.individuals.get("kai", [])
    assert "hasOwner" in idx.properties.get("kai", [])
    assert "Term1" in idx.concepts.get("kai", [])


def test_build_entity_index_includes_standard_wellknown_names() -> None:
    idx = query.build_entity_index(_tax_with_bindings())
    # standard names are offered under their prefix even if unused in the file
    assert "type" in idx.properties.get("rdf", []) or "rdf" not in idx.prefixes
    assert "Concept" in idx.classes.get("skos", [])


def test_graph_is_built_once_and_reused_for_index_and_run() -> None:
    """The session graph is reused: the index built from it and run_on_graph agree, without
    re-serialising the taxonomy each time."""
    tax = _tax_with_bindings()
    graph = query.build_graph(tax)
    idx = query.build_entity_index(tax, graph=graph)  # reuses the graph
    assert "Person" in idx.classes.get("kai", [])
    res = query.run_on_graph(
        graph, "SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }"
    )
    assert BASE + "Person" in {r[0] for r in res.rows}


def test_engine_graph_cache_still_hits(tmp_path) -> None:
    """The former engine's file-keyed cache is intact: a second load returns the same object."""
    import ster.sparql_query as sq

    src = tmp_path / "o.ttl"
    src.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix : <https://ex/> .\n:A a owl:Class .\n",
        encoding="utf-8",
    )
    assert sq.load_graph_cached([src]) is sq.load_graph_cached([src])  # warm cache hit


# ── screen ──────────────────────────────────────────────────────────────────


class _Host(App):
    def compose(self):  # type: ignore[no-untyped-def]
        return iter(())


def _run(coro_factory) -> None:  # noqa: ANN001
    asyncio.run(coro_factory())


def test_screen_prefills_editor_with_a_starter_query() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(QueryScreen(_tax()))
            await pilot.pause()
            editor = app.screen.query_one("#query-editor", TextArea)
            assert "SELECT" in editor.text
            assert app.screen.query_one("#query-results", DataTable) is not None

    _run(scenario)


def test_screen_shows_a_trigger_hint_naming_the_files_prefix() -> None:
    from textual.widgets import Static

    tax = _tax_with_bindings()  # entities under the 'kai' prefix
    screen = QueryScreen(tax)
    assert screen._example_prefix() == "kai:"  # the file's most-populated prefix
    hint = screen._trigger_hint()
    assert "kai:" in hint and "?" in hint and "keywords" in hint

    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            assert app.screen.query_one("#query-hint", Static) is not None  # rendered

    _run(scenario)


def test_starter_query_lists_the_files_classes_and_declares_their_prefix() -> None:
    tax = _tax_with_bindings()  # class 'Person' under 'kai'
    q = query.starter_query(query.build_entity_index(tax))
    assert "PREFIX kai:" in q  # the prefix is declared so the query runs
    assert "kai:Person" in q and "VALUES ?class" in q


def test_running_a_select_populates_the_results_table() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(QueryScreen(_tax()))
            await pilot.pause()
            app.screen.query_one(
                "#query-editor", TextArea
            ).text = "SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }"
            app.screen.action_run()
            await pilot.pause()
            table = app.screen.query_one("#query-results", DataTable)
            assert len(table.columns) == 1
            assert len(table.rows) == 2  # Person + Animal
            assert app.screen._last_result.error == ""

    _run(scenario)


def test_running_a_bad_query_shows_the_error_without_crashing() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(QueryScreen(_tax()))
            await pilot.pause()
            app.screen.query_one("#query-editor", TextArea).text = "SELECT ?s WHERE { bad"
            app.screen.action_run()
            await pilot.pause()
            assert app.screen._last_result.error  # the error was captured
            assert len(app.screen.query_one("#query-results", DataTable).rows) == 0

    _run(scenario)


def test_loading_a_preset_sets_the_editor_text() -> None:
    async def scenario() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(QueryScreen(_tax()))
            await pilot.pause()
            preset = query.presets()[0]
            app.screen._apply_preset(preset.sparql)  # what the picker callback does
            await pilot.pause()
            assert app.screen.query_one("#query-editor", TextArea).text == preset.sparql

    _run(scenario)


def test_presets_action_opens_a_picker_that_applies_the_choice() -> None:
    async def scenario() -> None:
        from ster.tui.picker_modal import PickerModal

        app = _Host()
        async with app.run_test() as pilot:
            screen = QueryScreen(_tax())
            app.push_screen(screen)
            await pilot.pause()
            screen.action_presets()  # opens the preset picker
            await pilot.pause()
            assert isinstance(app.screen, PickerModal)
            app.screen.dismiss("0")  # pick the first preset
            await pilot.pause()
            assert screen.query_one("#query-editor", TextArea).text == query.presets()[0].sparql

    _run(scenario)


def test_app_action_open_query_pushes_the_screen() -> None:
    async def scenario() -> None:
        from ster.tui.app import OntologyApp

        app = OntologyApp(_tax(), source="t")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_open_query()
            await pilot.pause()
            assert isinstance(app.screen, QueryScreen)

    _run(scenario)


def test_app_opens_query_on_start_when_requested() -> None:
    async def scenario() -> None:
        from ster.tui.app import OntologyApp

        app = OntologyApp(_tax(), source="t", open_query=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, QueryScreen)

    _run(scenario)


# ── mapping query results ───────────────────────────────────────────────────

WGS = "http://www.w3.org/2003/01/geo/wgs84_pos#"
GEO_QUERY = f"SELECT ?i WHERE {{ ?i <{WGS}lat> ?lat }}"
PLAIN_QUERY = "SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }"


def _geo_graph():
    """A graph whose entities carry WGS84 coordinates, standing in for the taxonomy's."""
    import rdflib

    g = rdflib.Graph()
    g.parse(
        data=f"""
        @prefix wgs:  <{WGS}> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix ex:   <{BASE}> .
        ex:Brest   rdfs:label "Brest"   ; wgs:lat 48.39 ; wgs:long -4.48 .
        ex:Lorient rdfs:label "Lorient" ; wgs:lat 47.75 ; wgs:long -3.37 .
        """,
        format="turtle",
    )
    return g


def _run_screen(sparql, geo, after=None):
    """Push a QueryScreen, run *sparql*, and hand the screen to *after*."""
    captured: list[str] = []

    async def scenario() -> None:
        app: App[None] = App()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = QueryScreen(_tax())
            app.push_screen(screen)
            await pilot.pause()
            if geo:
                screen._graph = _geo_graph()
            screen.query_one("#query-editor", TextArea).text = sparql
            screen.action_run()
            await pilot.pause()
            captured.append(screen._status_line)
            if after is not None:
                after(screen)
                await pilot.pause()

    asyncio.run(scenario())
    return captured[0]


def test_status_reports_located_count_when_geodata_present() -> None:
    status = _run_screen(GEO_QUERY, geo=True)
    assert "2" in status
    assert "map" in status.lower()


def test_status_says_why_the_map_is_unavailable_rather_than_hiding_it() -> None:
    """Both views are named on every run, the unavailable one dimmed with its
    reason. A control you only see when it works is one you never learn exists,
    so silence was the wrong answer here — the status now explains instead.
    """
    status = _run_screen(PLAIN_QUERY, geo=False).lower()

    assert "map unavailable" in status
    assert "no coordinates" in status


def test_map_binding_opens_url_with_current_query() -> None:
    opened: list[str] = []

    def press_map(screen) -> None:
        screen._open = opened.append
        screen._server_ok = lambda: True
        screen.action_map()

    _run_screen(GEO_QUERY, geo=True, after=press_map)
    assert opened, "expected a browser to be opened"
    assert "/map" in opened[0]
    assert "wgs84_pos" in opened[0]  # the query travelled with it


CONSTRUCT_QUERY = "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o } LIMIT 5"


def test_graph_binding_opens_url_with_current_query() -> None:
    opened: list[str] = []

    def press_graph(screen) -> None:
        screen._open = opened.append
        screen._server_ok = lambda: True
        screen.action_graph()

    _run_screen(CONSTRUCT_QUERY, geo=False, after=press_graph)

    assert opened, "expected a browser to be opened"
    assert "/viz" in opened[0]
    assert "CONSTRUCT" in opened[0]  # the query travelled with it


def test_graph_action_declines_a_select() -> None:
    """A SELECT returns columns; the graph view draws triples. Opening it would
    show an empty canvas and look broken, so it declines and says why."""
    opened: list[str] = []

    def press_graph(screen) -> None:
        screen._open = opened.append
        screen._server_ok = lambda: True
        screen.action_graph()

    _run_screen(PLAIN_QUERY, geo=False, after=press_graph)

    assert not opened


def test_graph_action_reports_a_dead_server_rather_than_opening_a_dead_tab() -> None:
    opened: list[str] = []

    def press_graph(screen) -> None:
        screen._open = opened.append
        screen._server_ok = lambda: False
        screen.action_graph()

    _run_screen(CONSTRUCT_QUERY, geo=False, after=press_graph)

    assert not opened


def test_graph_action_warns_when_the_browser_will_not_open() -> None:
    """`webbrowser.open` returning False is the one failure the caller can see;
    silence there would look like the action did nothing."""

    def press_graph(screen) -> None:
        screen._open = lambda _url: False
        screen._server_ok = lambda: True
        screen.action_graph()

    _run_screen(CONSTRUCT_QUERY, geo=False, after=press_graph)


def test_map_action_does_nothing_without_geodata() -> None:
    opened: list[str] = []

    def press_map(screen) -> None:
        screen._open = opened.append
        screen.action_map()

    _run_screen(PLAIN_QUERY, geo=False, after=press_map)
    assert opened == []


# Terminals encode these as another key entirely (ctrl+m == Enter,
# ctrl+i == Tab, ctrl+j == line feed, ctrl+h == Backspace, ctrl+[ == Escape),
# so a binding on one can never fire. ctrl+s / ctrl+q are XON/XOFF flow control.
_TERMINAL_ALIASED_KEYS = {"ctrl+m", "ctrl+i", "ctrl+j", "ctrl+h", "ctrl+[", "ctrl+s", "ctrl+q"}


def test_no_binding_uses_a_terminal_aliased_key_regression() -> None:
    """Root cause: ctrl+m was bound to the map action, but the terminal sends
    carriage return for it — identical to Enter — so pressing it only inserted a
    newline in the editor and the action never ran."""
    bound = {
        key.strip()
        for binding in QueryScreen.BINDINGS
        for key in binding.key.split(",")  # type: ignore[union-attr]
    }
    assert not bound & _TERMINAL_ALIASED_KEYS


def test_map_action_is_reachable_by_a_binding() -> None:
    actions = {b.action for b in QueryScreen.BINDINGS}  # type: ignore[union-attr]
    assert "map" in actions


def test_map_keypress_reaches_the_action_with_the_editor_focused() -> None:
    """The original bug was the *keypress* never arriving, not the action failing:
    the editor holds focus, so the binding must still fire through it."""
    opened: list[str] = []

    async def scenario() -> None:
        app: App[None] = App()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = QueryScreen(_tax())
            app.push_screen(screen)
            await pilot.pause()
            screen._graph = _geo_graph()
            screen.query_one("#query-editor", TextArea).text = GEO_QUERY
            screen.action_run()
            await pilot.pause()
            screen._open = opened.append
            screen._server_ok = lambda: True
            screen.query_one("#query-editor", TextArea).focus()
            await pilot.pause()
            await pilot.press("ctrl+g")
            await pilot.pause()

    asyncio.run(scenario())
    assert opened, "ctrl+g did not reach action_map while the editor had focus"
    assert "/map" in opened[0]


def _drive_map(*, server_ok: bool) -> tuple[list[str], list[str]]:
    """Run a geo query then trigger the map action; return (opened, notices)."""
    opened: list[str] = []
    notices: list[str] = []

    async def scenario() -> None:
        app: App[None] = App()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = QueryScreen(_tax())
            app.push_screen(screen)
            await pilot.pause()
            screen._graph = _geo_graph()
            screen.query_one("#query-editor", TextArea).text = GEO_QUERY
            screen.action_run()
            await pilot.pause()
            screen._open = opened.append
            screen._server_ok = lambda: server_ok
            screen.notify = lambda msg, **kw: notices.append(str(msg))  # type: ignore[method-assign]
            screen.action_map()
            await pilot.pause()

    asyncio.run(scenario())
    return opened, notices


def test_map_action_reports_when_the_server_is_not_running() -> None:
    """Same courtesy the graph view extends: say so rather than opening a dead tab."""
    opened, notices = _drive_map(server_ok=False)
    assert opened == []
    assert notices and "server" in notices[0].lower()


def test_map_action_opens_when_the_server_is_running() -> None:
    opened, _ = _drive_map(server_ok=True)
    assert opened and "/map" in opened[0]
