"""Behaviour tests for the MCP query-trace plugin boundary."""

from __future__ import annotations

import ast
from pathlib import Path

from ster.plugins import get, is_enabled, set_enabled
from ster.plugins.query_trace.sessions import AgentSession, TraceSession, sessions_for_project
from ster.query_trace.model import Event


def test_query_trace_plugin_is_registered_with_portable_dependency():
    spec = get("mcp_query_trace")
    assert spec is not None
    assert spec.dependency == "ster.query_trace"


def test_query_trace_plugin_enablement_is_persistent(monkeypatch, tmp_path):
    prefs = tmp_path / "prefs.json"
    monkeypatch.setattr("ster.nav.prefs._prefs_path", lambda: prefs)

    set_enabled("mcp_query_trace", True)
    assert is_enabled("mcp_query_trace") is True
    assert "mcp_query_trace" in prefs.read_text(encoding="utf-8")

    set_enabled("mcp_query_trace", False)
    assert is_enabled("mcp_query_trace") is False


def test_plugin_dependency_is_checked_as_an_importable_module():
    import importlib

    spec = get("mcp_query_trace")
    assert spec is not None
    assert importlib.util.find_spec(spec.dependency) is not None


def test_plugin_adapter_imports_only_portable_trace_module():
    root = Path(__file__).parents[2] / "ster" / "plugins" / "query_trace"
    forbidden = {"mcp_server", "mcp_context", "api", "model", "tui"}
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            alias.name.split(".")[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        )
        assert not forbidden & imported, f"application import leaked into {path}"


def test_sessions_are_limited_to_the_current_project(tmp_path):
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir()
    other.mkdir()
    (project / ".ster" / "query-traces").mkdir(parents=True)
    (other / ".ster" / "query-traces").mkdir(parents=True)
    (project / ".ster" / "query-traces" / "run-project.jsonl").write_text(
        '{"event":"run_started","event_id":"event-project-1","run_id":"run-project","trace_id":"trace-project","sequence":1,"timestamp":"2026-01-01T00:00:00Z","payload":{"question":"project"}}\n'
        '{"event":"run_completed","event_id":"event-project-2","run_id":"run-project","trace_id":"trace-project","sequence":2,"timestamp":"2026-01-01T00:00:01Z","payload":{"status":"completed"}}\n',
        encoding="utf-8",
    )
    (other / ".ster" / "query-traces" / "run-other.jsonl").write_text("", encoding="utf-8")

    rows = sessions_for_project(project)
    assert [row.run_id for row in rows] == ["run-project"]


def test_trace_panel_lists_provo_session(tmp_path):
    from ster.plugins.query_trace.panel import TracePanel

    project = tmp_path / "project"
    trace_dir = project / ".ster" / "query-traces"
    trace_dir.mkdir(parents=True)
    (trace_dir / "run-one.jsonl").write_text(
        '{"event":"run_started","event_id":"event-one-1","run_id":"run-one","trace_id":"trace-one","sequence":1,"timestamp":"2026-01-01T00:00:00Z","payload":{"question":"Find one"}}\n'
        '{"event":"run_completed","event_id":"event-one-2","run_id":"run-one","trace_id":"trace-one","sequence":2,"timestamp":"2026-01-01T00:00:01Z","payload":{"status":"completed"}}\n',
        encoding="utf-8",
    )
    opened: list[str] = []
    panel = TracePanel(project, open_browser=opened.append)

    assert panel.sessions[0].run_id == "run-one"


def test_trace_panel_renders_empty_project_message(tmp_path):
    from ster.plugins.query_trace.panel import TracePanel

    project = tmp_path / "project"
    project.mkdir()
    panel = TracePanel(project)

    assert str(list(panel.compose())[-1].render()) == "No recorded query sessions."


def test_trace_panel_opens_a_materialized_trace(tmp_path, monkeypatch):
    from textual.app import App, ComposeResult

    from ster.plugins.query_trace.panel import TracePanel

    project = tmp_path / "project"
    trace_dir = project / ".ster" / "query-traces"
    trace_dir.mkdir(parents=True)
    (trace_dir / "run-one.jsonl").write_text(
        '{"event":"run_started","event_id":"event-one-1","run_id":"run-one","trace_id":"trace-one","sequence":1,"timestamp":"2026-01-01T00:00:00Z","payload":{"question":"Find one"}}\n'
        '{"event":"run_completed","event_id":"event-one-2","run_id":"run-one","trace_id":"trace-one","sequence":2,"timestamp":"2026-01-01T00:00:01Z","payload":{"status":"completed"}}\n',
        encoding="utf-8",
    )
    opened: list[str] = []

    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield TracePanel(project, open_browser=opened.append)

    async def scenario() -> None:
        app = Host()
        async with app.run_test(size=(100, 24)) as pilot:
            await pilot.click("#trace-provo-run-one")

    import asyncio

    asyncio.run(scenario())
    assert opened and opened[0].startswith("file:")


def test_trace_panel_visual_snapshot(tmp_path):
    from textual.app import App, ComposeResult
    from textual.widgets import Footer

    from ster.plugins.query_trace.panel import TracePanel

    project = tmp_path / "project"
    trace_dir = project / ".ster" / "query-traces"
    trace_dir.mkdir(parents=True)
    (trace_dir / "run-visual.jsonl").write_text(
        '{"event":"run_started","event_id":"event-v-1","run_id":"run-visual","trace_id":"trace-v","sequence":1,"timestamp":"2026-01-01T00:00:00Z","payload":{"question":"Show visual trace"}}\n'
        '{"event":"run_completed","event_id":"event-v-2","run_id":"run-visual","trace_id":"trace-v","sequence":2,"timestamp":"2026-01-01T00:00:01Z","payload":{"status":"completed"}}\n',
        encoding="utf-8",
    )

    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield TracePanel(project)
            yield Footer()

    async def scenario() -> None:
        app = Host()
        async with app.run_test(size=(100, 24)) as pilot:
            await pilot.pause()
            assert any("Show visual trace" in str(widget.render()) for widget in app.query("Label"))
            assert app.query("#trace-provo-run-visual")

    import asyncio

    asyncio.run(scenario())


def test_agent_session_aggregates_questions_and_token_usage(tmp_path):
    session = TraceSession(
        run_id="run",
        trace_id="trace",
        question="query",
        status="completed",
        started="2026-01-01T00:00:00Z",
        ended="2026-01-01T00:00:01Z",
        path=tmp_path / "run.jsonl",
        event_count=2,
        agent_question="step question",
        agent_session_question="global question",
    )
    events = [
        Event(
            "run_started",
            "run",
            "trace",
            1,
            payload={"token_usage": {"input": 2, "output": 3, "total": 5}},
        )
    ]
    grouped = AgentSession(((session, events),))

    assert grouped.started == session.started
    assert grouped.ended == session.ended
    assert grouped.event_count == 2
    assert grouped.call_count == 1
    assert grouped.agent_question == "step question"
    assert grouped.session_question == "global question"
    assert grouped.token_usage == {"input": 2, "output": 3, "total": 5}
