"""Running a coding agent without knowing which one it is.

The bridge starts a command and reads what it prints. Nothing here, in server.py or in the page names an agent.

  * The command is a template (a "recipe" file, or ASK_AGENT_CMD). Placeholders: {prompt} {system_prompt}
    {session} {model} {ster_url} {ster_token} {ster_mcp_json}.
  * Its stdout is either plain answer text ("text", works with any CLI that prints its answer), or JSON lines in
    the neutral protocol below ("events"), optionally produced by a translator script the recipe pipes it through.
  * Whatever the agent reports, ster itself traces every SPARQL query it serves. The bridge reads those trace
    files, so the queries, their rows and durations are known for any agent.

Neutral protocol, one JSON object per line (every field but "e" is optional; what is missing is "not reported"):
    {"e":"session","session_id":"…"}                       enables follow-ups
    {"e":"step_start","step":"s1"}                          one model call
    {"e":"usage","step":"s1","input":n,"output":n,"cache_read":n,"cache_write":n}
    {"e":"text_delta","step":"s1","text":"…"}
    {"e":"tool_call","step":"s1","id":"c1","name":"run_sparql","input":{…}}
    {"e":"tool_result","id":"c1","text":"<ster's reply, unmodified>","is_error":false}
    {"e":"done","status":"completed","answer":"…","cost_usd":n,"usage":{…},"session_id":"…"}
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

_SERVERS_TTL = 5  # seconds a model server's answer (up? which models?) is remembered
_SERVERS: dict[str, tuple[float, dict]] = {}  # endpoint -> (when, what native.discover found)

# The tools a ster endpoint offers an agent. Agents name MCP tools with their own prefixes
# (<prefix>run_sparql), so a tool is recognised by how its name ends.
STER_TOOLS = tuple(
    sorted(
        [
            "export_query_trace",
            "get_current_context",
            "get_entity",
            "get_overview",
            "get_query_trace",
            "get_timeline",
            "get_vocabulary",
            "open_view",
            "run_sparql",
            "search_entities",
        ]
    )
)
REQUIRED_TOOLS = ("get_overview", "get_vocabulary", "search_entities", "run_sparql")


_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_PARTIAL = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*|\][^\x07\x1b]*)?"
)  # the start of a code, not yet finished


class AnsiStripper:
    """Removes terminal colour and cursor codes from streamed text, even when a code is split between two chunks."""

    def __init__(self) -> None:
        self.held = ""

    def feed(self, chunk: str) -> str:
        text = self.held + chunk
        cut = text.rfind("\x1b")
        # keep back only a tail that could still grow into a code; a stray ESC before ordinary text is just text
        self.held = text[cut:] if cut != -1 and _PARTIAL.fullmatch(text, cut) else ""
        if self.held:
            text = text[:cut]
        return _ANSI.sub("", text)


def ster_tool(name: str) -> str:
    for t in sorted(STER_TOOLS, key=len, reverse=True):
        if name == t or re.search(rf"[_.:/-]{t}$", name):
            return t
    return name


@dataclass(frozen=True)
class Invocation:
    """What one run hands an agent: the question, the prompt rules, the session to resume, and where ster is."""

    prompt: str
    system_prompt: str
    session: str | None
    model: str | None
    ster_url: str
    ster_token: str
    recipes_dir: Path


@dataclass
class Agent:  # pylint: disable=too-many-instance-attributes  # a record of one recipe's settings
    label: str
    binary: str  # what must be on the PATH for this to count as set up
    command: list[str]
    kind: str = "command"  # "command": run a program. "model": a model server; the page runs the loop (native.py)
    endpoint: str | None = None  # the model server's address, for kind "model"
    resume: list[str] = field(default_factory=list)  # appended when a session id exists
    model_args: list[str] = field(default_factory=list)  # appended when a model is chosen
    stdin: str = "prompt"  # "prompt" or "none"
    output: str = "events"  # "events" (neutral protocol) or "text" (plain answer)
    stream: list[dict] | None = (
        None  # rules (rules.py) that turn the agent's own lines into neutral events
    )
    translate: list[str] | None = (
        None  # or a command that does it (for a format the rules cannot express)
    )
    env: dict[str, str] = field(
        default_factory=dict
    )  # extra environment, with the same placeholders as `command`
    verified: bool = False  # run against the real agent by whoever wrote the recipe
    source: str = ""
    priority: int = 100

    def discover(self) -> dict:
        """For a model server: is it up, and which of its models can call tools (cached for a few seconds)."""
        from . import native  # imported here: native needs runner too

        hit = _SERVERS.get(self.endpoint or "")
        if not hit or time.time() - hit[0] > _SERVERS_TTL:
            hit = (time.time(), native.discover(self.endpoint or ""))
            _SERVERS[self.endpoint or ""] = hit
        return hit[1]

    def path(self) -> str | None:
        if self.kind == "model":
            return self.endpoint if self.discover()["reachable"] else None
        return shutil.which(self.binary)

    def available(self) -> bool:
        if self.kind == "model":  # only models that can call tools count
            return bool(self.discover()["models"])
        return bool(self.path())

    def version(self) -> str | None:
        p = self.path()
        if not p:
            return None
        if self.kind == "model":
            from . import native

            return native.choose_model(self.discover(), os.environ.get("ASK_MODEL"))
        try:
            out = subprocess.run(
                [p, "--version"], capture_output=True, text=True, timeout=4
            ).stdout.strip()
            return (out.splitlines() or [""])[0][:60] or None
        except (OSError, subprocess.SubprocessError):
            return None

    def _fill(self, inv: Invocation):
        mcp = json.dumps(
            {
                "mcpServers": {
                    "ster": {
                        "type": "http",
                        "url": inv.ster_url,
                        "headers": {"Authorization": f"Bearer {inv.ster_token}"},
                    }
                }
            }
        )
        fill = {
            "{prompt}": inv.prompt,
            "{system_prompt}": inv.system_prompt,
            "{session}": inv.session or "",
            "{model}": inv.model or "",
            "{ster_url}": inv.ster_url,
            "{ster_token}": inv.ster_token,
            "{ster_mcp_json}": mcp,
            "{recipes}": str(inv.recipes_dir),
        }
        pattern = re.compile("|".join(re.escape(k) for k in fill))
        # one pass: a value that itself contains "{ster_token}" (a prompt can) is inserted as it is, never expanded
        return lambda tok: pattern.sub(lambda m: fill[m.group(0)], tok)

    def argv(self, inv: Invocation) -> list[str]:
        sub = self._fill(inv)
        out = [sub(t) for t in self.command]
        if inv.session:
            out += [sub(t) for t in self.resume]
        if inv.model:
            out += [sub(t) for t in self.model_args]
        return out

    def environment(self, inv: Invocation) -> dict[str, str]:
        sub = self._fill(inv)
        return {k: sub(v) for k, v in self.env.items()}


def load_recipes(folder: str | Path) -> list[Agent]:
    found = []
    for f in sorted(Path(folder).glob("*.json")):
        try:
            r = json.loads(f.read_text())
            tr = r.get("translate")
            if r.get("type") == "model":  # a model server: no program, the page runs the loop
                found.append(
                    Agent(
                        label=r["label"],
                        binary="",
                        command=[],
                        kind="model",
                        endpoint=r["endpoint"],
                        verified=bool(r.get("verified")),
                        source=f.name,
                        priority=r.get("priority", 100),
                    )
                )
                continue
            found.append(
                Agent(
                    label=r["label"],
                    binary=r["binary"],
                    command=r["command"],
                    resume=r.get("resume", []),
                    model_args=r.get("model_args", []),
                    stdin=r.get("stdin", "prompt"),
                    output=r.get("output", "events"),
                    stream=r.get("stream"),
                    env=r.get("env", {}),
                    translate=[t.replace("{recipes}", str(Path(folder))) for t in tr]
                    if tr
                    else None,
                    verified=bool(r.get("verified")),
                    source=f.name,
                    priority=r.get("priority", 100),
                )
            )
        except (
            ValueError,
            KeyError,
            OSError,
        ) as exc:  # a broken recipe must not take the page down
            print(f"recipe {f.name} skipped: {type(exc).__name__}: {exc}")
    return sorted(found, key=lambda a: (a.priority, a.label))


def from_env(env: dict) -> Agent | None:
    """ASK_AGENT_CMD: any command, as a JSON list or a shell-style string. Plain text output unless ASK_AGENT_OUTPUT=events."""
    raw = env.get("ASK_AGENT_CMD")
    if not raw and env.get("ASK_MODEL_URL"):  # a model server instead of an agent
        return Agent(
            label=env.get("ASK_AGENT_LABEL") or "Model server",
            binary="",
            command=[],
            kind="model",
            endpoint=env["ASK_MODEL_URL"],
            source="ASK_MODEL_URL",
            priority=0,
        )
    if not raw:
        return None
    cmd = json.loads(raw) if raw.lstrip().startswith("[") else shlex.split(raw)
    return Agent(
        label=env.get("ASK_AGENT_LABEL") or Path(cmd[0]).name,
        binary=cmd[0],
        command=cmd,
        stdin=env.get("ASK_AGENT_STDIN", "none" if any("{prompt}" in t for t in cmd) else "prompt"),
        output=env.get("ASK_AGENT_OUTPUT", "text"),
        source="ASK_AGENT_CMD",
        priority=0,
    )


def select(recipes: list[Agent], custom: Agent | None, wanted: str | None) -> Agent | None:
    """The command that drives runs: the custom one, else the recipe named (by file or label), else the first set up."""
    if custom:
        return custom if custom.available() else None
    pool = [
        r
        for r in recipes
        if not wanted
        or wanted.lower()
        in (r.source.lower(), r.source.lower().removesuffix(".json"), r.label.lower())
    ]
    return next((r for r in pool if r.available()), None)


def _model_server_reason(agents: list[Agent]) -> dict | None:
    """A model server that answers but has no model able to call tools says so; one that does not answer is named too."""
    for a in agents:
        if a.kind != "model":
            continue
        info = a.discover()
        if not info["reachable"]:
            return {
                "code": "reason.endpoint_down",
                "params": {"endpoint": a.endpoint},
                "text": f"The model server at {a.endpoint} does not answer.",
            }
        if not info["models"]:
            return {
                "code": "reason.no_tool_model",
                "params": {"endpoint": a.endpoint, "models": ", ".join(info["all"]) or "none"},
                "text": f"The model server at {a.endpoint} has no model that can call tools (found: {', '.join(info['all']) or 'none'}).",
            }
    return None


def why_none(recipes: list[Agent], custom: Agent | None, wanted: str | None) -> dict:
    if custom and custom.kind == "model":
        return _model_server_reason([custom]) or {
            "code": "reason.none_installed",
            "params": {"list": custom.endpoint},
            "text": "Model server unavailable.",
        }
    if custom:
        return {
            "code": "reason.missing_binary",
            "params": {"binary": custom.binary},
            "text": f"'{custom.binary}' was not found in the PATH.",
        }
    if wanted and not any(
        wanted.lower()
        in (r.source.lower(), r.source.lower().removesuffix(".json"), r.label.lower())
        for r in recipes
    ):
        return {
            "code": "reason.unknown_recipe",
            "params": {"wanted": wanted},
            "text": f"No recipe named '{wanted}'.",
        }
    only_servers = [r for r in recipes if r.kind == "model"]
    if (
        only_servers
        and all(r.kind == "model" or not r.available() for r in recipes)
        and len(only_servers) == len(recipes)
        and (why := _model_server_reason(only_servers))
    ):
        return why
    if not recipes:
        return {
            "code": "reason.no_recipes",
            "params": {},
            "text": "No agent recipe is installed and ASK_AGENT_CMD is not set.",
        }
    names = [r.binary or r.endpoint or r.label for r in recipes]
    return {
        "code": "reason.none_installed",
        "params": {"list": ", ".join(names)},
        "text": "None of the recipes' programs is on the PATH: " + ", ".join(names) + ".",
    }


# ------------------------------------------------------------------ checks (no model call)
def _rpc(url: str, headers: dict, method: str, params: dict | None = None, timeout: float = 5):
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    ).encode()
    req = urllib.request.Request(
        url,
        body,
        {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **headers,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r).get("result", {})


def meta_namespace(instructions: str | None) -> str | None:
    """The namespace ster's instructions put its request-metadata keys under (the part before ``/agent-…``), if any."""
    found = re.search(
        r'"([\w.\-]+)/agent-(?:session-id|session-question|question)"', instructions or ""
    )
    return found.group(1) if found else None


