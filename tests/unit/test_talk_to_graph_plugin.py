"""The talk-to-graph plugin and the MCP plugin's rename."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ster import plugins
from ster.plugins import talk_to_graph


@pytest.fixture
def prefs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "prefs.json"
    monkeypatch.setattr("ster.nav.prefs._prefs_path", lambda: path)
    return path


def test_talk_to_graph_is_not_a_plugin_of_its_own_it_is_part_of_mcp(prefs):
    assert plugins.get("talk_to_graph") is None
    assert "Talk to graph" in plugins.get("mcp").description  # type: ignore[union-attr]
    assert plugins.is_enabled("mcp") is False
    assert talk_to_graph.is_enabled() is False


def test_one_switch_turns_on_the_page_and_the_recording(prefs, tmp_path, monkeypatch):
    from ster import query_trace
    from ster.plugins.query_trace import follow_setting

    monkeypatch.delenv("STER_QUERY_TRACE", raising=False)
    monkeypatch.setattr(query_trace.recorder, "_recorder", query_trace.NoOpTraceRecorder())
    follow_setting(tmp_path / "f.ttl")
    assert query_trace.get_recorder().enabled() is False

    plugins.set_enabled("mcp", True)
    assert talk_to_graph.is_enabled() is True
    follow_setting(tmp_path / "f.ttl")
    recorder = query_trace.get_recorder()
    assert recorder.enabled() is True
    assert recorder.directory == tmp_path.resolve() / ".ster" / "query-traces"  # type: ignore[attr-defined]


def test_an_explicit_environment_wins_over_the_switch(prefs, tmp_path, monkeypatch):
    from ster import query_trace
    from ster.plugins.query_trace import follow_setting

    monkeypatch.setattr(query_trace.recorder, "_recorder", query_trace.NoOpTraceRecorder())
    plugins.set_enabled("mcp", True)
    monkeypatch.setenv("STER_QUERY_TRACE", "0")
    follow_setting(tmp_path / "f.ttl")
    assert query_trace.get_recorder().enabled() is False


def test_the_query_trace_plugin_is_now_called_mcp():
    assert plugins.get("mcp") is not None
    assert plugins.get("mcp").name == "MCP"  # type: ignore[union-attr]
    assert plugins.get("mcp_query_trace") is None


def test_a_saved_choice_under_the_old_id_still_counts(prefs):
    prefs.write_text(json.dumps({"plugin.mcp_query_trace.enabled": True}))
    assert plugins.is_enabled("mcp") is True


def test_a_choice_under_the_new_id_wins_over_the_old_one(prefs):
    prefs.write_text(json.dumps({"plugin.mcp_query_trace.enabled": True}))
    plugins.set_enabled("mcp", False)
    assert plugins.is_enabled("mcp") is False


def test_agent_ready_needs_the_option_and_an_agent(prefs, monkeypatch):
    monkeypatch.setattr("agent_app.launcher.has_usable_agent", lambda *a, **k: True)
    assert talk_to_graph.agent_ready() is False
    plugins.set_enabled("mcp", True)
    assert talk_to_graph.agent_ready() is True
    monkeypatch.setattr("agent_app.launcher.has_usable_agent", lambda *a, **k: False)
    assert talk_to_graph.agent_ready() is False


def test_the_page_is_started_for_the_folder_of_the_file_and_pointed_at_sters_server(
    monkeypatch, tmp_path
):
    seen: list[tuple] = []

    def fake(project, host, port):
        seen.append((project, host, port))
        return SimpleNamespace(url="http://127.0.0.1:8780", error=None)

    monkeypatch.setattr("agent_app.launcher.ensure_running", fake)
    url, why = talk_to_graph.page_url(tmp_path / "f.ttl", "http://127.0.0.1", 8765)
    assert (url, why) == ("http://127.0.0.1:8780", None)
    assert seen == [
        (tmp_path.resolve(), "127.0.0.1", 8765)
    ]  # one page per open graph: no file, no context


def test_a_page_that_could_not_start_says_why(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent_app.launcher.ensure_running",
        lambda *a, **k: SimpleNamespace(url=None, error="no free port"),
    )
    assert talk_to_graph.page_url(tmp_path / "f.ttl", "http://h", 1) == (None, "no free port")


def test_the_a_key_is_bound_and_only_available_while_the_option_is_on(prefs):
    from ster.tui.app import OntologyApp

    assert any(b.key == "a" and b.action == "open_agent" for b in OntologyApp.BINDINGS)  # type: ignore[union-attr]
    app = OntologyApp.__new__(OntologyApp)
    assert OntologyApp.check_action(app, "open_agent", ()) is False
    plugins.set_enabled("mcp", True)
    assert OntologyApp.check_action(app, "open_agent", ()) is True


def test_the_project_folder_is_the_nearest_one_with_a_project_file(tmp_path):
    from ster.project import home_of

    (tmp_path / ".ster").mkdir()
    (tmp_path / ".ster" / "project.json").write_text("{}")
    (tmp_path / "data").mkdir()
    assert home_of(tmp_path / "data" / "g.ttl") == tmp_path.resolve()
    assert home_of(tmp_path / "g.ttl") == tmp_path.resolve()


def test_without_a_project_file_it_is_the_files_own_folder(tmp_path):
    from ster.project import home_of

    (tmp_path / "data").mkdir()
    assert home_of(tmp_path / "data" / "g.ttl") == (tmp_path / "data").resolve()


def test_traces_and_the_page_use_that_folder(prefs, tmp_path, monkeypatch):
    from ster import query_trace
    from ster.plugins.query_trace import follow_setting

    (tmp_path / ".ster").mkdir()
    (tmp_path / ".ster" / "project.json").write_text("{}")
    (tmp_path / "data").mkdir()
    monkeypatch.delenv("STER_QUERY_TRACE", raising=False)
    monkeypatch.setattr(query_trace.recorder, "_recorder", query_trace.NoOpTraceRecorder())
    plugins.set_enabled("mcp", True)
    follow_setting(tmp_path / "data" / "g.ttl")
    assert query_trace.get_recorder().directory == tmp_path.resolve() / ".ster" / "query-traces"  # type: ignore[attr-defined]


# ── the `a` key ───────────────────────────────────────────────────────────────


def _app_with_file(tmp_path):
    from ster import store
    from ster.tui.app import OntologyApp

    src = tmp_path / "o.ttl"
    src.write_text("@prefix : <https://example.org/o#> .\n", encoding="utf-8")
    app = OntologyApp(store.load(src), source="o.ttl", path=src)
    said: list[tuple[str, str | None]] = []
    app.notify = lambda message, severity=None, **_k: said.append((message, severity))  # type: ignore[method-assign]
    return app, said


def _stub(monkeypatch, *, running=True, page=("http://127.0.0.1:8781", None), opened=True):
    from ster.tui import query

    monkeypatch.setattr(query, "server_is_running", lambda: running)
    monkeypatch.setattr(query, "server_unavailable_reason", lambda: "ster is not running")
    monkeypatch.setattr(query, "open_browser", lambda _url: opened)
    monkeypatch.setattr(talk_to_graph, "page_url", lambda *_a: page)
    monkeypatch.setattr("ster.api_server.load_server_config", lambda: ("http://127.0.0.1", 8765))


def test_the_key_needs_a_file(tmp_path, monkeypatch):
    app, said = _app_with_file(tmp_path)
    app._path = None
    _stub(monkeypatch)
    app.action_open_agent()
    assert said and "Open a file first" in said[0][0]


def test_the_key_says_when_ster_is_not_running(tmp_path, monkeypatch):
    app, said = _app_with_file(tmp_path)
    _stub(monkeypatch, running=False)
    app.action_open_agent()
    assert said == [("ster is not running", "warning")]


def test_the_key_says_why_the_page_did_not_start(tmp_path, monkeypatch):
    app, said = _app_with_file(tmp_path)
    _stub(monkeypatch, page=(None, "no free port"))
    app.action_open_agent()
    assert said == [("no free port", "warning")]


def test_the_key_says_when_no_browser_opened(tmp_path, monkeypatch):
    app, said = _app_with_file(tmp_path)
    _stub(monkeypatch, opened=False)
    app.action_open_agent()
    assert "Couldn't open a browser" in said[0][0]


def test_the_key_opens_the_page_and_says_where(tmp_path, monkeypatch):
    app, said = _app_with_file(tmp_path)
    _stub(monkeypatch)
    app.action_open_agent()
    assert said == [("Agent page opened in your browser — http://127.0.0.1:8781", None)]


# ── a launch-time override can be taken away again ────────────────────────────


def test_an_override_can_be_removed(prefs):
    plugins.override("mcp", True)
    assert plugins.is_enabled("mcp") is True
    plugins.override("mcp", None)
    assert plugins.is_enabled("mcp") is False  # back to the saved choice
