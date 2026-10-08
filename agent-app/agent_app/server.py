"""Ask the ontology: a local web front end for the user's own coding agent.

    python -m agent_app                 # http://127.0.0.1:8780

The page POSTs a question here. The bridge runs a configured command (a recipe in recipes/, or
ASK_AGENT_CMD) and turns what it prints into a flat list of events
(steps, tool calls, token usage, results). Each ster tool result is joined with
the trace ster wrote for it (.ster/query-traces/run-*.jsonl), so the timeline
shows the SPARQL that ran, its rows and its duration next to the tokens it cost.

Runs outlive the browser tab: events are kept in memory while a run is live and
saved with the conversation, so a reload or a later visit replays the same list.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from . import history, native, reported, runner
from . import rules as rule_engine

WEB = Path(__file__).resolve().parent
STATIC = WEB / "static"  # the only folder served to the browser


def settings(env: dict, cwd: Path) -> dict:
    """Which project the page is about. ASK_PROJECT names it; otherwise the folder the server is run from. Its
    conversations, ster traces and agent working directory are all inside it, so a project's history stays with it."""
    root = Path(env["ASK_PROJECT"]).expanduser().resolve() if env.get("ASK_PROJECT") else cwd
    return {
        "root": root,
        "host": env.get("ASK_STER_HOST", "127.0.0.1"),
        "port": int(env.get("ASK_STER_PORT", "8765")),
    }


_cfg = settings(dict(os.environ), Path.cwd())
ROOT = _cfg["root"]
STER_DIR = ROOT / ".ster"
TRACES = STER_DIR / "query-traces"
STORE = STER_DIR / "agent-app" / "conversations"
STER_HOST, STER_PORT = _cfg["host"], _cfg["port"]
WEB_PORT = int(os.environ.get("ASK_PORT", "8780"))
MODEL = os.environ.get("ASK_MODEL")  # optional: the agent's --model value
RECIPES_DIR = Path(os.environ.get("ASK_RECIPES", WEB / "recipes"))
RECIPES = runner.load_recipes(RECIPES_DIR)  # JSON command templates; none is privileged
CUSTOM = runner.from_env(os.environ)  # or any command given in ASK_AGENT_CMD
WANT = os.environ.get("ASK_RECIPE")  # optional: name of the recipe to use


def current_agent() -> runner.Agent | None:
    """Looked up on each call: a program installed while the server runs is picked up."""
    return runner.select(RECIPES, CUSTOM, WANT)


TOKEN_FILE = Path.home() / ".config" / "ster" / "api_token"
RESULT_CAP = 6000  # characters of a tool result kept in an event

SYSTEM_PROMPT = """\
You answer questions about the ontology served by the ster MCP tools. Follow the
order the server asks for: get_overview, get_vocabulary, search_entities, then
run_sparql. Never invent a URI or a predicate.
Answer in the language of the question, briefly, in markdown. When a term in the
question is ambiguous or has no exact match, say which reading you chose and why.
You are read-only: do not try to change the ontology or the files.
The page draws a map or a timeline from your results, so shape them for it:
- A count, total or ratio per place or per date: return the place's or the date's IRI in its own
  column, then the number (SELECT ?country (COUNT(?store) AS ?stores) ...), never the label alone.
  The page then draws those places on a map and prints the number on each.
- A list of places or of dated things: put each entity's IRI in the first column, then its name
  and its date.
- Whatever entities you list or count, select their IRI as a column of its own, before the name
  (SELECT ?store ?label ...): a name alone cannot be placed on a map or dated on a timeline.
- If you answered with counts or totals about places or dated things and showed no map or timeline,
  end with one short line offering to show them on a map or a timeline. If the user accepts, run a
  query that returns the entity IRIs.
- When the user asks for a map or a timeline, answer with that query rather than describing it.
Give every run_sparql call its `question` argument: one plain sentence, in the language of the
question, saying what that query looks for, for example "Count the open epics of the CCDP". It is
shown as the step's title.
"""

app = FastAPI(title="Ask the ontology")


def migrate_state(ster_dir: Path) -> None:
    """The saved conversations used to live in .ster/webapp. Move them, once, to .ster/agent-app: nothing is lost."""
    old, new = ster_dir / "webapp", ster_dir / "agent-app"
    if old.is_dir() and not new.exists():
        shutil.move(str(old), str(new))


