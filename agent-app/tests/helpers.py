"""Test doubles: a fake ster, fake agents, and a running copy of the bridge that touches nothing real."""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parent.parent  # agent-app/
WEB = APP / "agent_app"  # the package
sys.path.insert(0, str(APP))

from agent_app import runner  # noqa: E402

TOOLS = list(runner.STER_TOOLS)  # the tools ster offers, as the page knows them
MAP_PAGE = '<html><body><textarea id="q" spellcheck="false">SELECT default</textarea><aside>details</aside></body></html>'


class FakeSter:  # pylint: disable=too-many-instance-attributes  # a fake ster: what it serves and what it saw
    """Just enough of ster: the MCP endpoint, /map, and the three read-only API calls the map makes."""

    def __init__(
        self,
        tools=None,
        file="/project/data.ttl",
        instructions="ask get_vocabulary first",
        replies=None,
        title="Test ontology",
    ):
        self.title = title
        self.started = (
            "2026-01-01T10:00:00Z"  # this ster process; a test changes it to simulate a restart
        )
        self.fingerprint = (
            "00aa11bb22cc33dd"  # the graph stamp it reports; a test changes it to edit the graph
        )
        self.tools, self.file, self.log = TOOLS if tools is None else tools, file, []
        self.instructions, self.replies = (
            instructions,
            replies or {},
        )  # replies: tool name -> text (or a function of its arguments)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # keep test output quiet  # noqa: V105
                pass

            def _send(self, code, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: V105
                outer.log.append(("GET", self.path, dict(self.headers), b""))
                if self.path == "/map":
                    return self._send(200, MAP_PAGE.encode(), "text/html")
                self._send(200, {"ok": True, "path": self.path})

            def do_POST(self):  # noqa: V105
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.log.append(("POST", self.path, dict(self.headers), body))
                if self.path == "/mcp":
                    req = json.loads(body)
                    m = req["method"]
                    if m == "initialize":
                        res = {"protocolVersion": "2025-03-26", "instructions": outer.instructions}
                    elif m == "tools/list":
                        res = {
                            "tools": [
                                {
                                    "name": t,
                                    "description": f"the {t} tool",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"q": {"type": "string"}},
                                    },
                                }
                                for t in outer.tools
                            ]
                        }
                    else:
                        params = req.get("params", {})
                        reply = outer.replies.get(
                            params.get("name"),
                            json.dumps(
                                {
                                    "file": outer.file,
                                    "title": outer.title,
                                    "ontology_uri": "https://example.org/o",
                                    "graph": {"triples": 12, "fingerprint": outer.fingerprint},
                                    "server": {"started": outer.started},
                                }
                            ),
                        )
                        text = reply(params.get("arguments", {})) if callable(reply) else reply
                        res = {"content": [{"type": "text", "text": text}], "isError": False}
                    return self._send(200, {"jsonrpc": "2.0", "id": req["id"], "result": res})
                if self.path.startswith("/api/query_trace/answers/"):
                    return self._send(201, {"id": self.path.rsplit("/", 1)[-1]})
                self._send(200, {"ok": True, "auth": self.headers.get("Authorization")})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class FakeModel:  # pylint: disable=too-many-instance-attributes  # a fake model server: what it serves and what it was sent
    """A model server: Ollama's own API (/api/*) or an OpenAI-compatible one (/v1/*), answering from a script."""

    def __init__(self, ollama=True, models=None, tools_capable=("big",)):
        self.ollama, self.models, self.tools_capable = ollama, models or ["big"], set(tools_capable)
        self.script, self.requests = (
            [],
            [],
        )  # script: the replies, in order. requests: what the page sent
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: V105
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: V105
                if self.path == "/api/tags" and outer.ollama:
                    return self._send(200, {"models": [{"name": m} for m in outer.models]})
                if self.path == "/v1/models" and not outer.ollama:
                    return self._send(200, {"data": [{"id": m} for m in outer.models]})
                self._send(404, {"error": "not found"})

            def do_POST(self):  # noqa: V105
                body = json.loads(
                    self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"
                )
                if self.path == "/api/show" and outer.ollama:
                    caps = ["completion"] + (
                        ["tools"] if body.get("model") in outer.tools_capable else []
                    )
                    return self._send(200, {"capabilities": caps})
                if self.path in ("/api/chat", "/v1/chat/completions"):
                    outer.requests.append(body)
                    if body.get("model") not in outer.models:
                        return self._send(404, {"error": f"model '{body.get('model')}' not found"})
                    reply = outer.script.pop(0) if outer.script else {"content": "(script ran out)"}
                    if "error" in reply:
                        return self._send(
                            reply.get("status", 400),
                            {"error": {"message": reply["error"]}}
                            if not outer.ollama
                            else {"error": reply["error"]},
                        )
                    return self._send(200, outer.wrap(reply))
                self._send(404, {"error": "not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.endpoint = f"http://127.0.0.1:{self.port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def wrap(self, reply):
        """reply: {content, calls: [(name, args)], tokens: (in, out)} in the shape this server's API uses."""
        calls, (tin, tout) = reply.get("calls", []), reply.get("tokens", (10, 5))
        if self.ollama:
            msg = {"role": "assistant", "content": reply.get("content", "")}
            if calls:
                msg["tool_calls"] = [{"function": {"name": n, "arguments": a}} for n, a in calls]
            return {"message": msg, "done": True, "prompt_eval_count": tin, "eval_count": tout}
        msg = {"role": "assistant", "content": reply.get("content") or None}
        if calls:
            msg["tool_calls"] = [
                {
                    "id": f"id{i}",
                    "type": "function",
                    "function": {
                        "name": n,
                        "arguments": a if isinstance(a, str) else json.dumps(a),
                    },
                }
                for i, (n, a) in enumerate(calls)
            ]
        return {
            "choices": [{"message": msg}],
            "usage": {"prompt_tokens": tin, "completion_tokens": tout},
        }

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def write_trace(folder: Path, run_id: str, query: str, columns: list[str], rows: list[list[str]]):
    """A trace file as ster writes it: one JSON event per line, finished by run_completed."""

    def ev(kind, seq, **payload):
        return {
            "event": kind,
            "run_id": run_id,
            "sequence": seq,
            "step_id": "raw-sparql",
            "payload": payload,
        }

    lines = [
        ev("run_started", 1, query_type="raw_sparql"),
        ev("step_planned", 2, step_kind="raw_sparql_execution", natural_language="run"),
        ev("query_generated", 3, query=query),
        ev("step_started", 4),
        ev(
            "step_completed",
            5,
            columns=columns,
            result_rows=rows,
            row_count=len(rows),
            duration_ms=1.5,
            status="completed",
            result_truncated=False,
        ),
        ev("run_completed", 6, status="completed"),
    ]
    (folder / f"{run_id}.jsonl").write_text("\n".join(json.dumps(x) for x in lines))


def agent_script(folder: Path, name: str, body: str) -> str:
    """Write a throwaway agent. The body may be an indented block with an unindented first line (an import prelude)."""
    lines = body.split("\n")
    cut = min(
        (len(l) - len(l.lstrip()) for l in lines if l.strip() and l.startswith(" ")), default=0
    )
    text = "\n".join(l[cut:] if l.startswith(" " * cut) else l for l in lines)
    path = folder / name
    path.write_text("import json, sys, os, time\n" + text)
    return str(path)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def free_range(n: int = 4) -> int:
    """The first of *n* consecutive free ports, searched from a random start so tests running in parallel do not
    pick overlapping ranges."""
    import random

    while True:
        first = random.randint(20000, 60000)  # noqa: S311 - a port, not a secret
        socks = []
        try:
            for port in range(first, first + n):
                sock = socket.socket()
                socks.append(sock)
                sock.bind(("127.0.0.1", port))
            return first
        except OSError:
            continue
        finally:
            for sock in socks:
                sock.close()


class Bridge:  # pylint: disable=too-many-instance-attributes  # the page under test, with its fake ster and folders
    """The real server.py app on a free port, with its state in a temp folder and its ster replaced by FakeSter."""

    def __init__(self, ster: FakeSter, custom: runner.Agent | None = None, recipes=None):
        import uvicorn
        from agent_app import server

        self.server, self.tmp = server, Path(tempfile.mkdtemp(prefix="ask-test-"))
        self.store, self.traces = self.tmp / "conversations", self.tmp / "traces"
        self.store.mkdir()
        self.traces.mkdir()
        token = self.tmp / "token"
        token.write_text("test-token")
        self.patches = [
            mock.patch.object(server, n, v)
            for n, v in {
                "ROOT": self.tmp,  # no project.json here, so a test is never about the real checkout
                "STER_DIR": self.tmp / ".ster",
                "STORE": self.store,
                "TRACES": self.traces,
                "STER_HOST": "127.0.0.1",
                "STER_PORT": ster.port,
                "TOKEN_FILE": token,
                "CUSTOM": custom,
                "RECIPES": recipes or [],
                "WANT": None,
            }.items()
        ]
        for p in self.patches:
            p.start()
        self.port = free_port()
        self.uv = uvicorn.Server(
            uvicorn.Config(server.app, host="127.0.0.1", port=self.port, log_level="error")
        )
        self.thread = threading.Thread(target=self.uv.run, daemon=True)
        self.thread.start()
        while not self.uv.started:
            pass
        self.base = f"http://127.0.0.1:{self.port}"

    def close(self):
        self.uv.should_exit = True  # noqa: V101
        self.thread.join(5)
        for p in self.patches:
            p.stop()

    def call(self, path, body=None, headers=None, method=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data,
            {"Content-Type": "application/json", **(headers or {})},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def redirect_of(self, path):
        """(status, Location) of a GET, without following the redirect."""

        class Stop(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):  # noqa: V105
                return None

        try:
            urllib.request.build_opener(Stop).open(self.base + path, timeout=30)
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Location", "")
        return 200, ""

    def json(self, path, body=None, **kw):
        status, raw = self.call(path, body, **kw)
        return status, json.loads(raw or b"null")

    def ask(self, prompt, conversation_id=None):
        status, r = self.json("/api/ask", {"prompt": prompt, "conversation_id": conversation_id})
        return status, r

    def events(self, turn_id):
        """Every event of a run, read from the SSE stream until it ends."""
        out = []
        with urllib.request.urlopen(f"{self.base}/api/runs/{turn_id}/events", timeout=30) as r:
            for raw in r:
                line = raw.decode().strip()
                if line.startswith("data: {") and line != "data: {}":
                    out.append(json.loads(line[6:]))
        return out


def translate_recorded(agent: runner.Agent, text: str) -> list[dict]:
    """The neutral events a recipe's rules make of a recorded agent stream (lines that are not JSON are skipped)."""
    from agent_app import rules

    engine, events = rules.Rules(agent.stream), []
    for line in text.splitlines():
        try:
            events += engine.apply(json.loads(line))
        except ValueError:
            continue
    return events
