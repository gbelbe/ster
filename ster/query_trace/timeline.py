"""Accessible HTML timeline for all recorded MCP query steps."""

from __future__ import annotations

import html
import json
from collections.abc import Iterable
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

from .model import Event


def render_timeline_html(
    sessions: Iterable[Any] | Iterable[Event],
    *,
    page: int = 1,
    page_size: int = 10,
    idle_seconds: int = 60,
    after: str = "",
    before: str = "",
    title: str = "MCP Query Timeline",
) -> str:
    # These reach the page's text and its pager links: whatever called us, only numbers go in.
    page, page_size, idle_seconds = int(page), int(page_size), int(idle_seconds)
    groups = list(sessions)
    if groups and isinstance(groups[0], Event):
        events = groups
        session = SimpleNamespace(
            run_id=events[0].run_id,
            question=events[0].payload.get("question", ""),
            status=events[-1].payload.get("status", "failed"),
            started=events[0].timestamp,
            ended=events[-1].timestamp,
            event_count=len(events),
        )
        groups = [
            SimpleNamespace(
                calls=((session, events),),
                call_count=1,
                started=session.started,
                ended=session.ended,
                event_count=session.event_count,
            )
        ]
    elif groups and isinstance(groups[0], tuple):
        groups = [
            SimpleNamespace(
                calls=(group,),
                call_count=1,
                started=group[0].started,
                ended=getattr(group[0], "ended", group[0].started),
                event_count=group[0].event_count,
                agent_question=getattr(group[0], "agent_question", None),
                session_question=getattr(group[0], "agent_session_question", None),
            )
            for group in groups
        ]
    start = max(0, (page - 1) * page_size)
    visible = groups[start : start + page_size]
    rows = "".join(
        _agent_group(agent_session, start + index + 1)
        for index, agent_session in enumerate(visible)
    )
    navigation = _navigation(page, page_size, len(groups), after, before, idle_seconds)
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>
 <style>body{{font:16px system-ui;margin:2rem;background:#10151d;color:#e8edf2}}main{{max-width:1100px;margin:auto}}h1{{color:#8fd3ff}}form{{display:flex;gap:1rem;flex-wrap:wrap;padding:1rem;background:#18222c;border:1px solid #344958;border-radius:6px}}label{{display:flex;gap:.4rem;align-items:center}}input,button{{font:inherit;padding:.35rem .5rem}}ol{{list-style:none;padding:0;border-left:2px solid #4e7892}}li{{padding:1rem 1.5rem;border-bottom:1px solid #29333d}}time{{color:#91a8b8;margin-right:1rem}}span{{color:#b8c4cd}}.agent-session{{margin:1.5rem 0;border:2px solid #4d7892;border-radius:10px;background:#101a22;padding:.5rem}}.agent-session>header{{padding:1rem;background:#18394a;border-radius:7px}}.agent-session>header h2{{margin:.2rem 0;color:#b8e4f7}}.run{{margin:1.2rem 0;border:1px solid #405563;border-radius:7px;background:#131d25}}.run>header{{padding:1rem;background:#182b38}}.run>header h2{{margin:0;color:#91c9e8;font-size:1.05rem}}.run>header p{{margin:.4rem 0;white-space:pre-wrap}}.agent-question-box{{margin:.8rem 0;padding:.7rem;background:#203b48;border-left:4px solid #8fd3ff;color:#e8f6fb;white-space:pre-wrap}}.run-summary{{margin:0}}.event-history{{border-top:1px solid #344958;padding:.7rem 1rem;color:#91c9e8}}.event-history summary{{cursor:pointer}}.trace-detail{{margin:.65rem 0 0 7.5rem;color:#d8e1e8;font-size:.9rem}}.trace-detail b{{color:#91c9e8}}.trace-results{{margin:.8rem 0;border:1px solid #344958;border-radius:5px;padding:.5rem;background:#18222c;overflow:auto}}.trace-results summary{{cursor:pointer;color:#91c9e8;font-weight:700}}table{{border-collapse:collapse;margin-top:.5rem;font-size:.85rem;min-width:500px}}th,td{{border:1px solid #405563;padding:.35rem .5rem;text-align:left}}th{{background:#243541;color:#b8dff2}}.trace-query{{margin:.65rem 0 0;padding:.7rem;background:#18222c;border:1px solid #344958;border-radius:5px;white-space:pre-wrap;overflow:auto;font:12px ui-monospace,monospace;max-height:180px}}.trace-query-top{{max-height:260px}}.sparql-keyword{{color:#8fd3ff;font-weight:700}}.pager{{display:flex;justify-content:space-between;margin:1rem 0}}</style></head>
 <body><main><h1>{html.escape(title)}</h1><form method="get"><label>From <input type="datetime-local" name="after" value="{html.escape(after, quote=True)}"></label><label>To <input type="datetime-local" name="before" value="{html.escape(before, quote=True)}"></label><label>Group calls within <input type="number" name="idle_seconds" min="1" max="3600" value="{idle_seconds}"> seconds</label><button>Apply</button></form><p>{start + 1 if groups else 0}-{min(start + page_size, len(groups))} of {len(groups)} agent sessions · {idle_seconds}s grouping window</p>{rows}{navigation}</main></body></html>"""


def _group(session: Any, events: list[Event], ordinal: int) -> str:
    run_id = html.escape(str(session.run_id))
    query = next(
        (event.payload.get("query") for event in events if event.event == "query_generated"),
        str(session.question),
    )
    query_block = (
        '<pre class="trace-query trace-query-top"><code class="language-sparql">'
        f"{_highlight_sparql(str(query))}</code></pre>"
    )
    call_description = _call_description(query)
    question_block = _question_block(session, call_description)
    called_at = _format_time(session.started)
    terminal = next(
        (event for event in reversed(events) if event.event in {"step_completed", "step_failed"}),
        events[-1] if events else None,
    )
    summary = _event_row(terminal) if terminal else ""
    history = "".join(_event_row(event) for event in events)
    return (
        f'<section class="run"><header><div class="run-kicker">Session {ordinal}</div>'
        f"<h2>Step {ordinal}: {html.escape(call_description)} at {called_at} ({run_id}) "
        f'<span class="status-badge">{html.escape(str(session.status))}</span></h2>'
        f"{query_block}{question_block}"
        f"<small>{html.escape(str(session.started))} · {session.event_count} events</small>"
        f'</header><ol class="run-summary" aria-label="Session {ordinal} summary">{summary}</ol>'
        f'<details class="event-history"><summary>Show all events ({session.event_count})</summary>'
        f"<ol>{history}</ol></details></section>"
    )


def _call_description(query: object) -> str:
    """Name non-SPARQL MCP calls from their serialized trace question."""
    try:
        request = json.loads(str(query))
    except json.JSONDecodeError:
        return "MCP raw-sparql called"
    tool = request.get("tool") if isinstance(request, dict) else None
    if not tool:
        return "MCP raw-sparql called"
    return f"MCP {tool} called"


def _question_block(session: Any, call_description: str) -> str:
    """Show the SPARQL-specific label only for raw SPARQL calls."""
    if not call_description.startswith("MCP raw-sparql"):
        return ""
    question = getattr(session, "agent_question", "") or "Not provided by agent."
    return (
        '<div class="agent-question-box"><b>SPARQL question</b><br>'
        f"{html.escape(str(question))}</div>"
    )


def _format_time(timestamp: str) -> str:
    """Format an event timestamp as the compact session-title time."""
    try:
        value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp
    return value.strftime("%H h %M min %S sec")


def _agent_group(agent_session: Any, ordinal: int) -> str:
    calls = agent_session.calls
    body = "".join(
        _group(session, events, index + 1) for index, (session, events) in enumerate(calls)
    )
    return (
        f'<section class="agent-session"><header><div class="run-kicker">Agent session {ordinal}</div>'
        f"<h2>{agent_session.call_count} MCP calls</h2>"
        f'<p class="agent-question"><b>Original user question</b><br>{html.escape(str(getattr(agent_session, "session_question", None) or "Not provided by agent."))}</p>'
        f'<p class="agent-tokens">{_session_token_summary(getattr(agent_session, "token_usage", None))}</p>'
        f"<small>{html.escape(agent_session.started)} → {html.escape(agent_session.ended)} · "
        f"{agent_session.event_count} events</small></header>{body}</section>"
    )


def _event_row(event: Event) -> str:
    label = event.step_id or event.event.replace("_", " ")
    return f"<li><time>{html.escape(event.timestamp)}</time> <b>{html.escape(label)}</b> <span>{html.escape(event.event.replace('_', ' '))}</span>{_details(event)}</li>"


def _details(event: Event) -> str:
    if event.event not in {"step_completed", "step_failed"}:
        return ""
    payload = event.payload
    facts = []
    for label, value in (
        ("Status", payload.get("status")),
        ("Objective", payload.get("objective")),
        (
            "Duration",
            f"{payload['duration_ms']} ms" if payload.get("duration_ms") is not None else None,
        ),
        ("Rows", payload.get("row_count")),
        ("Columns", ", ".join(payload.get("columns", [])) if payload.get("columns") else None),
        ("Tokens", _token_summary(payload.get("token_usage"))),
    ):
        if value not in (None, ""):
            facts.append(f"<b>{html.escape(label)}:</b> {html.escape(str(value))}")
    if payload.get("result_truncated"):
        facts.append(
            f"<b>Results:</b> {payload.get('row_count', 0)} total results, truncated to {len(payload.get('result_rows', []))}"
        )
    elif payload.get("row_count") is not None:
        facts.append(f"<b>Results:</b> {payload.get('row_count', 0)} total results")
    return f'<div class="trace-detail">{" · ".join(facts)}{_results_table(payload)}</div>'


def _token_summary(usage: object) -> str | None:
    if not isinstance(usage, dict):
        return None
    aliases = {
        "input_tokens": usage.get("input_tokens", usage.get("input")),
        "output_tokens": usage.get("output_tokens", usage.get("output")),
        "total_tokens": usage.get("total_tokens", usage.get("total")),
    }
    parts = [
        f"{label} {aliases[key]}"
        for label, key in (
            ("input", "input_tokens"),
            ("output", "output_tokens"),
            ("total", "total_tokens"),
        )
        if aliases.get(key) is not None
    ]
    if not parts:
        return None
    source = usage.get("source")
    return " · ".join(parts) + (f" · {source}" if source else "")


def _session_token_summary(usage: object) -> str:
    summary = _token_summary(usage)
    return f"Tokens: {summary}" if summary else "Token usage not provided by agent."


def _highlight_sparql(query: str) -> str:
    """Escape and apply lightweight highlighting without a runtime dependency."""
    escaped = html.escape(query)
    keywords = (
        "PREFIX|SELECT|WHERE|OPTIONAL|FILTER|GROUP BY|ORDER BY|LIMIT|COUNT|DISTINCT|"
        "AS|BIND|VALUES|FROM|GRAPH|UNION|ASK|CONSTRUCT|DESCRIBE"
    )
    import re

    return re.sub(
        rf"\b({keywords})\b",
        r'<span class="sparql-keyword">\1</span>',
        escaped,
        flags=re.IGNORECASE,
    )


def _results_table(payload: dict) -> str:
    rows, columns = payload.get("result_rows", []), payload.get("columns", [])
    if not rows or not columns:
        return ""
    header = "".join(f"<th>{html.escape(str(column))}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f'<details class="trace-results"><summary>Show results ({len(rows)} loaded)</summary><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></details>'


def _navigation(
    page: int, page_size: int, total: int, after: str, before: str, idle_seconds: int = 60
) -> str:
    if total <= page_size:
        return ""

    def link(target: int, label: str) -> str:
        query = urlencode(
            {
                "page": target,
                "page_size": page_size,
                "idle_seconds": idle_seconds,
                "after": after,
                "before": before,
            }
        )
        return f'<a href="?{query}">{label}</a>'

    previous = link(page - 1, "Previous") if page > 1 else ""
    following = link(page + 1, "Next") if page * page_size < total else ""
    return f'<nav class="pager">{previous}<span>Page {page}</span>{following}</nav>'