migrate_state(STER_DIR)
STORE.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------- guards
@app.middleware("http")  # noqa: V103
async def local_only(request: Request, call_next):
    """Refuse other hosts (DNS rebinding) and other origins (cross-site posts)."""
    host = request.headers.get("host", "").split(":")[0]
    origin = request.headers.get("origin")
    if host not in {"127.0.0.1", "localhost"}:
        return JSONResponse({"error": "bad host"}, status_code=403)
    if origin and origin.split("://", 1)[-1].split(":")[0] not in {"127.0.0.1", "localhost"}:
        return JSONResponse({"error": "bad origin"}, status_code=403)
    return await call_next(request)


# ------------------------------------------------------------------- ster side
def ster_up() -> bool:
    try:
        with socket.create_connection((STER_HOST, STER_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def ensure_ster() -> bool:
    """Start `ster serve` for this project when nothing listens on its port."""
    if ster_up():
        return True
    project = json.loads(
        (STER_DIR / "project.json").read_text()
    )  # raises: nothing to start ster on
    main = project["files"][0]
    cmd = [
        shutil.which("ster") or str(Path.home() / ".local/bin/ster"),
        "serve",
        main,
        "--host",
        STER_HOST,
        "--port",
        str(STER_PORT),
    ]
    for extra in project.get("context", {}).get(main, []):
        cmd += ["-x", extra]
    (STER_DIR / "agent-app").mkdir(parents=True, exist_ok=True)
    # tracing is what lets the page show each query with its rows and duration: switch it on and say where
    env = {**os.environ, "STER_QUERY_TRACE": "1", "STER_QUERY_TRACE_DIR": str(TRACES)}
    with open(
        STER_DIR / "agent-app" / "ster-serve.log", "ab"
    ) as log:  # the child keeps its own copy of the handle
        subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True)
    for _ in range(240):  # a project with many files takes a while to load
        if ster_up():
            return True
        time.sleep(0.25)
    return False


_served: dict = {"at": 0.0, "graph": None}
SERVED_TTL = (
    3.0  # seconds: a ster that was quit, or now serves another graph, shows within a few polls
)


def ster_graph(force: bool = False) -> dict | None:
    """What the ster on this page's port serves right now (title, ontology, triple count, fingerprint), or None
    when it does not answer. Asked at most every SERVED_TTL seconds."""
    if force or time.time() - _served["at"] > SERVED_TTL or _served.get("port") != STER_PORT:
        try:
            seen = runner.check_ster(
                f"http://{STER_HOST}:{STER_PORT}/mcp", {"Authorization": f"Bearer {ster_token()}"}
            )
            _served["graph"] = seen.get("graph") if seen.get("up") else None
        except OSError:
            _served["graph"] = None
        _served.update(at=time.time(), port=STER_PORT)
    return _served["graph"]


def ster_state(force: bool = False) -> dict:
    """``down`` when nothing answers, else ``up`` with the graph it serves. The page is connected to whatever graph
    its ster serves, so there is no wrong graph to refuse: a change is noticed per conversation (see ``graph``)."""
    if not ster_up():
        return {"state": "down", "graph": None}
    return {"state": "up", "graph": ster_graph(force)}


def ster_token() -> str:
    return TOKEN_FILE.read_text().strip()


def read_trace(run_id: str) -> dict | None:
    """What ster itself recorded for one tool call: SPARQL, rows, duration."""
    path = TRACES / f"{run_id}.jsonl"
    for _ in range(5):  # the file can land a moment after the response
        if path.exists():
            break
        time.sleep(0.1)
    else:
        return None
    steps: dict[str, dict] = {}
    info: dict = {
        "run_id": run_id,
        "file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "steps": [],
    }
    for line in path.read_text().splitlines():
        ev = json.loads(line)
        p = ev.get("payload", {})
        if ev["event"] == "run_started":
            info["query_type"] = p.get("query_type")
            info["agent_question"] = p.get(
                "agent_question"
            )  # in plain words, as the MCP asks the agent for it
        elif ev["event"] == "step_planned":
            steps[ev["step_id"]] = {"kind": p.get("step_kind"), "goal": p.get("natural_language")}
        elif ev["event"] == "query_generated":
            steps.setdefault(ev["step_id"], {})["query"] = p.get("query")
        elif ev["event"] == "step_completed":
            s = steps.setdefault(ev["step_id"], {})
            s.update(
                columns=p.get("columns"),
                rows=(p.get("result_rows") or [])[:300],
                row_count=p.get("row_count"),
                duration_ms=p.get("duration_ms"),
                truncated=p.get("result_truncated"),
                status=p.get("status"),
            )
    info["steps"] = list(steps.values())
    return info


# ------------------------------------------------------------------ run object
class Run:  # pylint: disable=too-many-instance-attributes  # the state of one turn, shared with the readers
    """One question being answered. Events are appended; readers wait on `cond`."""

    def __init__(self, conv: dict, turn: dict):
        self.conv, self.turn = conv, turn
        self.events: list[dict] = turn["events"]
        self.cond = asyncio.Condition()
        self.finished = False
        self.proc: asyncio.subprocess.Process | None = None
        self.t0 = time.monotonic()
        self.usage_seen: dict[str, dict] = {}
        self.seen_traces: set[str] = set()  # ster trace files that appeared during this run
        self.cancelled = False

    async def emit(self, kind: str, **data):
        ev = {"e": kind, "t": round((time.monotonic() - self.t0) * 1000), **data}
        async with self.cond:
            self.events.append(ev)
            self.cond.notify_all()
        return ev

    def persist(self):
        save(self.conv)

    async def emit_usage(self, step: str, counts: dict | None):
        """Merge the latest reported counts per model call. A count never reported stays absent ("not reported")."""
        merged = self.usage_seen.setdefault(step, {})
        merged.update(
            {
                k: v
                for k, v in (counts or {}).items()
                if v is not None and k in ("input", "output", "cache_read", "cache_write")
            }
        )
        if merged:
            await self.emit("usage", step=step, **merged)

    async def emit_tool_result(self, tool_id: str, content: str, is_error: bool):
        """A tool result, plus ster's own trace for it when the result names one."""
        await self.emit(
            "tool_result",
            id=tool_id,
            is_error=is_error,
            text=content[:RESULT_CAP],
            length=len(content),
            truncated=len(content) > RESULT_CAP,
        )
        m = re.search(r'"run_id":\s*"(run-[0-9a-f]+)"', content)
        if m:
            self.seen_traces.add(m.group(1))
            trace = await asyncio.to_thread(read_trace, m.group(1))
            if trace:
                await self.emit("trace", id=tool_id, **trace)
        save(self.conv)

    async def ingest(self, ev: dict):
        """One line of the neutral protocol (runner.py) from the agent or its translator."""
        kind = ev.get("e")
        if kind == "session":
            # some agents repeat their session id on every line; say it once
            if (
                ev.get("session_id")
                and ev["session_id"] != self.conv.get("session_id")
                or not any(e["e"] == "session" for e in self.events)
            ):
                await self.emit("session", **{k: v for k, v in ev.items() if k != "e"})
            if ev.get("session_id"):
                self.conv["session_id"] = ev["session_id"]
        elif kind in ("step_start", "text_delta", "thinking"):
            await self.emit(kind, **{k: v for k, v in ev.items() if k != "e"})
        elif kind == "usage":
            await self.emit_usage(ev.get("step") or "s0", ev)
        elif kind == "tool_call":
            await self.emit(
                "tool_call",
                step=ev.get("step"),
                id=ev["id"],
                name=runner.ster_tool(ev.get("name", "")),
                input=ev.get("input") or {},
            )
        elif kind == "tool_result":
            await self.emit_tool_result(ev["id"], ev.get("text") or "", bool(ev.get("is_error")))
        elif kind == "done":
            await self.emit("done", **{k: v for k, v in ev.items() if k != "e"})
            if ev.get("session_id"):
                self.conv["session_id"] = ev["session_id"]

    async def watch_traces(self, synthesize: bool, stop: asyncio.Event):
        """ster writes a trace file for every SPARQL query it serves, whichever agent asked. Count the ones that appear
        during this run and, when the agent reports no tool calls itself, turn them into tool_call/trace events."""
        t_start = time.time() - 1
        while True:
            finished = stop.is_set()
            for p in sorted(TRACES.glob("run-*.jsonl"), key=lambda p: p.stat().st_mtime):
                rid = p.stem
                if (
                    rid in self.seen_traces
                    or p.stat().st_mtime < t_start
                    or '"run_completed"' not in p.read_text()
                ):
                    continue
                self.seen_traces.add(rid)
                if synthesize:
                    trace = await asyncio.to_thread(read_trace, rid)
                    if trace and trace["steps"]:
                        query = next(
                            (st.get("query") for st in trace["steps"] if st.get("query")), ""
                        )
                        await self.emit(
                            "tool_call",
                            step="agent",
                            id=rid,
                            name="run_sparql",
                            input={"query": query},
                        )
                        await self.emit(
                            "tool_result",
                            id=rid,
                            is_error=False,
                            text="",
                            length=0,
                            truncated=False,
                        )
                        await self.emit("trace", id=rid, **trace)
                        save(self.conv)
            if finished:
                return
            try:
                await asyncio.wait_for(stop.wait(), 0.4)
            except TimeoutError:
                pass


RUNS: dict[str, Run] = {}


def conv_path(cid: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", cid):
        raise HTTPException(404)
    return STORE / f"{cid}.json"


def save(conv: dict):
    conv["updated"] = time.time()
    conv_path(conv["id"]).write_text(json.dumps(conv, ensure_ascii=False))


def load(cid: str) -> dict:
    p = conv_path(cid)
    if not p.exists():
        raise HTTPException(404)
    conv = json.loads(p.read_text())
    for turn in conv["turns"]:  # a turn left "running" by a dead server
        if turn["status"] == "running" and turn["id"] not in RUNS:
            turn["status"] = "interrupted"
    return conv


def last_step_text(events: list[dict]) -> str:
    """The text of the last model call that wrote any: the final answer, for agents with no final event."""
    by_step: dict[str, list[str]] = {}
    for e in events:
        if e["e"] == "text_delta":
            by_step.setdefault(e.get("step") or "", []).append(e["text"])
    return "".join(list(by_step.values())[-1]).strip() if by_step else ""


async def _fail(run: Run, why: dict) -> None:
    """End the turn with an error: *why* is a {code, params, text} reason, as runner.why_none gives."""
    await run.emit(
        "done",
        status="error",
        error=why["text"],
        error_code=why["code"],
        error_params=why["params"],
    )


def _no_model_reason(info: dict) -> dict:
    """Why no model server answers: the one asked for cannot call tools, or none is set up."""
    if (
        MODEL and info["reachable"] and info["models"]
    ):  # a model was asked for that cannot call tools
        models = ", ".join(info["models"])
        return {
            "code": "reason.model_not_capable",
            "params": {"model": MODEL, "models": models},
            "text": f"The model '{MODEL}' cannot call tools. Models that can: {models}.",
        }
    return runner.why_none(RECIPES, CUSTOM, WANT)


async def _drive_model(run: Run, agent: runner.Agent) -> None:
    """A model server: this page runs the agent loop (native.py)."""
    info = await asyncio.to_thread(agent.discover)
    model = native.choose_model(info, MODEL)
    if not model:
        await _fail(run, _no_model_reason(info))
        return
    job = native.Job(
        endpoint=agent.endpoint or "",
        model=model,
        api_name=info["api"],
        prompt=run.turn["prompt"],
        system_prompt=SYSTEM_PROMPT,
        ster_url=f"http://{STER_HOST}:{STER_PORT}/mcp",
        ster_token=ster_token(),
    )
    await native.drive(run, job)
    await run.emit("ster_seen", n=len(run.seen_traces))


def _invocation(run: Run) -> runner.Invocation:
    return runner.Invocation(
        prompt=run.turn["prompt"],
        system_prompt=SYSTEM_PROMPT,
        session=run.conv.get("session_id"),
        model=MODEL,
        ster_url=f"http://{STER_HOST}:{STER_PORT}/mcp",
        ster_token=ster_token(),
        recipes_dir=RECIPES_DIR,
    )


async def _start_processes(run: Run, agent: runner.Agent):
    """Start the agent's command (and its translator, if the recipe has one). Returns the stream to read."""
    inv = _invocation(run)
    big = 32 * 1024 * 1024
    pipe = asyncio.subprocess.PIPE
    cmd = await asyncio.create_subprocess_exec(
        *agent.argv(inv),
        cwd=ROOT,
        env={**os.environ, **agent.environment(inv)},
        stdin=pipe,
        stdout=pipe,
        stderr=pipe,
        limit=big,
    )
    procs = [cmd]
    reader = cmd.stdout
    if agent.stdin == "prompt":
        cmd.stdin.write(inv.prompt.encode())
    cmd.stdin.close()
    if (
        agent.translate
    ):  # the agent's own stream goes through a translator that prints neutral events
        tr = await asyncio.create_subprocess_exec(
            *agent.translate, cwd=ROOT, stdin=pipe, stdout=pipe, stderr=pipe, limit=big
        )
        procs.append(tr)

        async def pump():
            async for chunk in cmd.stdout:
                tr.stdin.write(chunk)
                await tr.stdin.drain()
            tr.stdin.close()

        # kept on the run so it is not collected mid-stream
        run.pump_task = asyncio.create_task(pump())  # noqa: V101
        reader = tr.stdout
    run.proc = cmd
    run.procs = procs
    return cmd, reader


async def _read_events(run: Run, agent: runner.Agent, reader, text_mode: bool) -> list[str]:
    """Turn what the agent prints into events. Returns the pieces of a plain-text answer."""
    answer: list[str] = []
    if text_mode:
        stripper = runner.AnsiStripper()
        await run.emit("step_start", step="agent")
        while chunk := await reader.read(512):
            piece = stripper.feed(chunk.decode(errors="replace"))
            if piece:
                answer.append(piece)
                await run.emit("text_delta", step="agent", text=piece)
        return answer
    translator = rule_engine.Rules(agent.stream) if agent.stream else None
    async for raw in reader:
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        for neutral in (
            (translator.apply(ev) if translator else [ev]) if isinstance(ev, dict) else []
        ):
            await run.ingest(neutral)
    return answer


async def _close_turn(run: Run, agent: runner.Agent, code: int, err: str, text: str | None) -> None:
    """The agent has exited. If it never said "done", say it for it: its text, its last step, or an error."""
    if any(e["e"] == "done" for e in run.events):
        return
    if text is not None and code == 0:
        await run.emit("done", status="completed", answer=text)
    elif code == 0 and (final := last_step_text(run.events)):
        # an agent that streams its steps but never says "done": the answer is what its last step wrote
        await run.emit("done", status="completed", answer=final)
    else:
        await run.emit(
            "done", status="error", error=err[-800:] or f"{agent.binary} exited with {code}"
        )


async def _drive_command(run: Run, agent: runner.Agent) -> None:
    """Run the configured command and turn what it prints into events."""
    cmd, reader = await _start_processes(run, agent)
    err_task = asyncio.create_task(cmd.stderr.read())
    text_mode = agent.output == "text" and not agent.translate and not agent.stream
    stop = asyncio.Event()
    watcher = asyncio.create_task(run.watch_traces(synthesize=text_mode, stop=stop))
    answer = await _read_events(run, agent, reader, text_mode)
    code = await cmd.wait()
    stop.set()
    await watcher
    err = (await err_task).decode(errors="replace").strip()
    await run.emit("ster_seen", n=len(run.seen_traces))
    await _close_turn(run, agent, code, err, "".join(answer).strip() if text_mode else None)


async def drive(run: Run):
    """Answer the turn's question with the configured agent."""
    agent = current_agent()
    await run.emit(
        "turn_start",
        prompt=run.turn["prompt"],
        resumed=bool(run.conv.get("session_id")),
        agent=agent.label if agent else None,
    )
    if not agent:
        await _fail(run, runner.why_none(RECIPES, CUSTOM, WANT))
    elif not await asyncio.to_thread(ensure_ster):
        await _fail(
            run,
            {
                "code": "err.ster_start",
                "params": {"port": STER_PORT},
                "text": f"ster did not start on port {STER_PORT}.",
            },
        )
    elif agent.kind == "model":
        await _drive_model(run, agent)
    else:
        await _drive_command(run, agent)


def report_answer(run: Run) -> bool:
    """Tell ster what the traces cannot see: the answer, and the id this conversation is resumed with.

    Best effort: ster down, or its tracing off, just means the history has no answer text.
    """
    turn, conv = run.turn, run.conv
    if turn.get("status") == "cancelled":
        return False
    runs = [e["run_id"] for e in run.events if e["e"] == "trace" and e.get("run_id")]
    body = {
        "question": turn["prompt"],
        "answer": turn.get("answer"),
        "status": turn.get("status", "error"),
        "agent": turn.get("agent"),
        **reported.model_field(run.events),
        "conversation_id": conv["id"],
        "resume_session_id": conv.get("session_id"),
        "run_ids": sorted(set(runs)),
        "token_usage": turn.get("usage"),
        "cost_usd": turn.get("cost_usd"),
        "duration_ms": turn.get("duration_ms"),
        "graph_fingerprint": turn.get("graph"),
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(turn.get("started", 0))),
    }
    if not isinstance(body["token_usage"], dict):
        body["token_usage"] = None
    try:
        status, _, _ = ster_fetch(
            "POST",
            f"/api/query_trace/answers/{turn['id']}",
            json.dumps({k: v for k, v in body.items() if v is not None}).encode(),
            {"Authorization": f"Bearer {ster_token()}", "Content-Type": "application/json"},
        )
    except OSError:  # ster is down, or its token is unreadable
        return False
    return status == HTTPStatus.CREATED


async def run_task(run: Run):
    try:
        await drive(run)
    except Exception as exc:  # surface bridge faults in the timeline
        await run.emit("done", status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        done = next((e for e in reversed(run.events) if e["e"] == "done"), {})
        run.turn["status"] = done.get("status", "error")
        run.turn["usage"] = done.get("usage")
        run.turn["cost_usd"] = done.get("cost_usd")
        run.turn["answer"] = done.get("answer")
        run.turn["duration_ms"] = run.events[-1]["t"] if run.events else 0
        save(run.conv)
        await asyncio.to_thread(report_answer, run)
        run.finished = True
        async with run.cond:
            run.cond.notify_all()


# ------------------------------------------------------------------------ API
@app.get("/api/status")
def status():
    a = current_agent()
    why = None if a else runner.why_none(RECIPES, CUSTOM, WANT)
    seen = ster_state()
    return {
        "ster": seen["state"] == "up",
        "ster_state": seen["state"],
        "ster_port": STER_PORT,
        "graph": seen["graph"],
        "map_url": f"http://{STER_HOST}:{STER_PORT}/map",
        "root": str(ROOT),
        "project": ROOT.name,
        "agent": {"label": a.label if a else None, "ready": bool(a), "reason": why},
    }


@app.get("/api/agent-check")  # noqa: V103
async def agent_check():
    """What the configured agent is, and what its last run really delivered. Makes no model call."""
    selected = current_agent()

    def info(a: runner.Agent) -> dict:
        return {
            "label": a.label,
            "binary": a.binary or a.endpoint,
            "path": a.path(),
            "version": a.version() if a.path() else None,
            "kind": a.kind,
            "output": "model"
            if a.kind == "model"
            else "events"
            if a.translate or a.stream
            else a.output,
            "verified": a.verified,
            "source": a.source,
            "selected": a is selected,
        }

    ster, listed = await asyncio.to_thread(
        lambda: (
            runner.check_ster(
                f"http://{STER_HOST}:{STER_PORT}/mcp", {"Authorization": f"Bearer {ster_token()}"}
            ),
            [info(a) for a in ([CUSTOM] if CUSTOM else []) + RECIPES],
        )
    )
    last = None  # the most recent finished run of this agent: what it really delivered
    for p in sorted(STORE.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        c = json.loads(p.read_text())
        for t in reversed(c["turns"]):
            if (
                (not selected or t.get("agent") == selected.label)
                and t["status"] == "completed"
                and t["events"]
            ):
                found = {
                    "conversation": c["title"][:60],
                    "prompt": t["prompt"][:80],
                    **runner.contract(t["events"]),
                }
                if found["counts"][
                    "tool_calls"
                ]:  # a run that used ster says more than one that did not
                    last = found
                    break
                last = last or found
        if last and last["counts"]["tool_calls"]:
            break
    return {
        "selected": info(selected) if selected else None,
        "reason": None if selected else runner.why_none(RECIPES, CUSTOM, WANT),
        "ster": ster,
        "agents": listed,
        "last_run": last,
    }


@app.post("/api/ask")
async def ask(body: dict):
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "empty prompt")
    if body.get("conversation_id"):
        conv = load(body["conversation_id"])
        if any(r.conv["id"] == conv["id"] and not r.finished for r in RUNS.values()):
            raise HTTPException(409, "this conversation is already answering")
    else:
        conv = {
            "id": uuid.uuid4().hex[:12],
            "title": prompt[:70],
            "created": time.time(),
            "session_id": None,
            "turns": [],
        }
    agent = current_agent()
    if not agent:
        raise HTTPException(409, runner.why_none(RECIPES, CUSTOM, WANT)["text"])
    seen = await asyncio.to_thread(ster_state, True)
    turn = {
        "id": uuid.uuid4().hex[:12],
        "prompt": prompt,
        "status": "running",
        "agent": agent.label,
        "graph": (seen["graph"] or {}).get("fingerprint"),  # which graph this answer is about
        "ster_started": (seen["graph"] or {}).get("started"),  # which ster process it was asked of
        "started": time.time(),
        "events": [],
    }
    conv["turns"].append(turn)
    save(conv)
    run = Run(conv, turn)
    RUNS[turn["id"]] = run
    asyncio.create_task(run_task(run))
    return {"conversation_id": conv["id"], "turn_id": turn["id"]}


@app.get("/api/runs/{turn_id}/events")
async def events(turn_id: str, request: Request, after: int = 0):
    run = RUNS.get(turn_id)
    if not run:
        raise HTTPException(404, "run not live; read the saved conversation")

    async def stream():
        i = after
        while True:
            async with run.cond:
                while i >= len(run.events) and not run.finished:
                    if await request.is_disconnected():
                        return
                    try:
                        await asyncio.wait_for(run.cond.wait(), 15)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                batch = run.events[i:]
            for ev in batch:
                yield f"id: {i}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                i += 1
            if run.finished and i >= len(run.events):
                yield "event: end\ndata: {}\n\n"
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/{turn_id}/cancel")  # noqa: V103
async def cancel(turn_id: str):
    run = RUNS.get(turn_id)
    if not run or run.finished:
        return {"cancelled": False}
    run.cancelled = True
    for p in getattr(run, "procs", [run.proc] if run.proc else []):
        if p.returncode is None:
            p.terminate()
    await run.emit("done", status="cancelled")
    return {"cancelled": True}


def _summary(c: dict) -> dict:
    """The history list's row for a conversation, with its token and cost totals."""
    tot = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    cost = 0.0
    for t in c["turns"]:
        # turns saved before the cost was stored still carry it in their final event
        cost += t.get("cost_usd") or next(
            (e.get("cost_usd") or 0 for e in reversed(t["events"]) if e["e"] == "done"), 0
        )
        for k, v in (t.get("usage") or {}).items():
            tot[k] = tot.get(k, 0) + (v or 0)
    return {
        "id": c["id"],
        "title": c["title"],
        "created": c["created"],
        "updated": c.get("updated", c["created"]),
        "turns": len(c["turns"]),
        "usage": tot,
        "cost_usd": cost,
        "prompts": [t["prompt"] for t in c["turns"]],
        "readonly": bool(c.get("readonly")),
    }


@app.get("/api/conversations")
def conversations():
    """This page's own conversations, plus those only ster's traces remember (marked read-only)."""
    own = [json.loads(p.read_text()) for p in STORE.glob("*.json")]
    known = {c["id"] for c in own}
    out = [_summary(c) for c in own]
    out += [_summary(c) for c in history.conversations(TRACES) if c["id"] not in known]
    return sorted(out, key=lambda c: c["updated"], reverse=True)


@app.get("/api/conversations/{cid}")  # noqa: V103
def conversation(cid: str):
    if conv_path(cid).exists():
        return load(cid)
    found = next((c for c in history.conversations(TRACES) if c["id"] == cid), None)
    if found is None:
        raise HTTPException(404)
    return history.with_events(found, lambda rid: read_trace(rid))


@app.delete("/api/conversations/{cid}")  # noqa: V103
def delete_conversation(cid: str):
    if not conv_path(cid).exists() and any(c["id"] == cid for c in history.conversations(TRACES)):
        raise HTTPException(
            409, "this conversation is kept by ster's traces; it is not this page's to delete"
        )
    conv_path(cid).unlink(missing_ok=True)
    return {"deleted": cid}


# ------------------------------------------------------------- embedded ster map
# ster serves its own map page, and an `embed=1` form of it with no header, query box
# or details panel. The bridge only looks up the agent's query for a tool call and
# sends the frame to that page (the page brings its own token, so nothing is proxied
# for it). The chat page itself asks ster "can these rows be placed or dated?" through
# the read-only calls below; a call without a token gets the bridge's own.
MAP_API = {
    ("POST", "locate"),
    ("POST", "timeline"),
    ("GET", "node-detail"),
    ("POST", "sparql_query"),
}


def ster_fetch(method: str, path: str, body: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(
        f"http://{STER_HOST}:{STER_PORT}{path}", data=body, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read(), r.headers.get("content-type", "application/json")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("content-type", "application/json")


def _query_of_call(conv: str, turn: str, tool: str) -> str:
    """The SPARQL a tool call of a saved turn ran, or a 404 when there is no such call or it ran no query."""
    c = load(conv)
    t = next((t for t in c["turns"] if t["id"] == turn), None)
    query = next(
        (
            e["input"].get("query")
            for e in (t or {}).get("events", [])
            if e["e"] == "tool_call" and e["id"] == tool
        ),
        None,
    )
    if not query:
        raise HTTPException(404, "no such query")
    return query


async def _redirect_to_ster(page: str, query: str, full: bool) -> RedirectResponse:
    """Send the caller to ster's *page* (map or timeline) for *query*, embedded unless *full*."""
    if not await asyncio.to_thread(ensure_ster):
        raise HTTPException(503, "ster is not running")
    url = f"http://{STER_HOST}:{STER_PORT}/{page}?q={quote(query)}" + ("" if full else "&embed=1")
    return RedirectResponse(url, status_code=302)


@app.get("/ster-map")  # noqa: V103
async def ster_map(conv: str, turn: str, tool: str, full: bool = False):
    """Send the caller to ster's map for the query a tool call ran (embedded unless *full*)."""
    return await _redirect_to_ster("map", _query_of_call(conv, turn, tool), full)


@app.get("/ster-timeline")  # noqa: V103
async def ster_timeline(conv: str, turn: str, tool: str, full: bool = False):
    """Send the caller to ster's timeline for the query a tool call ran (embedded unless *full*)."""
    return await _redirect_to_ster("timeline", _query_of_call(conv, turn, tool), full)


@app.get("/api/locales")  # noqa: V103
def locales():
    """The interface languages on offer: one JSON catalog per language in locales/."""
    out = []
    for p in sorted((STATIC / "locales").glob("*.json")):
        try:
            out.append({"code": p.stem, "name": json.loads(p.read_text()).get("_name", p.stem)})
        except ValueError:
            continue
    return out


@app.api_route("/api/{path:path}", methods=["GET", "POST"])  # noqa: V103
async def ster_api(path: str, request: Request):
    if (request.method, path) not in MAP_API:
        raise HTTPException(404)
    fwd = {
        k: v for k, v in request.headers.items() if k.lower() in ("authorization", "content-type")
    }
    if "authorization" not in {k.lower() for k in fwd}:
        fwd["Authorization"] = f"Bearer {TOKEN_FILE.read_text().strip()}"
    qs = request.url.query
    status, body, ctype = await asyncio.to_thread(
        ster_fetch,
        request.method,
        f"/api/{path}" + (f"?{qs}" if qs else ""),
        await request.body() or None,
        fwd,
    )
    return Response(body, status_code=status, media_type=ctype.split(";")[0])


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
