"""`ster show --endpoint` and the home-menu entry: option handling and launching.

The endpoint itself is covered in test_sparql_endpoint; here the TUI launch is
stubbed so these pin only what the command line does with what it is given.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ster import sparql_endpoint as ep
from ster.cli import _endpoint as cli_endpoint
from ster.cli import app
from ster.cli._exit import ExitCode
from ster.sparql_endpoint import EndpointError, NotRdfError

_runner = CliRunner()
URL = "https://graphdb.example/sparql"
EXPLICIT_LIMIT = 250
MENU_LIMIT = 4200


@pytest.fixture(autouse=True)  # noqa: V103
def _isolated_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "_CONFIG_FILE", tmp_path / "endpoint.json")


@pytest.fixture
def launched(monkeypatch):
    """Record what the viewer was asked to open, and pretend there is a terminal."""
    seen: list[tuple[ep.EndpointSource, str]] = []
    monkeypatch.setattr("ster.cli._viewer._is_interactive_terminal", lambda: True)
    monkeypatch.setattr(
        "ster.tui.launch_endpoint", lambda source, lang="en": seen.append((source, lang))
    )
    return seen


def test_show_endpoint_flag_launches_read_only(launched):
    result = _runner.invoke(app, ["show", "--endpoint", URL])

    assert result.exit_code == 0
    source, _lang = launched[0]
    assert source.url == URL and source.graph is None and source.query is None
    assert source.limit == ep.DEFAULT_LIMIT


def test_flags_reach_the_source(launched):
    _runner.invoke(
        app,
        [
            "show",
            "-e",
            URL,
            "--graph",
            "https://g/1",
            "--limit",
            str(EXPLICIT_LIMIT),
            "--header",
            "X-Key: abc",
        ],
    )

    source, _ = launched[0]
    assert source.graph == "https://g/1"
    assert source.limit == EXPLICIT_LIMIT
    assert source.headers == (("X-Key", "abc"),)


def test_limit_flag_beats_the_saved_limit_which_beats_the_default(launched):
    ep.save_limit(777)

    _runner.invoke(app, ["show", "-e", URL])
    _runner.invoke(app, ["show", "-e", URL, "--limit", "5"])

    assert [s.limit for s, _ in launched] == [777, 5]


def test_query_is_read_from_a_file_when_one_is_named(launched, tmp_path):
    rq = tmp_path / "q.rq"
    rq.write_text("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", encoding="utf-8")

    _runner.invoke(app, ["show", "-e", URL, "--query", str(rq)])

    assert launched[0][0].query == "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"


def test_query_text_is_used_as_given(launched):
    _runner.invoke(app, ["show", "-e", URL, "--query", "DESCRIBE <https://e#a>"])

    assert launched[0][0].query == "DESCRIBE <https://e#a>"


def test_graph_and_query_are_mutually_exclusive(launched):
    result = _runner.invoke(
        app, ["show", "-e", URL, "--graph", "https://g", "--query", "CONSTRUCT {} WHERE {}"]
    )

    assert result.exit_code == ExitCode.USAGE
    assert launched == []


def test_endpoint_and_file_are_mutually_exclusive(launched, tmp_path):
    ttl = tmp_path / "a.ttl"
    ttl.write_text("", encoding="utf-8")

    result = _runner.invoke(app, ["show", str(ttl), "--endpoint", URL])

    assert result.exit_code == ExitCode.USAGE
    assert launched == []


def test_a_select_query_is_refused_with_a_usage_error(launched):
    result = _runner.invoke(app, ["show", "-e", URL, "--query", "SELECT * WHERE { ?s ?p ?o }"])

    assert result.exit_code == ExitCode.USAGE
    assert "CONSTRUCT" in result.output
    assert launched == []


def test_a_malformed_header_is_a_usage_error(launched):
    result = _runner.invoke(app, ["show", "-e", URL, "--header", "no-colon-here"])

    assert result.exit_code == ExitCode.USAGE
    assert launched == []


def test_plain_prints_the_tree_without_a_terminal(monkeypatch):
    from ster import store

    taxonomy = store.taxonomy_from_bytes(
        b'@prefix skos: <http://www.w3.org/2004/02/skos/core#> . <https://e#a> a skos:Concept ; skos:prefLabel "Alpha"@en .'
    )
    monkeypatch.setattr(
        cli_endpoint, "load", lambda _source, _progress=None: ep.Snapshot(taxonomy, 2, False)
    )

    result = _runner.invoke(app, ["show", "-e", URL, "--plain"])

    assert result.exit_code == 0
    assert "Alpha" in result.output


def test_plain_reports_an_unreachable_endpoint_and_fails(monkeypatch):
    def _down(_source, _progress=None):
        raise EndpointError("Could not reach https://x: refused")

    monkeypatch.setattr(cli_endpoint, "load", _down)

    result = _runner.invoke(app, ["show", "-e", URL, "--plain"])

    assert result.exit_code == ExitCode.FILE
    assert "Could not reach" in result.output


def test_plain_warns_when_the_limit_cut_the_data(monkeypatch):
    from ster import store

    taxonomy = store.taxonomy_from_bytes(b"")
    monkeypatch.setattr(
        cli_endpoint, "load", lambda _source, _progress=None: ep.Snapshot(taxonomy, 5, True)
    )

    result = _runner.invoke(app, ["show", "-e", URL, "--limit", "5", "--plain"])

    assert "Row limit" in result.output


def test_the_viewer_needs_a_terminal(monkeypatch):
    monkeypatch.setattr("ster.cli._viewer._is_interactive_terminal", lambda: False)

    result = _runner.invoke(app, ["show", "-e", URL])

    assert result.exit_code == ExitCode.USAGE
    assert "interactive terminal" in result.output


# ── the home menu ─────────────────────────────────────────────────────────────


def _answers(monkeypatch, *replies: str):
    queue = list(replies)
    monkeypatch.setattr("ster.ask.text", lambda *_a, **_k: queue.pop(0))


def test_menu_entry_prompts_and_launches(monkeypatch, launched):
    _answers(monkeypatch, URL, "graph", "https://g/1", "300", "")

    cli_endpoint.run_endpoint_interactive()

    source, _ = launched[0]
    assert (source.url, source.graph, source.limit) == (URL, "https://g/1", 300)


def test_menu_remembers_the_row_limit_for_next_time(monkeypatch, launched):
    _answers(monkeypatch, URL, "default", str(MENU_LIMIT), "")

    cli_endpoint.run_endpoint_interactive()

    assert ep.saved_limit() == MENU_LIMIT


def test_menu_passes_a_header_through(monkeypatch, launched):
    _answers(monkeypatch, URL, "default", "100", "Authorization: Bearer t")

    cli_endpoint.run_endpoint_interactive()

    assert launched[0][0].headers == (("Authorization", "Bearer t"),)


def test_menu_survives_a_bad_row_limit(monkeypatch, launched):
    _answers(monkeypatch, URL, "default", "lots", "")

    cli_endpoint.run_endpoint_interactive()

    assert launched == []


def test_menu_stops_on_an_invalid_endpoint(monkeypatch, launched):
    _answers(monkeypatch, "ftp://nope", "default", "100", "")

    cli_endpoint.run_endpoint_interactive()

    assert launched == []


def test_the_file_list_offers_the_endpoint_row(monkeypatch):
    from ster.cli import _constants, _workspace_ui

    monkeypatch.setattr("ster.ask.text", lambda *_a, **_k: "3")  # 1 file → demo=2, endpoint=3
    choice = _workspace_ui._select_home_file_numeric([Path("a.ttl")])

    assert choice == _constants._ENDPOINT_SENTINEL


def test_choosing_the_endpoint_row_runs_the_flow_then_returns_to_the_list(monkeypatch):
    from ster.cli import _constants, _home, _workspace_ui

    ran: list[bool] = []
    monkeypatch.setattr(_home, "_print_home_intro", lambda: None)
    monkeypatch.setattr(
        _workspace_ui, "_select_home_file", lambda _found: _constants._ENDPOINT_SENTINEL
    )
    monkeypatch.setattr(cli_endpoint, "run_endpoint_interactive", lambda: ran.append(True))

    file, action = _home._home_obtain_action(None, None, [])

    assert ran == [True]
    assert file is None and action is _constants._CHANGE_FILE_SENTINEL


def test_plain_exits_4_when_the_answer_is_not_rdf(monkeypatch):
    def _html(_source, _progress=None):
        raise NotRdfError("https://x did not return RDF (login page)")

    monkeypatch.setattr(cli_endpoint, "load", _html)

    result = _runner.invoke(app, ["show", "-e", URL, "--plain"])

    assert result.exit_code == ExitCode.INVALID_RDF


def test_plain_warns_when_the_endpoint_answers_with_nothing(monkeypatch):
    from ster import store

    taxonomy = store.taxonomy_from_bytes(b"")
    monkeypatch.setattr(
        cli_endpoint, "load", lambda _source, _progress=None: ep.Snapshot(taxonomy, 0, False)
    )

    result = _runner.invoke(app, ["show", "-e", URL, "--plain"])

    assert result.exit_code == 0
    assert "no triples" in result.output


def test_timeout_flag_reaches_the_source(launched):
    result = _runner.invoke(app, ["show", "-e", URL, "--timeout", "7.5"])

    assert result.exit_code == 0
    assert launched[0][0].timeout == pytest.approx(7.5)


def test_the_default_timeout_applies_without_the_flag(launched):
    _runner.invoke(app, ["show", "-e", URL])

    assert launched[0][0].timeout == ep.DEFAULT_TIMEOUT


@pytest.mark.parametrize("timeout", ["0", "-3"])
def test_a_non_positive_timeout_is_a_usage_error(launched, timeout):
    result = _runner.invoke(app, ["show", "-e", URL, "--timeout", timeout])

    assert result.exit_code == ExitCode.USAGE
    assert launched == []


@pytest.mark.parametrize("url", ["http://[::1", "http://host/a b", "https://u:pw@host/sparql"])
def test_an_unsendable_url_is_a_usage_error_not_a_crash(launched, url):
    result = _runner.invoke(app, ["show", "-e", url, "--plain"])

    assert result.exit_code == ExitCode.USAGE
    assert "pw@" not in result.output
    assert launched == []


def test_a_header_with_a_line_break_is_a_usage_error(launched):
    result = _runner.invoke(app, ["show", "-e", URL, "--header", "X-A: b\nInjected: 1"])

    assert result.exit_code == ExitCode.USAGE