def graph_of(overview: dict) -> dict:
    """What a ster serves, as its overview says it: title, ontology, file, when this process started, and the graph's
    own stamp. A new start time means a restart; a new stamp means the graph changed."""
    return {
        "title": overview.get("title"),
        "ontology_uri": overview.get("ontology_uri"),
        "file": overview.get("file"),
        "started": (overview.get("server") or {}).get("started"),
        **(overview.get("graph") or {}),
    }


def check_ster_light(base: str, headers: dict, timeout: float = 5) -> dict:
    """Whether ster answers and what graph it serves, in one plain HTTP request.

    The page asks this every few seconds. The MCP handshake ``check_ster`` makes is three requests and, because
    ``get_overview`` is a tool call, leaves a trace each time; ster's REST overview is one request and leaves none.
    """
    out: dict = {"url": base, "up": False}
    request = urllib.request.Request(f"{base}/api/overview", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            out["graph"] = graph_of(json.load(response))
        out["up"] = True
    except (OSError, ValueError) as exc:  # unreachable, unauthorised, not ster
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def check_ster(url: str, headers: dict) -> dict:
    """What any MCP agent needs from ster: it answers, it lists the tools, and says which file it serves."""
    out = {"url": url, "up": False}
    try:
        init = _rpc(
            url,
            headers,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "ask-the-ontology-check", "version": "1"},
            },
        )
        out["up"] = True
        out["instructions"] = bool(init.get("instructions"))
        tools = [t["name"] for t in _rpc(url, headers, "tools/list").get("tools", [])]
        out["tools"] = tools
        out["missing"] = [t for t in REQUIRED_TOOLS if t not in tools]
        # a health check: ster is asked not to journal it
        quiet = {f"{ns}/untraced": True} if (ns := meta_namespace(init.get("instructions"))) else {}
        ov = _rpc(
            url, headers, "tools/call", {"name": "get_overview", "arguments": {}, "_meta": quiet}
        )
        overview = json.loads(ov["content"][0]["text"])
        out["file"] = overview.get("file")
        out["graph"] = graph_of(overview)
    except Exception as exc:  # unreachable, unauthorised, not ster
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def contract(events: list[dict]) -> dict:
    """What a run actually delivered, measured on its saved events: the same list the page is built from."""
    steps = [e for e in events if e["e"] == "step_start"]
    used = {e["step"] for e in events if e["e"] == "usage"}
    calls = [e for e in events if e["e"] == "tool_call"]
    sparql = [e for e in calls if e["name"] == "run_sparql"]
    traced = {e["id"] for e in events if e["e"] == "trace"}
    done = next((e for e in reversed(events) if e["e"] == "done"), None)
    seen = next((e["n"] for e in reversed(events) if e["e"] == "ster_seen"), None)
    observed = {  # None: the run gave no way to tell (e.g. it called no tool)
        "stream_steps": bool(steps),
        "token_usage": bool(steps) and all(s["step"] in used for s in steps),
        "cost": bool(done and done.get("cost_usd") is not None),
        "resume": any(e["e"] == "session" and e.get("session_id") for e in events),
        "sparql_rows": (all(c["id"] in traced for c in sparql) if sparql else None),
    }
    problems = []
    if not done:
        problems.append({"code": "prob.no_done", "params": {}})
    if sparql and seen == 0:
        problems.append(
            {"code": "prob.no_ster_traces", "params": {}}
        )  # it ran queries, ster saw none: another ster?
    for c in calls:
        if (
            next((e for e in events if e["e"] == "tool_result" and e["id"] == c["id"]), None)
            is None
            and c["id"] not in traced
        ):
            problems.append({"code": "prob.call_no_result", "params": {"name": c["name"]}})
    return {
        "observed": observed,
        "counts": {
            "steps": len(steps),
            "tool_calls": len(calls),
            "sparql": len(sparql),
            "traced": len(traced),
        },
        "problems": problems[:8],
    }
