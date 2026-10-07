"""Textual session list for the MCP query-trace timeline plugin."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Button, Label, Static

from ster.query_trace.jsonl import read_events
from ster.query_trace.materialize import materialize_events

from .sessions import TraceSession, materialized_path, sessions_for_project


class TracePanel(Vertical):
    """List current-project runs and open their PROV-O TriG traces."""

    def __init__(
        self,
        project: Path | None,
        *,
        open_browser: Callable[[str], object] = webbrowser.open,
        materialize: Callable[[TraceSession], Path] | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.sessions = sessions_for_project(project) if project else []
        self._open_browser = open_browser

    def compose(self) -> ComposeResult:
        yield Static(
            "MCP query sessions for the current project. Select a session to open its PROV-O trace.",
            classes="cfg-tab-intro",
        )
        if not self.sessions:
            yield Static("No recorded query sessions.", id="trace-empty")
            return
        with VerticalScroll(id="trace-sessions"):
            for session in self.sessions:
                yield Label(
                    f"{session.question or 'Unnamed query'}\n"
                    f"{session.status} · {session.started} · {session.event_count} events",
                    classes="trace-session-label",
                )
                yield Button("Open PROV-O trace", id=f"trace-provo-{session.run_id}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if not button_id.startswith("trace-"):
            return
        _, _view, run_id = button_id.split("-", 2)
        session = next((item for item in self.sessions if item.run_id == run_id), None)
        if session is None:
            return
        output = materialized_path(session)
        materialize_events(read_events(session.path)).serialize(destination=output, format="trig")
        self._open_browser(output.as_uri())
        self.app.notify("Opened PROV-O trace", severity="information")
